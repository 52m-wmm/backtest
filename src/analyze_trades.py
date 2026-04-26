"""Trade analysis and review tool for ETF backtest strategies."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd


PROCESSED_DIR = Path("data/processed")
REPORT_DIR = Path("reports")
OUTPUT_DIR = Path("reports/trade_reviews")


def load_dataset(symbol: str) -> pd.DataFrame:
    dataset_path = PROCESSED_DIR / f"{symbol}_dataset.csv"
    if not dataset_path.exists():
        raise FileNotFoundError(f"Missing {dataset_path}. Run build_dataset.py first.")
    df = pd.read_csv(dataset_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def load_trades(trades_file: str | None, symbol: str) -> pd.DataFrame:
    if trades_file and Path(trades_file).exists():
        trades_df = pd.read_csv(trades_file)
    else:
        possible_paths = [
            REPORT_DIR / f"premium_{symbol}_trades.csv",
            REPORT_DIR / f"ladder_v2_{symbol}_trades.csv",
            REPORT_DIR / f"ladder_v3_{symbol}_trades.csv",
            REPORT_DIR / f"ladder_v4_{symbol}_trades.csv",
        ]
        trades_df = None
        for path in possible_paths:
            if path.exists():
                trades_df = pd.read_csv(path)
                break
        if trades_df is None:
            raise FileNotFoundError(f"No trades file found for {symbol}. Specify --trades-file.")
    return trades_df


def normalize_trades_columns(trades_df: pd.DataFrame) -> pd.DataFrame:
    df = trades_df.copy()

    col_map = {}
    for col in df.columns:
        col_lower = col.lower()
        if "signal_date" in col_lower:
            if "signal_date" not in col_map:
                col_map[col] = "signal_date"
        elif "execute_date" in col_lower:
            if "execute_date" not in col_map:
                col_map[col] = "execute_date"
        elif "action" in col_lower:
            if "action" not in col_map:
                col_map[col] = "action"
        elif "execute_close" in col_lower:
            if "execute_close" not in col_map:
                col_map[col] = "execute_close"
        elif "execute_premium" in col_lower:
            if "execute_premium" not in col_map:
                col_map[col] = "execute_premium"
        elif col_lower == "signal" and "date" not in col_lower:
            if "action" not in col_map:
                col_map[col] = "action"
        elif col_lower == "price":
            if "execute_close" not in col_map:
                col_map[col] = "execute_close"
        elif col_lower == "premium":
            if "execute_premium" not in col_map:
                col_map[col] = "execute_premium"
        elif col_lower == "date":
            if "execute_date" not in col_map:
                col_map[col] = "execute_date"

    df = df.rename(columns=col_map)

    if "signal_date" not in df.columns and "execute_date" in df.columns:
        df["signal_date"] = df["execute_date"]
    if "execute_date" not in df.columns and "signal_date" in df.columns:
        df["execute_date"] = df["signal_date"]

    if "action" not in df.columns and "signal" in df.columns:
        df["action"] = df["signal"]

    if "execute_close" not in df.columns and "close" in df.columns:
        df["execute_close"] = df["close"]
    if "execute_premium" not in df.columns and "premium" in df.columns:
        df["execute_premium"] = df["premium"]

    if "action" in df.columns:
        df["action"] = df["action"].str.replace("BUY_SIGNAL", "BUY").str.replace("SELL_SIGNAL", "SELL")

    return df


def calculate_forward_returns(
    dataset_df: pd.DataFrame, execute_date: pd.Timestamp, execute_close: float, window: int = 20
) -> dict[str, float]:
    dataset_df = dataset_df.copy()
    dataset_df["date"] = pd.to_datetime(dataset_df["date"])
    execute_idx = dataset_df[dataset_df["date"] == execute_date].index
    if len(execute_idx) == 0:
        return {
            "forward_5d_return": None,
            "forward_10d_return": None,
            "forward_20d_return": None,
            "max_gain_20d": None,
            "max_drawdown_20d": None,
        }

    execute_idx = execute_idx[0]

    forward_5d_idx = execute_idx + 5
    forward_10d_idx = execute_idx + 10
    forward_20d_idx = execute_idx + 20

    forward_5d_return = None
    forward_10d_return = None
    forward_20d_return = None
    max_gain_20d = None
    max_drawdown_20d = None

    if forward_5d_idx < len(dataset_df):
        forward_5d_close = float(dataset_df.iloc[forward_5d_idx]["close"])
        forward_5d_return = forward_5d_close / execute_close - 1

    if forward_10d_idx < len(dataset_df):
        forward_10d_close = float(dataset_df.iloc[forward_10d_idx]["close"])
        forward_10d_return = forward_10d_close / execute_close - 1

    if forward_20d_idx < len(dataset_df):
        forward_20d_close = float(dataset_df.iloc[forward_20d_idx]["close"])
        forward_20d_return = forward_20d_close / execute_close - 1

    if forward_20d_idx < len(dataset_df):
        window_df = dataset_df.iloc[execute_idx : forward_20d_idx + 1]
        if "high" in window_df.columns:
            max_price = window_df["high"].max()
            min_price = window_df["low"].min()
        else:
            max_price = window_df["close"].max()
            min_price = window_df["close"].min()
        max_gain_20d = max_price / execute_close - 1
        max_drawdown_20d = min_price / execute_close - 1

    return {
        "forward_5d_return": forward_5d_return,
        "forward_10d_return": forward_10d_return,
        "forward_20d_return": forward_20d_return,
        "max_gain_20d": max_gain_20d,
        "max_drawdown_20d": max_drawdown_20d,
    }


def plot_trade(
    dataset_df: pd.DataFrame,
    execute_date: pd.Timestamp,
    action: str,
    output_path: Path,
    window: int = 40,
) -> None:
    dataset_df = dataset_df.copy()
    dataset_df["date"] = pd.to_datetime(dataset_df["date"])
    execute_idx = dataset_df[dataset_df["date"] == execute_date].index
    if len(execute_idx) == 0:
        return
    execute_idx = execute_idx[0]

    start_idx = max(0, execute_idx - window)
    end_idx = min(len(dataset_df), execute_idx + window + 1)

    plot_df = dataset_df.iloc[start_idx:end_idx].copy()

    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 1, height_ratios=[3, 1, 1], hspace=0.3)

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    ax3 = fig.add_subplot(gs[2])

    if "high" in plot_df.columns and "low" in plot_df.columns:
        for i, row in plot_df.iterrows():
            color = "red" if row["close"] >= row["open"] else "green"
            body_height = abs(row["close"] - row["open"])
            lower = min(row["open"], row["close"])
            upper = max(row["open"], row["close"])
            ax1.plot([i, i], [row["low"], row["high"]], color="black", linewidth=0.5)
            ax1.bar(i, body_height, bottom=lower, color=color, width=0.6, edgecolor="black", linewidth=0.5)
    else:
        ax1.plot(range(len(plot_df)), plot_df["close"], color="blue", linewidth=1, label="Close")

    if "etf_ma20" in plot_df.columns:
        ax1.plot(range(len(plot_df)), plot_df["etf_ma20"], color="orange", linewidth=1, label="MA20")
    if "etf_ma60" in plot_df.columns:
        ax1.plot(range(len(plot_df)), plot_df["etf_ma60"], color="purple", linewidth=1, label="MA60")

    exec_rel_idx = execute_idx - start_idx
    ax1.axvline(x=exec_rel_idx, color="red" if action == "BUY" else "green", linestyle="--", linewidth=2, label=f"{action} Execution")
    ax1.set_title(f"{action} Trade Execution", fontsize=12)
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)

    if "premium" in plot_df.columns:
        ax2.plot(range(len(plot_df)), plot_df["premium"], color="purple", linewidth=1)
        ax2.axhline(y=0, color="black", linestyle="-", linewidth=0.5)
        ax2.axvline(x=exec_rel_idx, color="red" if action == "BUY" else "green", linestyle="--", linewidth=2)
        ax2.set_title("Premium", fontsize=10)
        ax2.grid(True, alpha=0.3)

    if "volume" in plot_df.columns:
        ax3.bar(range(len(plot_df)), plot_df["volume"], color="gray", alpha=0.6)
        ax3.axvline(x=exec_rel_idx, color="red" if action == "BUY" else "green", linestyle="--", linewidth=2)
        ax3.set_title("Volume", fontsize=10)
        ax3.grid(True, alpha=0.3)

    xticks = range(0, len(plot_df), max(1, len(plot_df) // 10))
    xlabels = [plot_df.iloc[i]["date"].strftime("%Y-%m-%d") if i < len(plot_df) else "" for i in xticks]
    ax1.set_xticks(xticks)
    ax1.set_xticklabels(xlabels, rotation=45)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, help="ETF symbol")
    parser.add_argument("--trades-file", help="Path to trades CSV file")
    parser.add_argument("--window", type=int, default=40, help="Trading days window before/after")
    parser.add_argument("--output-dir", default="reports/trade_reviews", help="Output directory")
    args = parser.parse_args()

    dataset_df = load_dataset(args.symbol)
    trades_df = load_trades(args.trades_file, args.symbol)
    trades_df = normalize_trades_columns(trades_df)

    trades_df["execute_date"] = pd.to_datetime(trades_df["execute_date"])

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []

    for idx, trade in trades_df.iterrows():
        trade_index = idx
        action = str(trade.get("action", "")).upper()
        signal_date = trade.get("signal_date")
        execute_date = trade.get("execute_date")
        execute_price = trade.get("execute_close")
        execute_premium = trade.get("execute_premium")

        if pd.isna(execute_date):
            continue

        execute_date_ts = pd.to_datetime(execute_date)
        execute_price_float = float(execute_price) if pd.notna(execute_price) else None
        execute_premium_float = float(execute_premium) if pd.notna(execute_premium) else None

        dataset_row = dataset_df[dataset_df["date"] == execute_date_ts]
        if len(dataset_row) == 0:
            continue

        dataset_row = dataset_row.iloc[0]

        forward_returns = calculate_forward_returns(
            dataset_df, execute_date_ts, execute_price_float, args.window
        )

        summary_row = {
            "trade_index": trade_index,
            "action": action,
            "signal_date": signal_date,
            "execute_date": execute_date,
            "execute_price": execute_price_float,
            "execute_premium": execute_premium_float,
            "close": float(dataset_row.get("close")),
            "nav": float(dataset_row.get("nav")) if pd.notna(dataset_row.get("nav")) else None,
            "premium": float(dataset_row.get("premium")),
            "etf_ma20": float(dataset_row.get("etf_ma20")) if pd.notna(dataset_row.get("etf_ma20")) else None,
            "etf_ma60": float(dataset_row.get("etf_ma60")) if pd.notna(dataset_row.get("etf_ma60")) else None,
            "volume": float(dataset_row.get("volume")) if pd.notna(dataset_row.get("volume")) else None,
            "pct_chg": float(dataset_row.get("pct_chg")) if pd.notna(dataset_row.get("pct_chg")) else None,
            **forward_returns,
        }
        summary_rows.append(summary_row)

        date_str = execute_date_ts.strftime("%Y%m%d")
        chart_path = output_dir / f"{args.symbol}_{trade_index}_{action}_{date_str}.png"
        plot_trade(dataset_df, execute_date_ts, action, chart_path, args.window)
        print(f"[saved] {chart_path}")

    summary_df = pd.DataFrame(summary_rows)
    summary_path = output_dir / f"{args.symbol}_trade_context.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"[saved] {summary_path}")

    print(f"\n[done] Analyzed {len(summary_rows)} trades.")


if __name__ == "__main__":
    main()
