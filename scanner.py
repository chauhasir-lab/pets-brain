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


def save_signal(signal):
    conn = get_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO signals
            (symbol, action, entry_price, stop_loss, target, confidence, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            signal['symbol'], "BUY", signal['entry'],
            signal['sl'], signal['target1'],
            signal['score'], signal['reasons']
        ))
        cursor.execute("""
            INSERT INTO active_signals
            (symbol, setup_type, status, entry_price, stop_loss, target1, target2, score, rr, quantity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            signal['symbol'], signal.get('regime', 'NORMAL'), 'NEW',
            signal['entry'], signal['sl'], signal['target1'],
            signal['target2'], signal['score'], signal['rr'], signal['quantity']
        ))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Signal saved: {signal['symbol']}")
    except Exception as e:
        logger.error(f"Save signal error: {e}")


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
            ema20 = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            rsi = calculate_rsi(df)['rsi'].iloc[-1]
            volume_avg = df['volume'].rolling(window=10).mean().iloc[-1]
            latest_volume = df['volume'].iloc[-1]

            # TARGET 2 HIT
            if current_price >= float(target2):
                send_trade_update(symbol,
                    f"🚀 TARGET 2 HIT\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Full target achieved. Exit position."
                )
                close_trade(symbol, "TARGET2_HIT", current_price)
                continue

            # TARGET 1 HIT
            if current_price >= float(target1):
                send_trade_update(symbol,
                    f"🎯 TARGET 1 HIT\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Book 50% position here. Trail rest."
                )
                update_trade_note(symbol, "Target 1 achieved")

            # STOP LOSS HIT
            if current_price <= float(stop_loss):
                send_trade_update(symbol,
                    f"❌ STOP LOSS HIT\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Trade closed. Accept loss and move on."
                )
                close_trade(symbol, "SL_HIT", current_price)
                continue

            # TRAILING SL
            profit_move = current_price - float(entry_price)
            initial_risk = float(entry_price) - float(stop_loss)

            if profit_move >= (2 * initial_risk):
                new_sl = float(entry_price) + initial_risk
                update_stop_loss(symbol, new_sl)
                send_trade_update(symbol,
                    f"🚀 PROFIT LOCKED\n"
                    f"Stock: {symbol}\n"
                    f"Trailing SL moved to: ₹{round(new_sl, 2)}\n"
                    f"Risk free trade now."
                )
            elif profit_move >= initial_risk:
                update_stop_loss(symbol, float(entry_price))
                send_trade_update(symbol,
                    f"🔒 BREAKEVEN ACTIVATED\n"
                    f"Stock: {symbol}\n"
                    f"SL moved to entry: ₹{round(float(entry_price), 2)}\n"
                    f"No loss possible now."
                )

            # INTELLIGENT TRADE ANALYSIS
            price_strength = current_price > ema20
            volume_strength = latest_volume > volume_avg
            momentum_strength = rsi > 55

            if price_strength and volume_strength and momentum_strength:
                send_trade_update(symbol,
                    f"📈 TRADE HEALTHY\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Trend strong above EMA20.\n"
                    f"Volume participation healthy.\n"
                    f"Momentum intact.\n"
                    f"Holding remains valid."
                )
            elif current_price < ema20 or rsi < 48:
                send_trade_update(symbol,
                    f"⚠️ MOMENTUM WEAKENING\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Price losing EMA support.\n"
                    f"Momentum deteriorating.\n"
                    f"Probability of pullback increasing.\n"
                    f"Consider reducing exposure."
                )
            else:
                send_trade_update(symbol,
                    f"⏳ TRADE NEUTRAL\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Trade active but momentum mixed.\n"
                    f"No strong exit signal yet.\n"
                    f"Wait for confirmation."
                )

        except Exception as e:
            logger.error(f"Trade monitor error for {symbol}: {e}")


def run_scanner():
    if SCAN_LOCK["running"]:
        logger.warning("Scanner already running. Skipping.")
        return

    if not is_market_hours():
        logger.info("Market closed. Scanner sleeping.")
        return

    SCAN_LOCK["running"] = True

    try:
        expire_old_signals()
        evaluate_open_positions()

        if not KILL_SWITCH["active"]:
            logger.warning("Kill switch active.")
            return

        active_trades = get_active_bought_trades()
        if len(active_trades) >= MAX_ACTIVE_TRADES:
            logger.warning("Max active trades reached.")
            return

        batch_size = 10
        start = BATCH_INDEX[0]
        end = start + batch_size
        batch = WATCHLIST[start:end]

        if not batch:
            BATCH_INDEX[0] = 0
            logger.info("Watchlist completed. Resetting.")
            return

        logger.info(f"Scanning stocks {start} to {end}")

        for symbol in batch:
            try:
                if is_signal_active(symbol):
                    logger.info(f"Skipping duplicate: {symbol}")
                    continue

                df = get_dhan_data(symbol)
                if df is None:
                    logger.warning(f"No data for {symbol} — skipping")
                    continue

                result = analyze_setup(df, symbol)

                if result:
                    logger.info(f"Signal: {symbol} | Score: {result['score']} | RR: {result['rr']}")
                    save_signal(result)
                    send_alert(
                        symbol=result['symbol'],
                        action="BUY",
                        entry=result['entry'],
                        sl=result['sl'],
                        target1=result['target1'],
                        target2=result['target2'],
                        confidence=result['score'],
                        reason=result['reasons'],
                        trailing_sl=result.get('trailing_sl'),
                        quantity=result.get('quantity'),
                        nifty_trend=result.get('nifty_trend')
                    )

            except Exception as e:
                logger.error(f"Scanner error for {symbol}: {e}")

        BATCH_INDEX[0] = end

    finally:
        SCAN_LOCK["running"] = False


def send_test_alert():
    send_alert(
        symbol="TEST",
        action="BUY",
        entry=100,
        sl=95,
        target1=102,
        target2=104,
        confidence=85,
        reason="PETS system test"
    )
