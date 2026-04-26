"""
One-command interface for ETF backtest with multiple strategies.

Usage:
    python src/run.py --symbol 159632 --buy 0.01 --sell 0.03 --start 20230101
    python src/run.py --symbol 159509 --strategy ladder_v2 --start 20230101 --no-fetch
"""

from __future__ import annotations

import argparse
import pandas as pd

from backtest_ladder_v2 import print_backtest_result as print_ladder_result, run_ladder_backtest, save_reports as save_ladder_reports
from backtest_premium_v1 import backtest_premium_v1, print_backtest_result as print_premium_result, save_reports as save_premium_reports
from build_dataset import build_dataset
from fetch_data import fetch_etf_nav, fetch_etf_price


def default_end_date() -> str:
    return pd.Timestamp.today().strftime("%Y%m%d")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbol", required=True, help="ETF code, for example 159632 / 159509 / 513100"
    )
    parser.add_argument(
        "--strategy",
        default="premium_v1",
        choices=["premium_v1", "ladder_v2"],
        help="Strategy to run: premium_v1 (default) or ladder_v2",
    )
    parser.add_argument(
        "--buy", type=float, help="Buy premium (required for premium_v1)",
    )
    parser.add_argument(
        "--sell", type=float, help="Sell premium (required for premium_v1)",
    )
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default=default_end_date())
    parser.add_argument("--execution-lag", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.0003)
    parser.add_argument("--refresh", action="store_true", help="Force refetch data")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetch_data.py and use local CSV files",
    )

    parser.add_argument("--drawdown-window", type=int, default=60, help="Ladder: drawdown window")
    parser.add_argument("--rise-window", type=int, default=60, help="Ladder: rise window")
    parser.add_argument("--min-trade-delta", type=float, default=0.10, help="Ladder: min trade delta")
    parser.add_argument("--max-daily-buy", type=float, default=0.20, help="Ladder: max daily buy")
    parser.add_argument("--max-daily-sell", type=float, default=0.40, help="Ladder: max daily sell")

    args = parser.parse_args()

    if args.strategy == "premium_v1":
        if args.buy is None or args.sell is None:
            parser.error("--buy and --sell are required for premium_v1 strategy")
    if args.strategy == "ladder_v2":
        if args.buy is None:
            args.buy = 0.0
        if args.sell is None:
            args.sell = 1.0

    if not args.no_fetch:
        fetch_etf_price(args.symbol, args.start, args.end, refresh=args.refresh)
        fetch_etf_nav(args.symbol, args.start, args.end, refresh=args.refresh)

    build_dataset(args.symbol)

    if args.strategy == "premium_v1":
        df, trades_df, stats = backtest_premium_v1(
            symbol=args.symbol,
            buy_premium=args.buy,
            sell_premium=args.sell,
            start=args.start,
            end=args.end,
            execution_lag=args.execution_lag,
            fee_rate=args.fee_rate,
        )
        save_premium_reports(args.symbol, df, trades_df)
        print_premium_result(stats, trades_df)
    else:
        result = run_ladder_backtest(
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            fee_rate=args.fee_rate,
            execution_lag_days=args.execution_lag,
            drawdown_window=args.drawdown_window,
            rise_window=args.rise_window,
            min_trade_delta=args.min_trade_delta,
            max_daily_buy=args.max_daily_buy,
            max_daily_sell=args.max_daily_sell,
        )
        save_ladder_reports(args.symbol, result["daily"], result["trades"])
        print_ladder_result(result["stats"], result["trades"])

    print("\n[done] ETF backtest completed.")


if __name__ == "__main__":
    main()
