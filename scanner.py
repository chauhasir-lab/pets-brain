import time
import logging
from datetime import datetime
from strategy import analyze_setup
from database import execute_query, get_regime_performance

logger = logging.getLogger(__name__)

# =========================================
# INITIALIZATION & STEP 1: WATCHLIST SCORES
# =========================================
WATCHLIST_SCORES = {}
REGIME_CONFIDENCE = {}

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

LAST_CLEANUP_TIME = {
    "time": datetime.utcnow()
}

MARKET_BREADTH = {"bullish": 0, "bearish": 0}
LAST_SCAN_TIME = {"time": None}

# Placeholder state maps for cleanup engine logic
LAST_ALERT_STATE = {}
TRADE_STATE = {}
BREAKEVEN_DONE = {}
LAST_TRAILING_SL = {}
STATE_WEAKNESS_COUNT = {}
LIVE_CONFIDENCE = {}
TRADE_PRIORITY = {}

# Default Watchlist
WATCHLIST = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "ITC", "SBIN", "BHARTIARTL"]

def get_active_bought_trades():
    """Placeholder to fetch active trades from DB/System"""
    return []

def cleanup_memory():
    now = datetime.utcnow()

    # Cleanup old watchlist scores (Decay mechanism)
    for symbol in list(WATCHLIST_SCORES.keys()):
        WATCHLIST_SCORES[symbol] *= 0.95
        if abs(WATCHLIST_SCORES[symbol]) < 1:
            WATCHLIST_SCORES.pop(symbol, None)

    # Cleanup stale confidence and states for inactive symbols
    active_symbols = set()
    trades = get_active_bought_trades()
    for trade in trades:
        active_symbols.add(trade[0])

    all_maps = [
        LAST_ALERT_STATE,
        TRADE_STATE,
        BREAKEVEN_DONE,
        LAST_TRAILING_SL,
        STATE_WEAKNESS_COUNT,
        LIVE_CONFIDENCE,
        TRADE_PRIORITY
    ]

    for memory_map in all_maps:
        for symbol in list(memory_map.keys()):
            if symbol not in active_symbols:
                memory_map.pop(symbol, None)

    LAST_CLEANUP_TIME["time"] = now
    logger.info("Memory cleanup completed")

def run_scanner():
    global WATCHLIST
    
    try:
        # =========================================
        # PERIODIC MEMORY CLEANUP
        # =========================================
        minutes_since_cleanup = (
            datetime.utcnow() - LAST_CLEANUP_TIME["time"]
        ).total_seconds() / 60

        if minutes_since_cleanup > 60:
            cleanup_memory()

        # =========================================
        # REGIME LEARNING ENGINE
        # =========================================
        rows = get_regime_performance()
        if rows:
            for row in rows:
                regime = row[0]
                total = row[1]
                wins = row[2] or 0

                if total >= 5:
                    REGIME_CONFIDENCE[regime] = (wins / total)

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
        logger.error(f"Error scanning: {e}")

def start_scanner_loop():
    logger.info("PETS Scanner Loop Started.")
    while True:
        run_scanner()
        time.sleep(60)
