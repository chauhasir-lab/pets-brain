import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

# SECTOR MAP for Diversity Check
SECTOR_MAP = {
    "RELIANCE": "ENERGY", "TCS": "IT", "HDFCBANK": "BANKING", "INFY": "IT",
    "ICICIBANK": "BANKING", "HINDUNILVR": "FMCG", "ITC": "FMCG", "SBIN": "BANKING",
    "BHARTIARTL": "TELECOM", "KOTAKBANK": "BANKING", "LT": "CONSTRUCTION",
    "AXISBANK": "BANKING", "ASIANPAINT": "CONSUMER_DURABLES", "MARUTI": "AUTO",
    "TITAN": "CONSUMER_DURABLES", "SUNPHARMA": "PHARMA", "ULTRACEMCO": "CEMENT",
    "WIPRO": "IT", "NESTLEIND": "FMCG", "TECHM": "IT"
}

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1  + rs)).iloc[-1]

def detect_market_regime(df):
    """
    Detects if the market is TRENDING, SIDEWAYS, or VOLATILE
    """
    # ATR for Volatility
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(14).mean().iloc[-1]
    
    # ADX-like logic for trend strength
    ema_20 = df['close'].ewm(span=20, adjust=False).mean()
    ema_50 = df['close'].ewm(span=50, adjust=False).mean()
    
    current_atr_pct = (atr / df['close'].iloc[-1]) * 100
    
    # Logic
    if current_atr_pct > 2.5:
        return "HIGH_VOLATILITY", 2.0
    elif abs(ema_20.iloc[-1] - ema_50.iloc[-1]) / ema_50.iloc[-1] < 0.005:
        return "SIDEWAYS", 1.2
    elif ema_20.iloc[-1] > ema_50.iloc[-1]:
        return "TRENDING", 1.5
    else:
        return "NORMAL", 1.5

def get_nifty_trend():
    # Placeholder for Nifty Trend Logic - in real use, fetch Nifty50 data
    return "BULLISH"

def is_market_hours():
    now = datetime.now().time()
    return time(9, 15) <= now <= time(15, 30)

def analyze_setup(df, symbol):
    if df is None or len(df) < 50:
        return None

    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    score = 0
    reasons = []

    # Detect Market Regime
    regime, atr_multiplier = detect_market_regime(df)

    # =========================================
    # REGIME ADAPTIVE SCORING
    # =========================================
    regime_score_bonus = {
        "TRENDING": 15,
        "HIGH_VOLATILITY": -10,
        "SIDEWAYS": -15,
        "NORMAL": 5
    }
    
    score += regime_score_bonus.get(regime, 0)
    reasons.append(f"Regime {regime}")

    # --- TECHNICAL SCORING ---
    # EMA Cross/Alignment
    if latest['ema_20'] > latest['ema_50']:
        score += 20
        reasons.append("EMA Alignment")
    
    # RSI Logic
    rsi_val = calculate_rsi(df['close'])
    if 50 < rsi_val < 70:
        score += 15
        reasons.append(f"RSI Bullish ({round(rsi_val, 1)})")
    
    # Volume Pump
    avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
    if latest['volume'] > avg_volume * 1.5:
        score += 20
        reasons.append("Volume Surge")

    # --- RISK CALCULATIONS ---
    entry_price = float(latest['close'])
    stop_loss = entry_price - (atr_multiplier * (df['high'] - df['low']).rolling(14).mean().iloc[-1])
    target1 = entry_price + (entry_price - stop_loss) * 1.5
    target2 = entry_price + (entry_price - stop_loss) * 3.0
    
    rr = (target1 - entry_price) / (entry_price - stop_loss) if (entry_price - stop_loss) != 0 else 0

    # =========================================
    # IMPROVED ENTRY FILTERS (REGIME BASED)
    # =========================================
    minimum_score = {
        "TRENDING": 60,
        "NORMAL": 65,
        "HIGH_VOLATILITY": 75,
        "SIDEWAYS": 80
    }.get(regime, 65)

    if (
        latest['volume'] < avg_volume
        or latest['close'] < latest['vwap']
        or latest['ema_20'] < latest['ema_50']
        or rr < 1.8
        or rsi_val > 78
        or score < minimum_score
    ):
        return None

    # Quantity calculation based on ₹200 risk per trade
    risk_per_share = entry_price - stop_loss
    quantity = int(200 / risk_per_share) if risk_per_share > 0 else 1

    return {
        "symbol": symbol,
        "entry": round(entry_price, 2),
        "sl": round(stop_loss, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
        "rr": round(rr, 2),
        "score": score,
        "reasons": " | ".join(reasons),
        "regime": regime,
        "quantity": quantity
    }
