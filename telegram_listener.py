import requests
import os
import time
import logging

from database import get_connection

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

LAST_UPDATE_ID = 0


def update_signal_status(symbol, status):

    try:

        conn = get_connection()

        if not conn:
            return

        cursor = conn.cursor()

        cursor.execute("""
            UPDATE active_signals
            SET status = %s,
                last_updated = NOW()
            WHERE symbol = %s
            AND status != 'CLOSED'
        """, (status, symbol))

        conn.commit()

        cursor.close()
        conn.close()

        logger.info(f"{symbol} updated to {status}")

    except Exception as e:
        logger.error(f"Status update error: {e}")


def process_message(text):

    parts = text.strip().split()

    if len(parts) < 2:
        return

    command = parts[0].lower()
    symbol = parts[1].upper()

    if command == "/bought":
        update_signal_status(symbol, "BOUGHT")

    elif command == "/sold":
        update_signal_status(symbol, "CLOSED")

    elif command == "/ignore":
        update_signal_status(symbol, "IGNORED")


def poll_telegram():

    global LAST_UPDATE_ID

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    try:

        response = requests.get(
            url,
            params={
                "offset": LAST_UPDATE_ID + 1,
                "timeout": 30
            },
            timeout=35
        )

        data = response.json()

        if not data.get("ok"):
            return

        for update in data["result"]:

            LAST_UPDATE_ID = update["update_id"]

            message = update.get("message", {})

            text = message.get("text")

            if text:
                logger.info(f"Telegram command: {text}")
                process_message(text)

    except Exception as e:
        logger.error(f"Telegram polling error: {e}")


def run_listener():

    logger.info("Telegram listener started.")

    while True:

        poll_telegram()

        time.sleep(5)
