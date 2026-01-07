import os
import sys
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_connection

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
TXT_PATH = os.path.join(BASE_DIR, "data", "question_bank.txt")

def load_questions():
    print("--- STARTING DATA LOAD ---")
    conn = get_connection()
    cursor = conn.cursor()

    print("Checking database schema...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS question_bank (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_text TEXT NOT NULL,
        response_type TEXT DEFAULT 'scale',
        is_active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)

    try:
        cursor.execute("SELECT response_type FROM question_bank LIMIT 1")
    except Exception:
        print("Adding missing column: response_type")
        cursor.execute("ALTER TABLE question_bank ADD COLUMN response_type TEXT DEFAULT 'scale'")

    if not os.path.exists(TXT_PATH):
        print(f"ERROR: File not found at {TXT_PATH}")
        return

    with open(TXT_PATH, "r", encoding="utf-8") as f:
        raw_lines = [line.strip() for line in f if line.strip()]

    print(f"Found {len(raw_lines)} lines in text file.")

    count = 0
    for line in raw_lines:
        response_type = "scale"
        question_text = line

        if "[OPEN]" in line:
            response_type = "text"
            question_text = line.replace("[OPEN]", "").strip()

        cursor.execute("SELECT id FROM question_bank WHERE question_text = ?", (question_text,))
        if cursor.fetchone():
            continue

        cursor.execute(
            """
            INSERT INTO question_bank 
            (question_text, response_type, is_active, created_at) 
            VALUES (?, ?, 1, ?)
            """,
            (question_text, response_type, datetime.now(timezone.utc).isoformat())
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"SUCCESS: Loaded {count} new questions into DB.")
    print("--- DONE ---")

if __name__ == "__main__":
    load_questions()