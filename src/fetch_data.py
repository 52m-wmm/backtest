"""
Fetch ETF price, ETF NAV, and QQQ benchmark data.

Data sources:
- Chinese ETF price: AkShare
- Chinese ETF NAV: AkShare
- QQQ benchmark: Stooq free CSV

Usage:
    python src/fetch_data.py --symbol 159509 --start 20230101

Force refresh:
    python src/fetch_data.py --symbol 159509 --start 20230101 --refresh
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Callable, TypeVar

import akshare as ak
import pandas as pd

try:
    import efinance as ef
except ImportError:
    ef = None

RAW_DIR = Path("data/raw")

T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    *,
    name: str,
    retries: int = 3,
    sleep_seconds: float = 3.0,
) -> T:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"[warn] {name} failed attempt {attempt}/{retries}: {exc}")
            if attempt < retries:
                time.sleep(sleep_seconds)

    raise RuntimeError(
        f"{name} failed after {retries} attempts. Last error: {last_error}"
    )


def normalize_cn_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    df = df.copy()
    df[col] = pd.to_datetime(df[col])
    return df.sort_values(col).reset_index(drop=True)


def use_cached_file(out: Path, refresh: bool) -> bool:
    return out.exists() and not refresh


def fetch_etf_price(symbol: str, start: str, end: str, refresh: bool = False) -> Path:
    out = RAW_DIR / f"{symbol}_price.csv"

    if out.exists() and not refresh:
        print(f"[cache] ETF price: {out}")
        return out

    def _fetch_akshare() -> pd.DataFrame:
        return ak.fund_etf_hist_em(
            symbol=symbol,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="",  # 不复权，方便和净值算溢价
        )

    try:
        print(f"[fetch] ETF price from AkShare: {symbol}, {start} -> {end}")
        df = with_retry(_fetch_akshare, name=f"AkShare ETF price {symbol}")
        source = "akshare"
    except Exception as exc:
        print(f"[warn] AkShare ETF price failed: {exc}")
        print(f"[fallback] Try efinance ETF price: {symbol}")

        if ef is None:
            raise RuntimeError(
                "AkShare failed and efinance is not installed. "
                "Run: python -m pip install efinance"
            ) from exc

        def _fetch_efinance() -> pd.DataFrame:
            return ef.stock.get_quote_history(
                symbol,
                beg=start,
                end=end,
                klt=101,  # 日线
                fqt=0,  # 不复权
            )

        df = with_retry(_fetch_efinance, name=f"eFinance ETF price {symbol}")
        source = "efinance"

    if df is None or df.empty:
        raise RuntimeError(f"ETF price data is empty for {symbol}.")

    if "日期" not in df.columns:
        raise RuntimeError(
            f"ETF price data missing 日期 column. columns={list(df.columns)}"
        )

    df = normalize_cn_date_col(df, "日期")

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"[saved] {out} rows={len(df)} source={source}")
    return out


def fetch_etf_nav(symbol: str, start: str, end: str, refresh: bool = False) -> Path:
    out = RAW_DIR / f"{symbol}_nav.csv"

    if use_cached_file(out, refresh):
        print(f"[cache] ETF NAV: {out}")
        return out

    print(f"[fetch] ETF NAV from AkShare: {symbol}, {start} -> {end}")

    def _fetch() -> pd.DataFrame:
        return ak.fund_etf_fund_info_em(
            fund=symbol,
            start_date=start,
            end_date=end,
        )

    try:
        df = with_retry(_fetch, name=f"AkShare ETF NAV {symbol}")
    except Exception:
        if out.exists():
            print(f"[fallback-cache] ETF NAV: {out}")
            return out
        raise

    if df.empty:
        if out.exists():
            print(f"[fallback-cache] ETF NAV empty, using: {out}")
            return out
        raise RuntimeError(f"ETF NAV data is empty for {symbol}.")

    if "净值日期" not in df.columns:
        raise RuntimeError(
            f"ETF NAV data missing 净值日期 column. Columns: {list(df.columns)}"
        )

    df = normalize_cn_date_col(df, "净值日期")

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[saved] {out} rows={len(df)}")

    return out


def fetch_qqq_stooq(start: str, end: str, refresh: bool = False) -> Path:
    out = RAW_DIR / "QQQ.csv"

    if use_cached_file(out, refresh):
        print(f"[cache] QQQ benchmark: {out}")
        return out

    print(f"[fetch] QQQ from Stooq: {start} -> {end}")

    def _fetch() -> pd.DataFrame:
        url = f"https://stooq.com/q/d/l/?s=qqq.us&i=d&d1={start}&d2={end}"
        return pd.read_csv(url)

    try:
        df = with_retry(_fetch, name="Stooq QQQ")
    except Exception:
        if out.exists():
            print(f"[fallback-cache] QQQ benchmark: {out}")
            return out
        raise

    if df.empty:
        if out.exists():
            print(f"[fallback-cache] QQQ empty, using: {out}")
            return out
        raise RuntimeError("QQQ data is empty from Stooq.")

    required_cols = {"Date", "Open", "High", "Low", "Close", "Volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise RuntimeError(
            f"QQQ data missing columns: {missing}. Columns: {list(df.columns)}"
        )

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[saved] {out} rows={len(df)}")

    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbol",
        required=True,
        help="ETF code, e.g. 159509 / 159632 / 513100",
    )
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-fetch even if local CSV cache already exists.",
    )
    parser.add_argument(
        "--skip-benchmark",
        action="store_true",
        help="Only fetch ETF price and NAV, skip QQQ benchmark.",
    )

    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    fetch_etf_price(args.symbol, args.start, args.end, refresh=args.refresh)
    fetch_etf_nav(args.symbol, args.start, args.end, refresh=args.refresh)

    if not args.skip_benchmark:
        qqq_start = (pd.to_datetime(args.start) - pd.Timedelta(days=10)).strftime(
            "%Y%m%d"
        )
        fetch_qqq_stooq(qqq_start, args.end, refresh=args.refresh)

    print("[done] fetch completed")


if __name__ == "__main__":
    main()
