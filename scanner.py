import pandas as pd
import logging
from datetime import datetime

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
    update_stop_loss
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

    for trade in trades:
        try:
            (symbol, entry_price, stop_loss, target1, target2,
             quantity, rr, score, signal_time, setup_type) = trade

            df = get_dhan_data(symbol)
            if df is None or df.empty: continue

            current_price = float(df['close'].iloc[-1])
            ema20 = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]

            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / (loss + 1e-10)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])

            volume_avg = df['volume'].rolling(window=10).mean().iloc[-1]
            latest_volume = df['volume'].iloc[-1]

            # --- EXIT LOGIC ---
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

            # --- TRAILING SL ---
            profit_move = current_price - float(entry_price)
            initial_risk = float(entry_price) - float(stop_loss)

            if profit_move >= (2 * initial_risk):
                new_sl = float(entry_price) + initial_risk
                update_stop_loss(symbol, new_sl)
                send_trade_update(symbol, f"🚀 PROFIT LOCKED\nStock: {symbol}\nTrailing SL: ₹{round(new_sl, 2)}")
            elif profit_move >= initial_risk:
                update_stop_loss(symbol, float(entry_price))
                send_trade_update(symbol, f"🔒 BREAKEVEN\nStock: {symbol}\nSL moved to Entry.")

            # --- TRADE STATE ENGINE (PRIORITIZED) ---
            price_strength = current_price > ema20
            volume_strength = latest_volume > volume_avg
            momentum_strength = rsi > 55

            if current_price <= (float(stop_loss) * 1.01):
                current_state = "DANGER"
            elif current_price < ema20 or rsi < 48:
                current_state = "WEAKENING"
            elif price_strength and volume_strength and momentum_strength and current_price > float(target1):
                current_state = "STRONG"
            elif price_strength and momentum_strength:
                current_state = "HEALTHY"
            else:
                current_state = "NEUTRAL"

            TRADE_STATE[symbol] = current_state

            # --- SMART ALERTS ---
            if LAST_ALERT_STATE.get(symbol) != current_state:
                emoji = {"DANGER": "🛑", "WEAKENING": "⚠️", "STRONG": "🚀", "HEALTHY": "📈", "NEUTRAL": "⏳"}
                msg_body = {
                    "DANGER": "Price near stop-loss. Capital protection priority.",
                    "WEAKENING": "Momentum deteriorating. Watch closely.",
                    "STRONG": "Explosive continuation. Holding favorable.",
                    "HEALTHY": "Trend intact. No weakness detected.",
                    "NEUTRAL": "Sideways/Mixed. Trade still active."
                }
                
                msg = f"{emoji[current_state]} {current_state} TRADE\nStock: {symbol} | CMP: ₹{round(current_price, 2)}\n{msg_body[current_state]}"
                send_trade_update(symbol, msg)
                LAST_ALERT_STATE[symbol] = current_state

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

        for symbol in batch:
            try:
                if is_signal_active(symbol): continue
                df = get_dhan_data(symbol)
                if df is None: continue
                
                result = analyze_setup(df, symbol)
                if result:
                    save_signal(result)
                    send_alert(symbol=result['symbol'], action="BUY", entry=result['entry'], sl=result['sl'], 
                               target1=result['target1'], target2=result['target2'], confidence=result['score'], 
                               reason=result['reasons'], quantity=result.get('quantity'))
            except Exception as e:
                logger.error(f"Scanner error for {symbol}: {e}")

        BATCH_INDEX[0] = end
    finally:
        SCAN_LOCK["running"] = False
