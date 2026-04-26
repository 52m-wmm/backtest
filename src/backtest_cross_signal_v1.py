"""Cross-ETF signal strategy V1: use 159632 as signal, trade 159509."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
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
    return float((ret.mean() / ret.std()) * (252**0.5))


def run_cross_signal_backtest(
    signal_symbol: str,
    trade_symbol: str,
    start: str,
    end: str | None,
    signal_buy: float = 0.01,
    signal_sell: float = 0.06,
    trade_buy_max: float = 0.15,
    trade_sell: float = 0.20,
    execution_lag: int = 1,
    fee_rate: float = 0.0003,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    signal_path = PROCESSED_DIR / f"{signal_symbol}_dataset.csv"
    trade_path = PROCESSED_DIR / f"{trade_symbol}_dataset.csv"

    if not signal_path.exists():
        raise FileNotFoundError(f"Missing {signal_path}. Run build_dataset.py first.")
    if not trade_path.exists():
        raise FileNotFoundError(f"Missing {trade_path}. Run build_dataset.py first.")

    signal_df = pd.read_csv(signal_path)
    trade_df = pd.read_csv(trade_path)

    signal_df["date"] = pd.to_datetime(signal_df["date"])
    trade_df["date"] = pd.to_datetime(trade_df["date"])

    signal_df = signal_df[["date", "close", "premium"]].copy()
    signal_df.columns = ["date", "signal_close", "signal_premium"]
    signal_df["signal_close"] = pd.to_numeric(signal_df["signal_close"], errors="coerce")
    signal_df["signal_premium"] = pd.to_numeric(signal_df["signal_premium"], errors="coerce")

    trade_df = trade_df[["date", "close", "premium"]].copy()
    trade_df.columns = ["date", "trade_close", "trade_premium"]
    trade_df["trade_close"] = pd.to_numeric(trade_df["trade_close"], errors="coerce")
    trade_df["trade_premium"] = pd.to_numeric(trade_df["trade_premium"], errors="coerce")

    df = pd.merge(signal_df, trade_df, on="date", how="inner")
    df = df.dropna(subset=["date", "signal_close", "signal_premium", "trade_close", "trade_premium"])
    df = df.sort_values("date").reset_index(drop=True)

    if df.empty:
        raise RuntimeError("Merged dataset is empty after cleaning.")

    if start:
        start_ts = pd.to_datetime(start, format="%Y%m%d", errors="raise")
        df = df[df["date"] >= start_ts]
    if end:
        end_ts = pd.to_datetime(end, format="%Y%m%d", errors="raise")
        df = df[df["date"] <= end_ts]

    df = df.reset_index(drop=True)

    df["signal"] = ""
    df["execution"] = ""
    df["position"] = 0.0
    df["cash"] = 1.0
    df["shares"] = 0.0
    df["strategy_equity"] = 1.0
    df["benchmark_equity"] = df["trade_close"] / df["trade_close"].iloc[0]

    cash = 1.0
    shares = 0.0
    pending_order: dict[str, object] | None = None
    trades: list[dict[str, object]] = []

    def execute_order(order: dict[str, object], i: int) -> None:
        nonlocal cash, shares, pending_order

        row = df.iloc[i]
        signal_premium = float(row["signal_premium"])
        trade_premium = float(row["trade_premium"])
        trade_close = float(row["trade_close"])

        side = str(order["side"])

        if side == "BUY":
            if shares == 0 and cash > 0:
                if trade_premium <= trade_buy_max:
                    shares = cash * (1 - fee_rate) / trade_close
                    cash = 0.0
                    df.loc[i, "execution"] = "BUY"
                    trades.append(
                        {
                            "signal_date": order["signal_date"],
                            "signal_close": order["signal_close"],
                            "signal_premium": order["signal_premium"],
                            "execute_date": row["date"].date(),
                            "execute_close": trade_close,
                            "execute_premium": trade_premium,
                            "action": "BUY",
                        }
                    )
                else:
                    pass
            pending_order = None
        elif side == "SELL":
            if shares > 0:
                if signal_premium >= signal_sell or trade_premium >= trade_sell:
                    cash = shares * trade_close * (1 - fee_rate)
                    shares = 0.0
                    df.loc[i, "execution"] = "SELL"
                    trades.append(
                        {
                            "signal_date": order["signal_date"],
                            "signal_close": order["signal_close"],
                            "signal_premium": order["signal_premium"],
                            "execute_date": row["date"].date(),
                            "execute_close": trade_close,
                            "execute_premium": trade_premium,
                            "action": "SELL",
                        }
                    )
                else:
                    pass
            pending_order = None
        else:
            pending_order = None

    for i in range(len(df)):
        row = df.iloc[i]

        if pending_order is not None and int(pending_order["exec_i"]) == i:
            execute_order(pending_order, i)

        signal_premium = float(row["signal_premium"])
        trade_premium = float(row["trade_premium"])
        signal_close = float(row["signal_close"])
        trade_close = float(row["trade_close"])

        if pending_order is None:
            if shares == 0:
                if signal_premium <= signal_buy and trade_premium <= trade_buy_max:
                    exec_i = i + execution_lag
                    df.loc[i, "signal"] = "BUY_SIGNAL"

                    if exec_i < len(df):
                        order = {
                            "side": "BUY",
                            "signal_date": row["date"].date(),
                            "signal_close": signal_close,
                            "signal_premium": signal_premium,
                            "exec_i": exec_i,
                        }

                        if exec_i == i:
                            execute_order(order, i)
                        else:
                            pending_order = order

            elif shares > 0:
                if signal_premium >= signal_sell or trade_premium >= trade_sell:
                    exec_i = i + execution_lag
                    df.loc[i, "signal"] = "SELL_SIGNAL"

                    if exec_i < len(df):
                        order = {
                            "side": "SELL",
                            "signal_date": row["date"].date(),
                            "signal_close": signal_close,
                            "signal_premium": signal_premium,
                            "exec_i": exec_i,
                        }

                        if exec_i == i:
                            execute_order(order, i)
                        else:
                            pending_order = order

        equity = cash + shares * trade_close

        df.loc[i, "cash"] = cash
        df.loc[i, "shares"] = shares
        df.loc[i, "position"] = 1.0 if shares > 0 else 0.0
        df.loc[i, "strategy_equity"] = equity

    trades_df = pd.DataFrame(trades)

    final_equity = float(df["strategy_equity"].iloc[-1])
    benchmark_final = float(df["benchmark_equity"].iloc[-1])
    trading_days = len(df)

    stats = {
        "signal_symbol": signal_symbol,
        "trade_symbol": trade_symbol,
        "start": df["date"].iloc[0].date(),
        "end": df["date"].iloc[-1].date(),
        "strategy_name": "cross_signal_v1",
        "signal_buy": fmt_pct(signal_buy),
        "signal_sell": fmt_pct(signal_sell),
        "trade_buy_max": fmt_pct(trade_buy_max),
        "trade_sell": fmt_pct(trade_sell),
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


def save_reports(signal_symbol: str, trade_symbol: str, df: pd.DataFrame, trades_df: pd.DataFrame) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    equity_path = REPORT_DIR / f"cross_{signal_symbol}_to_{trade_symbol}_equity.csv"
    trades_path = REPORT_DIR / f"cross_{signal_symbol}_to_{trade_symbol}_trades.csv"
    chart_path = REPORT_DIR / f"cross_{signal_symbol}_to_{trade_symbol}_equity.png"

    df.to_csv(equity_path, index=False, encoding="utf-8-sig")
    trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")

    plt.figure(figsize=(12, 6))
    plt.plot(df["date"], df["strategy_equity"], label="Cross Signal V1")
    plt.plot(df["date"], df["benchmark_equity"], label="Buy & Hold")
    plt.title(f"{signal_symbol} -> {trade_symbol} Cross Signal Strategy")
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
    parser.add_argument("--signal-symbol", default="159632")
    parser.add_argument("--trade-symbol", default="159509")
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default=None)
    parser.add_argument("--signal-buy", type=float, default=0.01)
    parser.add_argument("--signal-sell", type=float, default=0.06)
    parser.add_argument("--trade-buy-max", type=float, default=0.15)
    parser.add_argument("--trade-sell", type=float, default=0.20)
    parser.add_argument("--execution-lag", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.0003)
    args = parser.parse_args()

    df, trades_df, stats = run_cross_signal_backtest(
        signal_symbol=args.signal_symbol,
        trade_symbol=args.trade_symbol,
        start=args.start,
        end=args.end,
        signal_buy=args.signal_buy,
        signal_sell=args.signal_sell,
        trade_buy_max=args.trade_buy_max,
        trade_sell=args.trade_sell,
        execution_lag=args.execution_lag,
        fee_rate=args.fee_rate,
    )

    save_reports(args.signal_symbol, args.trade_symbol, df, trades_df)
    print_backtest_result(stats, trades_df)


if __name__ == "__main__":
    main()
