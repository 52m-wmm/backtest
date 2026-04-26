"""Ladder position sizing strategy V2: buy more on drawdown, sell more on rise."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tabulate import tabulate


PROCESSED_DIR = Path("data/processed")
REPORT_DIR = Path("reports")


def fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


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


def run_ladder_backtest(
    symbol: str,
    start: str,
    end: str | None,
    fee_rate: float = 0.0003,
    execution_lag_days: int = 1,
    drawdown_window: int = 60,
    rise_window: int = 60,
    min_trade_delta: float = 0.10,
    max_daily_buy: float = 0.20,
    max_daily_sell: float = 0.40,
) -> dict[str, object]:
    dataset_path = PROCESSED_DIR / f"{symbol}_dataset.csv"
    if not dataset_path.exists():
        raise FileNotFoundError(f"Missing {dataset_path}. Run build_dataset.py first.")

    df = pd.read_csv(dataset_path)
    df["date"] = pd.to_datetime(df["date"])

    if "premium" not in df.columns:
        df["premium"] = df["close"] / df["nav"] - 1

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

    df["rolling_high"] = df["close"].rolling(drawdown_window).max()
    df["rolling_low"] = df["close"].rolling(rise_window).min()
    df["dd60"] = df["close"] / df["rolling_high"] - 1
    df["rise60"] = df["close"] / df["rolling_low"] - 1

    df = df.dropna(subset=["dd60", "rise60"]).reset_index(drop=True)

    df["target_position"] = 0.0

    for i in range(len(df)):
        row = df.iloc[i]
        premium = float(row["premium"])
        dd60 = float(row["dd60"])
        rise60 = float(row["rise60"])

        target = 0.0

        if premium <= 0 and dd60 <= -0.15:
            target = 1.00
        elif premium <= 0.01 and dd60 <= -0.10:
            target = max(target, 0.80)
        elif premium <= 0.01 and dd60 <= -0.05:
            target = max(target, 0.60)
        elif premium <= 0.01:
            target = max(target, 0.50)

        if premium >= 0.10:
            target = 0.00
        elif premium >= 0.08:
            target = min(target, 0.20)
        elif premium >= 0.06:
            target = min(target, 0.40)

        if premium >= 0.06 and rise60 >= 0.25:
            target = min(target, 0.20)
        if premium >= 0.08 and rise60 >= 0.35:
            target = 0.00

        df.loc[i, "target_position"] = target

    df["target_position"] = df["target_position"].clip(0.0, 1.0)

    pending_target: float | None = None
    pending_exec_day: int | None = None

    df["position"] = 0.0
    df["cash"] = 1.0
    df["shares"] = 0.0
    df["strategy_equity"] = 1.0
    df["benchmark_equity"] = df["close"] / df["close"].iloc[0]
    df["trade_delta"] = 0.0

    cash = 1.0
    shares = 0.0
    position = 0.0

    trades: list[dict[str, object]] = []

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])

        if pending_exec_day is not None and i == pending_exec_day:
            target = pending_target if pending_target is not None else position
            delta = target - position

            if abs(delta) >= min_trade_delta:
                delta = max(min(delta, max_daily_buy), -max_daily_sell)

                if delta > 0:
                    buy_notional = cash * delta
                    cost = buy_notional * (1 + fee_rate)
                    if cost <= cash:
                        shares_to_buy = buy_notional / price
                        shares += shares_to_buy
                        cash -= cost
                        position = shares * price / (cash + shares * price)
                        df.loc[i, "trade_delta"] = delta
                        trades.append(
                            {
                                "date": row["date"].date(),
                                "action": "BUY",
                                "price": price,
                                "delta": delta,
                                "position_after": position,
                            }
                        )
                elif delta < 0:
                    sell_notional = abs(delta) * (cash + shares * price)
                    sell_shares = sell_notional / price
                    if sell_shares <= shares:
                        cash_in = sell_shares * price * (1 - fee_rate)
                        cash += cash_in
                        shares -= sell_shares
                        position = shares * price / (cash + shares * price)
                        df.loc[i, "trade_delta"] = delta
                        trades.append(
                            {
                                "date": row["date"].date(),
                                "action": "SELL",
                                "price": price,
                                "delta": delta,
                                "position_after": position,
                            }
                        )

            pending_target = None
            pending_exec_day = None

        target_today = float(row["target_position"])
        if target_today != position and pending_exec_day is None:
            pending_target = target_today
            pending_exec_day = i + execution_lag_days
            if pending_exec_day >= len(df):
                pending_exec_day = None

        equity = cash + shares * price
        df.loc[i, "cash"] = cash
        df.loc[i, "shares"] = shares
        df.loc[i, "position"] = position
        df.loc[i, "strategy_equity"] = equity

    trades_df = pd.DataFrame(trades)

    final_equity = float(df["strategy_equity"].iloc[-1])
    benchmark_final = float(df["benchmark_equity"].iloc[-1])
    trading_days = len(df)

    stats = {
        "symbol": symbol,
        "start": df["date"].iloc[0].date(),
        "end": df["date"].iloc[-1].date(),
        "strategy_name": "ladder_v2",
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
        "avg_position": f"{float(df['position'].mean()):.4f}",
        "max_position": f"{float(df['position'].max()):.4f}",
        "min_position": f"{float(df['position'].min()):.4f}",
    }

    return {
        "daily": df,
        "trades": trades_df,
        "stats": stats,
    }


def save_reports(symbol: str, daily_df: pd.DataFrame, trades_df: pd.DataFrame) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    equity_path = REPORT_DIR / f"ladder_{symbol}_equity.csv"
    trades_path = REPORT_DIR / f"ladder_{symbol}_trades.csv"

    daily_df.to_csv(equity_path, index=False, encoding="utf-8-sig")
    trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")

    chart_path = REPORT_DIR / f"ladder_{symbol}_equity.png"
    plt.figure(figsize=(12, 6))
    plt.plot(daily_df["date"], daily_df["strategy_equity"], label="Ladder V2")
    plt.plot(daily_df["date"], daily_df["benchmark_equity"], label="Buy & Hold")
    plt.title(f"{symbol} Ladder V2 Strategy")
    plt.xlabel("Date")
    plt.ylabel("Equity")
    plt.legend()
    plt.tight_layout()
    plt.savefig(chart_path, dpi=150)
    plt.close()

    print(f"[saved] {equity_path}")
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default=None)
    parser.add_argument("--fee-rate", type=float, default=0.0003)
    parser.add_argument("--execution-lag-days", type=int, default=1)
    parser.add_argument("--drawdown-window", type=int, default=60)
    parser.add_argument("--rise-window", type=int, default=60)
    parser.add_argument("--min-trade-delta", type=float, default=0.10)
    parser.add_argument("--max-daily-buy", type=float, default=0.20)
    parser.add_argument("--max-daily-sell", type=float, default=0.40)
    args = parser.parse_args()

    result = run_ladder_backtest(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        fee_rate=args.fee_rate,
        execution_lag_days=args.execution_lag_days,
        drawdown_window=args.drawdown_window,
        rise_window=args.rise_window,
        min_trade_delta=args.min_trade_delta,
        max_daily_buy=args.max_daily_buy,
        max_daily_sell=args.max_daily_sell,
    )

    save_reports(args.symbol, result["daily"], result["trades"])
    print_backtest_result(result["stats"], result["trades"])


if __name__ == "__main__":
    main()
