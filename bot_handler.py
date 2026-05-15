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
    # Dynamic imports from database to avoid circular dependency
    from database import (
        close_trade, 
        update_trade_note, 
        get_trade_performance_summary, 
        execute_query,
        get_recent_trade_failures,
        mark_trade_as_bought,
        get_total_pnl,
        get_active_trade_summary
    )
    # Dynamic imports from scanner including new requested state metrics
    from scanner import (
        run_scanner, LAST_SCAN_TIME, SYSTEM_STATS, 
        MARKET_BREADTH, PORTFOLIO_HEAT, WATCHLIST_SCORES,
        TRADE_STATE, LIVE_CONFIDENCE, TRADE_PRIORITY,
        LOSS_STREAK, MARKET_PANIC
    )

    parts = command.split()
    if not parts: return
    base = parts[0].lower()

    if base == "/health":
        last_scan = LAST_SCAN_TIME.get("time")
        status = "ACTIVE" if last_scan and (datetime.utcnow() - last_scan).total_seconds() < 600 else "STALE"
        send_message(f"🧠 *PETS HEALTH*\nStatus: `{status}`\nLast Scan: `{last_scan}`")

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

    elif base == "/buy":
        if len(parts) < 2:
            send_message("⚠️ *Usage:* `/buy SYMBOL` (e.g., `/buy RELIANCE`)")
            return
        
        symbol = parts[1].upper()
        try:
            mark_trade_as_bought(symbol)
            send_message(f"✅ *{symbol}* marked as BOUGHT in database.")
        except Exception as e:
            send_message(f"❌ *Error:* `{str(e)}`")

    elif base == "/pnl":
        try:
            pnl = get_total_pnl()
            msg = (
                f"💰 *PETS TOTAL PNL*\n\n"
                f"Net Points: `{pnl}`"
            )
            send_message(msg)
        except Exception as e:
            send_message(f"❌ *Error calculating PNL:* `{str(e)}`")

    elif base == "/status":
        try:
            trades = get_active_trade_summary()
            if not trades:
                send_message("📭 *No active trades right now.*")
                return

            msg = "📊 *ACTIVE TRADE STATUS*\n\n"
            for trade in trades:
                (
                    symbol, entry_price, stop_loss, target1, target2,
                    quantity, rr, score, signal_time, setup_type, status
                ) = trade

                state = TRADE_STATE.get(symbol, "UNKNOWN")
                confidence = LIVE_CONFIDENCE.get(symbol, score)
                priority = TRADE_PRIORITY.get(symbol, "NORMAL")

                msg += (
                    f"🔹 *{symbol}*\n"
                    f"State: `{state}`\n"
                    f"Confidence: `{confidence}`\n"
                    f"Priority: `{priority}`\n"
                    f"Entry: `₹{entry_price}`\n"
                    f"SL: `₹{stop_loss}`\n"
                    f"T1: `₹{target1}` | T2: `₹{target2}`\n"
                    f"RR: `{rr}` | Setup: `{setup_type}`\n\n"
                )
            send_message(msg[:4000])
        except Exception as e:
            send_message(f"❌ *Error fetching status:* `{str(e)}`")

    elif base == "/risk":
        try:
            heat = round(PORTFOLIO_HEAT['active_risk'], 2)
            loss_streak = LOSS_STREAK.get('count', 0)
            market_panic = MARKET_PANIC.get('active', False)

            msg = (
                f"⚠️ *PETS RISK DASHBOARD*\n\n"
                f"Portfolio Heat: `₹{heat}`\n"
                f"Loss Streak: `{loss_streak}`\n"
                f"Market Panic Mode: `{market_panic}`\n"
            )
            send_message(msg)
        except Exception as e:
            send_message(f"❌ *Error fetching risk dashboard:* `{str(e)}`")

    elif base == "/market":
        try:
            bullish = MARKET_BREADTH.get('bullish', 0)
            bearish = MARKET_BREADTH.get('bearish', 0)
            total = bullish + bearish
            
            ratio = bullish / total if total > 0 else 0

            if ratio >= 0.65:
                regime = "TRENDING BULLISH"
            elif ratio >= 0.55:
                regime = "MODERATELY BULLISH"
            elif ratio >= 0.45:
                regime = "SIDEWAYS"
            else:
                regime = "WEAK / BEARISH"

            msg = (
                f"📈 *PETS MARKET READ*\n\n"
                f"Market Regime: `*{regime}*`\n"
                f"Bullish Breadth: `{bullish}`\n"
                f"Bearish Breadth: `{bearish}`\n"
                f"Internal Strength Ratio: `{round(ratio, 2)}`"
            )
            send_message(msg)
        except Exception as e:
            send_message(f"❌ *Error fetching market read:* `{str(e)}`")

    elif base == "/failures":
        rows = get_recent_trade_failures()
        if not rows:
            send_message("❌ *No recent failures found.*")
            return

        msg = "📉 *RECENT TRADE FAILURES*\n\n"
        for row in rows:
            (symbol, result, rr, score, regime, state, created_at) = row
            msg += (
                f"▪️ *{symbol}*\n"
                f"Exit: `{result}`\n"
                f"RR: `{rr}` | Score: `{score}`\n"
                f"Regime: `{regime}`\n"
                f"State: `{state}`\n\n"
            )
        send_message(msg[:4000])

    elif base == "/performance":
        perf = get_trade_performance_summary()
        msg = (
            f"📊 *WEEKLY PERFORMANCE*\n\n"
            f"Total Trades: `{perf['total']}`\n"
            f"Wins: `{perf['wins']}` ✅\n"
            f"Losses: `{perf['losses']}` ❌\n"
            f"Win Rate: `{perf['win_rate']}%`"
        )
        send_message(msg)

    elif base == "/scan":
        send_message("🔍 *Manual scan started...*")
        run_scanner()
        send_message("✅ *Scan complete.*")

    elif base == "/help":
        send_message("`/health`, `/diagnostics`, `/status`, `/risk`, `/market`, `/scan`, `/performance`, `/failures`, `/buy SYMBOL`, `/pnl`, `/signals`")

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
        except Exception as e:
            logger.error(f"Listener Error: {e}")
            time.sleep(5)
