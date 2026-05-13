import logging
import os
import requests
import time  # <--- Polling delay ke liye zaroori hai

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
    params = {"timeout": 20} # Long polling better hoti hai
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
        update_trade_note
    )
    from scanner import run_scanner

    parts = command.split()
    if not parts: return
    
    base = parts[0].lower()

    # --- COMMANDS LOGIC ---
    if base == "/status":
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

    elif base == "/signals":
        conn = get_connection()
        if not conn:
            send_message("❌ Database connection error.")
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, action, entry_price, stop_loss, target, confidence, created_at 
                FROM signals ORDER BY created_at DESC LIMIT 5
            """)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

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
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE active_signals 
                SET status = 'BOUGHT', bought = TRUE, last_updated = NOW() 
                WHERE symbol = %s AND status = 'NEW'
            """, (symbol,))
            updated = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()
            
            if updated == 0:
                send_message(f"❌ No 'NEW' signal found for {symbol}")
            else:
                send_message(f"✅ Trade marked *BOUGHT*: {symbol}")
        except Exception as e:
            send_message(f"DB Error: {e}")

    elif base == "/sold":
        if len(parts) < 2:
            send_message("Usage: `/sold SYMBOL`")
            return
        symbol = parts[1].upper()
        # close_trade logic handle karega analytics aur status update
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
            "`/status` - Check Engine\n"
            "`/scan` - Trigger Scanner\n"
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
    
    # Pre-start check
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
                    # Sirf authorized chat_id se command accept karega
                    user_chat_id = str(message.get("chat", {}).get("id", ""))
                    
                    if user_chat_id == str(TELEGRAM_CHAT_ID) and text.startswith("/"):
                        logger.info(f"Command received: {text}")
                        handle_command(text.strip())
            
            # API rate limiting se bachne ke liye chhota pause
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Bot listener loop error: {e}")
            time.sleep(5) # Error aane par 5 second wait karein
