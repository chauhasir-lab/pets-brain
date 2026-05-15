import yfinance as yf
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Yahoo Finance ticker mapping
TICKERS = {
    "RELIANCE": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "INFY": "INFY.NS",
    "ICICIBANK": "ICICIBANK.NS",
    "HINDUNILVR": "HINDUNILVR.NS",
    "ITC": "ITC.NS",
    "SBIN": "SBIN.NS",
    "BHARTIARTL": "BHARTIARTL.NS",
    "KOTAKBANK": "KOTAKBANK.NS",
    "LT": "LT.NS",
    "AXISBANK": "AXISBANK.NS",
    "ASIANPAINT": "ASIANPAINT.NS",
    "MARUTI": "MARUTI.NS",
    "TITAN": "TITAN.NS",
    "SUNPHARMA": "SUNPHARMA.NS",
    "ULTRACEMCO": "ULTRACEMCO.NS",
    "WIPRO": "WIPRO.NS",
    "NESTLEIND": "NESTLEIND.NS",
    "TECHM": "TECHM.NS",
    "HCLTECH": "HCLTECH.NS",
    "BAJFINANCE": "BAJFINANCE.NS",
    "NTPC": "NTPC.NS",
    "POWERGRID": "POWERGRID.NS",
    "ONGC": "ONGC.NS",
    "COALINDIA": "COALINDIA.NS",
    "TATASTEEL": "TATASTEEL.NS",
    "ADANIENT": "ADANIENT.NS",
    "ADANIPORTS": "ADANIPORTS.NS"
}


def get_dhan_data(symbol):
    try:

        ticker = TICKERS.get(symbol)

        if not ticker:
            logger.warning(f"No Yahoo ticker found for {symbol}")
            return None

        df = yf.download(
            ticker,
            period="5d",
            interval="15m",
            progress=False,
            auto_adjust=False
        )

        if df.empty:
            logger.warning(f"No Yahoo data for {symbol}")
            return None

        # Standardize column names
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        })

        # Keep only needed columns
        df = df[["open", "high", "low", "close", "volume"]]

        # Remove NaN
        df.dropna(inplace=True)

        # Convert all to float
        df = df.astype(float)

        # Minimum candles validation
        if len(df) < 20:
            logger.warning(f"Not enough candles for {symbol}")
            return None

        logger.info(f"Yahoo data fetched: {symbol} — {len(df)} candles")

        return df

    except Exception as e:
        logger.error(f"Yahoo fetch error for {symbol}: {e}")
        return None
