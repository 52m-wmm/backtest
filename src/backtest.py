"""
Simple no-lookahead backtest for A-share listed QDII / NASDAQ ETF premium strategy.

Usage:
    python src\backtest.py --symbol 159509 --buy-premium 0.15 --sell-premium 0.20

Conservative timing model:
    D close: official NAV / premium signal becomes available after close
    D+1 close: execute
    D+2: start earning returns

If you want to model intraday estimated premium instead, set:
    --execution-lag 0
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tabulate import tabulate


PROCESSED_DIR = Path("data/processed")
REPORT_DIR = Path("reports")


@dataclass
class BacktestResult:
    equity: pd.Series
    benchmark: pd.Series
    daily_returns: pd.Series
    trades: pd.DataFrame
    stats: dict


def max_drawdown(equity: pd.Series) -> float:
    roll_max = equity.cummax()
    dd = equity / roll_max - 1
    return float(dd.min())


def annualized_return(equity: pd.Series, trading_days: int = 252) -> float:
    if len(equity) < 2:
        return 0.0
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    years = len(equity) / trading_days
    if years <= 0:
        return 0.0
    return float((1 + total_return) ** (1 / years) - 1)


def sharpe_ratio(daily_returns: pd.Series, trading_days: int = 252) -> float:
    r = daily_returns.dropna()
    if r.std() == 0 or len(r) == 0:
        return 0.0
    return float((r.mean() / r.std()) * np.sqrt(trading_days))


def build_position(
    df: pd.DataFrame,
    buy_premium: float,
    sell_premium: float,
    qqq_ma: int,
    etf_ma: int,
    execution_lag: int,
) -> tuple[pd.Series, pd.DataFrame]:
    """
    Signal is generated on date i. The desired position is applied after close on i + execution_lag + 1.
    For official NAV premium, execution_lag=1 is conservative.
    """
    position = []
    orders = []
    holding = False

    qqq_ma_col = f"qqq_ma{qqq_ma}"
    etf_ma_col = f"etf_ma{etf_ma}"

    for i, row in df.iterrows():
        premium = row["premium"]
        qqq_ok = row["qqq_close"] > row[qqq_ma_col]
        etf_ok = row["close"] > row[etf_ma_col]

        buy_cond = (premium <= buy_premium) and qqq_ok and etf_ok
        sell_cond = (premium >= sell_premium) or (not qqq_ok) or (not etf_ok)

        signal = "HOLD"
        desired_holding = holding

        if not holding and buy_cond:
            desired_holding = True
            signal = "BUY_SIGNAL"
        elif holding and sell_cond:
            desired_holding = False
            signal = "SELL_SIGNAL"

        # 信号不直接当天生效，先记录 desired_holding，后面统一 shift 模拟执行延迟
        position.append(1 if desired_holding else 0)

        if signal != "HOLD":
            orders.append(
                {
                    "signal_date": row["date"],
                    "signal": signal,
                    "close": row["close"],
                    "premium": row["premium"],
                    "qqq_close": row["qqq_close"],
                    "qqq_ma": row[qqq_ma_col],
                    "etf_ma": row[etf_ma_col],
                }
            )

        holding = desired_holding

    raw_desired_position = pd.Series(
        position, index=df.index, name="raw_desired_position"
    )

    # execution_lag=1:
    # D 产生信号，D+1 收盘执行，D+2 的 close-to-close return 才能吃到。
    effective_position_for_return = (
        raw_desired_position.shift(execution_lag + 1).fillna(0).astype(int)
    )
    trades = pd.DataFrame(orders)
    return effective_position_for_return, trades


def run_backtest(
    symbol: str,
    buy_premium: float,
    sell_premium: float,
    qqq_ma: int,
    etf_ma: int,
    execution_lag: int,
    fee_rate: float,
) -> BacktestResult:
    path = PROCESSED_DIR / f"{symbol}_dataset.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run build_dataset.py first.")

    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(
        subset=[
            "close",
            "nav",
            "premium",
            "qqq_close",
            f"qqq_ma{qqq_ma}",
            f"etf_ma{etf_ma}",
        ]
    ).reset_index(drop=True)

    if df.empty:
        raise RuntimeError(
            "Dataset is empty after dropping NA. Try earlier start date or smaller MA windows."
        )

    position, signal_trades = build_position(
        df=df,
        buy_premium=buy_premium,
        sell_premium=sell_premium,
        qqq_ma=qqq_ma,
        etf_ma=etf_ma,
        execution_lag=execution_lag,
    )

    close = df["close"]
    returns = close.pct_change().fillna(0)

    # 手续费按仓位变化扣一次，A股 ETF 这里不考虑印花税
    turnover = position.diff().abs().fillna(position.abs())
    strategy_returns = position * returns - turnover * fee_rate

    equity = (1 + strategy_returns).cumprod()
    benchmark = (1 + returns).cumprod()

    df_out = df.copy()
    df_out["position"] = position
    df_out["strategy_return"] = strategy_returns
    df_out["equity"] = equity
    df_out["benchmark"] = benchmark

    trades = make_executed_trades(df_out, signal_trades, execution_lag)

    stats = {
        "symbol": symbol,
        "start": df_out["date"].min().date().isoformat(),
        "end": df_out["date"].max().date().isoformat(),
        "buy_premium": f"{buy_premium:.2%}",
        "sell_premium": f"{sell_premium:.2%}",
        "execution_lag_days": execution_lag,
        "final_equity": f"{equity.iloc[-1]:.4f}",
        "strategy_total_return": f"{equity.iloc[-1] - 1:.2%}",
        "benchmark_total_return": f"{benchmark.iloc[-1] - 1:.2%}",
        "strategy_ann_return": f"{annualized_return(equity):.2%}",
        "benchmark_ann_return": f"{annualized_return(benchmark):.2%}",
        "strategy_max_drawdown": f"{max_drawdown(equity):.2%}",
        "benchmark_max_drawdown": f"{max_drawdown(benchmark):.2%}",
        "strategy_sharpe": f"{sharpe_ratio(strategy_returns):.2f}",
        "trade_signals": len(signal_trades),
        "days_in_market": int(position.sum()),
        "market_exposure": f"{position.mean():.2%}",
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_csv = REPORT_DIR / f"{symbol}_backtest_daily.csv"
    trades_csv = REPORT_DIR / f"{symbol}_trades.csv"
    chart_png = REPORT_DIR / f"{symbol}_equity.png"

    df_out.to_csv(report_csv, index=False, encoding="utf-8-sig")
    trades.to_csv(trades_csv, index=False, encoding="utf-8-sig")
    plot_equity(df_out, symbol, chart_png)

    print("\n=== Backtest Stats ===")
    print(tabulate(stats.items(), headers=["Metric", "Value"], tablefmt="github"))

    print("\n=== Recent Signals ===")
    if trades.empty:
        print("No signals.")
    else:
        print(trades.tail(10).to_string(index=False))

    print(f"\n[saved] {report_csv}")
    print(f"[saved] {trades_csv}")
    print(f"[saved] {chart_png}")

    return BacktestResult(
        equity=equity,
        benchmark=benchmark,
        daily_returns=strategy_returns,
        trades=trades,
        stats=stats,
    )


def make_executed_trades(
    df: pd.DataFrame, signal_trades: pd.DataFrame, execution_lag: int
) -> pd.DataFrame:
    if signal_trades.empty:
        return signal_trades

    rows = []
    date_to_idx = {d: i for i, d in enumerate(df["date"])}

    for _, sig in signal_trades.iterrows():
        signal_date = pd.to_datetime(sig["signal_date"])
        i = date_to_idx.get(signal_date)
        if i is None:
            continue
        exec_i = i + execution_lag + 1
        if exec_i >= len(df):
            continue

        exec_row = df.iloc[exec_i]
        rows.append(
            {
                **sig.to_dict(),
                "execute_date": exec_row["date"],
                "execute_close": exec_row["close"],
                "execute_premium": exec_row["premium"],
            }
        )

    return pd.DataFrame(rows)


def plot_equity(df: pd.DataFrame, symbol: str, out: Path) -> None:
    plt.figure(figsize=(12, 6))
    plt.plot(df["date"], df["equity"], label="Strategy")
    plt.plot(df["date"], df["benchmark"], label="Buy & Hold")
    plt.title(f"{symbol} Strategy vs Buy & Hold")
    plt.xlabel("Date")
    plt.ylabel("Equity")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--buy-premium", type=float, required=True, help="0.15 means 15 percent"
    )
    parser.add_argument(
        "--sell-premium", type=float, required=True, help="0.20 means 20 percent"
    )
    parser.add_argument("--qqq-ma", type=int, default=20, choices=[20, 60])
    parser.add_argument("--etf-ma", type=int, default=20, choices=[20, 60])
    parser.add_argument(
        "--execution-lag",
        type=int,
        default=1,
        help="1 = official NAV conservative mode; 0 = intraday estimated NAV style",
    )
    parser.add_argument(
        "--fee-rate", type=float, default=0.0002, help="0.0002 = 2 bp per trade"
    )
    args = parser.parse_args()

    run_backtest(
        symbol=args.symbol,
        buy_premium=args.buy_premium,
        sell_premium=args.sell_premium,
        qqq_ma=args.qqq_ma,
        etf_ma=args.etf_ma,
        execution_lag=args.execution_lag,
        fee_rate=args.fee_rate,
    )


if __name__ == "__main__":
    main()
