import logging
from datetime import datetime

logger = logging.getLogger(__name__)

LAST_SCAN_TIME = {"time": None}
LAST_CLEANUP_TIME = {"time": datetime.utcnow()}
SYSTEM_STATS = {
    "total_scans": 0,
    "successful_signals": 0,
    "last_signal_time": None
}
MARKET_BREADTH = {"bullish": 0, "bearish": 0}
PORTFOLIO_HEAT = {"active_risk": 0.0}
WATCHLIST_SCORES = {}
TRADE_STATE = {}
LIVE_CONFIDENCE = {}
TRADE_PRIORITY = {}
LOSS_STREAK = {"count": 0}
MARKET_PANIC = {"active": False}

SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "WIPRO", "NESTLEIND", "TECHM",
    "HCLTECH", "BAJFINANCE", "NTPC", "POWERGRID", "ONGC",
    "COALINDIA", "TATASTEEL", "ADANIENT", "ADANIPORTS"
]

def run_scanner():
    from database import is_signal_active, execute_query
    from bot_handler import send_message
    from dhan_data import get_dhan_data
    from strategy import analyze_setup

    logger.info("Executing PETS Market Scan...")
    LAST_SCAN_TIME["time"] = datetime.utcnow()
    SYSTEM_STATS["total_scans"] += 1

    bullish_count = 0
    bearish_count = 0

    try:
        for symbol in SYMBOLS:
            try:
                df = get_dhan_data(symbol)

                if df is None or len(df) < 50:
                    continue

                latest = df.iloc[-1]

                # Breadth
                vwap = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
                if latest['close'] > vwap.iloc[-1]:
                    bullish_count += 1
                else:
                    bearish_count += 1

                if is_signal_active(symbol):
                    continue

                signal = analyze_setup(df, symbol)

                if signal:
                    WATCHLIST_SCORES[symbol] = min(WATCHLIST_SCORES.get(symbol, 0) + 2, 100)

                    if WATCHLIST_SCORES[symbol] >= 2:
                        query = """
                            INSERT INTO active_signals (
                                symbol, setup_type, status, entry_price, stop_loss,
                                target1, target2, score, rr, quantity, signal_time
                            ) VALUES (%s, %s, 'NEW', %s, %s, %s, %s, %s, %s, %s, NOW())
                        """
                        execute_query(
                            query,
                            (
                                symbol, "VWAP_MOMENTUM",
                                signal["entry"], signal["sl"],
                                signal["target1"], signal["target2"],
                                signal["score"], signal["rr"],
                                signal["quantity"]
                            ),
                            commit=True
                        )

                        SYSTEM_STATS["successful_signals"] += 1
                        SYSTEM_STATS["last_signal_time"] = datetime.utcnow()

                        alert_msg = (
                            f"🚀 *PETS SIGNAL*\n\n"
                            f"Stock: `{symbol}`\n"
                            f"Entry: `₹{signal['entry']}`\n"
                            f"SL: `₹{signal['sl']}`\n"
                            f"T1: `₹{signal['target1']}` | T2: `₹{signal['target2']}`\n"
                            f"Score: `{signal['score']}` | RR: `{signal['rr']}`\n"
                            f"Regime: `{signal['regime']}`\n"
                            f"Reasons: `{signal['reasons']}`\n\n"
                            f"/buy {symbol} to track."
                        )
                        send_message(alert_msg)
                else:
                    WATCHLIST_SCORES[symbol] = max(
                        WATCHLIST_SCORES.get(symbol, 0) - 0.1, -10
                    )

            except Exception as e:
                logger.error(f"Symbol error {symbol}: {e}")
                continue

        MARKET_BREADTH["bullish"] = bullish_count
        MARKET_BREADTH["bearish"] = bearish_count

        total = bullish_count + bearish_count
        if total > 0 and bullish_count / total < 0.3:
            MARKET_PANIC["active"] = True
        else:
            MARKET_PANIC["active"] = False

        risk_query = "SELECT COALESCE(SUM(quantity * (entry_price - stop_loss)), 0) FROM active_signals WHERE status = 'BOUGHT'"
        risk_res = execute_query(risk_query, fetchone=True)
        PORTFOLIO_HEAT["active_risk"] = float(risk_res[0]) if risk_res else 0.0

        logger.info("PETS Engine scan iteration finalized successfully.")

    except Exception as e:
        logger.error(f"Scanner Execution Failure: {e}")
