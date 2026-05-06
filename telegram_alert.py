import requests
import os
import logging

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_alert(symbol, action, entry, sl, target, confidence, reason, trailing_sl=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured.")
        return

    trailing_line = f"📉 *Trailing SL:* ₹{trailing_sl}\n" if trailing_sl else ""

    message = f"""
🚀 *PETS TRADE SIGNAL*

📌 *Stock:* {symbol}
📊 *Action:* {action}
💰 *Entry:* ₹{entry}
🛑 *Stop Loss:* ₹{sl}
{trailing_line}🎯 *Target:* ₹{target}
📈 *Confidence:* {confidence}%
📝 *Reason:* {reason}

⚠️ _Trade at your own risk._
    """

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
        logger.info(f"Alert sent for {symbol}")
    except Exception as e:
        logger.error(f"Telegram alert failed: {e}")
