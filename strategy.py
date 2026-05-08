import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def calculate_vwap(df):
    df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
    return df

def calculate_ema(df, period):
    df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
    return df

def calculate_atr(df, period=14):
    df['tr'] = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def check_volume_spike(df):
    avg_volume = df['volume'].rolling(window=10).mean()
    latest_volume = df['volume'].iloc[-1]
    return latest_volume > (avg_volume.iloc[-1] * 1.5)

def calculate_trailing_sl(entry, atr, current_price):
    trail_distance = 1.5 * atr
    trailing_sl = round(current_price - trail_distance, 2)
    return max(trailing_sl, round(entry - trail_distance, 2))

def analyze_setup(df, symbol):
    try:
        df = calculate_vwap(df)
        df = calculate_ema(df, 20)
        df = calculate_ema(df, 50)
        df = calculate_atr(df)
        df = calculate_rsi(df)

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        score = 0
        reasons = []

        if prev['close'] < prev['vwap'] and latest['close'] > latest['vwap']:
            score += 30
            reasons.append("VWAP Reclaim")

        if latest['close'] > latest['ema_20'] > latest['ema_50']:
            score += 20
            reasons.append("EMA Bullish")

        if check_volume_spike(df):
            score += 25
            reasons.append("Volume Spike")

        if 50 < latest['rsi'] < 70:
            score += 15
            reasons.append("RSI Momentum")

        atr = latest['atr']
        entry = latest['close']
        sl = round(entry - (1.5 * atr), 2)
       target = round(entry + (4 * atr), 2)
        rr = round((target - entry) / (entry - sl), 2)
        trailing_sl = calculate_trailing_sl(entry, atr, entry)

        if rr >= 2:
            score += 10
            reasons.append(f"RR {rr}")
        elif rr >= 1.5:
            score += 0
            reasons.append(f"RR {rr}")
        else:
            score -= 10

        logger.info(f"Symbol: {symbol} | Score: {score} | Reasons: {', '.join(reasons)}")

        return {
            "symbol": symbol,
            "score": score,
            "entry": entry,
            "sl": sl,
            "trailing_sl": trailing_sl,
            "target": target,
            "rr": rr,
            "reasons": ", ".join(reasons)
        }

    except Exception as e:
        logger.error(f"Strategy error for {symbol}: {e}")
        return None
