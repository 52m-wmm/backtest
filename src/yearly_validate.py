"""Yearly validation for a fixed premium strategy parameter set."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from tabulate import tabulate

from backtest_premium_v1 import backtest_premium_v1


PROCESSED_DIR = Path("data/processed")
REPORT_DIR = Path("reports")


def parse_pct(value: object) -> float:
    text = str(value).strip()
    if text.endswith("%"):
        return float(text[:-1]) / 100
    return float(text)


def normalize_date_text(value: object) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def to_result_row(period: str, buy: float, sell: float, stats: dict[str, object]) -> dict[str, object]:
    return {
        "period": period,
        "symbol": str(stats["symbol"]),
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
        "days_in_market": int(stats["days_in_market"]),
        "market_exposure": parse_pct(stats["market_exposure"]),
    }


def load_date_range(symbol: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    dataset_path = PROCESSED_DIR / f"{symbol}_dataset.csv"
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Missing {dataset_path}. Run `python src/run.py --symbol {symbol} --buy ... --sell ... --no-fetch` first."
        )

    df = pd.read_csv(dataset_path, usecols=["date"])
    if df.empty:
        raise RuntimeError(f"Dataset {dataset_path} is empty.")

    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        raise RuntimeError(f"Dataset {dataset_path} has no valid date values.")

    return dates.min(), dates.max()


def year_periods(start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> list[tuple[int, str, str]]:
    periods: list[tuple[int, str, str]] = []
    for year in range(start_ts.year, end_ts.year + 1):
        year_start = max(start_ts, pd.Timestamp(year=year, month=1, day=1))
        year_end = min(end_ts, pd.Timestamp(year=year, month=12, day=31))
        if year_start <= year_end:
            periods.append(
                (
                    year,
                    year_start.strftime("%Y%m%d"),
                    year_end.strftime("%Y%m%d"),
                )
            )
    return periods


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--buy", type=float, required=True)
    parser.add_argument("--sell", type=float, required=True)
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default=None)
    parser.add_argument("--execution-lag", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.0003)
    args = parser.parse_args()

    if args.buy >= args.sell:
        raise ValueError("--buy must be lower than --sell.")

    data_min, data_max = load_date_range(args.symbol)

    start_ts = pd.to_datetime(args.start, format="%Y%m%d", errors="raise")
    end_ts = data_max if args.end is None else pd.to_datetime(args.end, format="%Y%m%d", errors="raise")

    start_ts = max(start_ts, data_min)
    end_ts = min(end_ts, data_max)

    if start_ts > end_ts:
        raise RuntimeError(
            f"Requested window has no overlap with dataset. requested=({args.start},{args.end}) "
            f"data=({data_min.strftime('%Y%m%d')},{data_max.strftime('%Y%m%d')})"
        )

    rows: list[dict[str, object]] = []

    for year, year_start, year_end in year_periods(start_ts, end_ts):
        _, _, stats = backtest_premium_v1(
            symbol=args.symbol,
            buy_premium=args.buy,
            sell_premium=args.sell,
            start=year_start,
            end=year_end,
            execution_lag=args.execution_lag,
            fee_rate=args.fee_rate,
        )
        rows.append(to_result_row(str(year), args.buy, args.sell, stats))

    _, _, full_stats = backtest_premium_v1(
        symbol=args.symbol,
        buy_premium=args.buy,
        sell_premium=args.sell,
        start=start_ts.strftime("%Y%m%d"),
        end=end_ts.strftime("%Y%m%d"),
        execution_lag=args.execution_lag,
        fee_rate=args.fee_rate,
    )
    rows.append(to_result_row("ALL", args.buy, args.sell, full_stats))

    result_df = pd.DataFrame(rows)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    buy_text = str(args.buy).replace(".", "p")
    sell_text = str(args.sell).replace(".", "p")
    out = REPORT_DIR / f"yearly_{args.symbol}_{buy_text}_{sell_text}.csv"
    result_df.to_csv(out, index=False, encoding="utf-8-sig")

    print("\n=== Yearly Validation ===")
    print(
        tabulate(
            result_df,
            headers="keys",
            tablefmt="github",
            showindex=False,
            floatfmt=".4f",
        )
    )
    print(f"[saved] {out}")


if __name__ == "__main__":
    main()
