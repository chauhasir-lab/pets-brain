import time
import logging
from datetime import datetime
from strategy import analyze_setup
from database import execute_query

logger = logging.getLogger(__name__)

# =========================================
# INITIALIZATION & STEP 1: WATCHLIST SCORES
# =========================================
WATCHLIST_SCORES = {}

PORTFOLIO_HEAT = {
    "active_risk": 0.0,
    "max_risk_capacity": 2000.0 
}

SYSTEM_STATS = {
    "total_scans": 0,
    "successful_signals": 0,
    "last_signal_time": None,
    "last_error": None
}

MARKET_BREADTH = {"bullish": 0, "bearish": 0}
LAST_SCAN_TIME = {"time": None}

# Default Watchlist
WATCHLIST = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "ITC", "SBIN", "BHARTIARTL"]

def run_scanner():
    global WATCHLIST
    SYSTEM_STATS["total_scans"] += 1
    LAST_SCAN_TIME["time"] = datetime.utcnow()
    
    # Reset Breadth
    MARKET_BREADTH["bullish"] = 0
    MARKET_BREADTH["bearish"] = 0

    # =========================================
    # STEP 4: DYNAMIC WATCHLIST SORTING
    # =========================================
    WATCHLIST.sort(
        key=lambda x: WATCHLIST_SCORES.get(x, 0),
        reverse=True
    )

    for symbol in WATCHLIST:
        try:
            # Data fetch logic (Assuming external function or API)
            df = None 
            
            result = analyze_setup(df, symbol)

            if result:
                # =========================================
                # STEP 2: SUCCESS SIGNAL REWARD (+10)
                # =========================================
                WATCHLIST_SCORES[symbol] = WATCHLIST_SCORES.get(symbol, 0) + 10
                
                SYSTEM_STATS["successful_signals"] += 1
                SYSTEM_STATS["last_signal_time"] = datetime.utcnow()
                MARKET_BREADTH["bullish"] += 1
            else:
                # =========================================
                # STEP 3: REJECTION PENALTY (-1)
                # =========================================
                WATCHLIST_SCORES[symbol] = WATCHLIST_SCORES.get(symbol, 0) - 1
                MARKET_BREADTH["bearish"] += 1
                continue

        except Exception as e:
            SYSTEM_STATS["last_error"] = str(e)
            logger.error(f"Error scanning {symbol}: {e}")

def start_scanner_loop():
    logger.info("PETS Scanner Loop Started.")
    while True:
        run_scanner()
        time.sleep(60)
