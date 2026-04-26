"""Fetch ETF price and NAV data with local CSV cache."""

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


def normalize_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    out = df.copy()
    out[col] = pd.to_datetime(out[col], errors="coerce")
    out = out.dropna(subset=[col]).sort_values(col).reset_index(drop=True)
    return out


def use_cached_file(out: Path, refresh: bool) -> bool:
    return out.exists() and not refresh


def get_date_col(df: pd.DataFrame, candidates: list[str]) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise RuntimeError(f"Date column not found. columns={list(df.columns)}")


def map_tx_symbol(symbol: str) -> str:
    if symbol.startswith(("159", "160", "162", "18")):
        return f"sz{symbol}"
    if symbol.startswith(("510", "513", "520", "560", "588")):
        return f"sh{symbol}"
    raise ValueError(
        "Cannot map symbol to Tencent market prefix. "
        f"symbol={symbol}, expected prefixes: "
        "sz(159/160/162/18), sh(510/513/520/560/588)"
    )


def fetch_etf_price(symbol: str, start: str, end: str, refresh: bool = False) -> Path:
    out = RAW_DIR / f"{symbol}_price.csv"

    if use_cached_file(out, refresh):
        print(f"[cache] ETF price: {out}")
        return out

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    source_errors: list[str] = []

    def _fetch_akshare_fund_etf() -> pd.DataFrame:
        return ak.fund_etf_hist_em(
            symbol=symbol,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="",
        )

    try:
        print(f"[fetch] price source=akshare.fund_etf_hist_em symbol={symbol}")
        df = with_retry(
            _fetch_akshare_fund_etf,
            name=f"akshare.fund_etf_hist_em({symbol})",
        )
        source = "akshare.fund_etf_hist_em"
    except Exception as exc:
        msg = f"akshare.fund_etf_hist_em failed: {exc}"
        source_errors.append(msg)
        print(f"[warn] {msg}")

        try:
            if ef is None:
                raise RuntimeError("efinance package is not available")

            def _fetch_efinance() -> pd.DataFrame:
                return ef.stock.get_quote_history(
                    symbol,
                    beg=start,
                    end=end,
                    klt=101,
                    fqt=0,
                )

            print(f"[fetch] price source=efinance.stock.get_quote_history symbol={symbol}")
            df = with_retry(
                _fetch_efinance,
                name=f"efinance.stock.get_quote_history({symbol})",
            )
            source = "efinance.stock.get_quote_history"
        except Exception as exc2:
            msg2 = f"efinance.stock.get_quote_history failed: {exc2}"
            source_errors.append(msg2)
            print(f"[warn] {msg2}")

            tx_symbol = map_tx_symbol(symbol)

            def _fetch_tx() -> pd.DataFrame:
                return ak.stock_zh_a_hist_tx(
                    symbol=tx_symbol,
                    start_date=start,
                    end_date=end,
                    adjust="",
                )

            try:
                print(f"[fetch] price source=akshare.stock_zh_a_hist_tx symbol={tx_symbol}")
                df = with_retry(
                    _fetch_tx,
                    name=f"akshare.stock_zh_a_hist_tx({tx_symbol})",
                )
                source = "akshare.stock_zh_a_hist_tx"
            except Exception as exc3:
                msg3 = f"akshare.stock_zh_a_hist_tx failed: {exc3}"
                source_errors.append(msg3)
                print(f"[error] {msg3}")
                raise RuntimeError(
                    "All ETF price sources failed: " + " | ".join(source_errors)
                ) from exc3

    if df is None or df.empty:
        raise RuntimeError(f"ETF price data is empty for {symbol}.")

    date_col = get_date_col(df, ["日期", "date", "Date"])
    df = normalize_date_col(df, date_col)
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"[saved] {out} rows={len(df)} source={source}")
    return out


def fetch_etf_nav(symbol: str, start: str, end: str, refresh: bool = False) -> Path:
    out = RAW_DIR / f"{symbol}_nav.csv"

    if use_cached_file(out, refresh):
        print(f"[cache] ETF NAV: {out}")
        return out

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[fetch] nav source=akshare.fund_etf_fund_info_em symbol={symbol}")

    def _fetch() -> pd.DataFrame:
        return ak.fund_etf_fund_info_em(
            fund=symbol,
            start_date=start,
            end_date=end,
        )

    df = with_retry(_fetch, name=f"akshare.fund_etf_fund_info_em({symbol})")
    if df.empty:
        raise RuntimeError(f"ETF NAV data is empty for {symbol}.")

    date_col = get_date_col(df, ["净值日期", "日期", "date", "Date"])
    df = normalize_date_col(df, date_col)
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

    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    fetch_etf_price(args.symbol, args.start, args.end, refresh=args.refresh)
    fetch_etf_nav(args.symbol, args.start, args.end, refresh=args.refresh)

    print("[done] fetch completed")


if __name__ == "__main__":
    main()
