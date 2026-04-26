"""
Parameter scan.

Example:
    python src\scan_params.py --symbol 159509
"""

from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

import pandas as pd

from backtest import run_backtest


REPORT_DIR = Path("reports")


def parse_float_list(s: str) -> list[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--buy-list", default="0.10,0.12,0.15,0.18")
    parser.add_argument("--sell-list", default="0.16,0.18,0.20,0.22,0.25")
    parser.add_argument("--execution-lag", type=int, default=1)
    args = parser.parse_args()

    rows = []
    for buy_premium, sell_premium in product(parse_float_list(args.buy_list), parse_float_list(args.sell_list)):
        if sell_premium <= buy_premium:
            continue

        result = run_backtest(
            symbol=args.symbol,
            buy_premium=buy_premium,
            sell_premium=sell_premium,
            qqq_ma=20,
            etf_ma=20,
            execution_lag=args.execution_lag,
            fee_rate=0.0002,
        )

        rows.append(
            {
                "symbol": args.symbol,
                "buy_premium": buy_premium,
                "sell_premium": sell_premium,
                **result.stats,
            }
        )

    out = REPORT_DIR / f"{args.symbol}_param_scan.csv"
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[saved] {out}")


if __name__ == "__main__":
    main()
