import schedule
import time
import logging
import threading

from database import (
    create_tables,
    get_connection
)

# Scanner file se run_scanner function import ho raha hai
from scanner import run_scanner

# Bot listener jo Telegram commands handle karega
from bot_handler import start_bot_listener

# Token refresh logic
from token_manager import refresh_fyers_token

# Alerts logic
from telegram_alert import (
    send_daily_summary,
    send_trade_update
)

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def daily_summary():
    """Din bhar ke top 5 signals ki summary bhejta hai"""
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
    """Din khatam hone par PnL aur performance review bhejta hai"""
    conn = get_connection()
    if not conn:
        return

    try:
        cursor = conn.cursor()
        
        # Wins calculation
        cursor.execute("""
            SELECT COUNT(*) FROM trade_analytics 
            WHERE result IN ('TARGET1_HIT', 'TARGET2_HIT') 
            AND created_at::date = CURRENT_DATE
        """)
        wins = cursor.fetchone()[0]

        # Losses calculation
        cursor.execute("""
            SELECT COUNT(*) FROM trade_analytics 
            WHERE result = 'SL_HIT' 
            AND created_at::date = CURRENT_DATE
        """)
        losses = cursor.fetchone()[0]

        # Performance Report Template
        report = f'''
📊 *PETS DAILY PERFORMANCE REVIEW*

✅ Wins: {wins}
❌ Losses: {losses}

🚀 PETS memory updated successfully.
'''
        send_trade_update("DAILY REVIEW", report)
        cursor.close()
        conn.close()
        logger.info("Daily review generated.")
    except Exception as e:
        logger.error(f"Performance analysis error: {e}")

def main():
    logger.info("PETS Engine starting...")

    # 1. Database tables check/create karein
    create_tables()

    # 2. Telegram Bot ko alag thread mein start karein
    bot_thread = threading.Thread(
        target=start_bot_listener,
        daemon=True
    )
    bot_thread.start()

    # --- SCHEDULING LOGIC ---

    # Har 30 seconds mein scanner run hoga
    schedule.every(30).seconds.do(run_scanner)

    # Roz subah 8 baje token refresh
    schedule.every().day.at("08:00").do(refresh_fyers_token)

    # Market close hone ke baad summaries (Timing badal sakte hain)
    schedule.every().day.at("15:35").do(daily_summary)
    schedule.every().day.at("15:40").do(analyze_daily_performance)

    logger.info("Schedules active. PETS is now running.")

    # Loop jo schedules ko check karta rahega
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
