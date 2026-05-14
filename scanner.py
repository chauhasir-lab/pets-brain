import logging
import pandas as pd
# Yahan apne zaroori imports check kar lein (dhan_data, database etc.)
from dhan_data import get_dhan_data
from database import get_active_bought_trades, close_trade, update_trade_note, update_stop_loss
# Agar calculate_rsi alag file mein hai to wahan se import karein
# from technical_indicators import calculate_rsi 

logger = logging.getLogger(__name__)

# --- GLOBAL STATES (Spam Control ke liye) ---
SCAN_LOCK = {"running": False}
LAST_ALERT_STATE = {} 

def evaluate_open_positions():
    trades = get_active_bought_trades()
    if not trades:
        return

    logger.info(f"Monitoring {len(trades)} active trades")

    for trade in trades:
        try:
            (symbol, entry_price, stop_loss, target1, target2,
             quantity, rr, score, signal_time, setup_type) = trade

            df = get_dhan_data(symbol)
            if df is None:
                continue

            current_price = float(df['close'].iloc[-1])
            # RSI aur EMA calculation
            ema20 = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            
            # Simple RSI logic (agar aapka function alag hai to use use karein)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]

            volume_avg = df['volume'].rolling(window=10).mean().iloc[-1]
            latest_volume = df['volume'].iloc[-1]

            # 1. TARGET 2 HIT
            if current_price >= float(target2):
                from telegram_alert import send_trade_update
                send_trade_update(symbol, f"🚀 TARGET 2 HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nFull target achieved.")
                close_trade(symbol, "TARGET2_HIT", current_price)
                LAST_ALERT_STATE.pop(symbol, None)
                continue

            # 2. TARGET 1 HIT
            if current_price >= float(target1):
                from telegram_alert import send_trade_update
                send_trade_update(symbol, f"🎯 TARGET 1 HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nBook 50% & Trail.")
                update_trade_note(symbol, "Target 1 achieved")

            # 3. STOP LOSS HIT
            if current_price <= float(stop_loss):
                from telegram_alert import send_trade_update
                send_trade_update(symbol, f"❌ STOP LOSS HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nExit position.")
                close_trade(symbol, "SL_HIT", current_price)
                LAST_ALERT_STATE.pop(symbol, None)
                continue

            # 4. SMART NOTIFICATION LOGIC (State Change Only)
            current_state = "NEUTRAL"
            price_strength = current_price > ema20
            volume_strength = latest_volume > volume_avg
            momentum_strength = rsi > 55

            if price_strength and volume_strength and momentum_strength:
                current_state = "HEALTHY"
            elif current_price < ema20 or rsi < 48:
                current_state = "WEAKENING"

            # Sirf tab alert bhejega jab state badlegi
            if LAST_ALERT_STATE.get(symbol) != current_state:
                from telegram_alert import send_trade_update
                
                if current_state == "HEALTHY":
                    msg = f"📈 TRADE HEALTHY\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nTrend strong, holding valid."
                elif current_state == "WEAKENING":
                    msg = f"⚠️ MOMENTUM WEAKENING\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nPrice below EMA20. Caution!"
                else:
                    msg = f"⏳ TRADE NEUTRAL\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nMomentum mixed."
                
                send_trade_update(symbol, msg)
                LAST_ALERT_STATE[symbol] = current_state

        except Exception as e:
            logger.error(f"Error evaluating {symbol}: {e}")

def run_scanner():
    """Ye function main.py call karta hai, iska hona zaroori hai"""
    if SCAN_LOCK["running"]:
        return

    SCAN_LOCK["running"] = True
    try:
        logger.info("PETS Scanner cycle started...")
        evaluate_open_positions()
        # Yahan aap apna naya stock scanning logic (watchlist) bhi dal sakte hain
    except Exception as e:
        logger.error(f"Scanner Run Error: {e}")
    finally:
        SCAN_LOCK["running"] = False
