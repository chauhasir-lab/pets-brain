import logging
import os
import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 10}
    if offset:
        params["offset"] = offset
    response = requests.get(url, params=params)
    return response.json()

def handle_command(command):
    from database import get_connection
    from scanner import run_scanner

    if command == "/status":
        send_message("✅ *PETS Engine Active*\n\nScanner: Running\nDatabase: Connected\nFyers: Connected")

    elif command == "/scan":
        send_message("🔍 Manual scan started...")
        run_scanner()
        send_message("✅ Scan complete.")

    elif command == "/signals":
        conn = get_connection()
        if not conn:
            send_message("❌ Database error.")
            return
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, action, entry_price, stop_loss, target, confidence, created_at FROM signals ORDER BY created_at DESC LIMIT 5")
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            if not rows:
                send_message("No signals found today.")
                return
            msg = "*Last 5 Signals:*\n\n"
            for row in rows:
                msg += f"📌 {row[0]} | {row[1]} | Entry: {row[2]} | SL: {row[3]} | Target: {row[4]} | Score: {row[5]}\n\n"
            send_message(msg)
        except Exception as e:
            send_message(f"Error: {e}")

    elif command == "/help":
        send_message("*PETS Commands:*\n\n/status - System status\n/scan - Manual scan\n/signals - Last 5 signals\n/help - Commands list")

def start_bot_listener():
    logger.info("Bot listener started.")
    offset = None
    while True:
        try:
            updates = get_updates(offset)
            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text", "")
                chat_id = str(message.get("chat", {}).get("id", ""))
                if chat_id == TELEGRAM_CHAT_ID and text.startswith("/"):
                    handle_command(text.strip())
        except Exception as e:
            logger.error(f"Bot listener error: {e}")
