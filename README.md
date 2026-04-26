# ETF Premium Backtest CLI

一个纯 Python 的 ETF 溢价回测项目，统一入口是 `src/run.py`。

项目不依赖 `Tushare`，也不需要 `.env` 或 token。

## 安装

推荐 Python 3.11+。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

Windows PowerShell 可改为：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

## 统一运行入口

```bash
python src/run.py --symbol 159632 --buy 0.01 --sell 0.03 --start 20230101
```

参数说明：

- `--symbol`：ETF 代码，例如 `159632` / `159509` / `513100`
- `--buy`：买入溢价阈值，例如 `0.01` 表示 1%
- `--sell`：卖出溢价阈值，例如 `0.03` 表示 3%
- `--start`：开始日期，默认 `20230101`
- `--end`：结束日期，默认今天
- `--refresh`：强制重新抓取数据
- `--no-fetch`：跳过抓取，直接使用本地 CSV
- `--execution-lag`：执行延迟交易日，默认 `1`
- `--fee-rate`：手续费率，默认 `0.0003`

## 示例命令

```bash
python src/run.py --symbol 159632 --buy 0.01 --sell 0.03 --start 20230101
python src/run.py --symbol 159509 --buy 0.15 --sell 0.20 --start 20230101
python src/run.py --symbol 159632 --buy 0.01 --sell 0.03 --start 20230101 --no-fetch
```

## 输出文件

- `data/raw/{symbol}_price.csv`
- `data/raw/{symbol}_nav.csv`
- `data/processed/{symbol}_dataset.csv`
- `reports/{symbol}_premium_v1_daily.csv`
- `reports/{symbol}_premium_v1_trades.csv`
- `reports/{symbol}_premium_v1_equity.png`

## 策略规则（Premium V1）

- 空仓且 `premium <= buy`：次一交易日买入（默认 `execution_lag=1`）
- 持仓且 `premium >= sell`：次一交易日卖出
- 其他情况维持原仓位

其中：`premium = close / nav - 1`。

## 数据源与缓存

价格抓取优先级：

1. `akshare.fund_etf_hist_em`
2. `efinance.stock.get_quote_history`
3. `akshare.stock_zh_a_hist_tx`（Tencent 源）

净值抓取：`akshare.fund_etf_fund_info_em`。

默认有缓存：如果 `data/raw/{symbol}_price.csv` 与 `data/raw/{symbol}_nav.csv` 已存在且未指定 `--refresh`，会直接复用。
