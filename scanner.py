import pandas as pd
import numpy as np
import logging
import os
from datetime import datetime, timedelta

from strategy import analyze_setup
from telegram_alert import send_alert
from database import (
    get_connection,
    is_signal_active,
    expire_old_signals
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

KILL_SWITCH = {"losses": 0, "active": True}
BATCH_INDEX = [0]

DHAN_SECURITY_IDS = {
    "RELIANCE": "2885",
    "TCS": "11536",
    "HDFCBANK": "1333",
    "INFY": "1594",
    "ICICIBANK": "4963"
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

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=15m&period1={start}&period2={end}"

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

        logger.info(f"Yahoo data: {symbol} — {len(df)} candles")

        return df

    except Exception as e:
        logger.error(f"Yahoo error {symbol}: {e}")
        return get_dummy_data(symbol)


def save_signal(signal):
    conn = get_connection()

    if not conn:
        return

    try:
        cursor = conn.cursor()

        # Save old signal history
        cursor.execute("""
            INSERT INTO signals
            (symbol, action, entry_price, stop_loss, target, confidence, reason)
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

        # Save active signal
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

        logger.info(f"Signal saved: {signal['symbol']}")

    except Exception as e:
        logger.error(f"Save signal error: {e}")


def run_scanner():

    if not KILL_SWITCH["active"]:
        logger.warning("Kill switch active.")
        return

    batch_size = 10

    start = BATCH_INDEX[0]
    end = start + batch_size

    batch = WATCHLIST[start:end]

    if not batch:
        BATCH_INDEX[0] = 0
        logger.info("Watchlist completed. Resetting.")
        return

    logger.info(f"Scanning batch {start}-{end}")

    for symbol in batch:

        try:

            # Prevent duplicate signals
            if is_signal_active(symbol):
                logger.info(f"Skipping duplicate active signal: {symbol}")
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


def send_test_alert():

    send_alert(
        symbol="TEST",
        action="BUY",
        entry=100,
        sl=95,
        target1=102,
        target2=104,
        confidence=85,
        reason="PETS System Test"
    )
