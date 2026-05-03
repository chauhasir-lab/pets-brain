import psycopg2
import os
import logging

logger = logging.getLogger(__name__)

def get_connection():
    try:
        conn = psycopg2.connect(os.environ.get("NEON_DATABASE_URL"))
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None

def create_tables():
    conn = get_connection()
    if not conn:
        return
    
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            entry_price NUMERIC(12,4),
            stop_loss NUMERIC(12,4),
            target NUMERIC(12,4),
            confidence INTEGER,
            reason TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_log (
            id SERIAL PRIMARY KEY,
            symbol TEXT,
            action TEXT,
            result TEXT,
            pnl NUMERIC(12,2),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Tables ready.")
