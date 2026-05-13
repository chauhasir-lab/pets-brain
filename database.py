import pg8000
import os
import logging

logger = logging.getLogger(__name__)


def get_connection():

    try:

        conn = pg8000.connect(
            os.environ.get("NEON_DATABASE_URL")
        )

        return conn

    except Exception:

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

    # Historical signals
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

    # Trade log
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

    # Active lifecycle trades
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

            notes TEXT
        );
    """)

    # Analytics memory
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

            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    conn.commit()

    cursor.close()
    conn.close()

    logger.info("Tables ready.")


def is_signal_active(symbol):

    try:

        conn = get_connection()

        if not conn:
            return False

        cursor = conn.cursor()

        cursor.execute("""
            SELECT id
            FROM active_signals
            WHERE symbol = %s

            AND (
                status IN (
                    'NEW',
                    'ACTIVE',
                    'BOUGHT'
                )

                OR (
                    cooldown_until IS NOT NULL
                    AND cooldown_until > NOW()
                )
            )

            LIMIT 1
        """, (symbol,))

        result = cursor.fetchone()

        cursor.close()
        conn.close()

        return result is not None

    except Exception as e:

        logger.error(
            f"Error checking active signal: {e}"
        )

        return False
def expire_old_signals():

    try:

        conn = get_connection()

        if not conn:
            return

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

        if not conn:
            return []

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                symbol,
                entry_price,
                stop_loss,
                target1,
                target2,
                quantity,
                rr,
                score,
                signal_time,
                setup_type
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

        if not conn:
            return

        cursor = conn.cursor()

        # Fetch trade data
        cursor.execute("""
            SELECT
                symbol,
                setup_type,
                entry_price,
                stop_loss,
                target1,
                target2,
                quantity,
                rr,
                score,
                signal_time,
                notes
            FROM active_signals
            WHERE symbol = %s
            AND status = 'BOUGHT'
            LIMIT 1
        """, (symbol,))

        trade = cursor.fetchone()

        if not trade:
            cursor.close()
            conn.close()
            return

        (
            symbol,
            setup_type,
            entry_price,
            stop_loss,
            target1,
            target2,
            quantity,
            rr,
            confidence,
            signal_time,
            notes
        ) = trade

        if exit_price is None:
            exit_price = entry_price

        pnl = (
            (float(exit_price) - float(entry_price))
            * int(quantity)
        )

        holding_minutes = 0

        try:
            from datetime import datetime

            holding_minutes = int(
                (datetime.utcnow() - signal_time).total_seconds() / 60
            )
        except Exception:
            pass

        # Save analytics
        cursor.execute("""
            INSERT INTO trade_analytics
            (
                symbol,
                setup_type,
                market_regime,
                result,
                entry_price,
                exit_price,
                stop_loss,
                target1,
                target2,
                quantity,
                pnl,
                rr,
                holding_minutes,
                confidence,
                notes
            )
            VALUES
            (%s, %s, %s, %s, %s, %s, %s,
             %s, %s, %s, %s, %s, %s,
             %s, %s)
        """, (
            symbol,
            setup_type,
            "UNKNOWN",
            result,
            entry_price,
            exit_price,
            stop_loss,
            target1,
            target2,
            quantity,
            pnl,
            rr,
            holding_minutes,
            confidence,
            notes
        ))

        # Close active trade
        cursor.execute("""
            UPDATE active_signals
            SET status = %s,
                sold = TRUE,
                last_updated = NOW()
                cooldown_until = NOW() + INTERVAL '45 minutes'
            WHERE symbol = %s
            AND status = 'BOUGHT'
        """, (result, symbol))

        conn.commit()

        cursor.close()
        conn.close()

        logger.info(f"Trade closed and saved: {symbol}")

    except Exception as e:

        logger.error(f"Close trade error: {e}")


def update_trade_note(symbol, note):

    try:

        conn = get_connection()

        if not conn:
            return

        cursor = conn.cursor()

        cursor.execute("""
            UPDATE active_signals
            SET notes = %s,
                last_updated = NOW()
            WHERE symbol = %s
            AND status = 'BOUGHT'
        """, (note, symbol))

        conn.commit()

        cursor.close()
        conn.close()

    except Exception as e:

        logger.error(f"Trade note update error: {e}")
