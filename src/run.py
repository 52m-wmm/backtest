"""
One-command interface for ETF premium backtest.

Usage:
    python src/run.py --symbol 159632 --buy 0.01 --sell 0.03 --start 20230101
    python src/run.py --symbol 159509 --buy 0.15 --sell 0.20 --start 20230101
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cmd(cmd: list[str]) -> None:
    print("\n[cmd]", " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


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
    parser.add_argument("--end", default=None)
    parser.add_argument("--execution-lag", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.0003)
    parser.add_argument("--refresh", action="store_true", help="Force refetch data")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetch_data.py and use local CSV files",
    )

    args = parser.parse_args()

    py = sys.executable

    if not args.no_fetch:
        fetch_cmd = [
            py,
            "src/fetch_data.py",
            "--symbol",
            args.symbol,
            "--start",
            args.start,
            "--skip-benchmark",
        ]

        if args.end:
            fetch_cmd.extend(["--end", args.end])

        if args.refresh:
            fetch_cmd.append("--refresh")

        run_cmd(fetch_cmd)

    run_cmd(
        [
            py,
            "src/build_dataset.py",
            "--symbol",
            args.symbol,
        ]
    )

    run_cmd(
        [
            py,
            "src/backtest_premium_v1.py",
            "--symbol",
            args.symbol,
            "--buy",
            str(args.buy),
            "--sell",
            str(args.sell),
            "--execution-lag",
            str(args.execution_lag),
            "--fee-rate",
            str(args.fee_rate),
        ]
    )

    print("\n[done] ETF premium backtest completed.")


if __name__ == "__main__":
    main()
