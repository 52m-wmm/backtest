"""
Build aligned dataset.

V1:
- ETF daily price
- ETF official NAV
- premium = close / nav - 1

Optional:
- If data/raw/QQQ.csv exists, merge QQQ benchmark.
- If QQQ.csv does not exist, keep qqq filter always true so backtest can run.

Usage:
    python src\\build_dataset.py --symbol 159509
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")


def read_csv_required(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run fetch_data.py first.")
    return pd.read_csv(path)


def add_missing_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def build_dataset(symbol: str) -> Path:
    price_path = RAW_DIR / f"{symbol}_price.csv"
    nav_path = RAW_DIR / f"{symbol}_nav.csv"
    qqq_path = RAW_DIR / "QQQ.csv"

    price = read_csv_required(price_path)
    nav = read_csv_required(nav_path)

    price["date"] = pd.to_datetime(price["日期"])
    nav["date"] = pd.to_datetime(nav["净值日期"])

    price = price.rename(
        columns={
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
            "换手率": "turnover",
        }
    )

    nav = nav.rename(
        columns={
            "单位净值": "nav",
            "累计净值": "acc_nav",
            "日增长率": "nav_pct_chg",
        }
    )

    price = add_missing_columns(
        price,
        ["open", "close", "high", "low", "volume", "amount", "pct_chg", "turnover"],
    )
    nav = add_missing_columns(nav, ["nav", "acc_nav", "nav_pct_chg"])

    df = price[
        [
            "date",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "pct_chg",
            "turnover",
        ]
    ].merge(
        nav[["date", "nav", "acc_nav", "nav_pct_chg"]],
        on="date",
        how="left",
    )

    df = df.sort_values("date").reset_index(drop=True)

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    df["premium"] = df["close"] / df["nav"] - 1

    if qqq_path.exists():
        print(f"[benchmark] using QQQ file: {qqq_path}")

        qqq = pd.read_csv(qqq_path)
        qqq["us_date"] = pd.to_datetime(qqq["Date"])
        qqq = qqq.rename(
            columns={
                "Close": "qqq_close",
                "Open": "qqq_open",
                "High": "qqq_high",
                "Low": "qqq_low",
                "Volume": "qqq_volume",
            }
        )

        qqq = add_missing_columns(
            qqq,
            ["qqq_close", "qqq_open", "qqq_high", "qqq_low", "qqq_volume"],
        )

        qqq_small = qqq[
            ["us_date", "qqq_close", "qqq_open", "qqq_high", "qqq_low", "qqq_volume"]
        ].sort_values("us_date")

        df = pd.merge_asof(
            df.sort_values("date"),
            qqq_small,
            left_on="date",
            right_on="us_date",
            direction="backward",
            allow_exact_matches=False,
        )

        df["qqq_close"] = pd.to_numeric(df["qqq_close"], errors="coerce")
        df["qqq_ma20"] = df["qqq_close"].rolling(20).mean()
        df["qqq_ma60"] = df["qqq_close"].rolling(60).mean()
        df["benchmark_available"] = True

    else:
        print(
            "[benchmark] QQQ.csv not found. Skip QQQ filter for V1 premium-only backtest."
        )

        df["us_date"] = pd.NaT
        df["qqq_close"] = 1.0
        df["qqq_open"] = 1.0
        df["qqq_high"] = 1.0
        df["qqq_low"] = 1.0
        df["qqq_volume"] = 0.0

        # 让 backtest.py 里的 qqq_ok = qqq_close > qqq_ma 永远成立
        df["qqq_ma20"] = 0.0
        df["qqq_ma60"] = 0.0
        df["benchmark_available"] = False

    df["etf_ma20"] = df["close"].rolling(20).mean()
    df["etf_ma60"] = df["close"].rolling(60).mean()

    df["premium_rank_60"] = df["premium"].rolling(60).rank(pct=True)
    df["premium_rank_120"] = df["premium"].rolling(120).rank(pct=True)

    out = PROCESSED_DIR / f"{symbol}_dataset.csv"
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    df.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"[saved] {out} rows={len(df)}")
    print(df.tail(5).to_string(index=False))

    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()

    build_dataset(args.symbol)


if __name__ == "__main__":
    main()
