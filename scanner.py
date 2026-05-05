import pandas as pd
import numpy as np
import logging
from strategy import analyze_setup
from telegram_alert import send_alert
from database import get_connection

logger = logging.getLogger(__name__)

WATCHLIST = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "WIPRO", "NESTLEIND", "TECHM"
]

KILL_SWITCH = {"losses": 0, "active": True}

def save_signal(signal):
    conn = get_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO signals 
            (symbol, action, entry_price, stop_loss, target, confidence, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            signal['symbol'], "BUY", signal['entry'],
            signal['sl'], signal['target'], signal['score'], signal['reasons']
        ))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Save signal error: {e}")

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

def run_scanner():
    if not KILL_SWITCH["active"]:
        logger.warning("Kill switch active. Scanner paused.")
        return
    logger.info("Scanning market...")
    for symbol in WATCHLIST:
        try:
            df = get_dummy_data(symbol)
            result = analyze_setup(df, symbol)
            if result and result['score'] >= 80:
                logger.info(f"Signal found: {symbol} | Score: {result['score']}")
                save_signal(result)
                send_alert(
                    symbol=result['symbol'],
                    action="BUY",
                    entry=result['entry'],
                    sl=result['sl'],
                    target=result['target'],
                    confidence=result['score'],
                    reason=result['reasons']
