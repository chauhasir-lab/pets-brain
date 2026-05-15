import logging
import pandas as pd
from dhan_data import get_dhan_data
from database import get_active_bought_trades, close_trade, update_trade_note, update_stop_loss

logger = logging.getLogger(__name__)

# --- GLOBAL STATES ---
SCAN_LOCK = {"running": False}
LAST_ALERT_STATE = {} # Spam control ke liye
TRADE_STATE = {}      # Trade lifecycle intelligence ke liye

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
            
            # RSI Calculation
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]

            volume_avg = df['volume'].rolling(window=10).mean().iloc[-1]
            latest_volume = df['volume'].iloc[-1]

            # 1. HARD EXIT LOGIC (Targets & SL)
            if current_price >= float(target2):
                from telegram_alert import send_trade_update
                send_trade_update(symbol, f"🚀 TARGET 2 HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nFull target achieved.")
                close_trade(symbol, "TARGET2_HIT", current_price)
                LAST_ALERT_STATE.pop(symbol, None)
                TRADE_STATE.pop(symbol, None)
                continue

            if current_price >= float(target1):
                from telegram_alert import send_trade_update
                send_trade_update(symbol, f"🎯 TARGET 1 HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nBook 50% & Trail.")
                update_trade_note(symbol, "Target 1 achieved")

            if current_price <= float(stop_loss):
                from telegram_alert import send_trade_update
                send_trade_update(symbol, f"❌ STOP LOSS HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nExit position.")
                close_trade(symbol, "SL_HIT", current_price)
                LAST_ALERT_STATE.pop(symbol, None)
                TRADE_STATE.pop(symbol, None)
                continue

            # 4. TRADE STATE ENGINE
            current_state = "NEUTRAL"
            price_strength = current_price > ema20
            volume_strength = latest_volume > volume_avg
            momentum_strength = rsi > 55

            # STRONG TRADE
            if (price_strength and volume_strength and momentum_strength and current_price > float(target1)):
                current_state = "STRONG"

            # HEALTHY TRADE
            elif (price_strength and momentum_strength):
                current_state = "HEALTHY"

            # WEAKENING TRADE
            elif (current_price < ema20 or rsi < 48):
                current_state = "WEAKENING"

            # DANGER ZONE
            elif (current_price <= (float(stop_loss) * 1.01)):
                current_state = "DANGER"

            TRADE_STATE[symbol] = current_state

            # SMART ALERT CONTROL
            if LAST_ALERT_STATE.get(symbol) != current_state:
                from telegram_alert import send_trade_update

                if current_state == "STRONG":
                    msg = (f"🚀 STRONG TRADE\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\n"
                           f"Trade showing strong continuation.\nPrice sustaining above EMA20.\n"
                           f"Momentum and participation strong.\nHolding remains favorable.")

                elif current_state == "HEALTHY":
                    msg = (f"📈 HEALTHY TRADE\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\n"
                           f"Trend structure remains intact.\nMomentum stable.\nNo major weakness detected.")

                elif current_state == "WEAKENING":
                    msg = (f"⚠️ MOMENTUM WEAKENING\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\n"
                           f"Momentum deteriorating.\nPrice losing trend quality.\nWatch closely for breakdown risk.")

                elif current_state == "DANGER":
                    msg = (f"🛑 DANGER ZONE\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\n"
                           f"Price approaching stop-loss region.\nBreakdown probability increasing.\nCapital protection priority now.")
                else:
                    msg = (f"⏳ TRADE NEUTRAL\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\n"
                           f"Trade still active.\nNo strong directional edge currently.")

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
