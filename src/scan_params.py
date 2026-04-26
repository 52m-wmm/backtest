"""Parameter scan for premium strategy."""

from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

import pandas as pd
from tabulate import tabulate

from backtest_premium_v1 import backtest_premium_v1


REPORT_DIR = Path("reports")


SORT_BY_MAP = {
    "strategy_total_return": "strategy_total_return",
    "strategy_ann_return": "strategy_ann_return",
    "sharpe": "strategy_sharpe",
    "max_drawdown": "strategy_max_drawdown",
}


def parse_float_list(s: str) -> list[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def parse_pct(value: object) -> float:
    text = str(value).strip()
    if text.endswith("%"):
        return float(text[:-1]) / 100
    return float(text)


def normalize_date_text(value: object) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def to_result_row(symbol: str, buy: float, sell: float, stats: dict[str, object]) -> dict[str, object]:
    return {
        "symbol": symbol,
        "start": normalize_date_text(stats["start"]),
        "end": normalize_date_text(stats["end"]),
        "buy_premium": buy,
        "sell_premium": sell,
        "final_equity": float(stats["final_equity"]),
        "strategy_total_return": parse_pct(stats["strategy_total_return"]),
        "benchmark_total_return": parse_pct(stats["benchmark_total_return"]),
        "strategy_ann_return": parse_pct(stats["strategy_ann_return"]),
        "benchmark_ann_return": parse_pct(stats["benchmark_ann_return"]),
        "strategy_max_drawdown": parse_pct(stats["strategy_max_drawdown"]),
        "benchmark_max_drawdown": parse_pct(stats["benchmark_max_drawdown"]),
        "strategy_sharpe": float(stats["strategy_sharpe"]),
        "trade_count": int(stats["trade_count"]),
        "market_exposure": parse_pct(stats["market_exposure"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--buy-values",
        default="-0.01,0,0.005,0.01,0.015,0.02,0.025,0.03",
        help='Comma-separated buy thresholds, e.g. "-0.01,0,0.01"',
    )
    parser.add_argument(
        "--sell-values",
        default="0.04,0.05,0.06,0.07,0.08,0.09,0.10",
        help='Comma-separated sell thresholds, e.g. "0.04,0.05,0.06"',
    )
    parser.add_argument("--execution-lag", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.0003)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument(
        "--sort-by",
        default="sharpe",
        choices=["strategy_total_return", "strategy_ann_return", "sharpe", "max_drawdown"],
    )
    args = parser.parse_args()

    buy_values = parse_float_list(args.buy_values)
    sell_values = parse_float_list(args.sell_values)

    if not buy_values:
        raise ValueError("--buy-values is empty after parsing.")
    if not sell_values:
        raise ValueError("--sell-values is empty after parsing.")

    rows: list[dict[str, object]] = []
    tested_count = 0
    skipped_count = 0

    for buy_premium, sell_premium in product(buy_values, sell_values):
        if sell_premium <= buy_premium:
            skipped_count += 1
            continue

        tested_count += 1
        _, _, stats = backtest_premium_v1(
            symbol=args.symbol,
            buy_premium=buy_premium,
            sell_premium=sell_premium,
            start=args.start,
            end=args.end,
            execution_lag=args.execution_lag,
            fee_rate=args.fee_rate,
        )

        rows.append(to_result_row(args.symbol, buy_premium, sell_premium, stats))

    if not rows:
        raise RuntimeError("No valid buy/sell combinations to evaluate.")

    df = pd.DataFrame(rows)
    sort_col = SORT_BY_MAP[args.sort_by]
    ascending = args.sort_by == "max_drawdown"
    df = df.sort_values(sort_col, ascending=ascending).reset_index(drop=True)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    end_text = args.end or pd.Timestamp.today().strftime("%Y%m%d")
    out = REPORT_DIR / f"scan_{args.symbol}_{args.start}_{end_text}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    top_n = max(1, args.top)
    top_df = df.head(top_n)

    print("\n=== Scan Summary ===")
    print(
        f"symbol={args.symbol} tested={tested_count} skipped={skipped_count} "
        f"sort_by={args.sort_by} top={top_n}"
    )

    print("\n=== Top Results ===")
    print(
        tabulate(
            top_df,
            headers="keys",
            tablefmt="github",
            showindex=False,
            floatfmt=".4f",
        )
    )

    print(f"[saved] {out}")


if __name__ == "__main__":
    main()
