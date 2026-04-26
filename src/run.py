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
from backtest_ladder_v3 import print_backtest_result as print_ladder_v3_result, run_ladder_v3_backtest, save_reports as save_ladder_v3_reports
from backtest_cross_signal_v1 import print_backtest_result as print_cross_result, run_cross_signal_backtest, save_reports as save_cross_reports
from backtest_ladder_v4 import print_backtest_result as print_ladder_v4_result, run_ladder_v4_backtest, save_reports as save_ladder_v4_reports
from backtest_premium_v1 import backtest_premium_v1, print_backtest_result as print_premium_result, save_reports as save_premium_reports
from build_dataset import build_dataset
from fetch_data import fetch_etf_nav, fetch_etf_price


def default_end_date() -> str:
    return pd.Timestamp.today().strftime("%Y%m%d")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbol", help="ETF code (required for single-ETF strategies)",
    )
    parser.add_argument(
        "--strategy",
        default="premium_v1",
        choices=["premium_v1", "ladder_v2", "ladder_v3", "ladder_v4", "cross_signal_v1"],
        help="Strategy to run: premium_v1 (default), ladder_v2, ladder_v3, ladder_v4, or cross_signal_v1",
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

    parser.add_argument("--drawdown-window", type=int, default=60, help="Ladder V2: drawdown window")
    parser.add_argument("--rise-window", type=int, default=60, help="Ladder V2: rise window")
    parser.add_argument("--min-trade-delta", type=float, default=0.10, help="Ladder: min trade delta")
    parser.add_argument("--max-daily-buy", type=float, default=0.20, help="Ladder V2: max daily buy")
    parser.add_argument("--max-daily-sell", type=float, default=0.40, help="Ladder V2: max daily sell")
    parser.add_argument("--cooldown-days", type=int, default=5, help="Ladder V3: cooldown days")
    parser.add_argument("--rebalance-threshold", type=float, default=0.15, help="Ladder V3: rebalance threshold")
    parser.add_argument("--initial-cash", type=float, default=1.0, help="Ladder V3: initial cash")
    parser.add_argument("--min-hold-days", type=int, default=10, help="Ladder V4: min hold days")
    parser.add_argument("--core-position", type=float, default=0.60, help="Ladder V4: core position")
    parser.add_argument("--signal-symbol", default="159632", help="Cross: signal ETF symbol")
    parser.add_argument("--trade-symbol", default="159509", help="Cross: trade ETF symbol")
    parser.add_argument("--signal-buy", type=float, default=0.01, help="Cross: signal buy premium")
    parser.add_argument("--signal-sell", type=float, default=0.06, help="Cross: signal sell premium")
    parser.add_argument("--trade-buy-max", type=float, default=0.15, help="Cross: trade buy max premium")
    parser.add_argument("--trade-sell", type=float, default=0.20, help="Cross: trade sell premium")

    args = parser.parse_args()

    if args.strategy == "premium_v1":
        if args.symbol is None:
            parser.error("--symbol is required for premium_v1 strategy")
        if args.buy is None or args.sell is None:
            parser.error("--buy and --sell are required for premium_v1 strategy")
    if args.strategy == "ladder_v2":
        if args.symbol is None:
            parser.error("--symbol is required for ladder_v2 strategy")
        if args.buy is None:
            args.buy = 0.0
        if args.sell is None:
            args.sell = 1.0
    if args.strategy == "ladder_v3":
        if args.symbol is None:
            parser.error("--symbol is required for ladder_v3 strategy")
        if args.buy is None:
            args.buy = 0.0
        if args.sell is None:
            args.sell = 1.0
    if args.strategy == "ladder_v4":
        if args.symbol is None:
            parser.error("--symbol is required for ladder_v4 strategy")
        if args.buy is None:
            args.buy = 0.0
        if args.sell is None:
            args.sell = 1.0
    if args.strategy == "cross_signal_v1":
        if args.buy is None:
            args.buy = 0.0
        if args.sell is None:
            args.sell = 1.0

    if not args.no_fetch:
        if args.strategy == "cross_signal_v1":
            fetch_etf_price(args.signal_symbol, args.start, args.end, refresh=args.refresh)
            fetch_etf_nav(args.signal_symbol, args.start, args.end, refresh=args.refresh)
            fetch_etf_price(args.trade_symbol, args.start, args.end, refresh=args.refresh)
            fetch_etf_nav(args.trade_symbol, args.start, args.end, refresh=args.refresh)
            build_dataset(args.signal_symbol)
            build_dataset(args.trade_symbol)
        else:
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
    elif args.strategy == "ladder_v2":
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
    elif args.strategy == "ladder_v3":
        result = run_ladder_v3_backtest(
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            fee_rate=args.fee_rate,
            initial_cash=args.initial_cash,
            cooldown_days=args.cooldown_days,
            rebalance_threshold=args.rebalance_threshold,
            min_trade_delta=args.min_trade_delta,
        )
        save_ladder_v3_reports(args.symbol, result["daily"], result["trades"])
        print_ladder_v3_result(result["stats"], result["trades"])
    elif args.strategy == "ladder_v4":
        result = run_ladder_v4_backtest(
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            fee_rate=args.fee_rate,
            initial_cash=args.initial_cash,
            cooldown_days=args.cooldown_days,
            min_hold_days=args.min_hold_days,
            rebalance_threshold=args.rebalance_threshold,
            core_position=args.core_position,
        )
        save_ladder_v4_reports(args.symbol, result["daily"], result["trades"])
        print_ladder_v4_result(result["stats"], result["trades"])
    elif args.strategy == "cross_signal_v1":
        df, trades_df, stats = run_cross_signal_backtest(
            signal_symbol=args.signal_symbol,
            trade_symbol=args.trade_symbol,
            start=args.start,
            end=args.end,
            signal_buy=args.signal_buy,
            signal_sell=args.signal_sell,
            trade_buy_max=args.trade_buy_max,
            trade_sell=args.trade_sell,
            execution_lag=args.execution_lag,
            fee_rate=args.fee_rate,
        )
        save_cross_reports(args.signal_symbol, args.trade_symbol, df, trades_df)
        print_cross_result(stats, trades_df)

    print("\n[done] ETF backtest completed.")


if __name__ == "__main__":
    main()
