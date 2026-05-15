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

        # Download data
        df = yf.download(
            ticker,
            period="5d",
            interval="15m",
            progress=False,
            auto_adjust=False,
            multi_level_index=False
        )

        # Empty check
        if df is None or df.empty:
            logger.warning(f"No Yahoo data for {symbol}")
            return None

        # Flatten + lowercase columns safely
        df.columns = [str(col).lower().strip() for col in df.columns]

        # Required columns validation
        required_cols = ["open", "high", "low", "close", "volume"]
        missing = [col for col in required_cols if col not in df.columns]

        if missing:
            logger.error(f"Missing columns for {symbol}: {missing}")
            logger.error(f"Available columns: {df.columns.tolist()}")
            return None

        # Keep only required columns
        df = df[required_cols].copy()

        # Force numeric conversion
        for col in required_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Remove NaN rows
        df.dropna(inplace=True)

        # Float conversion
        df = df.astype(float)

        # Minimum candle validation
        if len(df) < 20:
            logger.warning(f"Not enough candles for {symbol}: {len(df)}")
            return None

        logger.info(f"Yahoo data fetched: {symbol} — {len(df)} candles")
        return df

    except Exception as e:
        logger.error(f"Yahoo fetch error for {symbol}: {e}")
        return None

def get_higher_timeframe_data(symbol):
    try:
        ticker = TICKERS.get(symbol)
        if not ticker:
            return None

        # Download hourly data for higher timeframe analysis
        df = yf.download(
            ticker,
            period="1mo",
            interval="1h",
            progress=False,
            auto_adjust=False,
            multi_level_index=False
        )

        if df is None or df.empty:
            return None

        # Format columns
        df.columns = [str(col).lower().strip() for col in df.columns]

        required_cols = ["open", "high", "low", "close", "volume"]
        df = df[required_cols].copy()

        # Numeric conversion and cleanup
        for col in required_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.dropna(inplace=True)
        
        return df

    except Exception as e:
        logger.error(f"Higher timeframe fetch error for {symbol}: {e}")
        return None
