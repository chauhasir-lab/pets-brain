import pandas as pd
import logging
from dhanhq import dhanhq
import os

logger = logging.getLogger(__name__)

DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN")

dhan = dhanhq(
    DHAN_CLIENT_ID,
    DHAN_ACCESS_TOKEN
)

SECURITY_IDS = {
    "RELIANCE": "2885",
    "TCS": "11536",
    "HDFCBANK": "1333",
    "INFY": "1594",
    "ICICIBANK": "4963",
    "LT": "11483",
    "SBIN": "3045",
    "ITC": "1660",
    "AXISBANK": "5900",
    "BHARTIARTL": "10604"
}


def get_dhan_data(symbol):

    try:

        security_id = SECURITY_IDS.get(symbol)

        if not security_id:

            logger.warning(
                f"No security ID for {symbol}"
            )

            return None

        data = dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment="NSE_EQ",
            instrument_type="EQUITY",
            interval=15
        )

        candles = data.get("data")

        if not candles:

            return None

        df = pd.DataFrame({
            "open": candles["open"],
            "high": candles["high"],
            "low": candles["low"],
            "close": candles["close"],
            "volume": candles["volume"]
        })

        if len(df) < 20:
            return None

        return df

    except Exception as e:

        logger.error(
            f"Dhan fetch error for {symbol}: {e}"
        )

        return None