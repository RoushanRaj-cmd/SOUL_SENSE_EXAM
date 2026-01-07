from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, Boolean, Index, func, event
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone
import logging

Base = declarative_base()
logger = logging.getLogger(__name__)

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False, index=True)  # Added index
    password_hash = Column(String, nullable=False)
    created_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat(), index=True)  # Added index
    last_login = Column(String, nullable=True, index=True)  # Added index

    # Relationships
    scores = relationship("Score", back_populates="user", cascade="all, delete-orphan")
    responses = relationship("Response", back_populates="user", cascade="all, delete-orphan")

    # Composite index for common query patterns
    __table_args__ = (
        Index('idx_user_username_created', 'username', 'created_at'),
    )

class Score(Base):
    __tablename__ = 'scores'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, index=True)  # Added index
    total_score = Column(Integer, index=True)  # Added index
    age = Column(Integer, index=True)  # Added index
    detailed_age_group = Column(String, index=True)  # Added index
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)  # Added index
    timestamp = Column(String, default=lambda: datetime.now(timezone.utc).isoformat(), index=True)  # Added timestamp and index

    user = relationship("User", back_populates="scores")

    # Composite indexes for performance
    __table_args__ = (
        Index('idx_score_username_timestamp', 'username', 'timestamp'),
        Index('idx_score_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_score_age_score', 'age', 'total_score'),
        Index('idx_score_agegroup_score', 'detailed_age_group', 'total_score'),
    )

class Response(Base):
    __tablename__ = 'responses'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, index=True)  # Added index
    question_id = Column(Integer, index=True)  # Added index
    response_value = Column(Integer, index=True)  # Added index
    response_text = Column(Text, nullable=True)   # Stores the open-ended answer
    sentiment_score = Column(Float, nullable=True) # Stores the NLTK compound score (-1.0 to 1.0)
    age_group = Column(String, index=True)  # Added index
    detailed_age_group = Column(String, index=True)  # Added index
    timestamp = Column(String, default=lambda: datetime.now(timezone.utc).isoformat(), index=True)  # Added index
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)  # Added index

    user = relationship("User", back_populates="responses")

    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_response_user_question', 'user_id', 'question_id'),
        Index('idx_response_username_timestamp', 'username', 'timestamp'),
        Index('idx_response_question_timestamp', 'question_id', 'timestamp'),
        Index('idx_response_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_response_agegroup_timestamp', 'detailed_age_group', 'timestamp'),
    )

class QuestionCategory(Base):
    __tablename__ = 'question_category'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, index=True)  # Added index
    description = Column(Text)

    # Index for name lookups
    __table_args__ = (
        Index('idx_category_name', 'name'),
    )

class Question(Base):
    __tablename__ = 'question_bank'

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_text = Column(Text, nullable=False)
    response_type = Column(String, default="scale", nullable=False)
    category_id = Column(Integer, default=0, index=True)  # Added index
    difficulty = Column(Integer, default=1, index=True)  # Added index
    min_age = Column(Integer, default=0)
    max_age = Column(Integer, default=120)
    weight = Column(Float, default=1.0)
    is_active = Column(Integer, default=1, index=True)  # Added index
    tooltip = Column(Text, nullable=True)
    created_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat(), index=True)  # Added index

    # Composite indexes for optimized querying
    __table_args__ = (
        Index('idx_question_active_difficulty', 'is_active', 'difficulty'),
        Index('idx_question_category_active', 'category_id', 'is_active'),
        Index('idx_question_active_created', 'is_active', 'created_at'),
        Index('idx_question_age_range', 'min_age', 'max_age'),
        Index('idx_question_fulltext', 'question_text'),  # For full-text search if supported
    )

class QuestionMetadata(Base):
    __tablename__ = 'question_metadata'
    
    question_id = Column(Integer, primary_key=True, index=True)  # Added index
    source = Column(String, index=True)  # Added index
    version = Column(String, index=True)  # Added index
    tags = Column(String, index=True)  # Added index

    # Composite index for version and source queries
    __table_args__ = (
        Index('idx_metadata_source_version', 'source', 'version'),
        Index('idx_metadata_tags', 'tags'),
    )

class JournalEntry(Base):
    __tablename__ = 'journal_entries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, index=True)  # Added index
    entry_date = Column(String, default=lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), index=True)  # Added index
    content = Column(Text)
    sentiment_score = Column(Float, index=True)  # Added index
    emotional_patterns = Column(Text)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)  # Added user_id and index

    # Composite indexes for common journal queries
    __table_args__ = (
        Index('idx_journal_username_date', 'username', 'entry_date'),
        Index('idx_journal_user_sentiment', 'user_id', 'sentiment_score'),
        Index('idx_journal_date_sentiment', 'entry_date', 'sentiment_score'),
    )

# ==================== DATABASE PERFORMANCE OPTIMIZATIONS ====================

@event.listens_for(Base.metadata, 'before_create')
def receive_before_create(target, connection, **kw):
    """Optimize database settings before tables are created"""
    logger.info("Optimizing database settings...")
    
    # SQLite specific optimizations
    if connection.engine.name == 'sqlite':
        connection.execute('PRAGMA journal_mode = WAL')  # Write-Ahead Logging for better concurrency
        connection.execute('PRAGMA synchronous = NORMAL')  # Good balance of safety and performance
        connection.execute('PRAGMA cache_size = -2000')  # 2MB cache
        connection.execute('PRAGMA temp_store = MEMORY')  # Store temp tables in memory
        connection.execute('PRAGMA mmap_size = 268435456')  # 256MB memory map
        connection.execute('PRAGMA foreign_keys = ON')  # Enable foreign key constraints

@event.listens_for(Question.__table__, 'after_create')
def receive_after_create_question(target, connection, **kw):
    """Create additional indexes and optimizations after question table creation"""
    logger.info("Creating question search optimization indexes...")
    
    # Create full-text search virtual table if needed (for larger question banks)
    try:
        # Check if FTS5 extension is available
        connection.execute("SELECT fts5(?)", ('test',))
        
        # Create virtual table for full-text search
        connection.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS question_search 
            USING fts5(id, question_text, content='question_bank', content_rowid='id')
        """)
        
        # Create triggers to keep the search index updated
        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS question_ai AFTER INSERT ON question_bank BEGIN
                INSERT INTO question_search(rowid, question_text) VALUES (new.id, new.question_text);
            END;
        """)
        
        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS question_ad AFTER DELETE ON question_bank BEGIN
                INSERT INTO question_search(question_search, rowid, question_text) VALUES('delete', old.id, old.question_text);
            END;
        """)
        
        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS question_au AFTER UPDATE ON question_bank BEGIN
                INSERT INTO question_search(question_search, rowid, question_text) VALUES('delete', old.id, old.question_text);
                INSERT INTO question_search(rowid, question_text) VALUES (new.id, new.question_text);
            END;
        """)
        
        logger.info("Full-text search indexes created for questions")
    except:
        logger.warning("FTS5 not available, skipping full-text search optimization")

# ==================== CACHE AND PERFORMANCE TABLES ====================

class QuestionCache(Base):
    """Cache table for frequently accessed questions"""
    __tablename__ = 'question_cache'
    
    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey('question_bank.id'), unique=True, index=True)
    question_text = Column(Text, nullable=False)
    category_id = Column(Integer, index=True)
    difficulty = Column(Integer, index=True)
    is_active = Column(Integer, default=1, index=True)
    cached_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    access_count = Column(Integer, default=0, index=True)
    
    __table_args__ = (
        Index('idx_cache_active_difficulty', 'is_active', 'difficulty'),
        Index('idx_cache_category_active', 'category_id', 'is_active'),
        Index('idx_cache_access_time', 'access_count', 'cached_at'),
    )

class StatisticsCache(Base):
    """Cache for frequently calculated statistics"""
    __tablename__ = 'statistics_cache'
    
    id = Column(Integer, primary_key=True)
    stat_name = Column(String, unique=True, index=True)  # e.g., 'avg_score_global', 'question_count'
    stat_value = Column(Float)
    stat_json = Column(Text)  # For complex statistics
    calculated_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    valid_until = Column(String, index=True)
    
    __table_args__ = (
        Index('idx_stats_name_valid', 'stat_name', 'valid_until'),
    )

# ==================== PERFORMANCE HELPER FUNCTIONS ====================

def create_performance_indexes(engine):
    """Create additional performance indexes that might be needed"""
    with engine.connect() as conn:
        # Create indexes that might not be in the model definitions
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_responses_composite 
            ON responses(username, question_id, response_value, timestamp)
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_scores_composite 
            ON scores(username, total_score, age, timestamp)
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_questions_quick_load 
            ON question_bank(is_active, id, question_text)
        """)
        
        # Optimize the database
        conn.execute('PRAGMA optimize')
        
        logger.info("Performance indexes created and database optimized")

def preload_frequent_data(session):
    """Preload frequently accessed data into cache"""
    try:
        # Cache active questions
        active_questions = session.query(Question).filter(
            Question.is_active == 1
        ).order_by(Question.id).all()
        
        for question in active_questions:
            cache_entry = QuestionCache(
                question_id=question.id,
                question_text=question.question_text,
                category_id=question.category_id,
                difficulty=question.difficulty,
                is_active=question.is_active
            )
            session.merge(cache_entry)
        
        # Cache global statistics
        from sqlalchemy import func
        avg_score = session.query(func.avg(Score.total_score)).scalar() or 0
        question_count = session.query(func.count(Question.id)).filter(
            Question.is_active == 1
        ).scalar() or 0
        
        stats = [
            ('avg_score_global', avg_score, datetime.now(timezone.utc).isoformat()),
            ('question_count', question_count, datetime.now(timezone.utc).isoformat()),
            ('active_users', session.query(func.count(User.id)).scalar() or 0, 
             datetime.now(timezone.utc).isoformat())
        ]
        
        for stat_name, stat_value, calculated_at in stats:
            cache_entry = StatisticsCache(
                stat_name=stat_name,
                stat_value=stat_value,
                calculated_at=calculated_at,
                valid_until=(datetime.utcnow() + timedelta(hours=24)).isoformat()
            )
            session.merge(cache_entry)
        
        session.commit()
        logger.info("Frequent data preloaded into cache")
        
    except Exception as e:
        logger.error(f"Failed to preload data: {e}")
        session.rollback()

# ==================== QUERY OPTIMIZATION FUNCTIONS ====================

def get_active_questions_optimized(session, limit=None, offset=0):
    """Optimized query for loading active questions"""
    # Try cache first
    cached = session.query(QuestionCache).filter(
        QuestionCache.is_active == 1
    ).order_by(QuestionCache.question_id)
    
    if limit:
        cached = cached.limit(limit)
    if offset:
        cached = cached.offset(offset)
    
    cached_results = cached.all()
    
    if cached_results:
        # Update access count
        for cache_entry in cached_results:
            cache_entry.access_count += 1
        session.commit()
        
        return [(c.question_id, c.question_text) for c in cached_results]
    
    # Fallback to direct query if cache misses
    query = session.query(Question.id, Question.question_text).filter(
        Question.is_active == 1
    ).order_by(Question.id)
    
    if limit:
        query = query.limit(limit)
    if offset:
        query = query.offset(offset)
    
    return query.all()

def get_user_scores_optimized(session, username, limit=50):
    """Optimized query for user scores with pagination"""
    return session.query(Score).filter(
        Score.username == username
    ).order_by(
        Score.timestamp.desc()
    ).limit(limit).all()

# Initialize logger
logging.basicConfig(level=logging.INFO)
