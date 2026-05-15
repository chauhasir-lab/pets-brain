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

KILL_SWITCH = {
    "losses": 0,
    "active": True
}

BATCH_INDEX = [0]

SCAN_LOCK = {
    "running": False
}

MAX_ACTIVE_TRADES = 3

LAST_ALERT_STATE = {}

TRADE_STATE = {}

BREAKEVEN_DONE = {}


def save_signal(signal):

    conn = get_connection()

    if not conn:
        return

    try:

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO signals (
                symbol,
                action,
                entry_price,
                stop_loss,
                target,
                confidence,
                reason
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            signal['symbol'],
            "BUY",
            signal['entry'],
            signal['sl'],
            signal['target1'],
            signal['score'],
            signal['reasons']
        ))

        cursor.execute("""
            INSERT INTO active_signals (
                symbol,
                setup_type,
                status,
                entry_price,
                stop_loss,
                target1,
                target2,
                score,
                rr,
                quantity
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
        """, (
            signal['symbol'],
            signal.get('regime', 'NORMAL'),
            'NEW',
            signal['entry'],
            signal['sl'],
            signal['target1'],
            signal['target2'],
            signal['score'],
            signal['rr'],
            signal['quantity']
        ))

        conn.commit()

        cursor.close()

        conn.close()

    except Exception as e:

        logger.error(
            f"Save signal error: {e}"
        )


def evaluate_open_positions():

    trades = get_active_bought_trades()

    if not trades:
        return

    logger.info(
        f"Monitoring {len(trades)} trades"
    )

    for trade in trades:

        try:

            (
                symbol,
                entry_price,
                stop_loss,
                target1,
                target2,
                quantity,
                rr,
                score,
                signal_time,
                setup_type
            ) = trade

            df = get_dhan_data(symbol)

            if df is None or df.empty:
                continue

            current_price = float(
                df['close'].iloc[-1]
            )

            ema20 = float(
                df['close']
                .ewm(span=20, adjust=False)
                .mean()
                .iloc[-1]
            )

            # RSI
            delta = df['close'].diff()

            gain = (
                delta.where(delta > 0, 0)
                .rolling(window=14)
                .mean()
            )

            loss = (
                (-delta.where(delta < 0, 0))
                .rolling(window=14)
                .mean()
            )

            rs = gain / (loss + 1e-10)

            rsi = float(
                (
                    100 -
                    (
                        100 / (1 + rs)
                    )
                ).iloc[-1]
            )

            volume_avg = float(
                df['volume']
                .rolling(window=10)
                .mean()
                .iloc[-1]
            )

            latest_volume = float(
                df['volume'].iloc[-1]
            )

            # =========================================
            # EXIT LOGIC
            # =========================================

            if current_price >= float(target2):

                send_trade_update(
                    symbol,
                    (
                        f"🚀 TARGET 2 HIT\n"
                        f"Stock: {symbol}\n"
                        f"CMP: ₹{round(current_price, 2)}\n"
                        f"Full target achieved."
                    )
                )

                close_trade(
                    symbol,
                    "TARGET2_HIT",
                    current_price
                )

                LAST_ALERT_STATE.pop(
                    symbol,
                    None
                )

                TRADE_STATE.pop(
                    symbol,
                    None
                )

                BREAKEVEN_DONE.pop(
                    symbol,
                    None
                )

                continue

            # =========================================
            # TARGET 1 → BREAKEVEN
            # =========================================

            if (
                current_price >= float(target1)
                and not BREAKEVEN_DONE.get(symbol)
            ):

                new_sl = round(
                    float(entry_price),
                    2
                )

                update_stop_loss(
                    symbol,
                    new_sl
                )

                send_trade_update(
                    symbol,
                    (
                        f"🎯 TARGET 1 HIT\n"
                        f"Stock: {symbol}\n"
                        f"CMP: ₹{round(current_price, 2)}\n"
                        f"SL shifted to breakeven.\n"
                        f"Risk-free trade now."
                    )
                )

                update_trade_note(
                    symbol,
                    (
                        "Target 1 achieved | "
                        "Breakeven activated"
                    )
                )

                BREAKEVEN_DONE[symbol] = True

            # =========================================
            # STOP LOSS
            # =========================================

            if current_price <= float(stop_loss):

                send_trade_update(
                    symbol,
                    (
                        f"❌ STOP LOSS HIT\n"
                        f"Stock: {symbol}\n"
                        f"CMP: ₹{round(current_price, 2)}\n"
                        f"Exit position."
                    )
                )

                close_trade(
                    symbol,
                    "SL_HIT",
                    current_price
                )

                LAST_ALERT_STATE.pop(
                    symbol,
                    None
                )

                TRADE_STATE.pop(
                    symbol,
                    None
                )

                BREAKEVEN_DONE.pop(
                    symbol,
                    None
                )

                continue

            # =========================================
            # TRADE STATE ENGINE
            # =========================================

            price_strength = (
                current_price > ema20
            )

            volume_strength = (
                latest_volume > volume_avg
            )

            momentum_strength = (
                rsi > 55
            )

            if (
                current_price <=
                (float(stop_loss) * 1.01)
            ):

                current_state = "DANGER"

            elif (
                current_price < ema20
                or rsi < 48
            ):

                current_state = "WEAKENING"

            elif (
                price_strength
                and volume_strength
                and momentum_strength
                and current_price > float(target1)
            ):

                current_state = "STRONG"

            elif (
                price_strength
                and momentum_strength
            ):

                current_state = "HEALTHY"

            else:

                current_state = "NEUTRAL"

            TRADE_STATE[symbol] = current_state

            # =========================================
            # ADAPTIVE TRAILING LOGIC
            # =========================================

            if current_state == "STRONG":

                new_sl = round(
                    max(
                        float(stop_loss),
                        current_price * 0.992
                    ),
                    2
                )

                if new_sl > float(stop_loss):

                    update_stop_loss(
                        symbol,
                        new_sl
                    )

                    logger.info(
                        f"{symbol} trailing "
                        f"SL updated to {new_sl}"
                    )

            elif current_state == "WEAKENING":

                new_sl = round(
                    max(
                        float(stop_loss),
                        current_price * 0.996
                    ),
                    2
                )

                if new_sl > float(stop_loss):

                    update_stop_loss(
                        symbol,
                        new_sl
                    )

                    logger.info(
                        f"{symbol} defensive "
                        f"SL updated to {new_sl}"
                    )

            # =========================================
            # SMART ALERT ENGINE
            # =========================================

            if (
                LAST_ALERT_STATE.get(symbol)
                != current_state
            ):

                if current_state == "STRONG":

                    msg = (
                        f"🚀 STRONG TRADE\n"
                        f"Stock: {symbol}\n"
                        f"CMP: ₹{round(current_price, 2)}\n"
                        f"Strong continuation.\n"
                        f"Momentum and trend healthy."
                    )

                elif current_state == "HEALTHY":

                    msg = (
                        f"📈 HEALTHY TRADE\n"
                        f"Stock: {symbol}\n"
                        f"CMP: ₹{round(current_price, 2)}\n"
                        f"Trend intact.\n"
                        f"No major weakness detected."
                    )

                elif current_state == "WEAKENING":

                    msg = (
                        f"⚠️ MOMENTUM WEAKENING\n"
                        f"Stock: {symbol}\n"
                        f"CMP: ₹{round(current_price, 2)}\n"
                        f"Momentum deteriorating.\n"
                        f"Watch closely."
                    )

                elif current_state == "DANGER":

                    msg = (
                        f"🛑 DANGER ZONE\n"
                        f"Stock: {symbol}\n"
                        f"CMP: ₹{round(current_price, 2)}\n"
                        f"Price near stop-loss.\n"
                        f"Capital protection priority."
                    )

                else:

                    msg = (
                        f"⏳ TRADE NEUTRAL\n"
                        f"Stock: {symbol}\n"
                        f"CMP: ₹{round(current_price, 2)}\n"
                        f"No strong directional edge."
                    )

                send_trade_update(
                    symbol,
                    msg
                )

                LAST_ALERT_STATE[symbol] = current_state

        except Exception as e:

            logger.error(
                f"Trade monitor error "
                f"for {symbol}: {e}"
            )


def run_scanner():

    if (
        SCAN_LOCK["running"]
        or not is_market_hours()
    ):
        return

    SCAN_LOCK["running"] = True

    try:

        expire_old_signals()

        evaluate_open_positions()

        if (
            not KILL_SWITCH["active"]
            or len(
                get_active_bought_trades()
            ) >= MAX_ACTIVE_TRADES
        ):
            return

        batch_size = 10

        start = BATCH_INDEX[0]

        end = start + batch_size

        batch = WATCHLIST[start:end]

        if not batch:

            BATCH_INDEX[0] = 0

            return

        logger.info(
            f"Scanning batch: {batch}"
        )

        for symbol in batch:

            try:

                if is_signal_active(symbol):
                    continue

                df = get_dhan_data(symbol)

                if df is None:
                    continue

                result = analyze_setup(
                    df,
                    symbol
                )

                if result:

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
                        quantity=result.get('quantity')
                    )

                    logger.info(
                        f"Signal generated: "
                        f"{symbol}"
                    )

            except Exception as e:

                logger.error(
                    f"Scanner error "
                    f"for {symbol}: {e}"
                )

        BATCH_INDEX[0] = end

    finally:

        SCAN_LOCK["running"] = False
