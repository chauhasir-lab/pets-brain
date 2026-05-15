import pandas as pd
import logging
from datetime import datetime, timedelta

from strategy import (
    analyze_setup,
    calculate_rsi,
    is_market_hours,
    get_nifty_trend,
    SECTOR_MAP # STEP 2: Sector Map Import
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
LIVE_CONFIDENCE = {}
SECTOR_EXPOSURE = {} # STEP 1: Global Exposure Tracker


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
            
            # Classification & Live Engine
            priority = "HIGH" if score >= 90 else "MEDIUM" if score >= 75 else "LOW"
            TRADE_PRIORITY[symbol] = priority

            df = get_dhan_data(symbol)
            if df is None or df.empty: continue

            current_price = float(df['close'].iloc[-1])
            ema20 = float(df['close'].ewm(span=20, adjust=False).mean().iloc[-1])
            rsi = calculate_rsi(df['close'])
            
            # TRADE STATE & CONFIDENCE
            price_strength = (current_price > ema20)
            if current_price < ema20 or rsi < 48: current_state = "WEAKENING"
            elif price_strength and rsi > 55: current_state = "STRONG" if current_price > float(target1) else "HEALTHY"
            else: current_state = "NEUTRAL"
            
            live_score = score + (10 if current_state == "STRONG" else -10 if current_state == "WEAKENING" else 0)
            LIVE_CONFIDENCE[symbol] = live_score

            # EXIT LOGIC: Confidence Collapse
            if live_score < 50:
                close_trade(symbol, "CONFIDENCE_EXIT", current_price)
                for d in [TRADE_STATE, BREAKEVEN_DONE, LAST_TRAILING_SL, LIVE_CONFIDENCE, TRADE_PRIORITY]: d.pop(symbol, None)
                continue

            # TARGET/SL Logic
            if current_price >= float(target2):
                close_trade(symbol, "TARGET2_HIT", current_price)
                LOSS_STREAK["count"] = 0
                for d in [TRADE_STATE, BREAKEVEN_DONE, LAST_TRAILING_SL, LIVE_CONFIDENCE, TRADE_PRIORITY]: d.pop(symbol, None)
                continue
            
            if current_price <= float(stop_loss):
                close_trade(symbol, "SL_HIT", current_price)
                LOSS_STREAK["count"] += 1
                for d in [TRADE_STATE, BREAKEVEN_DONE, LAST_TRAILING_SL, LIVE_CONFIDENCE, TRADE_PRIORITY]: d.pop(symbol, None)
                continue

            # ADAPTIVE TRAILING
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

        # =========================================
        # STEP 3: SECTOR EXPOSURE RESET
        # =========================================
        SECTOR_EXPOSURE.clear()
        active_trades = get_active_bought_trades()
        for trade in active_trades:
            trade_symbol = trade[0]
            sector = SECTOR_MAP.get(trade_symbol, "UNKNOWN")
            SECTOR_EXPOSURE[sector] = SECTOR_EXPOSURE.get(sector, 0) + 1

        if LOSS_STREAK["count"] >= 3:
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
            # =========================================
            # STEP 4: SECTOR EXPOSURE CHECK
            # =========================================
            sector = SECTOR_MAP.get(symbol, "UNKNOWN")
            sector_count = SECTOR_EXPOSURE.get(sector, 0)
            
            if sector_count >= 2:
                logger.warning(f"{sector} sector overloaded - Skipping {symbol}")
                continue

            if RECENTLY_CLOSED.get(symbol) and (datetime.utcnow() - RECENTLY_CLOSED[symbol]).total_seconds() / 60 < 60:
                continue

            try:
                if is_signal_active(symbol): continue
                df = get_dhan_data(symbol)
                if df is not None:
                    result = analyze_setup(df, symbol)
                    if result:
                        save_signal(result)
                        # STEP 5: Update exposure on success
                        SECTOR_EXPOSURE[sector] = SECTOR_EXPOSURE.get(sector, 0) + 1
                        send_alert(symbol=result['symbol'], action="BUY", entry=result['entry'], sl=result['sl'], target1=result['target1'], target2=result['target2'], confidence=result['score'], reason=result['reasons'], quantity=result.get('quantity'))
            except Exception as e:
                logger.error(f"Scanner error for {symbol}: {e}")

        BATCH_INDEX[0] = start + batch_size
    finally:
        SCAN_LOCK["running"] = False
