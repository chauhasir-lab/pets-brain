import logging
import os
import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_message(text):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
    )


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

    parts = command.strip().split()

    base_command = parts[0].lower()

    symbol = None

    if len(parts) > 1:
        symbol = parts[1].upper()

    # STATUS
    if base_command == "/status":

        send_message(
            "✅ *PETS Engine Active*\n\n"
            "Scanner: Running\n"
            "Database: Connected\n"
            "Fyers: Connected"
        )

    # MANUAL SCAN
    elif base_command == "/scan":

        send_message("🔍 Manual scan started...")

        run_scanner()

        send_message("✅ Scan complete.")

    # LAST SIGNALS
    elif base_command == "/signals":

        conn = get_connection()

        if not conn:
            send_message("❌ Database error.")
            return

        try:

            cursor = conn.cursor()

            cursor.execute("""
                SELECT symbol,
                       action,
                       entry_price,
                       stop_loss,
                       target,
                       confidence,
                       created_at
                FROM signals
                ORDER BY created_at DESC
                LIMIT 5
            """)

            rows = cursor.fetchall()

            cursor.close()
            conn.close()

            if not rows:
                send_message("No signals found today.")
                return

            msg = "*Last 5 Signals:*\n\n"

            for row in rows:

                msg += (
                    f"📌 {row[0]} | {row[1]}\n"
                    f"Entry: ₹{row[2]}\n"
                    f"SL: ₹{row[3]}\n"
                    f"Target: ₹{row[4]}\n"
                    f"Score: {row[5]}\n\n"
                )

            send_message(msg)

        except Exception as e:

            send_message(f"Error: {e}")

    # BOUGHT
    elif base_command == "/bought" and symbol:

        try:

            conn = get_connection()

            if not conn:
                send_message("❌ Database connection failed.")
                return

            cursor = conn.cursor()

            cursor.execute("""
                UPDATE active_signals
                SET status = 'BOUGHT',
                    bought = TRUE,
                    last_updated = NOW()
                WHERE symbol = %s
                AND status != 'CLOSED'
            """, (symbol,))

            conn.commit()

            cursor.close()
            conn.close()

            send_message(f"✅ Trade marked as BOUGHT: {symbol}")

        except Exception as e:

            send_message(f"Error updating trade: {e}")

    # SOLD
    elif base_command == "/sold" and symbol:

        try:

            conn = get_connection()

            if not conn:
                send_message("❌ Database connection failed.")
                return

            cursor = conn.cursor()

            cursor.execute("""
                UPDATE active_signals
                SET status = 'CLOSED',
                    sold = TRUE,
                    last_updated = NOW()
                WHERE symbol = %s
            """, (symbol,))

            conn.commit()

            cursor.close()
            conn.close()

            send_message(f"✅ Trade CLOSED: {symbol}")

        except Exception as e:

            send_message(f"Error closing trade: {e}")

    # IGNORE
    elif base_command == "/ignore" and symbol:

        try:

            conn = get_connection()

            if not conn:
                send_message("❌ Database connection failed.")
                return

            cursor = conn.cursor()

            cursor.execute("""
                UPDATE active_signals
                SET status = 'IGNORED',
                    last_updated = NOW()
                WHERE symbol = %s
                AND status = 'NEW'
            """, (symbol,))

            conn.commit()

            cursor.close()
            conn.close()

            send_message(f"🚫 Trade ignored: {symbol}")

        except Exception as e:

            send_message(f"Error ignoring trade: {e}")

    # HELP
    elif base_command == "/help":

        send_message(
            "*PETS Commands:*\n\n"
            "/status - System status\n"
            "/scan - Manual scan\n"
            "/signals - Last 5 signals\n"
            "/bought SYMBOL\n"
            "/sold SYMBOL\n"
            "/ignore SYMBOL\n"
            "/help - Commands list"
        )

    else:

        send_message(
            "❓ Unknown command.\n\n"
            "Use /help"
        )


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

                chat_id = str(
                    message.get("chat", {}).get("id", "")
                )

                if (
                    chat_id == TELEGRAM_CHAT_ID
                    and text.startswith("/")
                ):

                    logger.info(f"Telegram command: {text}")

                    handle_command(text.strip())

        except Exception as e:

            logger.error(f"Bot listener error: {e}")
