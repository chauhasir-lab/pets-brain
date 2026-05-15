import pandas as pd
import logging

from dhan_data import get_dhan_data
from strategy import analyze_setup

logger = logging.getLogger(__name__)


def simulate_trade(df, entry_index):

    try:

        entry_candle = df.iloc[entry_index]

        entry = float(entry_candle['close'])

        atr = float(entry_candle['atr'])

        sl = entry - (1.5 * atr)

        target = entry + (3 * atr)

        future_df = df.iloc[
            entry_index + 1:
            entry_index + 20
        ]

        for _, candle in future_df.iterrows():

            low = float(candle['low'])

            high = float(candle['high'])

            if low <= sl:

                return {
                    "result": "SL_HIT",
                    "entry": entry,
                    "exit": sl,
                    "pnl": sl - entry
                }

            if high >= target:

                return {
                    "result": "TARGET_HIT",
                    "entry": entry,
                    "exit": target,
                    "pnl": target - entry
                }

        final_close = float(
            future_df.iloc[-1]['close']
        )

        return {
            "result": "TIME_EXIT",
            "entry": entry,
            "exit": final_close,
            "pnl": final_close - entry
        }

    except Exception as e:

        logger.error(
            f"Trade simulation error: {e}"
        )

        return None


def run_backtest(symbol):

    try:

        df = get_dhan_data(symbol)

        if df is None or len(df) < 100:

            print(
                f"Not enough data for {symbol}"
            )

            return

        results = []

        for i in range(50, len(df) - 20):

            slice_df = df.iloc[:i].copy()

            setup = analyze_setup(
                slice_df,
                symbol
            )

            if not setup:
                continue

            simulated = simulate_trade(
                slice_df,
                len(slice_df) - 1
            )

            if simulated:

                results.append(simulated)

        if not results:

            print(
                f"No trades found for {symbol}"
            )

            return

        total = len(results)

        wins = len([
            r for r in results
            if r['pnl'] > 0
        ])

        losses = total - wins

        total_pnl = round(
            sum(r['pnl'] for r in results),
            2
        )

        win_rate = round(
            (wins / total) * 100,
            2
        )

        print("\n====================")

        print(f"BACKTEST: {symbol}")

        print("====================")

        print(f"Total Trades: {total}")

        print(f"Wins: {wins}")

        print(f"Losses: {losses}")

        print(f"Win Rate: {win_rate}%")

        print(f"Total PnL: {total_pnl}")

        print("====================\n")

    except Exception as e:

        logger.error(
            f"Backtest error: {e}"
        )


if __name__ == "__main__":

    run_backtest("RELIANCE")
