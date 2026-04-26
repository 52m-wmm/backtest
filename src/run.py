"""
One-command interface for ETF premium backtest.

Usage:
    python src/run.py --symbol 159632 --buy 0.01 --sell 0.03 --start 20230101
    python src/run.py --symbol 159509 --buy 0.15 --sell 0.20 --start 20230101
"""

from __future__ import annotations

import argparse
import pandas as pd

from backtest_premium_v1 import backtest_premium_v1, print_backtest_result, save_reports
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
        "--buy", type=float, required=True, help="Buy premium, 0.01 means 1 percent"
    )
    parser.add_argument(
        "--sell", type=float, required=True, help="Sell premium, 0.03 means 3 percent"
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

    args = parser.parse_args()

    if not args.no_fetch:
        fetch_etf_price(args.symbol, args.start, args.end, refresh=args.refresh)
        fetch_etf_nav(args.symbol, args.start, args.end, refresh=args.refresh)

    build_dataset(args.symbol)

    df, trades_df, stats = backtest_premium_v1(
        symbol=args.symbol,
        buy_premium=args.buy,
        sell_premium=args.sell,
        execution_lag=args.execution_lag,
        fee_rate=args.fee_rate,
    )
    save_reports(args.symbol, df, trades_df)
    print_backtest_result(stats, trades_df)

    print("\n[done] ETF premium backtest completed.")


if __name__ == "__main__":
    main()
