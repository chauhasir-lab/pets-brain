import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Global state trackers for diagnostics and bot monitoring
LAST_SCAN_TIME = {"time": None}
SYSTEM_STATS = {
    "total_scans": 0,
    "successful_signals": 0,
    "last_signal_time": None
}
MARKET_BREADTH = {"bullish": 0, "bearish": 0}
PORTFOLIO_HEAT = {"active_risk": 0.0}
WATCHLIST_SCORES = {}

def fetch_market_data():
    """
    Simulates fetching real-time market data or feeds.
    Replace this with your actual NSE/BSE data fetching logic.
    """
    # Example mock data structure
    return [
        {"symbol": "RELIANCE", "close": 2450, "vwap": 2440, "rsi": 62, "volume_shock": True},
        {"symbol": "TCS", "close": 3200, "vwap": 3215, "rsi": 45, "volume_shock": False},
        {"symbol": "INFY", "close": 1500, "vwap": 1490, "rsi": 58, "volume_shock": True},
        {"symbol": "SBIN", "close": 570, "vwap": 565, "rsi": 66, "volume_shock": True},
    ]

def evaluate_vwap_momentum(stock):
    """
    Core strategy evaluation logic based on VWAP and Momentum.
    """
    symbol = stock["symbol"]
    close = stock["close"]
    vwap = stock["vwap"]
    rsi = stock["rsi"]
    volume_shock = stock["volume_shock"]

    # Bullish condition: Price above VWAP, healthy RSI, and volume confirmation
    if close > vwap and 55 <= rsi <= 70 and volume_shock:
        return {
            "symbol": symbol,
            "setup_type": "VWAP_MOMENTUM",
            "entry_price": close,
            "stop_loss": round(vwap * 0.99, 2), # 1% below VWAP
            "target1": round(close * 1.02, 2),  # 2% Target 1
            "target2": round(close * 1.04, 2),  # 4% Target 2
            "score": 85,
            "rr": 2.0
        }
    return None

def run_scanner():
    """
    Main scanner engine execution loop.
    Triggers via cron or manual command from the Telegram Bot.
    """
    from database import is_signal_active, execute_query
    from bot_handler import send_message

    logger.info("Executing PETS Market Scan...")
    LAST_SCAN_TIME["time"] = datetime.utcnow()
    SYSTEM_STATS["total_scans"] += 1

    try:
        stocks = fetch_market_data()
        
        # Reset breadth for current calculation run
        bullish_count = 0
        bearish_count = 0

        for stock in stocks:
            symbol = stock["symbol"]
            
            # Simple breadth check
            if stock["close"] > stock["vwap"]:
                bullish_count += 1
            else:
                bearish_count += 1

            # Check if this stock already has an active monitoring cycle running
            if is_signal_active(symbol):
                continue

            # Run evaluation setup
            signal = evaluate_vwap_momentum(stock)

            if signal:
                # Stock setup qualified -> Increase or set priority score
                WATCHLIST_SCORES[symbol] = min(WATCHLIST_SCORES.get(symbol, 0) + 2, 100)
                
                # If score breaks system generation threshold, push to active signals
                if WATCHLIST_SCORES[symbol] >= 10: 
                    query = """
                        INSERT INTO active_signals (
                            symbol, setup_type, status, entry_price, stop_loss, 
                            target1, target2, score, rr, quantity, signal_time
                        ) VALUES (%s, %s, 'NEW', %s, %s, %s, %s, %s, %s, 10, NOW())
                    """
                    execute_query(
                        query, 
                        (
                            signal["symbol"], signal["setup_type"], signal["entry_price"],
                            signal["stop_loss"], signal["target1"], signal["target2"],
                            signal["score"], signal["rr"]
                        ),
                        commit=True
                    )

                    # Update global metrics
                    SYSTEM_STATS["successful_signals"] += 1
                    SYSTEM_STATS["last_signal_time"] = datetime.utcnow()

                    # Fire off alert to admin panel/Telegram channel
                    alert_msg = (
                        f"🚀 *PETS MOMENTUM SIGNAL*\n\n"
                        f"Stock: `{symbol}`\n"
                        f"Entry: `₹{signal['entry_price']}`\n"
                        f"SL: `₹{signal['stop_loss']}`\n"
                        f"T1: `₹{signal['target1']}` | T2: `₹{signal['target2']}`\n"
                        f"Score: `{signal['score']}` | RR: `{signal['rr']}`\n\n"
                        f"Action: Type `/buy {symbol}` to track position."
                    )
                    send_message(alert_msg)
            else:
                # Setup not met -> Decay logic with floor limit of -10
                WATCHLIST_SCORES[symbol] = max(
                    WATCHLIST_SCORES.get(symbol, 0) - 0.1,
                    -10
                )

        # Update market tracking global metrics
        MARKET_BREADTH["bullish"] = bullish_count
        MARKET_BREADTH["bearish"] = bearish_count

        # Dynamically calculate current total risk load from DB
        risk_query = "SELECT COALESCE(SUM(quantity * (entry_price - stop_loss)), 0) FROM active_signals WHERE status = 'BOUGHT'"
        risk_res = execute_query(risk_query, fetchone=True)
        PORTFOLIO_HEAT["active_risk"] = float(risk_res[0]) if risk_res else 0.0

        logger.info("PETS Engine scan iteration finalized successfully.")

    except Exception as e:
        logger.error(f"Scanner Execution Failure: {e}")
