import pandas as pd
import logging
from datetime import datetime, timedelta

from strategy import (
    analyze_setup,
    calculate_rsi,
    is_market_hours
)

from telegram_alert import (
    send_alert,
    send_trade_update
)

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

MAX_ACTIVE_TRADES = 5


def get_yahoo_data(symbol):

    try:

        import urllib.request
        import json

        yahoo_symbol = f"{symbol}.NS"

        end = int(datetime.now().timestamp())

        start = int(
            (
                datetime.now()
                - timedelta(days=60)
            ).timestamp()
        )

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{yahoo_symbol}"
            f"?interval=15m"
            f"&period1={start}"
            f"&period2={end}"
        )

        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0'
            }
        )

        response = urllib.request.urlopen(
            req,
            timeout=10
        )

        data = json.loads(
            response.read()
        )

        result = data['chart']['result'][0]

        timestamps = result['timestamp']

        ohlcv = result['indicators']['quote'][0]

        df = pd.DataFrame({
            'open': ohlcv['open'],
            'high': ohlcv['high'],
            'low': ohlcv['low'],
            'close': ohlcv['close'],
            'volume': ohlcv['volume']
        })

        df.index = pd.to_datetime(
            timestamps,
            unit='s'
        )

        df.dropna(inplace=True)

        if len(df) < 20:

            logger.warning(
                f"Insufficient data: {symbol}"
            )

            return None

        return df

    except Exception as e:

        logger.error(
            f"Yahoo fetch error for {symbol}: {e}"
        )

        return None


def save_signal(signal):

    conn = get_connection()

    if not conn:
        return

    try:

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO signals
            (
                symbol,
                action,
                entry_price,
                stop_loss,
                target,
                confidence,
                reason
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s
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
            INSERT INTO active_signals
            (
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
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
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

        logger.info(
            f"Signal saved: {signal['symbol']}"
        )

    except Exception as e:

        logger.error(
            f"Save signal error: {e}"
        )


def evaluate_open_positions():

    trades = get_active_bought_trades()

    if not trades:
        return

    logger.info(
        f"Monitoring {len(trades)} active trades"
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

            df = get_yahoo_data(symbol)

            if df is None:
                continue

            current_price = float(
                df['close'].iloc[-1]
            )

            ema20 = (
                df['close']
                .ewm(span=20, adjust=False)
                .mean()
                .iloc[-1]
            )

            rsi_df = calculate_rsi(df)

            rsi = rsi_df['rsi'].iloc[-1]

            # TARGET 2
            if current_price >= float(target2):

                send_trade_update(
                    symbol,
                    f"""
🚀 TARGET 2 HIT

Stock: {symbol}
CMP: ₹{round(current_price, 2)}

Full target achieved.
"""
                )

                close_trade(
                    symbol,
                    "TARGET2_HIT",
                    current_price
                )

                continue

            # TARGET 1
            if current_price >= float(target1):

                send_trade_update(
                    symbol,
                    f"""
🎯 TARGET 1 HIT

Stock: {symbol}
CMP: ₹{round(current_price, 2)}

Book partial profits.
"""
                )

                update_trade_note(
                    symbol,
                    "Target 1 achieved"
                )

            # STOP LOSS
            if current_price <= float(stop_loss):

                send_trade_update(
                    symbol,
                    f"""
❌ STOP LOSS HIT

Stock: {symbol}
CMP: ₹{round(current_price, 2)}

Trade closed.
"""
                )

                close_trade(
                    symbol,
                    "SL_HIT",
                    current_price
                )

                continue

            # TRAILING LOGIC
            profit_move = (
                current_price
                - float(entry_price)
            )

            initial_risk = (
                float(entry_price)
                - float(stop_loss)
            )

            # Breakeven
            if profit_move >= initial_risk:

                new_sl = float(entry_price)

                update_stop_loss(
                    symbol,
                    new_sl
                )

            # Profit lock
            if profit_move >= (2 * initial_risk):

                new_sl = (
                    float(entry_price)
                    + initial_risk
                )

                update_stop_loss(
                    symbol,
                    new_sl
                )

            # Weakness warning
            if (
                current_price < ema20
                or rsi < 48
            ):

                send_trade_update(
                    symbol,
                    f"""
⚠️ MOMENTUM WEAKENING

Stock: {symbol}

EMA20 / RSI weakness detected.
"""
                )

        except Exception as e:

            logger.error(
                f"Trade monitor error for {symbol}: {e}"
            )


def run_scanner():

    if SCAN_LOCK["running"]:

        logger.warning(
            "Scanner already running. Skipping."
        )

        return

    if not is_market_hours():

        logger.info(
            "Market closed. Scanner sleeping."
        )

        return

    SCAN_LOCK["running"] = True

    try:

        expire_old_signals()

        evaluate_open_positions()

        if not KILL_SWITCH["active"]:

            logger.warning(
                "Kill switch active."
            )

            return

        active_trades = get_active_bought_trades()

        if len(active_trades) >= MAX_ACTIVE_TRADES:

            logger.warning(
                "Max active trades reached."
            )

            return

        batch_size = 10

        start = BATCH_INDEX[0]

        end = start + batch_size

        batch = WATCHLIST[start:end]

        if not batch:

            BATCH_INDEX[0] = 0

            logger.info(
                "Watchlist completed. Resetting."
            )

            return

        logger.info(
            f"Scanning stocks {start} to {end}"
        )

        for symbol in batch:

            try:

                if is_signal_active(symbol):

                    logger.info(
                        f"Skipping duplicate signal: {symbol}"
                    )

                    continue

                df = get_yahoo_data(symbol)

                if df is None:
                    continue

                result = analyze_setup(
                    df,
                    symbol
                )

                if result:

                    logger.info(
                        f"""
SIGNAL FOUND

Symbol: {symbol}
Score: {result['score']}
RR: {result['rr']}
Regime: {result['regime']}
"""
                    )

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
                        trailing_sl=result.get(
                            'trailing_sl'
                        ),
                        quantity=result.get(
                            'quantity'
                        ),
                        nifty_trend=result.get(
                            'nifty_trend'
                        )
                    )

            except Exception as e:

                logger.error(
                    f"Scanner error for {symbol}: {e}"
                )

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