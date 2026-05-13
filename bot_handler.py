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

    from database import (
        get_connection,
        close_trade,
        update_trade_note
    )

    from scanner import run_scanner

    parts = command.split()

    base = parts[0].lower()

    # STATUS
    if base == "/status":

        send_message(
            "✅ PETS Engine Active\n\n"
            "Scanner: Running\n"
            "Database: Connected\n"
            "Trade Lifecycle: Active"
        )

    # MANUAL SCAN
    elif base == "/scan":

        send_message("🔍 Manual scan started...")

        run_scanner()

        send_message("✅ Scan complete.")

    # LAST SIGNALS
    elif base == "/signals":

        conn = get_connection()

        if not conn:

            send_message("❌ Database error.")

            return

        try:

            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    symbol,
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

                send_message("No signals found.")

                return

            msg = "*Last 5 Signals:*\n\n"

            for row in rows:

                msg += (
                    f"📌 {row[0]} | "
                    f"{row[1]} | "
                    f"Entry: ₹{row[2]} | "
                    f"SL: ₹{row[3]} | "
                    f"Target: ₹{row[4]} | "
                    f"Score: {row[5]}\n\n"
                )

            send_message(msg)

        except Exception as e:

            send_message(f"Error: {e}")

    # BOUGHT
    elif base == "/bought":

        if len(parts) < 2:

            send_message(
                "Usage:\n/bought SYMBOL"
            )

            return

        symbol = parts[1].upper()

        conn = get_connection()

        if not conn:

            send_message("DB error.")

            return

        try:

            cursor = conn.cursor()

            cursor.execute("""
                UPDATE active_signals
                SET status = 'BOUGHT',
                    bought = TRUE,
                    last_updated = NOW()
                WHERE symbol = %s
                AND status = 'NEW'
            """, (symbol,))

            updated_rows = cursor.rowcount

            conn.commit()

            cursor.close()
            conn.close()

            if updated_rows == 0:

                send_message(
                    f"❌ No active NEW trade found for {symbol}"
                )

            else:

                send_message(
                    f"✅ Trade marked BOUGHT:\n{symbol}"
                )

        except Exception as e:

            send_message(f"Error: {e}")

    # SOLD
    elif base == "/sold":

        if len(parts) < 2:

            send_message(
                "Usage:\n/sold SYMBOL"
            )

            return

        symbol = parts[1].upper()

        close_trade(
            symbol,
            "MANUAL_EXIT"
        )

        send_message(
            f"✅ Trade closed manually:\n{symbol}"
        )

    # FEEDBACK
    elif base == "/feedback":

        if len(parts) < 3:

            send_message(
                "Usage:\n"
                "/feedback SYMBOL your_note"
            )

            return

        symbol = parts[1].upper()

        note = " ".join(parts[2:])

        update_trade_note(
            symbol,
            note
        )

        send_message(
            f"🧠 Feedback saved for {symbol}"
        )

    # HELP
    elif base == "/help":

        send_message(
            """
📘 PETS COMMANDS

/status
/scan
/signals
/bought SYMBOL
/sold SYMBOL
/feedback SYMBOL NOTE
/help
"""
        )

    else:

        send_message(
            "Unknown command.\nUse /help"
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
                chat_id = str(message.get("chat", {}).get("id", ""))
                if chat_id == TELEGRAM_CHAT_ID and text.startswith("/"):
                    logger.info(f"Telegram command: {text}")
                    handle_command(text.strip())
        except Exception as e:
            logger.error(f"Bot listener error: {e}")
