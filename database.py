import pg8000
import os
import logging
from datetime import datetime

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

    # 1. Raw Signals Table
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

    # 2. Simple Trade Log (Legacy support)
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

    # 3. Active Management Table (The Brain of PETS)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_signals (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            setup_type TEXT DEFAULT 'VWAP_MOMENTUM',
            status TEXT DEFAULT 'NEW',
            entry_price NUMERIC(12,4),
            stop_loss NUMERIC(12,4),
            target1 NUMERIC(12,4),
            target2 NUMERIC(12,4),
            score INTEGER,
            rr NUMERIC(12,4),
            quantity INTEGER,
            signal_time TIMESTAMP DEFAULT NOW(),
            last_updated TIMESTAMP DEFAULT NOW(),
            expiry_time TIMESTAMP,
            telegram_message_id TEXT,
            bought BOOLEAN DEFAULT FALSE,
            sold BOOLEAN DEFAULT FALSE,
            notes TEXT,
            cooldown_until TIMESTAMP
        );
    """)

    # 4. Long-term Analytics Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_analytics (
            id SERIAL PRIMARY KEY,
            symbol TEXT,
            setup_type TEXT,
            market_regime TEXT,
            result TEXT,
            entry_price NUMERIC(12,4),
            exit_price NUMERIC(12,4),
            stop_loss NUMERIC(12,4),
            target1 NUMERIC(12,4),
            target2 NUMERIC(12,4),
            quantity INTEGER,
            pnl NUMERIC(12,2),
            rr NUMERIC(12,4),
            holding_minutes INTEGER,
            confidence INTEGER,
            notes TEXT,
            sector TEXT,
            final_state TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    conn.commit()
    cursor.close()
    conn.close()
    logger.info("PETS Database Tables Ready.")

def is_signal_active(symbol):
    try:
        conn = get_connection()
        if not conn: return False
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM active_signals
            WHERE symbol = %s
            AND (
                status IN ('NEW', 'ACTIVE', 'BOUGHT')
                OR (cooldown_until IS NOT NULL AND cooldown_until > NOW())
            )
            LIMIT 1
        """, (symbol,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"Error checking active signal: {e}")
        return False

def expire_old_signals():
    try:
        conn = get_connection()
        if not conn: return
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE active_signals
            SET status = 'EXPIRED'
            WHERE status = 'NEW'
            AND signal_time < NOW() - INTERVAL '2 hours'
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Expire signal error: {e}")

def get_active_bought_trades():
    try:
        conn = get_connection()
        if not conn: return []
        cursor = conn.cursor()
        cursor.execute("""
            SELECT symbol, entry_price, stop_loss, target1, target2, 
                   quantity, rr, score, signal_time, setup_type
            FROM active_signals
            WHERE status = 'BOUGHT'
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Fetch active trades error: {e}")
        return []

def close_trade(symbol, result, exit_price=None):
    try:
        conn = get_connection()
        if not conn: return
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT entry_price, stop_loss, target1, target2, quantity, 
                   rr, score, signal_time, setup_type
            FROM active_signals
            WHERE symbol = %s
            AND status IN ('BOUGHT', 'ACTIVE', 'NEW')
            ORDER BY signal_time DESC LIMIT 1
        """, (symbol,))
        trade = cursor.fetchone()
        
        if not trade:
            cursor.close()
            conn.close()
            return

        (entry_price, stop_loss, target1, target2, quantity, 
         rr, score, signal_time, setup_type) = trade

        holding_minutes = int((datetime.utcnow() - signal_time).total_seconds() / 60)
        pnl = round((float(exit_price or 0) - float(entry_price)) * int(quantity), 2) if exit_price else 0

        # Silent Sector Fetch
        sector = None
        try:
            from strategy import SECTOR_MAP
            sector = SECTOR_MAP.get(symbol)
        except: pass

        # Log into Analytics
        cursor.execute("""
            INSERT INTO trade_analytics
            (symbol, setup_type, market_regime, result, entry_price, exit_price, 
             stop_loss, target1, target2, quantity, pnl, rr, holding_minutes, confidence, sector)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (symbol, setup_type, setup_type, result, entry_price, exit_price, 
              stop_loss, target1, target2, quantity, pnl, rr, holding_minutes, score, sector))

        # Update Active Signal Status
        cursor.execute("""
            UPDATE active_signals
            SET status = %s, sold = TRUE, last_updated = NOW(),
                cooldown_until = NOW() + INTERVAL '45 minutes'
            WHERE symbol = %s AND status IN ('BOUGHT', 'ACTIVE', 'NEW')
        """, (result, symbol))

        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Trade finalized: {symbol} | Result: {result}")
    except Exception as e:
        logger.error(f"Close trade error: {e}")

def update_stop_loss(symbol, new_sl):
    try:
        conn = get_connection()
        if not conn: return
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE active_signals
            SET stop_loss = %s, last_updated = NOW()
            WHERE symbol = %s AND status = 'BOUGHT'
        """, (new_sl, symbol))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"SL update error: {e}")

def update_trade_note(symbol, note):
    """Saves a note/feedback for an active signal."""
    conn = get_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE active_signals
            SET notes = %s
            WHERE symbol = %s
            AND status != 'CLOSED'
        """, (note, symbol))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Update trade note error: {e}")

def save_trade_analytics(symbol, result, entry_price, exit_price, stop_loss, target1, target2, rr, score, regime, state):
    conn = get_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trade_analytics (
                symbol, result, entry_price, exit_price, stop_loss, 
                target1, target2, rr, score, market_regime, final_state, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (symbol, result, entry_price, exit_price, stop_loss, target1, target2, rr, score, regime, state))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Manual analytics save error: {e}")

def get_trade_performance_summary():
    """Fetches win/loss summary for the last 7 days."""
    conn = get_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN result IN ('TARGET1_HIT', 'TARGET2_HIT') THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result IN (
                    'SL_HIT', 'SOS_EXIT', 'DEAD_EXIT', 
                    'QUALITY_DECAY_EXIT', 'CONFIDENCE_EXIT', 'MARKET_PANIC_EXIT'
                ) THEN 1 ELSE 0 END) as losses
            FROM trade_analytics
            WHERE created_at >= NOW() - INTERVAL '7 days'
        """)

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row or row[0] == 0:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0}

        total = int(row[0])
        wins = int(row[1] or 0)
        losses = int(row[2] or 0)
        win_rate = round((wins / total) * 100, 2) if total > 0 else 0

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate
        }
    except Exception as e:
        logger.error(f"Performance summary calculation error: {e}")
        return None
