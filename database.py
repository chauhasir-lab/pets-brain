import pg8000
import os
import logging
import re
from datetime import datetime
from contextlib import closing  # Step 1: Added closing for safety

logger = logging.getLogger(__name__)

def get_connection():
    try:
        # Standard Neon/Postgres connection string
        conn = pg8000.connect(
            os.environ.get("NEON_DATABASE_URL")
        )
        return conn
    except Exception:
        try:
            # Fallback parsing for specific environments
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

# STEP 2: Database Safety Wrapper
def execute_query(query, params=None, fetchone=False, fetchall=False, commit=False):
    conn = get_connection()
    if not conn:
        return None
    try:
        with closing(conn.cursor()) as cursor:
            cursor.execute(query, params or ())
            result = None
            if fetchone:
                result = cursor.fetchone()
            elif fetchall:
                result = cursor.fetchall()
            
            if commit:
                conn.commit()
            return result
    except Exception as e:
        logger.error(f"Database query error: {e}")
        return None
    finally:
        conn.close()

def create_tables():
    # Table creation queries
    queries = [
        """CREATE TABLE IF NOT EXISTS signals (
            id SERIAL PRIMARY KEY, symbol TEXT NOT NULL, action TEXT NOT NULL,
            entry_price NUMERIC(12,4), stop_loss NUMERIC(12,4), target NUMERIC(12,4),
            confidence INTEGER, reason TEXT, created_at TIMESTAMP DEFAULT NOW()
        );""",
        """CREATE TABLE IF NOT EXISTS trade_log (
            id SERIAL PRIMARY KEY, symbol TEXT, action TEXT, result TEXT,
            pnl NUMERIC(12,2), created_at TIMESTAMP DEFAULT NOW()
        );""",
        """CREATE TABLE IF NOT EXISTS active_signals (
            id SERIAL PRIMARY KEY, symbol TEXT NOT NULL, setup_type TEXT DEFAULT 'VWAP_MOMENTUM',
            status TEXT DEFAULT 'NEW', entry_price NUMERIC(12,4), stop_loss NUMERIC(12,4),
            target1 NUMERIC(12,4), target2 NUMERIC(12,4), score INTEGER, rr NUMERIC(12,4),
            quantity INTEGER, signal_time TIMESTAMP DEFAULT NOW(), last_updated TIMESTAMP DEFAULT NOW(),
            expiry_time TIMESTAMP, telegram_message_id TEXT, bought BOOLEAN DEFAULT FALSE,
            sold BOOLEAN DEFAULT FALSE, notes TEXT, cooldown_until TIMESTAMP
        );""",
        """CREATE TABLE IF NOT EXISTS trade_analytics (
            id SERIAL PRIMARY KEY, symbol TEXT, setup_type TEXT, market_regime TEXT,
            result TEXT, entry_price NUMERIC(12,4), exit_price NUMERIC(12,4),
            stop_loss NUMERIC(12,4), target1 NUMERIC(12,4), target2 NUMERIC(12,4),
            quantity INTEGER, pnl NUMERIC(12,2), rr NUMERIC(12,4), holding_minutes INTEGER,
            confidence INTEGER, notes TEXT, sector TEXT, final_state TEXT, created_at TIMESTAMP DEFAULT NOW()
        );"""
    ]
    for q in queries:
        execute_query(q, commit=True)
    logger.info("PETS Database Tables Hardened & Ready.")

def is_signal_active(symbol):
    query = """
        SELECT id FROM active_signals
        WHERE symbol = %s
        AND (status IN ('NEW', 'ACTIVE', 'BOUGHT')
        OR (cooldown_until IS NOT NULL AND cooldown_until > NOW()))
        LIMIT 1
    """
    result = execute_query(query, (symbol,), fetchone=True)
    return result is not None

def expire_old_signals():
    query = """
        UPDATE active_signals SET status = 'EXPIRED'
        WHERE status = 'NEW' AND signal_time < NOW() - INTERVAL '2 hours'
    """
    execute_query(query, commit=True)

def get_active_bought_trades():
    query = """
        SELECT symbol, entry_price, stop_loss, target1, target2, 
               quantity, rr, score, signal_time, setup_type
        FROM active_signals WHERE status = 'BOUGHT'
    """
    return execute_query(query, fetchall=True) or []

def update_stop_loss(symbol, new_sl):
    query = """
        UPDATE active_signals SET stop_loss = %s, last_updated = NOW()
        WHERE symbol = %s AND status = 'BOUGHT'
    """
    execute_query(query, (new_sl, symbol), commit=True)

def update_trade_note(symbol, note):
    query = """
        UPDATE active_signals SET notes = %s
        WHERE symbol = %s AND status != 'CLOSED'
    """
    execute_query(query, (note, symbol), commit=True)

def get_trade_performance_summary():
    query = """
        SELECT COUNT(*) as total,
               SUM(CASE WHEN result IN ('TARGET1_HIT', 'TARGET2_HIT') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN result IN ('SL_HIT', 'SOS_EXIT', 'DEAD_EXIT', 'QUALITY_DECAY_EXIT', 'CONFIDENCE_EXIT', 'MARKET_PANIC_EXIT') THEN 1 ELSE 0 END) as losses
        FROM trade_analytics
        WHERE created_at >= NOW() - INTERVAL '7 days'
    """
    row = execute_query(query, fetchone=True)
    if not row or row[0] == 0:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0}
    
    total, wins, losses = int(row[0]), int(row[1] or 0), int(row[2] or 0)
    return {
        "total": total, "wins": wins, "losses": losses,
        "win_rate": round((wins / total) * 100, 2)
    }

def close_trade(symbol, result, exit_price=None):
    # Fetch trade details first
    fetch_query = """
        SELECT entry_price, stop_loss, target1, target2, quantity, 
               rr, score, signal_time, setup_type
        FROM active_signals
        WHERE symbol = %s AND status IN ('BOUGHT', 'ACTIVE', 'NEW')
        ORDER BY signal_time DESC LIMIT 1
    """
    trade = execute_query(fetch_query, (symbol,), fetchone=True)
    
    if not trade:
        return

    (entry_price, stop_loss, target1, target2, quantity, rr, score, signal_time, setup_type) = trade
    holding_minutes = int((datetime.utcnow() - signal_time).total_seconds() / 60)
    pnl = round((float(exit_price or 0) - float(entry_price)) * int(quantity), 2) if exit_price else 0

    # Log into Analytics
    analytics_query = """
        INSERT INTO trade_analytics
        (symbol, setup_type, market_regime, result, entry_price, exit_price, 
         stop_loss, target1, target2, quantity, pnl, rr, holding_minutes, confidence)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    execute_query(analytics_query, (symbol, setup_type, setup_type, result, entry_price, exit_price, 
                                   stop_loss, target1, target2, quantity, pnl, rr, holding_minutes, score), commit=True)

    # Update Status
    status_query = """
        UPDATE active_signals
        SET status = %s, sold = TRUE, last_updated = NOW(),
            cooldown_until = NOW() + INTERVAL '45 minutes'
        WHERE symbol = %s AND status IN ('BOUGHT', 'ACTIVE', 'NEW')
    """
    execute_query(status_query, (result, symbol), commit=True)
    logger.info(f"Trade finalized safely: {symbol}")
