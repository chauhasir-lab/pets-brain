import pandas as pd
import logging
from datetime import datetime, timedelta
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

        today = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

        data = dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment="NSE_EQ",
            instrument_type="EQUITY",
            interval=15,
            from_date=from_date,
            to_date=today
        )

        # Log raw response structure for debugging
        logger.info(f"Dhan raw response keys for {symbol}: {list(data.keys()) if isinstance(data, dict) else type(data)}")

        # Handle different response formats
        if isinstance(data, dict):
            # Try 'data' key first
            candles = data.get("data")

            if candles is None:
                logger.warning(f"No 'data' key for {symbol}. Keys: {list(data.keys())}")
                return None

            # If candles is a list of dicts
            if isinstance(candles, list) and len(candles) > 0:
                df = pd.DataFrame(candles)
                # Rename columns if needed
                col_map = {}
                for col in df.columns:
                    cl = col.lower()
                    if 'open' in cl:
                        col_map[col] = 'open'
                    elif 'high' in cl:
                        col_map[col] = 'high'
                    elif 'low' in cl:
                        col_map[col] = 'low'
                    elif 'close' in cl:
                        col_map[col] = 'close'
                    elif 'volume' in cl:
                        col_map[col] = 'volume'
                df.rename(columns=col_map, inplace=True)

            # If candles is a dict with OHLCV lists
            elif isinstance(candles, dict):
                # Find correct keys
                keys = list(candles.keys())
                open_key = next((k for k in keys if 'open' in k.lower()), None)
                high_key = next((k for k in keys if 'high' in k.lower()), None)
                low_key = next((k for k in keys if 'low' in k.lower()), None)
                close_key = next((k for k in keys if 'close' in k.lower()), None)
                vol_key = next((k for k in keys if 'volume' in k.lower()), None)

                if not all([open_key, high_key, low_key, close_key, vol_key]):
                    logger.warning(f"Missing OHLCV keys for {symbol}: {keys}")
                    return None

                df = pd.DataFrame({
                    "open": candles[open_key],
                    "high": candles[high_key],
                    "low": candles[low_key],
                    "close": candles[close_key],
                    "volume": candles[vol_key]
                })
            else:
                logger.warning(f"Unexpected candles format for {symbol}: {type(candles)}")
                return None

        elif isinstance(data, pd.DataFrame):
            df = data
        else:
            logger.warning(f"Unexpected response type for {symbol}: {type(data)}")
            return None

        # Ensure required columns exist
        required = ['open', 'high', 'low', 'close', 'volume']
        for col in required:
            if col not in df.columns:
                logger.warning(f"Missing column '{col}' for {symbol}. Columns: {list(df.columns)}")
                return None

        df = df[required].copy()
        df = df.apply(pd.to_numeric, errors='coerce')
        df.dropna(inplace=True)

        if len(df) < 20:
            logger.warning(f"Not enough candles for {symbol}: {len(df)}")
            return None

        logger.info(f"Dhan data fetched: {symbol} — {len(df)} candles")
        return df

    except Exception as e:
        logger.error(f"Dhan fetch error for {symbol}: {e}")
        return None
