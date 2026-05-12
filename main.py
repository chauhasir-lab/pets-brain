import schedule
import time
import logging
import threading

from database import (
    create_tables,
    get_connection
)

from scanner import run_scanner

from bot_handler import start_bot_listener

from token_manager import refresh_fyers_token

from telegram_alert import (
    send_daily_summary,
    send_trade_update
)

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


def daily_summary():

    conn = get_connection()

    if not conn:
        return

    try:

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                symbol,
                confidence,
                entry_price,
                target
            FROM signals
            WHERE created_at::date = CURRENT_DATE
            ORDER BY confidence DESC
            LIMIT 5
        """)

        rows = cursor.fetchall()

        count = len(rows)

        top = ""

        for r in rows:

            top += (
                f"• {r[0]} | "
                f"Confidence: {r[1]}% | "
                f"Entry: ₹{r[2]} | "
                f"Target: ₹{r[3]}\n"
            )

        if not top:
            top = "No signals today."

        send_daily_summary(count, top)

        cursor.close()
        conn.close()

    except Exception as e:

        logger.error(f"Daily summary error: {e}")


def analyze_daily_performance():

    conn = get_connection()

    if not conn:
        return

    try:

        cursor = conn.cursor()

        # Wins
        cursor.execute("""
            SELECT COUNT(*)
            FROM trade_analytics
            WHERE result IN ('TARGET1_HIT', 'TARGET2_HIT')
            AND created_at::date = CURRENT_DATE
        """)

        wins = cursor.fetchone()[0]

        # Losses
        cursor.execute("""
            SELECT COUNT(*)
            FROM trade_analytics
            WHERE result = 'SL_HIT'
            AND created_at::date = CURRENT_DATE
        """)

        losses = cursor.fetchone()[0]

        # Best stock
        cursor.execute("""
            SELECT symbol, SUM(pnl) as total_pnl
            FROM trade_analytics
            WHERE created_at::date = CURRENT_DATE
            GROUP BY symbol
            ORDER BY total_pnl DESC
            LIMIT 1
        """)

        best_stock = cursor.fetchone()

        # Worst stock
        cursor.execute("""
            SELECT symbol, SUM(pnl) as total_pnl
            FROM trade_analytics
            WHERE created_at::date = CURRENT_DATE
            GROUP BY symbol
            ORDER BY total_pnl ASC
            LIMIT 1
        """)

        worst_stock = cursor.fetchone()

        # Best setup
        cursor.execute("""
            SELECT setup_type, COUNT(*)
            FROM trade_analytics
            WHERE result IN ('TARGET1_HIT', 'TARGET2_HIT')
            AND created_at::date = CURRENT_DATE
            GROUP BY setup_type
            ORDER BY COUNT(*) DESC
            LIMIT 1
        """)

        best_setup = cursor.fetchone()

        report = f'''
📊 PETS DAILY PERFORMANCE REVIEW

✅ Wins: {wins}
❌ Losses: {losses}

🏆 Best Stock:
{best_stock[0] if best_stock else "N/A"}

📉 Worst Stock:
{worst_stock[0] if worst_stock else "N/A"}

🧠 Best Setup:
{best_setup[0] if best_setup else "N/A"}

🚀 PETS memory updated successfully.
'''

        send_trade_update("DAILY REVIEW", report)

        cursor.close()
        conn.close()

        logger.info("Daily review generated.")

    except Exception as e:

        logger.error(f"Performance analysis error: {e}")


def main():

    logger.info("PETS Engine started.")

    create_tables()

    # Telegram bot listener
    bot_thread = threading.Thread(
        target=start_bot_listener,
        daemon=True
    )

    bot_thread.start()

    # Scanner
    schedule.every(30).seconds.do(run_scanner)

    # Token refresh
    schedule.every().day.at("08:00").do(
        refresh_fyers_token
    )

    # Daily signal summary
    schedule.every().day.at("15:35").do(
        daily_summary
    )

    # Daily self review
    schedule.every().day.at("15:40").do(
        analyze_daily_performance
    )

    while True:

        schedule.run_pending()

        time.sleep(1)


if __name__ == "__main__":

    main()
