import pandas as pd
import numpy as np
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DAILY_TRADES = {"count": 0, "date": None}

def is_market_hours():
    now = datetime.utcnow()
    ist_hour = now.hour + 5
    ist_minute = now.minute + 30
    if ist_minute >= 60:
        ist_minute -= 60
        ist_hour += 1
    if ist_hour >= 24:
        ist_hour -= 24
    ist_time = ist_hour * 100 + ist_minute
    return (920 <= ist_time <= 1030) or (1345 <= ist_time <= 1445)

def check_daily_limit():
    today = datetime.utcnow().date()
    if DAILY_TRADES["date"] != today:
        DAILY_TRADES["count"] = 0
        DAILY_TRADES["date"] = today
    return DAILY_TRADES["count"] < 3

def increment_trade_count():
    DAILY_TRADES["count"] += 1

def get_nifty_trend():
    try:
        import urllib.request
        import json
        from datetime import timedelta
        end = int(datetime.utcnow().timestamp())
        start = int((datetime.utcnow() - timedelta(days=3)).timestamp())
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=1d&period1={start}&period2={end}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=10)
        data = json.loads(response.read())
        closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
        closes = [c for c in closes if c is not None]
        if len(closes) >= 2:
            change_pct = ((closes[-1] - closes[-2]) / closes[-2]) * 100
            logger.info(f"Nifty change: {round(change_pct, 2)}%")
            if change_pct < -1.5:
                return "BEARISH"
            else:
                return "BULLISH"
    except Exception as e:
        logger.error(f"Nifty trend error: {e}")
    return "BULLISH"

def calculate_vwap(df):
    df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
    return df

def calculate_ema(df, period):
    df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
    return df

def calculate_atr(df, period=20):
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df

def detect_market_regime(df):
    atr = df['atr'].iloc[-1]
    avg_atr = df['atr'].rolling(window=20).mean().iloc[-1]
    ema20 = df['ema_20'].iloc[-1]
    ema50 = df['ema_50'].iloc[-1]

    if ema20 > ema50 and atr > avg_atr:
        return "TRENDING", 1.8
    elif atr < avg_atr * 0.8:
        return "SIDEWAYS", 1.2
    elif atr > avg_atr * 1.5:
        return "HIGH_VOLATILITY", 2.0
    else:
        return "NORMAL", 1.5

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

def calculate_position_size(entry, sl, capital=10000):
    risk_amount = capital * 0.01
    risk_per_share = entry - sl
    if risk_per_share <= 0:
        return 0
    qty = int(risk_amount / risk_per_share)
    return max(qty, 1)

def analyze_setup(df, symbol):
    try:
        if not is_market_hours():
            return None

        if not check_daily_limit():
            logger.info("Daily trade limit reached.")
            return None

        nifty_trend = get_nifty_trend()
        if nifty_trend == "BEARISH":
            logger.info(f"Nifty bearish — skipping {symbol}")
            return None

        df = calculate_vwap(df)
        df = calculate_ema(df, 20)
        df = calculate_ema(df, 50)
        df = calculate_atr(df, period=20)
        df = calculate_rsi(df)

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        regime, atr_multiplier = detect_market_regime(df)

        score = 0
        reasons = []

        score += 20
        reasons.append("Nifty OK")

        if prev['close'] < prev['vwap'] and latest['close'] > latest['vwap']:
            score += 15
            reasons.append("VWAP Reclaim")

        if latest['close'] > latest['ema_20'] > latest['ema_50']:
            score += 15
            reasons.append("EMA Bullish")

        if check_volume_spike(df):
            score += 20
            reasons.append("Volume Spike")

        if 50 < latest['rsi'] < 70:
            score += 15
            reasons.append("RSI Momentum")

        atr = latest['atr']
        entry = latest['close']
        sl = round(entry - (atr_multiplier * atr), 2)
        target1 = round(entry + (entry * 0.02), 2)
        target2 = round(entry + (entry * 0.04), 2)
        trailing_sl = round(entry - (atr_multiplier * atr), 2)

        rr = round((target1 - entry) / (entry - sl), 2) if (entry - sl) > 0 else 0
        quantity = calculate_position_size(entry, sl)

        if rr >= 2:
            score += 15
            reasons.append(f"RR {rr}")
        elif rr >= 1.5:
            score += 5
            reasons.append(f"RR {rr}")
        else:
            score -= 15

        logger.info(f"Symbol: {symbol} | Score: {score} | Regime: {regime} | ATR mult: {atr_multiplier} | T1: {target1} | Qty: {quantity}")

        return {
            "symbol": symbol,
            "score": score,
            "entry": entry,
            "sl": sl,
            "trailing_sl": trailing_sl,
            "target1": target1,
            "target2": target2,
            "rr": rr,
            "quantity": quantity,
            "nifty_trend": nifty_trend,
            "regime": regime,
            "reasons": ", ".join(reasons)
        }

    except Exception as e:
        logger.error(f"Strategy error for {symbol}: {e}")
        return None