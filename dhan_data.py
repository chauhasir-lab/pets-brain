import pandas as pd
import logging
from dhanhq import dhanhq
import os

logger = logging.getLogger(__name__)

DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN")

dhan = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)

SECURITY_IDS = {
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
    "HDFCLIFE": "467", "IRCTC": "543556", "DABUR": "627",
    "MARICO": "4067", "COLPAL": "1674", "GODREJCP": "10099",
    "TRENT": "1964", "DMART": "11867", "NYKAA": "543522",
    "PAYTM": "543396", "NAUKRI": "535794", "ABCAPITAL": "540691",
    "MUTHOOTFIN": "533398", "CHOLAFIN": "519183", "SBICARD": "543066",
    "TORNTPHARM": "500420", "AUROPHARMA": "524804", "ALKEM": "539523",
    "LUPIN": "500257", "BIOCON": "532523", "VOLTAS": "500575",
    "HAVELLS": "517354", "CROMPTON": "539876", "POLYCAB": "542652",
    "ADANIGREEN": "541450", "TATAPOWER": "500400", "GAIL": "532155",
    "IGL": "532514", "PETRONET": "532522", "CONCOR": "531344",
    "MOTHERSON": "517334", "BOSCHLTD": "500530", "EXIDEIND": "500086"
}


def get_dhan_data(symbol):
    try:
        security_id = SECURITY_IDS.get(symbol)
        if not security_id:
            logger.warning(f"No security ID for {symbol}")
            return None

        data = dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment="NSE_EQ",
            instrument_type="EQUITY",
            interval=15
        )

        candles = data.get("data")
        if not candles:
            logger.warning(f"No candle data for {symbol}")
            return None

        df = pd.DataFrame({
            "open": candles["open"],
            "high": candles["high"],
            "low": candles["low"],
            "close": candles["close"],
            "volume": candles["volume"]
        })

        df.dropna(inplace=True)

        if len(df) < 20:
            logger.warning(f"Not enough candles for {symbol}: {len(df)}")
            return None

        logger.info(f"Dhan data fetched: {symbol} — {len(df)} candles")
        return df

    except Exception as e:
        logger.error(f"Dhan fetch error for {symbol}: {e}")
        return None
