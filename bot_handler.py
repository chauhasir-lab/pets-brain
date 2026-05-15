import logging
import os
import requests
import time
from datetime import datetime

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_message(text):
    if not TELEGRAM_BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram failed: {e}")

def handle_command(command):
    # Dynamic imports to avoid circular dependency
    from database import (
        close_trade, update_trade_note, 
        get_trade_performance_summary, execute_query
    )
    from scanner import (
        run_scanner, LAST_SCAN_TIME, SYSTEM_STATS, 
        MARKET_BREADTH, PORTFOLIO_HEAT, WATCHLIST_SCORES
    )

    parts = command.split()
    if not parts: return
    base = parts[0].lower()

    if base == "/health":
        last_scan = LAST_SCAN_TIME.get("time")
        status = "ACTIVE" if last_scan and (datetime.utcnow() - last_scan).total_seconds() < 600 else "STALE"
        send_message(f"🧠 *PETS HEALTH*\nStatus: `{status}`\nLast Scan: `{last_scan}`")

    # =========================================
    # STEP 5: IMPROVED DIAGNOSTICS
    # =========================================
    elif base == "/diagnostics":
        last_signal = SYSTEM_STATS.get("last_signal_time")
        signal_age = f"{round((datetime.utcnow() - last_signal).total_seconds()/60, 1)}m ago" if last_signal else "None"
        
        # Get Top 5 Priority Stocks
        top_symbols = sorted(WATCHLIST_SCORES.items(), key=lambda x: x[1], reverse=True)[:5]
        watchlist_str = "\n".join([f"🔹 `{s}`: {sc}" for s, sc in top_symbols])

        msg = (
            f"📊 *PETS DIAGNOSTICS*\n\n"
            f"Total Scans: `{SYSTEM_STATS['total_scans']}`\n"
            f"Signals: `{SYSTEM_STATS['successful_signals']}`\n"
            f"Last Signal: `{signal_age}`\n\n"
            f"📈 *Breadth:* Bullish `{MARKET_BREADTH['bullish']}` | Bearish `{MARKET_BREADTH['bearish']}`\n"
            f"🔥 *Portfolio Heat:* `₹{round(PORTFOLIO_HEAT['active_risk'], 2)}`\n\n"
            f"🔝 *Top Watchlist:* \n{watchlist_str or 'No data yet'}"
        )
        send_message(msg)

    elif base == "/status":
        send_message("✅ *PETS Engine Active*")

    elif base == "/scan":
        send_message("🔍 *Manual scan started...*")
        run_scanner()
        send_message("✅ *Scan complete.*")

    elif base == "/help":
        send_message("`/health`, `/diagnostics`, `/status`, `/scan`, `/performance`, `/signals`")

def start_bot_listener():
    logger.info("Bot Listener Started.")
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            resp = requests.get(url, params={"offset": offset, "timeout": 20}).json()
            if resp.get("ok"):
                for update in resp.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    if str(msg.get("chat", {}).get("id")) == str(TELEGRAM_CHAT_ID):
                        handle_command(msg.get("text", ""))
            time.sleep(1)
        except:
            time.sleep(5)
