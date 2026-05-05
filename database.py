import pg8000
import os
import logging

logger = logging.getLogger(__name__)

def get_connection():
    try:
        conn = pg8000.connect(os.environ.get("NEON_DATABASE_URL"))
        return conn
    except Exception as e:
        try:
            import re
            url = os.environ.get("NEON_DATABASE_URL")
            pattern = r'postgresql://([^:]+):([^@]+)@([^/]+)/(.+)'
            match = re.match(pattern, url)
            conn = pg8000.connect(
                user=match.group(1),
                password=match.group(2),
                host=match.group(3),
                database=match.group(4),
                ssl_context=True
            )
            return conn
        except Exception as e2:
            logger.error(f"Database connection failed: {e2}")
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
