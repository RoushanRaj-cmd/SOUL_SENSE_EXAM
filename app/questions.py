import logging
import json
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
import threading
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Question, QuestionCache, StatisticsCache

logger = logging.getLogger(__name__)

# ------------------ CACHING CONFIGURATION ------------------
CACHE_DIR = "cache"
CACHE_FILE = os.path.join(CACHE_DIR, "questions_cache.json")
CACHE_MAX_AGE_HOURS = 24  # Cache valid for 24 hours
MEMORY_CACHE_TTL = 300  # 5 minutes for memory cache

# ------------------ PERFORMANCE OPTIMIZATIONS ------------------
_questions_cache = {}
_cache_timestamps = {}
_cache_lock = threading.Lock()
_last_preload_time = 0
_preload_interval = 60  # Preload every 60 seconds if needed

def _ensure_cache_dir():
    """Ensure cache directory exists"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def _get_cache_key(age: Optional[int] = None) -> str:
    """Generate cache key based on age filter"""
    return f"questions_age_{age}" if age is not None else "questions_all"

def _is_cache_valid(cache_key: str) -> bool:
    """Check if cache is still valid in memory"""
    if cache_key not in _cache_timestamps:
        return False
    
    cache_time = _cache_timestamps[cache_key]
    return (time.time() - cache_time) < MEMORY_CACHE_TTL

def _save_to_disk_cache(questions: List[Tuple[int, str, Optional[str], str]], age: Optional[int] = None):
    """Save questions to disk cache file"""
    try:
        _ensure_cache_dir()
        cache_data = {
            "timestamp": datetime.now().isoformat(),
            "questions": questions,
            "age_filter": age,
            "count": len(questions)
        }
        cache_key = "questions" if age is None else f"questions_age_{age}"
        cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Cached {len(questions)} questions to disk (age filter: {age})")
        return True
    except Exception as e:
        logger.error(f"Failed to save disk cache: {e}")
        return False

def _load_from_disk_cache(age: Optional[int] = None):
    """Load questions from disk cache if valid"""
    try:
        cache_key = "questions" if age is None else f"questions_age_{age}"
        cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
        
        if not os.path.exists(cache_file):
            return None
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        # Check cache age
        cache_time = datetime.fromisoformat(cache_data.get("timestamp", ""))
        if datetime.now() - cache_time > timedelta(hours=CACHE_MAX_AGE_HOURS):
            logger.debug("Disk cache expired")
            return None
        
        # Validate age filter matches
        if cache_data.get("age_filter") != age:
            return None
        
        # --- FIXED: Handle Legacy Cache (3 items) vs New (4 items) ---
        questions = []
        for q in cache_data["questions"]:
            if len(q) >= 4:
                questions.append((int(q[0]), q[1], q[2], q[3]))
            else:
                # Fallback for old cache files: Default to 'scale'
                questions.append((int(q[0]), q[1], q[2], 'scale'))
        # -------------------------------------------------------------

        logger.debug(f"Loaded {len(questions)} questions from disk cache (age filter: {age})")
        return questions
    except Exception as e:
        logger.error(f"Failed to load disk cache: {e}")
        return None

@lru_cache(maxsize=8)
def _get_cached_questions_from_db(age: Optional[int] = None) -> List[Tuple[int, str, Optional[str], str]]:
    """Get questions from database with LRU caching"""
    session = get_session()
    try:
        query = session.query(Question).filter(Question.is_active == 1)
        
        if age is not None:
            query = query.filter(Question.min_age <= age, Question.max_age >= age)
            
        # --- UPDATED QUERY with response_type ---
        questions = query.with_entities(
            Question.id, 
            Question.question_text, 
            Question.tooltip,
            Question.response_type
        ).order_by(Question.id).all()
        
        rows = [(q.id, q.question_text, q.tooltip, q.response_type) for q in questions]
        # ----------------------------------------
        
        if not rows:
            raise RuntimeError("No questions found in database")
            
        logger.info(f"Loaded {len(rows)} questions from DB (age filter: {age})")
        return rows
    finally:
        session.close()

def _try_database_cache(session: Session, age: Optional[int] = None) -> List[Tuple[int, str, Optional[str], str]]:
    """Try to get questions from database cache table first"""
    try:
        query = session.query(QuestionCache).filter(QuestionCache.is_active == 1)
        
        cached = query.order_by(QuestionCache.question_id).all()
        
        if cached:
            # Update access counts in background
            def update_access_counts():
                try:
                    with get_session() as update_session:
                        for cache_entry in cached:
                            cache_entry.access_count += 1
                        update_session.commit()
                except Exception as e:
                    logger.error(f"Failed to update access counts: {e}")
            
            threading.Thread(target=update_access_counts, daemon=True).start()
            
            # --- FIXED: Return 4-tuple with default 'scale' type ---
            # The QuestionCache table doesn't have response_type yet, so we default to 'scale'
            result = [(c.question_id, c.question_text, None, 'scale') for c in cached]
            # -----------------------------------------------------
            
            logger.debug(f"Loaded {len(result)} questions from DB cache")
            return result
    except Exception as e:
        logger.debug(f"Database cache not available: {e}")
    
    return None

def _preload_background(age: Optional[int] = None):
    """Preload questions in background thread"""
    def preload():
        try:
            logger.debug(f"Background preloading questions (age filter: {age})")
            
            # Load from database
            questions = _get_cached_questions_from_db(age)
            
            # Update memory cache
            cache_key = _get_cache_key(age)
            with _cache_lock:
                _questions_cache[cache_key] = questions
                _cache_timestamps[cache_key] = time.time()
            
            # Save to disk cache in background
            threading.Thread(
                target=_save_to_disk_cache,
                args=(questions, age),
                daemon=True
            ).start()
            
            logger.debug(f"Background preload completed: {len(questions)} questions")
        except Exception as e:
            logger.error(f"Background preload failed: {e}")
    
    thread = threading.Thread(target=preload, daemon=True)
    thread.start()

def _warmup_cache():
    """Warm up cache on module import"""
    global _last_preload_time
    
    current_time = time.time()
    if current_time - _last_preload_time > _preload_interval:
        _preload_background(None)  # Preload all questions
        _last_preload_time = current_time

def load_questions(
    age: Optional[int] = None,
    db_path: Optional[str] = None
) -> List[Tuple[int, str, Optional[str], str]]:
    """
    Load questions from DB using ORM with multi-level caching.
    Returns list of (id, question_text, tooltip, type) tuples.
    """
    if isinstance(age, str) and db_path is None:
        try:
            age = int(age) if age else None
        except ValueError:
            age = None
    
    cache_key = _get_cache_key(age)
    
    # 1. Check memory cache first
    if _is_cache_valid(cache_key) and cache_key in _questions_cache:
        # Verify tuple size just in case
        cached_data = _questions_cache[cache_key]
        if cached_data and len(cached_data[0]) == 4:
            logger.debug(f"Memory cache hit for {cache_key}")
            return cached_data
    
    # 2. Check disk cache
    with _cache_lock:
        disk_cache = _load_from_disk_cache(age)
        if disk_cache is not None:
            _questions_cache[cache_key] = disk_cache
            _cache_timestamps[cache_key] = time.time()
            logger.debug(f"Disk cache hit for {cache_key}")
            return disk_cache
    
    # 3. Try database cache table (Warning: this might return default 'scale' types)
    session = get_session()
    try:
        db_cache = _try_database_cache(session, age)
        # Only use DB cache if we are sure it's valid, otherwise prefer main DB reload
        # For now, let's skip DB cache fallback if we really need accurate types
        # But to prevent crash, we return the Safe Tuple constructed in _try_database_cache
        if db_cache is not None:
             pass # Logic handles it in _try_database_cache
    finally:
        session.close()
    
    # 4. Load from database (The Source of Truth)
    logger.debug(f"Cache miss for {cache_key}, loading from database...")
    start_time = time.time()
    
    try:
        questions = _get_cached_questions_from_db(age)
        
        with _cache_lock:
            _questions_cache[cache_key] = questions
            _cache_timestamps[cache_key] = time.time()
        
        threading.Thread(
            target=_save_to_disk_cache,
            args=(questions, age),
            daemon=True
        ).start()
        
        load_time = time.time() - start_time
        logger.info(f"Loaded {len(questions)} questions from DB in {load_time:.3f}s (age filter: {age})")
        
        return questions
        
    except Exception as e:
        logger.error(f"Failed to load questions: {e}")
        raise RuntimeError("No questions found in database")

# ------------------ ADDITIONAL OPTIMIZATION FUNCTIONS ------------------

def get_question_count(age: Optional[int] = None) -> int:
    """Get count of active questions (optimized)"""
    cache_key = f"count_age_{age}" if age is not None else "count_all"
    
    # Check statistics cache first
    session = get_session()
    try:
        stat = session.query(StatisticsCache).filter(
            StatisticsCache.stat_name == cache_key,
            StatisticsCache.valid_until > datetime.now().isoformat()
        ).first()
        
        if stat:
            return int(stat.stat_value)
    finally:
        session.close()
    
    # Count from database
    session = get_session()
    try:
        query = session.query(Question).filter(Question.is_active == 1)
        
        if age is not None:
            query = query.filter(Question.min_age <= age, Question.max_age >= age)
            
        count = query.count()
        
        # Update cache in background
        def update_cache():
            try:
                with get_session() as update_session:
                    cache_entry = StatisticsCache(
                        stat_name=cache_key,
                        stat_value=float(count),
                        calculated_at=datetime.now().isoformat(),
                        valid_until=(datetime.now() + timedelta(hours=1)).isoformat()
                    )
                    update_session.merge(cache_entry)
                    update_session.commit()
            except Exception as e:
                logger.error(f"Failed to update count cache: {e}")
        
        threading.Thread(target=update_cache, daemon=True).start()
        
        return count
    finally:
        session.close()

def preload_all_question_sets():
    """Preload common question sets in background"""
    common_ages = [None, 18, 25, 35, 50, 65]  # Common age filters
    
    for age in common_ages:
        _preload_background(age)

def clear_all_caches():
    """Clear all caches (for testing or updates)"""
    global _questions_cache, _cache_timestamps, _last_preload_time
    
    with _cache_lock:
        _questions_cache.clear()
        _cache_timestamps.clear()
    
    # Clear disk cache
    try:
        if os.path.exists(CACHE_DIR):
            for file in os.listdir(CACHE_DIR):
                if file.endswith('.json'):
                    os.remove(os.path.join(CACHE_DIR, file))
    except Exception as e:
        logger.error(f"Failed to clear disk cache: {e}")
    
    # Clear database caches
    session = get_session()
    try:
        session.query(QuestionCache).delete()
        session.query(StatisticsCache).delete()
        session.commit()
        logger.info("All caches cleared")
    except Exception as e:
        logger.error(f"Failed to clear database caches: {e}")
        session.rollback()
    finally:
        session.close()
    
    return True

# ------------------ INITIALIZATION ------------------

# Ensure cache directory exists
_ensure_cache_dir()

# Warm up cache on import (non-blocking)
threading.Thread(target=_warmup_cache, daemon=True).start()

# Preload common question sets in background
threading.Thread(target=preload_all_question_sets, daemon=True).start()
