import pandas as pd
import logging
from datetime import datetime, timedelta

from strategy import (
    analyze_setup,
    calculate_rsi,
    is_market_hours,
    get_nifty_trend,
    SECTOR_MAP 
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
    save_trade_analytics,
    execute_query 
)

logger = logging.getLogger(__name__)

# --- STEP 1: MARKET BREADTH & SYSTEM STATS ---
MARKET_BREADTH = {
    "bullish": 0,
    "bearish": 0
}

SYSTEM_STATS = {
    "last_signal_time": None,
    "last_error": None,
    "total_scans": 0,
    "successful_signals": 0
}

LAST_SCAN_TIME = {
    "time": None
}

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
SECTOR_EXPOSURE = {} 


def save_signal(signal):
    query_signal = """
        INSERT INTO signals (symbol, action, entry_price, stop_loss, target, confidence, reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    execute_query(query_signal, (signal['symbol'], "BUY", signal['entry'], signal['sl'], 
                                 signal['target1'], signal['score'], signal['reasons']), commit=True)

    query_active = """
        INSERT INTO active_signals (symbol, setup_type, status, entry_price, stop_loss, target1, target2, score, rr, quantity)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    execute_query(query_active, (signal['symbol'], signal.get('regime', 'NORMAL'), 'NEW', signal['entry'], 
                                 signal['sl'], signal['target1'], signal['target2'], signal['score'], 
                                 signal['rr'], signal['quantity']), commit=True)


def evaluate_open_positions():
    trades = get_active_bought_trades()
    if not trades: return

    for trade in trades:
        try:
            (symbol, entry_price, stop_loss, target1, target2, 
             quantity, rr, score, signal_time, setup_type) = trade
            
            TRADE_PRIORITY[symbol] = "HIGH" if score >= 90 else "MEDIUM" if score >= 75 else "LOW"

            df = get_dhan_data(symbol)
            if df is None or df.empty: continue

            current_price = float(df['close'].iloc[-1])
            ema20 = float(df['close'].ewm(span=20, adjust=False).mean().iloc[-1])
            rsi = calculate_rsi(df['close'])
            
            price_strength = (current_price > ema20)
            if current_price < ema20 or rsi < 48: current_state = "WEAKENING"
            elif price_strength and rsi > 55: current_state = "STRONG" if current_price > float(target1) else "HEALTHY"
            else: current_state = "NEUTRAL"
            
            live_score = score + (10 if current_state == "STRONG" else -10 if current_state == "WEAKENING" else 0)
            LIVE_CONFIDENCE[symbol] = live_score

            if live_score < 50:
                close_trade(symbol, "CONFIDENCE_EXIT", current_price)
                for d in [TRADE_STATE, BREAKEVEN_DONE, LAST_TRAILING_SL, LIVE_CONFIDENCE, TRADE_PRIORITY]: d.pop(symbol, None)
                continue

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

            if current_price >= float(target1) and not BREAKEVEN_DONE.get(symbol):
                update_stop_loss(symbol, round(float(entry_price), 2))
                BREAKEVEN_DONE[symbol] = True

        except Exception as e:
            logger.error(f"Trade monitor error for {symbol}: {e}")
            SYSTEM_STATS["last_error"] = str(e)


def run_scanner():
    if SCAN_LOCK["running"] or not is_market_hours(): return
    SCAN_LOCK["running"] = True
    try:
        # --- STEP 2: RESET BREADTH & STATS ---
        MARKET_BREADTH["bullish"] = 0
        MARKET_BREADTH["bearish"] = 0
        
        LAST_SCAN_TIME["time"] = datetime.utcnow()
        SYSTEM_STATS["total_scans"] += 1

        market_trend = get_nifty_trend()
        if market_trend == "BULLISH": LOSS_STREAK["count"] = 0
        MARKET_PANIC["active"] = (market_trend == "BEARISH")

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
                
                # --- STEP 3: CALCULATE MARKET BREADTH ---
                if df is not None and len(df) > 20:
                    ema20 = (df['close'].ewm(span=20, adjust=False).mean().iloc[-1])
                    current_price = float(df['close'].iloc[-1])

                    if current_price > ema20:
                        MARKET_BREADTH["bullish"] += 1
                    else:
                        MARKET_BREADTH["bearish"] += 1

                    # --- STEP 4: MARKET BREADTH FILTER ---
                    total_breadth = MARKET_BREADTH["bullish"] + MARKET_BREADTH["bearish"]
                    
                    if total_breadth > 0:
                        bullish_ratio = MARKET_BREADTH["bullish"] / total_breadth
                        if bullish_ratio < 0.55:
                            logger.warning(f"Weak market breadth detected for {symbol} (Ratio: {bullish_ratio:.2f})")
                            continue

                    # Analyze setup after breadth check
                    result = analyze_setup(df, symbol)
                    if result:
                        save_signal(result)
                        SYSTEM_STATS["successful_signals"] += 1
                        SYSTEM_STATS["last_signal_time"] = datetime.utcnow()
                        
                        SECTOR_EXPOSURE[sector] = SECTOR_EXPOSURE.get(sector, 0) + 1
                        send_alert(symbol=result['symbol'], action="BUY", entry=result['entry'], 
                                   sl=result['sl'], target1=result['target1'], target2=result['target2'], 
                                   confidence=result['score'], reason=result['reasons'], quantity=result.get('quantity'))
            
            except Exception as e:
                logger.error(f"Scanner error for {symbol}: {e}")
                SYSTEM_STATS["last_error"] = str(e)

        BATCH_INDEX[0] = start + batch_size
    except Exception as e:
        logger.error(f"Global run_scanner error: {e}")
        SYSTEM_STATS["last_error"] = str(e)
    finally:
        SCAN_LOCK["running"] = False
