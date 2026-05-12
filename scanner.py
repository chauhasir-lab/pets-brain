import pandas as pd
import numpy as np
import logging
import os
from datetime import datetime, timedelta
from strategy import analyze_setup
from telegram_alert import send_alert
from database import get_connection

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
    "RELIANCE": "2885", "TCS": "11536", "HDFCBANK": "1333",
    "INFY": "1594", "ICICIBANK": "4963", "HINDUNILVR": "1394",
    "ITC": "1660", "SBIN": "3045", "BHARTIARTL": "10604",
    "KOTAKBANK": "1922", "LT": "11483", "AXISBANK": "5900",
    "ASIANPAINT": "236", "MARUTI": "10999", "TITAN": "3506",
    "SUNPHARMA": "3351", "ULTRACEMCO": "11532", "WIPRO": "3787",
    "NESTLEIND": "17963", "TECHM": "13538", "HCLTECH": "7229",
    "BAJFINANCE": "317", "BAJAJFINSV": "16675", "NTPC": "11630",
    "POWERGRID": "14977", "ONGC": "2475", "COALINDIA": "20374",
    "JSWSTEEL": "11723", "TATASTEEL": "3492", "ADANIENT": "25",
    "ADANIPORTS": "15083", "DIVISLAB": "10940", "DRREDDY": "881",
    "CIPLA": "694", "APOLLOHOSP": "157", "EICHERMOT": "910",
    "HEROMOTOCO": "1348", "BAJAJ-AUTO": "16669", "TATACONSUM": "3432",
    "BRITANNIA": "547", "GRASIM": "1232", "INDUSINDBK": "5258",
    "BPCL": "526", "IOC": "1624", "HINDALCO": "1363",
    "VEDL": "3063", "UPL": "11287", "SBILIFE": "21808",
    "HDFCLIFE": "467", "IRCTC": "543556"
}


def get_dummy_data(symbol):
    np.random.seed(42)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=50, freq='5min')
    close = np.random.uniform(100, 500, 50).cumsum()
    df = pd.DataFrame({
        'open': close * np.random.uniform(0.99, 1.01, 50),
        'high': close * np.random.uniform(1.00, 1.02, 50),
        'low': close * np.random.uniform(0.98, 1.00, 50),
        'close': close,
        'volume': np.random.randint(100000, 500000, 50)
    }, index=dates)
    return df


def get_dhan_data(symbol):
    try:
        from dhanhq import dhanhq
        client_id = os.environ.get("DHAN_CLIENT_ID")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN")
        dhan = dhanhq(client_id, access_token)

        security_id = DHAN_SECURITY_IDS.get(symbol)
        if not security_id:
            return get_yahoo_data(symbol)

        today = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

        response = dhan.historical_daily_data(
            security_id=security_id,
            exchange_segment="NSE_EQ",
            instrument_type="EQUITY",
            from_date=from_date,
            to_date=today
        )

        if response and 'data' in response:
            data = response['data']
            df = pd.DataFrame(data)
            df.rename(columns={
                'open': 'open', 'high': 'high',
                'low': 'low', 'close': 'close',
                'volume': 'volume'
            }, inplace=True)
            df.index = pd.to_datetime(df.index) if df.index.dtype != 'datetime64[ns]' else df.index
            logger.info(f"Dhan data: {symbol} — {len(df)} candles")
            return df
        else:
            return get_yahoo_data(symbol)

    except Exception as e:
        logger.error(f"Dhan error {symbol}: {e}")
        return get_yahoo_data(symbol)


def get_yahoo_data(symbol):
    try:
        import urllib.request
        import json
        yahoo_symbol = f"{symbol}.NS"
        end = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=5)).timestamp())
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=15m&period1={start}&period2={end}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
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
        cursor.execute(
            "INSERT INTO signals (symbol, action, entry_price, stop_loss, target, confidence, reason) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (signal['symbol'], "BUY", signal['entry'], signal['sl'], signal['target1'], signal['score'], signal['reasons'])
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Save signal error: {e}")


def run_scanner():
    if not KILL_SWITCH["active"]:
        logger.warning("Kill switch active. Scanner paused.")
        return

    batch_size = 10
    start = BATCH_INDEX[0]
    end = start + batch_size
    batch = WATCHLIST[start:end]

    if not batch:
        BATCH_INDEX[0] = 0
        logger.info("Full watchlist scanned. Resetting.")
        return

    logger.info(f"Scanning batch {start}-{end}: {batch}")

    for symbol in batch:
        try:
            df = get_dhan_data(symbol)
            result = analyze_setup(df, symbol)
            if result and result['score'] >= 60:
                logger.info(f"Signal found: {symbol} | Score: {result['score']}")
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
