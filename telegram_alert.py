import requests
import os
import logging

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_alert(symbol, action, entry, sl, target1, target2, confidence, reason, trailing_sl=None, quantity=None, nifty_trend=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured.")
        return

    trailing_line = f"📉 *Trailing SL:* ₹{trailing_sl}\n" if trailing_sl else ""
    qty_line = f"📦 *Quantity:* {quantity} shares *(₹10k capital)*\n" if quantity else ""
    trend_line = f"📊 *Nifty Trend:* {nifty_trend}\n" if nifty_trend else ""

    message = f"""
🚀 *PETS TRADE SIGNAL*

📌 *Stock:* {symbol}
📊 *Action:* {action}
💰 *Entry:* ₹{round(entry, 2)}
🛑 *Stop Loss:* ₹{sl}
{trailing_line}{qty_line}{trend_line}🎯 *Target 1:* ₹{target1} *(Book 50% here)*
🎯 *Target 2:* ₹{target2} *(Trail rest)*
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

def send_daily_summary(signals_count, top_signals):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    msg = f"""
📊 *PETS Daily Summary*

🔍 Total Signals Today: {signals_count}
⏰ Market Closed: 3:30 PM

*Top Signals:*
{top_signals}

_See you tomorrow at 9:15 AM_ 🚀
    """

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
