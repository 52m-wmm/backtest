"""Low-frequency core + tactical position strategy V4 for 159632."""

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


def run_ladder_v4_backtest(
    symbol: str,
    start: str,
    end: str | None,
    fee_rate: float = 0.0003,
    initial_cash: float = 1.0,
    cooldown_days: int = 15,
    min_hold_days: int = 10,
    rebalance_threshold: float = 0.25,
    core_position: float = 0.60,
) -> dict[str, object]:
    dataset_path = PROCESSED_DIR / f"{symbol}_dataset.csv"
    if not dataset_path.exists():
        raise FileNotFoundError(f"Missing {dataset_path}. Run build_dataset.py first.")

    df = pd.read_csv(dataset_path)
    df["date"] = pd.to_datetime(df["date"])

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["premium"] = pd.to_numeric(df["premium"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    if "etf_ma20" in df.columns:
        df["etf_ma20"] = pd.to_numeric(df["etf_ma20"], errors="coerce")
    else:
        df["etf_ma20"] = np.nan

    if "etf_ma60" in df.columns:
        df["etf_ma60"] = pd.to_numeric(df["etf_ma60"], errors="coerce")
    else:
        df["etf_ma60"] = np.nan

    df = df.dropna(subset=["date", "close", "premium"]).sort_values("date").reset_index(drop=True)

    if df.empty:
        raise RuntimeError("Dataset is empty after cleaning.")

    if start:
        start_ts = pd.to_datetime(start, format="%Y%m%d", errors="raise")
        df = df[df["date"] >= start_ts]
    if end:
        end_ts = pd.to_datetime(end, format="%Y%m%d", errors="raise")
        df = df[df["date"] <= end_ts]

    df = df.reset_index(drop=True)

    df["amount_ma20"] = df["amount"].rolling(20).mean()

    cash = initial_cash
    shares = 0.0
    cooldown_counter = 0
    hold_days_counter = 0
    last_trade_day = -999

    df["target_position"] = 0.0
    df["position"] = 0.0
    df["cash"] = cash
    df["shares"] = 0.0
    df["strategy_equity"] = initial_cash
    df["benchmark_equity"] = df["close"] / df["close"].iloc[0]

    trades: list[dict[str, object]] = []

    for i in range(len(df)):
        row = df.iloc[i]
        close = float(row["close"])
        premium = float(row["premium"])
        amount = float(row["amount"]) if pd.notna(row["amount"]) else 0.0
        etf_ma20 = float(row["etf_ma20"]) if pd.notna(row["etf_ma20"]) else np.nan
        etf_ma60 = float(row["etf_ma60"]) if pd.notna(row["etf_ma60"]) else np.nan
        amount_ma20 = float(row["amount_ma20"]) if pd.notna(row["amount_ma20"]) else 0.0

        current_position = shares * close / (cash + shares * close) if cash + shares * close > 0 else 0.0

        if cooldown_counter > 0:
            cooldown_counter -= 1

        if shares > 0:
            hold_days_counter += 1

        if not pd.isna(etf_ma60) and not pd.isna(etf_ma20):
            if close > etf_ma60 and etf_ma20 > etf_ma60:
                max_position = 1.00
            elif close >= etf_ma60:
                max_position = 0.85
            elif close < etf_ma60 and etf_ma20 < etf_ma60:
                max_position = 0.60
            else:
                max_position = 0.70
        else:
            max_position = 0.80

        if premium <= -0.02:
            target = 1.00
        elif premium <= 0.00:
            target = 0.90
        elif premium <= 0.01:
            target = 0.80
        elif premium >= 0.10:
            target = 0.30
        elif premium >= 0.08:
            target = 0.50
        elif premium >= 0.06:
            target = 0.70
        else:
            target = current_position

        if premium >= 0.12:
            target = 0.00

        target = max(target, core_position) if target > core_position else target
        target = min(target, max_position)

        df.loc[i, "target_position"] = target
        df.loc[i, "position"] = current_position

        delta = target - current_position

        if abs(delta) >= rebalance_threshold and cooldown_counter == 0:
            liquidity_ok = True
            if delta > 0 and amount_ma20 > 0 and amount < amount_ma20 * 0.5:
                liquidity_ok = False

            hold_ok = True
            if delta > 0 and not (premium <= -0.02):
                hold_ok = hold_days_counter >= min_hold_days
            if delta < 0 and not (premium >= 0.10):
                hold_ok = hold_days_counter >= min_hold_days

            if liquidity_ok and hold_ok:
                equity = cash + shares * close
                target_value = equity * target
                current_value = shares * close
                delta_value = target_value - current_value

                if delta_value > 0:
                    buy_notional = delta_value
                    cost = buy_notional * (1 + fee_rate)
                    if cost <= cash:
                        shares_to_buy = buy_notional / close
                        shares += shares_to_buy
                        cash -= cost
                        position_after = shares * close / (cash + shares * close)
                        trades.append(
                            {
                                "date": row["date"].date(),
                                "action": "BUY",
                                "price": close,
                                "premium": premium,
                                "target_position": target,
                                "position_before": current_position,
                                "position_after": position_after,
                                "delta_position": delta,
                                "reason": "REBALANCE",
                            }
                        )
                        cooldown_counter = cooldown_days
                        hold_days_counter = 0
                        last_trade_day = i
                elif delta_value < 0:
                    sell_notional = abs(delta_value)
                    sell_shares = sell_notional / close
                    if sell_shares <= shares:
                        cash_in = sell_shares * close * (1 - fee_rate)
                        cash += cash_in
                        shares -= sell_shares
                        position_after = shares * close / (cash + shares * close)
                        trades.append(
                            {
                                "date": row["date"].date(),
                                "action": "SELL",
                                "price": close,
                                "premium": premium,
                                "target_position": target,
                                "position_before": current_position,
                                "position_after": position_after,
                                "delta_position": delta,
                                "reason": "REBALANCE",
                            }
                        )
                        cooldown_counter = cooldown_days
                        hold_days_counter = 0
                        last_trade_day = i

        df.loc[i, "cash"] = cash
        df.loc[i, "shares"] = shares
        current_position = shares * close / (cash + shares * close) if cash + shares * close > 0 else 0.0
        df.loc[i, "position"] = current_position
        df.loc[i, "strategy_equity"] = cash + shares * close

    trades_df = pd.DataFrame(trades)

    final_equity = float(df["strategy_equity"].iloc[-1])
    benchmark_final = float(df["benchmark_equity"].iloc[-1])
    trading_days = len(df)

    stats = {
        "symbol": symbol,
        "start": df["date"].iloc[0].date(),
        "end": df["date"].iloc[-1].date(),
        "strategy_name": "ladder_v4",
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

    equity_path = REPORT_DIR / f"ladder_v4_{symbol}_equity.csv"
    trades_path = REPORT_DIR / f"ladder_v4_{symbol}_trades.csv"
    chart_path = REPORT_DIR / f"ladder_v4_{symbol}_equity.png"

    daily_df.to_csv(equity_path, index=False, encoding="utf-8-sig")
    trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")

    plt.figure(figsize=(12, 6))
    plt.plot(daily_df["date"], daily_df["strategy_equity"], label="Ladder V4")
    plt.plot(daily_df["date"], daily_df["benchmark_equity"], label="Buy & Hold")
    plt.title(f"{symbol} Ladder V4 Strategy")
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
    parser.add_argument("--initial-cash", type=float, default=1.0)
    parser.add_argument("--cooldown-days", type=int, default=15)
    parser.add_argument("--min-hold-days", type=int, default=10)
    parser.add_argument("--rebalance-threshold", type=float, default=0.25)
    parser.add_argument("--core-position", type=float, default=0.60)
    args = parser.parse_args()

    result = run_ladder_v4_backtest(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        fee_rate=args.fee_rate,
        initial_cash=args.initial_cash,
        cooldown_days=args.cooldown_days,
        min_hold_days=args.min_hold_days,
        rebalance_threshold=args.rebalance_threshold,
        core_position=args.core_position,
    )

    save_reports(args.symbol, result["daily"], result["trades"])
    print_backtest_result(result["stats"], result["trades"])


if __name__ == "__main__":
    main()
