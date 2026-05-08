import schedule
import time
import logging
import threading
from database import create_tables
from scanner import run_scanner
from bot_handler import start_bot_listener
from token_manager import refresh_fyers_token
from telegram_alert import send_daily_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def daily_summary():
    from database import get_connection
    conn = get_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, confidence, entry_price, target FROM signals WHERE created_at::date = CURRENT_DATE ORDER BY confidence DESC LIMIT 5")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        count = len(rows)
        top = ""
        for r in rows:
            top += f"• {r[0]} | Confidence: {r[1]}% | Entry: ₹{r[2]} | Target: ₹{r[3]}\n"
        if not top:
            top = "No signals today."
        send_daily_summary(count, top)
    except Exception as e:
        logger.error(f"Daily summary error: {e}")

def main():
    logger.info("PETS Engine started.")
    create_tables()

    bot_thread = threading.Thread(target=start_bot_listener, daemon=True)
    bot_thread.start()

    schedule.every(30).seconds.do(run_scanner)
    schedule.every().day.at("08:00").do(refresh_fyers_token)
    schedule.every().day.at("10:00").do(daily_summary)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
