import pandas as pd
import logging
from datetime import datetime, timedelta # STEP 2: Updated import

from strategy import analyze_setup, calculate_rsi, is_market_hours
from telegram_alert import send_alert, send_trade_update
from dhan_data import get_dhan_data

from database import (
    get_connection,
    is_signal_active,
    expire_old_signals,
    get_active_bought_trades,
    close_trade,
    update_trade_note,
    update_stop_loss,
    save_trade_analytics
)

logger = logging.getLogger(__name__)

WATCHLIST = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "WIPRO", "NESTLEIND", "TECHM",
    "HCLTECH", "BAJFINANCE", "BAJAJFINSV", "NTPC", "POWERGRID",
    "ONGC", "COALINDIA", "JSWSTEEL", "TATASTEEL", "ADANIENT",
    "ADANIPORTS", "DIVISLAB", "DRREDDY", "CIPLA", "APOLLOHOSP",
    "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO", "TATACONSUM", "BRITANNIA",
    "GRASIM", "INDUSINDBK", "BPCL", "IOC", "HINDALCO",
    "VEDL", "UPL", "SHREECEM", "SBILIFE", "HDFCLIFE"
]

KILL_SWITCH = {"losses": 0, "active": True}
BATCH_INDEX = [0]
SCAN_LOCK = {"running": False}
MAX_ACTIVE_TRADES = 3

LAST_ALERT_STATE = {}
TRADE_STATE = {}
BREAKEVEN_DONE = {}
LAST_TRAILING_SL = {}
RECENTLY_CLOSED = {} # STEP 1: Cooldown memory tracker


def save_signal(signal):
    conn = get_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO signals (symbol, action, entry_price, stop_loss, target, confidence, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (signal['symbol'], "BUY", signal['entry'], signal['sl'], signal['target1'], signal['score'], signal['reasons']))

        cursor.execute("""
            INSERT INTO active_signals (symbol, setup_type, status, entry_price, stop_loss, target1, target2, score, rr, quantity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (signal['symbol'], signal.get('regime', 'NORMAL'), 'NEW', signal['entry'], signal['sl'], signal['target1'], signal['target2'], signal['score'], signal['rr'], signal['quantity']))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Save signal error: {e}")


def evaluate_open_positions():
    trades = get_active_bought_trades()
    if not trades: return

    logger.info(f"Monitoring {len(trades)} trades")

    for trade in trades:
        try:
            (symbol, entry_price, stop_loss, target1, target2, 
             quantity, rr, score, signal_time, setup_type) = trade

            df = get_dhan_data(symbol)
            if df is None or df.empty: continue

            current_price = float(df['close'].iloc[-1])
            ema20 = float(df['close'].ewm(span=20, adjust=False).mean().iloc[-1])

            # Indicator Logic
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0).rolling(window=14).mean())
            loss = ((-delta.where(delta < 0, 0)).rolling(window=14).mean())
            rs = gain / (loss + 1e-10)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])

            # =========================================
            # EXIT LOGIC - TARGET 2
            # =========================================
            if current_price >= float(target2):
                send_trade_update(symbol, f"🚀 TARGET 2 HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}")
                
                save_trade_analytics(
                    symbol=symbol, result="TARGET2_HIT", entry_price=entry_price, exit_price=current_price,
                    stop_loss=stop_loss, target1=target1, target2=target2, rr=rr, score=score,
                    regime=setup_type, state=TRADE_STATE.get(symbol)
                )

                close_trade(symbol, "TARGET2_HIT", current_price)
                
                # Cleanup and Cooldown
                LAST_ALERT_STATE.pop(symbol, None)
                TRADE_STATE.pop(symbol, None)
                BREAKEVEN_DONE.pop(symbol, None)
                LAST_TRAILING_SL.pop(symbol, None)
                
                RECENTLY_CLOSED[symbol] = datetime.utcnow() # STEP 3: Add to cooldown
                continue

            # =========================================
            # TARGET 1 → BREAKEVEN
            # =========================================
            if current_price >= float(target1) and not BREAKEVEN_DONE.get(symbol):
                new_sl = round(float(entry_price), 2)
                update_stop_loss(symbol, new_sl)
                BREAKEVEN_DONE[symbol] = True

            # =========================================
            # STOP LOSS
            # =========================================
            if current_price <= float(stop_loss):
                send_trade_update(symbol, f"❌ STOP LOSS HIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}")

                save_trade_analytics(
                    symbol=symbol, result="SL_HIT", entry_price=entry_price, exit_price=current_price,
                    stop_loss=stop_loss, target1=target1, target2=target2, rr=rr, score=score,
                    regime=setup_type, state=TRADE_STATE.get(symbol)
                )

                close_trade(symbol, "SL_HIT", current_price)
                
                # Cleanup and Cooldown
                LAST_ALERT_STATE.pop(symbol, None)
                TRADE_STATE.pop(symbol, None)
                BREAKEVEN_DONE.pop(symbol, None)
                LAST_TRAILING_SL.pop(symbol, None)
                
                RECENTLY_CLOSED[symbol] = datetime.utcnow() # STEP 4: Add to cooldown
                continue

            # =========================================
            # TRAILING LOGIC (STRONG/WEAKENING)
            # =========================================
            price_strength = (current_price > ema20)
            momentum_strength = (rsi > 55)

            if current_price <= (float(stop_loss) * 1.01): current_state = "DANGER"
            elif current_price < ema20 or rsi < 48: current_state = "WEAKENING"
            elif price_strength and momentum_strength and current_price > float(target1): current_state = "STRONG"
            elif price_strength and momentum_strength: current_state = "HEALTHY"
            else: current_state = "NEUTRAL"

            TRADE_STATE[symbol] = current_state

            if current_state in ["STRONG", "WEAKENING"]:
                multiplier = 0.992 if current_state == "STRONG" else 0.996
                new_sl = round(max(float(stop_loss), current_price * multiplier), 2)
                previous_sl = LAST_TRAILING_SL.get(symbol)

                if new_sl > float(stop_loss) and new_sl != previous_sl:
                    update_stop_loss(symbol, new_sl)
                    LAST_TRAILING_SL[symbol] = new_sl

        except Exception as e:
            logger.error(f"Trade monitor error for {symbol}: {e}")


def run_scanner():
    if SCAN_LOCK["running"] or not is_market_hours(): return
    SCAN_LOCK["running"] = True
    try:
        expire_old_signals()
        evaluate_open_positions()

        if not KILL_SWITCH["active"] or len(get_active_bought_trades()) >= MAX_ACTIVE_TRADES:
            return

        batch_size = 10
        start = BATCH_INDEX[0]
        end = start + batch_size
        batch = WATCHLIST[start:end]

        if not batch:
            BATCH_INDEX[0] = 0
            return

        logger.info(f"Scanning batch: {batch}")
        for symbol in batch:
            # STEP 5: Cooldown Check logic
            cooldown_time = RECENTLY_CLOSED.get(symbol)
            if cooldown_time:
                minutes_passed = (datetime.utcnow() - cooldown_time).total_seconds() / 60
                if minutes_passed < 60:
                    logger.info(f"{symbol} in cooldown period")
                    continue

            try:
                if is_signal_active(symbol): continue
                df = get_dhan_data(symbol)
                if df is None: continue
                result = analyze_setup(df, symbol)
                if result:
                    save_signal(result)
                    send_alert(symbol=result['symbol'], action="BUY", entry=result['entry'], sl=result['sl'], target1=result['target1'], target2=result['target2'], confidence=result['score'], reason=result['reasons'], quantity=result.get('quantity'))
            except Exception as e:
                logger.error(f"Scanner error for {symbol}: {e}")

        BATCH_INDEX[0] = end
    finally:
        SCAN_LOCK["running"] = False
