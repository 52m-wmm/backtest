"""Build aligned ETF dataset from local price and NAV CSV files."""

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


def resolve_column(df: pd.DataFrame, candidates: list[str], field_name: str) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise RuntimeError(
        f"Cannot find column for {field_name}. candidates={candidates}, columns={list(df.columns)}"
    )


def build_dataset(symbol: str) -> Path:
    price_path = RAW_DIR / f"{symbol}_price.csv"
    nav_path = RAW_DIR / f"{symbol}_nav.csv"

    price = read_csv_required(price_path)
    nav = read_csv_required(nav_path)

    price_date_col = resolve_column(price, ["日期", "date", "Date"], "price date")
    price_close_col = resolve_column(price, ["收盘", "close", "Close"], "price close")

    nav_date_col = resolve_column(nav, ["净值日期", "日期", "date", "Date"], "nav date")
    nav_value_col = resolve_column(nav, ["单位净值", "nav", "NAV"], "nav value")

    price_clean = price[[price_date_col, price_close_col]].rename(
        columns={price_date_col: "date", price_close_col: "close"}
    )
    nav_clean = nav[[nav_date_col, nav_value_col]].rename(
        columns={nav_date_col: "date", nav_value_col: "nav"}
    )

    price_clean["date"] = pd.to_datetime(price_clean["date"], errors="coerce")
    nav_clean["date"] = pd.to_datetime(nav_clean["date"], errors="coerce")

    price_clean["close"] = pd.to_numeric(price_clean["close"], errors="coerce")
    nav_clean["nav"] = pd.to_numeric(nav_clean["nav"], errors="coerce")

    price_clean = price_clean.dropna(subset=["date", "close"])
    nav_clean = nav_clean.dropna(subset=["date", "nav"])

    dataset = (
        price_clean.merge(nav_clean, on="date", how="inner")
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )

    if dataset.empty:
        raise RuntimeError(
            "Merged dataset is empty. Check if price/nav date ranges overlap and columns are valid."
        )

    dataset["premium"] = dataset["close"] / dataset["nav"] - 1

    out = PROCESSED_DIR / f"{symbol}_dataset.csv"
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"[saved] {out} rows={len(dataset)}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()

    build_dataset(args.symbol)


if __name__ == "__main__":
    main()
