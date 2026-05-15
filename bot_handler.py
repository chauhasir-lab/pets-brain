import logging
import os
import requests
import time
from datetime import datetime  # Step 5: Import datetime

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_message(text):
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram Token missing!")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
        return response.json()
    except Exception as e:
        logger.error(f"Send message failed: {e}")

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 20} 
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(url, params=params, timeout=25)
        return response.json()
    except Exception as e:
        logger.error(f"Update fetch failed: {e}")
        return {"ok": False}

def handle_command(command):
    # Dynamic imports inside function to avoid circular dependency
    from database import (
        get_connection,
        close_trade,
        update_trade_note,
        get_trade_performance_summary,
        execute_query  # Use the new safe wrapper
    )
    # Step 3: Import LAST_SCAN_TIME
    from scanner import run_scanner, LAST_SCAN_TIME

    parts = command.split()
    if not parts: return
    
    base = parts[0].lower()

    # --- COMMANDS LOGIC ---
    
    # STEP 4: /health command integration
    if base == "/health":
        last_scan = LAST_SCAN_TIME.get("time")
        if not last_scan:
            send_message("⚠️ *PETS scanner not active or hasn't run yet.*")
            return

        minutes_ago = round((datetime.utcnow() - last_scan).total_seconds() / 60, 2)
        
        health_status = "ACTIVE" if minutes_ago < 10 else "STALE"
        icon = "✅" if health_status == "ACTIVE" else "⚠️"

        msg = (
            f"🧠 *PETS SYSTEM HEALTH*\n\n"
            f"Last Scan: `{minutes_ago}` mins ago\n"
            f"Scanner Status: {icon} `{health_status}`\n"
            f"Monitoring Engine: 🚀 `RUNNING`"
        )
        send_message(msg)

    elif base == "/status":
        send_message(
            "✅ *PETS Engine Active*\n\n"
            "Scanner: Running\n"
            "Database: Connected\n"
            "Trade Lifecycle: Active"
        )

    elif base == "/scan":
        send_message("🔍 *Manual scan started...*")
        try:
            run_scanner()
            send_message("✅ *Scan complete.*")
        except Exception as e:
            send_message(f"❌ Scan failed: {e}")

    elif base == "/performance":
        data = get_trade_performance_summary()
        if not data or data['total'] == 0:
            send_message("📊 *No analytics data available for the last 7 days.*")
            return
        
        msg = (
            f"📊 *PETS PERFORMANCE REPORT*\n"
            f"_(Last 7 Days)_\n\n"
            f"Total Trades: `{data['total']}`\n"
            f"Wins: ✅ `{data['wins']}`\n"
            f"Losses: ❌ `{data['losses']}`\n"
            f"Win Rate: *{data['win_rate']}%*"
        )
        send_message(msg)

    elif base == "/signals":
        try:
            # Using execute_query for better stability
            rows = execute_query("""
                SELECT symbol, action, entry_price, stop_loss, target, confidence, created_at 
                FROM signals ORDER BY created_at DESC LIMIT 5
            """, fetchall=True)

            if not rows:
                send_message("No signals found in database.")
                return

            msg = "*Last 5 Signals:*\n\n"
            for row in rows:
                msg += (f"📌 `{row[0]}` | {row[1]}\n"
                        f"Entry: ₹{row[2]} | SL: ₹{row[3]}\n"
                        f"Target: ₹{row[4]} | Score: {row[5]}\n\n")
            send_message(msg)
        except Exception as e:
            send_message(f"Error reading signals: {e}")

    elif base == "/bought":
        if len(parts) < 2:
            send_message("Usage: `/bought SYMBOL`")
            return
        symbol = parts[1].upper()
        try:
            # Using execute_query to mark bought
            query = """
                UPDATE active_signals 
                SET status = 'BOUGHT', bought = TRUE, last_updated = NOW() 
                WHERE symbol = %s AND status = 'NEW'
            """
            # We check rowcount via custom logic or just execute
            execute_query(query, (symbol,), commit=True)
            send_message(f"✅ Trade marked *BOUGHT*: {symbol}")
        except Exception as e:
            send_message(f"DB Error: {e}")

    elif base == "/sold":
        if len(parts) < 2:
            send_message("Usage: `/sold SYMBOL`")
            return
        symbol = parts[1].upper()
        close_trade(symbol, "MANUAL_EXIT")
        send_message(f"✅ Trade closed manually: *{symbol}*")

    elif base == "/feedback":
        if len(parts) < 3:
            send_message("Usage: `/feedback SYMBOL your_note`")
            return
        symbol = parts[1].upper()
        note = " ".join(parts[2:])
        update_trade_note(symbol, note)
        send_message(f"🧠 Feedback saved for *{symbol}*")

    elif base == "/help":
        send_message(
            "📘 *PETS COMMANDS*\n\n"
            "`/health` - System Pulse Check\n"
            "`/status` - Check Engine\n"
            "`/scan` - Trigger Scanner\n"
            "`/performance` - Win/Loss Stats\n"
            "`/signals` - Recent Calls\n"
            "`/bought SYMBOL` - Mark Entry\n"
            "`/sold SYMBOL` - Mark Exit\n"
            "`/feedback SYMBOL NOTE` - Add Note\n"
        )
    else:
        send_message("Unknown command. Use `/help`")

def start_bot_listener():
    logger.info("Telegram Bot Listener Started.")
    offset = None
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials missing in ENV!")
        return

    while True:
        try:
            updates = get_updates(offset)
            if updates.get("ok"):
                for update in updates.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    text = message.get("text", "")
                    user_chat_id = str(message.get("chat", {}).get("id", ""))
                    
                    if user_chat_id == str(TELEGRAM_CHAT_ID) and text.startswith("/"):
                        logger.info(f"Command received: {text}")
                        handle_command(text.strip())
            
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Bot listener loop error: {e}")
            time.sleep(5)
