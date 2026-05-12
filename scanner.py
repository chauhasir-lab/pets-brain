import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta

from strategy import analyze_setup

from telegram_alert import (
    send_alert,
    send_target_hit,
    send_sl_hit,
    send_trade_update
)

from database import (
    get_connection,
    is_signal_active,
    expire_old_signals,
    get_active_bought_trades,
    close_trade,
    update_trade_note
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
    "VEDL", "UPL", "SHREECEM", "SBILIFE", "HDFCLIFE",
    "DABUR", "MARICO", "COLPAL", "GODREJCP", "PGHH",
    "UNITDSPR", "TRENT", "DMART", "NYKAA",
    "PAYTM", "POLICYBZR", "NAUKRI", "IRCTC",
    "ABCAPITAL", "MUTHOOTFIN", "CHOLAFIN", "BAJAJHLDNG", "SBICARD",
    "TORNTPHARM", "AUROPHARMA", "ALKEM", "LUPIN", "BIOCON",
    "PIIND", "ATUL", "DEEPAKNTR", "ASTRAL", "SUPREMEIND",
    "VOLTAS", "HAVELLS", "CROMPTON", "POLYCAB", "KEI",
    "ADANIGREEN", "TATAPOWER", "CESC",
    "GAIL", "IGL", "PETRONET", "CONCOR",
    "MOTHERSON", "BOSCHLTD", "BALKRISIND", "EXIDEIND"
]

KILL_SWITCH = {
    "losses": 0,
    "active": True
}

BATCH_INDEX = [0]

SCAN_LOCK = {
    "running": False
}


def get_dummy_data(symbol):

    np.random.seed(42)

    dates = pd.date_range(
        end=pd.Timestamp.now(),
        periods=50,
        freq='15min'
    )

    close = np.random.uniform(100, 500, 50)

    df = pd.DataFrame({
        'open': close * np.random.uniform(0.99, 1.01, 50),
        'high': close * np.random.uniform(1.00, 1.02, 50),
        'low': close * np.random.uniform(0.98, 1.00, 50),
        'close': close,
        'volume': np.random.randint(100000, 500000, 50)
    }, index=dates)

    return df


def get_yahoo_data(symbol):

    try:

        import urllib.request
        import json

        yahoo_symbol = f"{symbol}.NS"

        end = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=5)).timestamp())

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{yahoo_symbol}?interval=15m&period1={start}&period2={end}"
        )

        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )

        response = urllib.request.urlopen(req, timeout=10)

        data = json.loads(response.read())

        result = data['chart']['result'][0]

        timestamps = result['timestamp']

        ohlcv = result['indicators']['quote'][0]

        df = pd.DataFrame({
            'open': ohlcv['open'],
            'high': ohlcv['high'],
            'low': ohlcv['low'],
            'close': ohlcv['close'],
            'volume': ohlcv['volume']
        }, index=pd.to_datetime(timestamps, unit='s'))

        df.dropna(inplace=True)

        if len(df) < 20:
            return get_dummy_data(symbol)

        return df

    except Exception as e:

        logger.error(f"Yahoo fetch error for {symbol}: {e}")

        return get_dummy_data(symbol)


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
            VALUES (%s, %s, %s, %s, %s, %s, %s)
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
                status,
                entry_price,
                stop_loss,
                target1,
                target2,
                score,
                rr,
                quantity
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            signal['symbol'],
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

        logger.error(f"Save signal error: {e}")


def monitor_active_trades():

    trades = get_active_bought_trades()

    if not trades:
        return

    logger.info(f"Monitoring {len(trades)} active trades")

    for trade in trades:

        try:

            symbol = trade[0]
            entry = float(trade[1])
            sl = float(trade[2])
            target1 = float(trade[3])
            target2 = float(trade[4])

            df = get_yahoo_data(symbol)

            current_price = float(df['close'].iloc[-1])

            # STOP LOSS HIT
            if current_price <= sl:

                send_sl_hit(symbol, sl, current_price)

                close_trade(symbol, "SL_HIT")

                continue

            # TARGET 2 HIT
            if current_price >= target2:

                send_target_hit(symbol, target2, current_price)

                close_trade(symbol, "TARGET2_HIT")

                continue

            # TARGET 1 HIT
            if current_price >= target1:

                note = (
                    f"Target 1 reached near ₹{target1}. "
                    f"Consider partial booking."
                )

                send_target_hit(symbol, target1, current_price)

                update_trade_note(symbol, note)

        except Exception as e:

            logger.error(f"Trade monitor error: {e}")


def run_scanner():

    if SCAN_LOCK["running"]:
        logger.warning("Scanner already running. Skipping.")
        return

    SCAN_LOCK["running"] = True

    try:

        expire_old_signals()

        monitor_active_trades()

        if not KILL_SWITCH["active"]:
            logger.warning("Kill switch active.")
            return

        batch_size = 10

        start = BATCH_INDEX[0]
        end = start + batch_size

        batch = WATCHLIST[start:end]

        if not batch:
            BATCH_INDEX[0] = 0
            logger.info("Watchlist completed.")
            return

        logger.info(f"Scanning stocks {start} to {end}")

        for symbol in batch:

            try:

                if is_signal_active(symbol):
                    logger.info(f"Skipping duplicate signal: {symbol}")
                    continue

                df = get_yahoo_data(symbol)

                result = analyze_setup(df, symbol)

                if result and result['score'] >= 60:

                    logger.info(
                        f"Signal found: {symbol} | Score: {result['score']}"
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
