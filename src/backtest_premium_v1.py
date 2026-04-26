"""
Pure premium-band backtest V1.

Rule:
- No position and premium <= buy_premium: buy
- Has position and premium >= sell_premium: sell
- Otherwise hold current state

Usage:
    python src/backtest_premium_v1.py --symbol 159632 --buy 0.01 --sell 0.03
    python src/backtest_premium_v1.py --symbol 159509 --buy 0.15 --sell 0.20
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tabulate import tabulate


PROCESSED_DIR = Path("data/processed")
REPORT_DIR = Path("reports")


def normalize_threshold(value: float) -> float:
    # Allow both 0.15 and 15 for 15 percent.
    if value > 1:
        return value / 100
    return value


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1
    return float(dd.min())


def annual_return(final_equity: float, trading_days: int) -> float:
    if trading_days <= 1:
        return 0.0
    return float(final_equity ** (252 / trading_days) - 1)


def sharpe_ratio(equity: pd.Series) -> float:
    ret = equity.pct_change().dropna()
    if ret.empty or ret.std() == 0:
        return 0.0
    return float((ret.mean() / ret.std()) * np.sqrt(252))


def fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def backtest_premium_v1(
    symbol: str,
    buy_premium: float,
    sell_premium: float,
    start: str | None = None,
    end: str | None = None,
    execution_lag: int = 1,
    fee_rate: float = 0.0003,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    buy_premium = normalize_threshold(buy_premium)
    sell_premium = normalize_threshold(sell_premium)

    if buy_premium >= sell_premium:
        raise ValueError("buy_premium must be lower than sell_premium")

    path = PROCESSED_DIR / f"{symbol}_dataset.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run build_dataset.py first.")

    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["premium"] = pd.to_numeric(df["premium"], errors="coerce")

    if start:
        start_ts = pd.to_datetime(start, format="%Y%m%d", errors="raise")
        df = df[df["date"] >= start_ts]
    if end:
        end_ts = pd.to_datetime(end, format="%Y%m%d", errors="raise")
        df = df[df["date"] <= end_ts]

    df = (
        df.dropna(subset=["date", "close", "premium"])
        .sort_values("date")
        .reset_index(drop=True)
    )

    if df.empty:
        raise RuntimeError("Dataset is empty after cleaning.")

    df["signal"] = ""
    df["execution"] = ""
    df["position"] = 0.0
    df["cash"] = 1.0
    df["shares"] = 0.0
    df["strategy_equity"] = 1.0
    df["benchmark_equity"] = df["close"] / df["close"].iloc[0]

    cash = 1.0
    shares = 0.0
    pending_order: dict[str, object] | None = None
    trades: list[dict[str, object]] = []

    def execute_order(order: dict[str, object], i: int) -> None:
        nonlocal cash, shares, pending_order

        row = df.iloc[i]
        price = float(row["close"])
        premium = float(row["premium"])

        side = str(order["side"])

        if side == "BUY" and shares == 0 and cash > 0:
            shares = cash * (1 - fee_rate) / price
            cash = 0.0
            df.loc[i, "execution"] = "BUY"
        elif side == "SELL" and shares > 0:
            cash = shares * price * (1 - fee_rate)
            shares = 0.0
            df.loc[i, "execution"] = "SELL"
        else:
            pending_order = None
            return

        trades.append(
            {
                "signal_date": order["signal_date"],
                "signal": f"{side}_SIGNAL",
                "signal_close": order["signal_close"],
                "signal_premium": order["signal_premium"],
                "execute_date": row["date"].date(),
                "execute_close": price,
                "execute_premium": premium,
            }
        )

        pending_order = None

    for i in range(len(df)):
        row = df.iloc[i]

        # 1. Execute pending order first.
        if pending_order is not None and int(pending_order["exec_i"]) == i:
            execute_order(pending_order, i)

        close = float(row["close"])
        premium = float(row["premium"])

        # 2. Generate new signal only when there is no pending order.
        if pending_order is None:
            if shares == 0 and premium <= buy_premium:
                exec_i = i + execution_lag
                df.loc[i, "signal"] = "BUY_SIGNAL"

                if exec_i < len(df):
                    order = {
                        "side": "BUY",
                        "signal_date": row["date"].date(),
                        "signal_close": close,
                        "signal_premium": premium,
                        "exec_i": exec_i,
                    }

                    if exec_i == i:
                        execute_order(order, i)
                    else:
                        pending_order = order

            elif shares > 0 and premium >= sell_premium:
                exec_i = i + execution_lag
                df.loc[i, "signal"] = "SELL_SIGNAL"

                if exec_i < len(df):
                    order = {
                        "side": "SELL",
                        "signal_date": row["date"].date(),
                        "signal_close": close,
                        "signal_premium": premium,
                        "exec_i": exec_i,
                    }

                    if exec_i == i:
                        execute_order(order, i)
                    else:
                        pending_order = order

        equity = cash + shares * close

        df.loc[i, "cash"] = cash
        df.loc[i, "shares"] = shares
        df.loc[i, "position"] = 1.0 if shares > 0 else 0.0
        df.loc[i, "strategy_equity"] = equity

    trades_df = pd.DataFrame(trades)

    final_equity = float(df["strategy_equity"].iloc[-1])
    benchmark_final = float(df["benchmark_equity"].iloc[-1])
    trading_days = len(df)

    stats = {
        "symbol": symbol,
        "start": df["date"].iloc[0].date(),
        "end": df["date"].iloc[-1].date(),
        "buy_premium": fmt_pct(buy_premium),
        "sell_premium": fmt_pct(sell_premium),
        "execution_lag_days": execution_lag,
        "fee_rate": fmt_pct(fee_rate),
        "final_equity": f"{final_equity:.4f}",
        "strategy_total_return": fmt_pct(final_equity - 1),
        "benchmark_total_return": fmt_pct(benchmark_final - 1),
        "strategy_ann_return": fmt_pct(annual_return(final_equity, trading_days)),
        "benchmark_ann_return": fmt_pct(annual_return(benchmark_final, trading_days)),
        "strategy_max_drawdown": fmt_pct(max_drawdown(df["strategy_equity"])),
        "benchmark_max_drawdown": fmt_pct(max_drawdown(df["benchmark_equity"])),
        "strategy_sharpe": f"{sharpe_ratio(df['strategy_equity']):.2f}",
        "trade_count": len(trades_df),
        "days_in_market": int(df["position"].sum()),
        "market_exposure": fmt_pct(float(df["position"].mean())),
    }

    return df, trades_df, stats


def save_reports(symbol: str, df: pd.DataFrame, trades_df: pd.DataFrame) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    daily_path = REPORT_DIR / f"{symbol}_premium_v1_daily.csv"
    trades_path = REPORT_DIR / f"{symbol}_premium_v1_trades.csv"
    chart_path = REPORT_DIR / f"{symbol}_premium_v1_equity.png"

    df.to_csv(daily_path, index=False, encoding="utf-8-sig")
    trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")

    plt.figure(figsize=(12, 6))
    plt.plot(df["date"], df["strategy_equity"], label="Premium Strategy")
    plt.plot(df["date"], df["benchmark_equity"], label="Buy & Hold")
    plt.title(f"{symbol} Premium Strategy V1")
    plt.xlabel("Date")
    plt.ylabel("Equity")
    plt.legend()
    plt.tight_layout()
    plt.savefig(chart_path, dpi=150)
    plt.close()

    print(f"[saved] {daily_path}")
    print(f"[saved] {trades_path}")
    print(f"[saved] {chart_path}")


def print_backtest_result(stats: dict[str, object], trades_df: pd.DataFrame) -> None:
    print("\n=== Backtest Stats ===")
    print(tabulate(stats.items(), headers=["Metric", "Value"], tablefmt="github"))

    print("\n=== Recent Trades ===")
    if trades_df.empty:
        print("No trades.")
    else:
        print(trades_df.tail(10).to_string(index=False))


def run_backtest(
    symbol: str,
    buy_premium: float,
    sell_premium: float,
    start: str | None = None,
    end: str | None = None,
    execution_lag: int = 1,
    fee_rate: float = 0.0003,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    return backtest_premium_v1(
        symbol=symbol,
        buy_premium=buy_premium,
        sell_premium=sell_premium,
        start=start,
        end=end,
        execution_lag=execution_lag,
        fee_rate=fee_rate,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, help="ETF code, for example 159632")
    parser.add_argument(
        "--buy", type=float, required=True, help="Buy premium, 0.01 means 1 percent"
    )
    parser.add_argument(
        "--sell", type=float, required=True, help="Sell premium, 0.03 means 3 percent"
    )
    parser.add_argument(
        "--execution-lag", type=int, default=1, help="Execution lag in trading days"
    )
    parser.add_argument(
        "--fee-rate", type=float, default=0.0003, help="0.0003 means 0.03 percent"
    )

    args = parser.parse_args()

    df, trades_df, stats = backtest_premium_v1(
        symbol=args.symbol,
        buy_premium=args.buy,
        sell_premium=args.sell,
        execution_lag=args.execution_lag,
        fee_rate=args.fee_rate,
    )

    save_reports(args.symbol, df, trades_df)
    print_backtest_result(stats, trades_df)


if __name__ == "__main__":
    main()
