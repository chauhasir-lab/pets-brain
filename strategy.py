import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta

from database import get_connection

logger = logging.getLogger(__name__)

DAILY_TRADES = {"count": 0, "date": None}

RISK_PER_TRADE = 0.02

SECTOR_MAP = {
    "TCS": "IT",
    "INFY": "IT",
    "WIPRO": "IT",

    "HDFCBANK": "BANK",
    "ICICIBANK": "BANK",
    "SBIN": "BANK",

    "SUNPHARMA": "PHARMA",
    "CIPLA": "PHARMA",
    "BIOCON": "PHARMA",

    "TATASTEEL": "METAL",
    "JSWSTEEL": "METAL",

    "RELIANCE": "ENERGY",
    "ONGC": "ENERGY",
    
    "LT": "INFRA"
}


def is_market_hours():
    try:
        import pytz
        tz = pytz.timezone('Asia/Kolkata')
        now = datetime.now(tz)
        if now.weekday() > 4:
            return False
        ist_time = now.hour * 100 + now.minute
        return 915 <= ist_time <= 1530
    except Exception:
        now = datetime.utcnow()
        ist = now + timedelta(hours=5, minutes=30)
        if ist.weekday() > 4:
            return False
        ist_time = ist.hour * 100 + ist.minute
        return 915 <= ist_time <= 1530


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

        end = int(datetime.utcnow().timestamp())
        start = int(
            (datetime.utcnow() - timedelta(days=5)).timestamp()
        )

        url = (
            f"https://query1.finance.yahoo.com/v8/"
            f"finance/chart/%5ENSEI?"
            f"interval=1d&period1={start}&period2={end}"
        )

        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        response = urllib.request.urlopen(req, timeout=10)
        data = json.loads(response.read())
        closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
        closes = [c for c in closes if c is not None]

        if len(closes) >= 2:
            change_pct = (
                (closes[-1] - closes[-2]) / closes[-2]
            ) * 100
            logger.info(f"Nifty change: {round(change_pct, 2)}%")
            if change_pct < -1.5:
                return "BEARISH"
            return "BULLISH"
    except Exception as e:
        logger.error(f"Nifty trend error: {e}")
    return "BULLISH"


def calculate_vwap(df):
    df['tp'] = (df['high'] + df['low'] + df['close']) / 3
    df['tpv'] = df['tp'] * df['volume']
    df['vwap'] = (df['tpv'].cumsum() / df['volume'].cumsum())
    return df


def calculate_ema(df, period):
    df[f'ema_{period}'] = (df['close'].ewm(span=period, adjust=False).mean())
    return df


def calculate_atr(df, period=20):
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr'] = (df['tr'].rolling(window=period).mean())
    return df


def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0).rolling(window=period).mean())
    loss = ((-delta.where(delta < 0, 0)).rolling(window=period).mean())
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))
    return df


def check_volume_spike(df):
    avg_volume = (df['volume'].rolling(window=10).mean())
    latest_volume = df['volume'].iloc[-1]
    return latest_volume > (avg_volume.iloc[-1] * 1.5)


def calculate_position_size(
    entry,
    sl,
    capital=10000
):
    try:
        # Max 25% of capital per trade
        max_capital_allocation = capital * 0.25

        # Amount to risk (2% of total capital)
        risk_amount = capital * RISK_PER_TRADE

        # Absolute difference between entry and sl
        risk_per_share = abs(entry - sl)

        # Institutional safeguard: Minimum 0.5% risk distance
        min_risk_distance = entry * 0.005

        if risk_per_share < min_risk_distance:
            risk_per_share = min_risk_distance

        # Quantity based on risk
        risk_qty = int(
            risk_amount / risk_per_share
        )

        # Quantity based on capital allocation limit
        capital_qty = int(
            max_capital_allocation / entry
        )

        # Final qty is the lower of the two
        qty = min(
            risk_qty,
            capital_qty
        )

        # Ensure at least 1 share
        qty = max(qty, 1)

        return qty

    except Exception as e:
        logger.error(
            f"Position sizing error: {e}"
        )
        return 1


def detect_market_regime(df):
    atr = df['atr'].iloc[-1]
    avg_atr = (df['atr'].rolling(window=20).mean().iloc[-1])
    ema20 = df['ema_20'].iloc[-1]
    ema50 = df['ema_50'].iloc[-1]

    if atr > avg_atr * 1.5:
        return "HIGH_VOLATILITY", 2.0
    elif ema20 > ema50 and atr > avg_atr:
        return "TRENDING", 1.5
    elif atr < avg_atr * 0.8:
        return "SIDEWAYS", 1.2
    return "NORMAL", 1.3


def get_stock_personality(symbol, regime):
    try:
        conn = get_connection()
        if not conn:
            return 0
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) FILTER (WHERE result IN ('TARGET1_HIT', 'TARGET2_HIT')) as wins,
                COUNT(*) FILTER (WHERE result = 'SL_HIT') as losses
            FROM trade_analytics
            WHERE symbol = %s AND (market_regime = %s OR market_regime IS NULL)
        """, (symbol, regime))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row: return 0
        wins, losses = row[0] or 0, row[1] or 0
        total = wins + losses
        if total < 3: return 0
        
        win_rate = wins / total
        if win_rate >= 0.75: return 20
        elif win_rate >= 0.65: return 12
        elif win_rate < 0.35: return -20
        elif win_rate < 0.45: return -12
        return 0
    except Exception as e:
        logger.error(f"Stock personality error: {e}")
        return 0


def get_sector_strength(symbol):
    try:
        sector = SECTOR_MAP.get(symbol)
        if not sector: return 0
        conn = get_connection()
        if not conn: return 0
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) FILTER (WHERE result IN ('TARGET1_HIT', 'TARGET2_HIT')) as wins,
                COUNT(*) FILTER (WHERE result = 'SL_HIT') as losses
            FROM trade_analytics
            WHERE sector = %s
        """, (sector,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row: return 0
        wins, losses = row[0] or 0, row[1] or 0
        total = wins + losses
        if total < 5: return 0
        
        win_rate = wins / total
        if win_rate >= 0.7: return 15
        elif win_rate >= 0.6: return 8
        elif win_rate < 0.4: return -10
        return 0
    except Exception as e:
        logger.error(f"Sector strength error: {e}")
        return 0


def analyze_setup(df, symbol):
    try:
        if not is_market_hours():
            logger.info(f"Outside market hours — skipping {symbol}")
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
        df = df.dropna(subset=['atr', 'ema_20', 'ema_50', 'rsi', 'vwap'])

        if len(df) < 20: return None

        latest = df.iloc[-2]
        prev = df.iloc[-3]
        recent_high = df['high'].rolling(window=10).max().iloc[-3]
        structure_breakout = (latest['close'] > recent_high)

        candle_body = abs(latest['close'] - latest['open'])
        candle_range = (latest['high'] - latest['low'])
        upper_wick = (latest['high'] - max(latest['close'], latest['open']))

        strong_bullish_candle = (
            candle_body > (0.5 * candle_range)
            and upper_wick < (0.3 * candle_range)
        )

        regime, atr_multiplier = detect_market_regime(df)
        avg_volume = (df['volume'].rolling(window=10).mean().iloc[-1])

        score = 0
        reasons = ["Nifty OK"]
        score += 20

        if (prev['close'] < prev['vwap'] and latest['close'] > latest['vwap']
            and latest['volume'] > avg_volume and strong_bullish_candle 
            and structure_breakout):
            score += 20
            reasons.append("Strong VWAP Structure Breakout")

        if latest['close'] > latest['ema_20'] > latest['ema_50']:
            score += 15
            reasons.append("EMA Bullish")

        if check_volume_spike(df):
            score += 20
            reasons.append("Volume Spike")

        if 55 < latest['rsi'] < 78:
            score += 15
            reasons.append("RSI Momentum")

        personality_score = get_stock_personality(symbol, regime)
        score += personality_score
        if personality_score != 0:
            reasons.append(f"History Feedback {personality_score}")

        sector_score = get_sector_strength(symbol)
        score += sector_score
        if sector_score != 0:
            reasons.append(f"Sector Feedback {sector_score}")

        atr = latest['atr']
        entry = latest['close']
        sl = round(entry - (atr_multiplier * atr), 2)
        target1 = round(entry + (2.0 * atr_multiplier * atr), 2)
        target2 = round(entry + (3.5 * atr_multiplier * atr), 2)
        trailing_sl = sl

        rr = round((target1 - entry) / (entry - sl), 2) if (entry - sl) > 0 else 0
        quantity = calculate_position_size(entry, sl)

        if rr >= 2:
            score += 15
            reasons.append(f"RR {rr}")
        elif rr >= 1.5:
            score += 5
            reasons.append(f"RR {rr}")
        else:
            score -= 10

        # HARD FILTERS
        if latest['volume'] < avg_volume or latest['close'] < latest['vwap'] or \
           latest['ema_20'] < latest['ema_50'] or rr < 1.8 or latest['rsi'] > 78 or score < 65:
            return None

        logger.info(f"{symbol} | Score={score} | Regime={regime} | RR={rr}")

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
