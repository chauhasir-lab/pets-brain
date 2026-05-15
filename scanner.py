import pandas as pd
import logging
from datetime import datetime, timedelta

from strategy import (
    analyze_setup,
    calculate_rsi,
    is_market_hours,
    get_nifty_trend
)
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
RECENTLY_CLOSED = {}
MARKET_PANIC = {"active": False}
STATE_WEAKNESS_COUNT = {}
LOSS_STREAK = {"count": 0}
TRADE_PRIORITY = {}
LIVE_CONFIDENCE = {} # STEP 1: Live score tracking


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
            
            # TRADE PRIORITY CLASSIFICATION
            if score >= 90: priority = "HIGH"
            elif score >= 75: priority = "MEDIUM"
            else: priority = "LOW"
            TRADE_PRIORITY[symbol] = priority

            trade_age_hours = (datetime.utcnow() - signal_time).total_seconds() / 3600

            df = get_dhan_data(symbol)
            if df is None or df.empty: continue

            current_price = float(df['close'].iloc[-1])
            ema20 = float(df['close'].ewm(span=20, adjust=False).mean().iloc[-1])
            volume_avg = float(df['volume'].rolling(window=10).mean().iloc[-1])
            latest_volume = float(df['volume'].iloc[-1])
            
            # Indicator logic
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0).rolling(window=14).mean())
            loss = ((-delta.where(delta < 0, 0)).rolling(window=14).mean())
            rsi = float((100 - (100 / (1 + (gain / (loss + 1e-10))))).iloc[-1])

            # TRADE STATE Engine
            price_strength = (current_price > ema20)
            if current_price <= (float(stop_loss) * 1.01): current_state = "DANGER"
            elif current_price < ema20 or rsi < 48: current_state = "WEAKENING"
            elif price_strength and rsi > 55 and current_price > float(target1): current_state = "STRONG"
            elif price_strength and rsi > 55: current_state = "HEALTHY"
            else: current_state = "NEUTRAL"
            TRADE_STATE[symbol] = current_state

            # STEP 2: LIVE CONFIDENCE ENGINE
            live_score = score
            if current_price > ema20: live_score += 5
            if rsi > 60: live_score += 5
            if latest_volume > volume_avg: live_score += 5
            
            if current_state == "STRONG": live_score += 10
            elif current_state == "WEAKENING": live_score -= 10
            elif current_state == "DANGER": live_score -= 20
            
            LIVE_CONFIDENCE[symbol] = live_score

            # STEP 3: CONFIDENCE COLLAPSE EXIT
            if live_score < 50:
                send_trade_update(symbol, (f"📉 CONFIDENCE COLLAPSE EXIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}\nConfidence severely degraded. Edge lost."))
                save_trade_analytics(symbol=symbol, result="CONFIDENCE_EXIT", entry_price=entry_price, exit_price=current_price, stop_loss=stop_loss, target1=target1, target2=target2, rr=rr, score=live_score, regime=setup_type, state="CONFIDENCE_EXIT")
                close_trade(symbol, "CONFIDENCE_EXIT", current_price)
                LOSS_STREAK["count"] += 1
                for d in [LAST_ALERT_STATE, TRADE_STATE, BREAKEVEN_DONE, LAST_TRAILING_SL, STATE_WEAKNESS_COUNT, TRADE_PRIORITY, LIVE_CONFIDENCE]: d.pop(symbol, None)
                RECENTLY_CLOSED[symbol] = datetime.utcnow()
                continue

            # =========================================
            # TARGET / SL HIT Logic
            # =========================================
            if current_price >= float(target2):
                save_trade_analytics(symbol=symbol, result="TARGET2_HIT", entry_price=entry_price, exit_price=current_price, stop_loss=stop_loss, target1=target1, target2=target2, rr=rr, score=score, regime=setup_type, state=TRADE_STATE.get(symbol))
                close_trade(symbol, "TARGET2_HIT", current_price)
                LOSS_STREAK["count"] = 0
                for d in [LAST_ALERT_STATE, TRADE_STATE, BREAKEVEN_DONE, LAST_TRAILING_SL, STATE_WEAKNESS_COUNT, TRADE_PRIORITY, LIVE_CONFIDENCE]: d.pop(symbol, None)
                RECENTLY_CLOSED[symbol] = datetime.utcnow()
                continue

            if current_price <= float(stop_loss):
                save_trade_analytics(symbol=symbol, result="SL_HIT", entry_price=entry_price, exit_price=current_price, stop_loss=stop_loss, target1=target1, target2=target2, rr=rr, score=score, regime=setup_type, state=TRADE_STATE.get(symbol))
                close_trade(symbol, "SL_HIT", current_price)
                LOSS_STREAK["count"] += 1
                for d in [LAST_ALERT_STATE, TRADE_STATE, BREAKEVEN_DONE, LAST_TRAILING_SL, STATE_WEAKNESS_COUNT, TRADE_PRIORITY, LIVE_CONFIDENCE]: d.pop(symbol, None)
                RECENTLY_CLOSED[symbol] = datetime.utcnow()
                continue

            # =========================================
            # QUALITY DECAY Logic
            # =========================================
            if current_state == "WEAKENING": STATE_WEAKNESS_COUNT[symbol] = STATE_WEAKNESS_COUNT.get(symbol, 0) + 1
            else: STATE_WEAKNESS_COUNT[symbol] = 0

            decay_threshold = 5 if priority == "HIGH" else 3
            if STATE_WEAKNESS_COUNT.get(symbol, 0) >= decay_threshold:
                send_trade_update(symbol, f"📉 QUALITY DECAY EXIT\nStock: {symbol}\nCMP: ₹{round(current_price, 2)}")
                save_trade_analytics(symbol=symbol, result="QUALITY_DECAY_EXIT", entry_price=entry_price, exit_price=current_price, stop_loss=stop_loss, target1=target1, target2=target2, rr=rr, score=score, regime=setup_type, state="QUALITY_DECAY")
                close_trade(symbol, "QUALITY_DECAY_EXIT", current_price)
                LOSS_STREAK["count"] += 1
                for d in [LAST_ALERT_STATE, TRADE_STATE, BREAKEVEN_DONE, LAST_TRAILING_SL, STATE_WEAKNESS_COUNT, TRADE_PRIORITY, LIVE_CONFIDENCE]: d.pop(symbol, None)
                RECENTLY_CLOSED[symbol] = datetime.utcnow()
                continue

            # =========================================
            # ADAPTIVE TRAILING & BREAKEVEN
            # =========================================
            if (current_state == "STRONG" and priority == "HIGH"):
                new_sl = round(max(float(stop_loss), current_price * 0.992), 2)
                if new_sl > float(stop_loss): update_stop_loss(symbol, new_sl)
            elif (current_state == "WEAKENING" and priority != "HIGH"):
                new_sl = round(max(float(stop_loss), current_price * 0.996), 2)
                if new_sl > float(stop_loss): update_stop_loss(symbol, new_sl)

            if current_price >= float(target1) and not BREAKEVEN_DONE.get(symbol):
                update_stop_loss(symbol, round(float(entry_price), 2))
                BREAKEVEN_DONE[symbol] = True

        except Exception as e:
            logger.error(f"Trade monitor error for {symbol}: {e}")


def run_scanner():
    if SCAN_LOCK["running"] or not is_market_hours(): return
    SCAN_LOCK["running"] = True
    try:
        market_trend = get_nifty_trend()
        if market_trend == "BULLISH": LOSS_STREAK["count"] = 0
        MARKET_PANIC["active"] = (market_trend == "BEARISH")

        if LOSS_STREAK["count"] >= 3:
            logger.warning("LOSS STREAK DEFENSE ACTIVE")
            evaluate_open_positions()
            return

        expire_old_signals()
        evaluate_open_positions()

        if len(get_active_bought_trades()) >= MAX_ACTIVE_TRADES: return

        batch_size = 10
        start = BATCH_INDEX[0]
        batch = WATCHLIST[start:start + batch_size]

        if not batch:
            BATCH_INDEX[0] = 0
            return

        for symbol in batch:
            if RECENTLY_CLOSED.get(symbol) and (datetime.utcnow() - RECENTLY_CLOSED[symbol]).total_seconds() / 60 < 60:
                continue
            try:
                if is_signal_active(symbol): continue
                df = get_dhan_data(symbol)
                if df is not None:
                    result = analyze_setup(df, symbol)
                    if result:
                        save_signal(result)
                        send_alert(symbol=result['symbol'], action="BUY", entry=result['entry'], sl=result['sl'], target1=result['target1'], target2=result['target2'], confidence=result['score'], reason=result['reasons'], quantity=result.get('quantity'))
            except Exception as e:
                logger.error(f"Scanner error for {symbol}: {e}")

        BATCH_INDEX[0] = start + batch_size
    finally:
        SCAN_LOCK["running"] = False
