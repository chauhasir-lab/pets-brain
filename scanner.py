import logging
import pandas as pd
from dhan_data import get_dhan_data
from database import get_active_bought_trades, close_trade, update_trade_note, update_stop_loss
from telegram_alert import send_trade_update

logger = logging.getLogger(__name__)

# --- GLOBAL STATES ---
SCAN_LOCK = {"running": False}
LAST_ALERT_STATE = {} 
TRADE_STATE = {}  # Trade lifecycle intelligence store

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
            if df is None or df.empty:
                continue

            current_price = float(df['close'].iloc[-1])
            
            # Technical Indicators
            ema20 = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            
            # RSI Logic
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]

            volume_avg = df['volume'].rolling(window=10).mean().iloc[-1]
            latest_volume = df['volume'].iloc[-1]

            # --- 1. HARD EXIT LOGIC (Targets & SL) ---
            if current_price >= float(target2):
                send_trade_update(symbol, f"🚀 TARGET 2 HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nFull target achieved.")
                close_trade(symbol, "TARGET2_HIT", current_price)
                LAST_ALERT_STATE.pop(symbol, None)
                TRADE_STATE.pop(symbol, None)
                continue

            if current_price >= float(target1):
                send_trade_update(symbol, f"🎯 TARGET 1 HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nBook 50% & Trail.")
                update_trade_note(symbol, "Target 1 achieved")

            if current_price <= float(stop_loss):
                send_trade_update(symbol, f"❌ STOP LOSS HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nExit position.")
                close_trade(symbol, "SL_HIT", current_price)
                LAST_ALERT_STATE.pop(symbol, None)
                TRADE_STATE.pop(symbol, None)
                continue

            # --- 2. INTELLIGENT STATE CLASSIFICATION ---
            current_state = "NEUTRAL"
            price_strength = current_price > ema20
            volume_strength = latest_volume > volume_avg
            momentum_strength = rsi > 55

            if price_strength and volume_strength and momentum_strength and current_price > float(target1):
                current_state = "STRONG"
            elif price_strength and momentum_strength:
                current_state = "HEALTHY"
            elif current_price < ema20 or rsi < 48:
                current_state = "WEAKENING"
            elif current_price <= (float(stop_loss) * 1.01): # SL ke 1% pass
                current_state = "DANGER"

            # Sync with Trade Intelligence engine
            TRADE_STATE[symbol] = current_state

            # --- 3. SMART NOTIFICATION (Only on State Change) ---
            if LAST_ALERT_STATE.get(symbol) != current_state:
                
                status_emoji = {
                    "STRONG": "🔥",
                    "HEALTHY": "📈",
                    "WEAKENING": "⚠️",
                    "DANGER": "🚨",
                    "NEUTRAL": "⏳"
                }
                
                msg_map = {
                    "STRONG": "Trend is explosive! Holding above Target 1.",
                    "HEALTHY": "Trend strong, holding valid.",
                    "WEAKENING": "Momentum fading. Price below EMA20 or RSI weak.",
                    "DANGER": "Very close to Stop Loss! Watch carefully.",
                    "NEUTRAL": "Momentum mixed, sideways movement."
                }

                emoji = status_emoji.get(current_state, "🔔")
                note = msg_map.get(current_state, "State updated.")
                
                msg = f"{emoji} TRADE {current_state}\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\n{note}"
                
                send_trade_update(symbol, msg)
                LAST_ALERT_STATE[symbol] = current_state

        except Exception as e:
            logger.error(f"Error evaluating {symbol}: {e}")

def run_scanner():
    if SCAN_LOCK["running"]:
        return

    SCAN_LOCK["running"] = True
    try:
        logger.info("PETS Scanner cycle started...")
        evaluate_open_positions()
    except Exception as e:
        logger.error(f"Scanner Run Error: {e}")
    finally:
        SCAN_LOCK["running"] = False
