# ETF Premium Backtest Starter

这是一个本地轻量回测系统，适合先验证：

- 159509 / 159632 / 513100 这类 A 股场内 QDII / 纳指 ETF
- 溢价择时
- QQQ 趋势过滤
- ETF 自身 MA 过滤

> 重要：这不是投资建议，只是策略研究工具。第一版使用官方历史净值计算溢价，实盘还需要结合实时估算净值、成交量、限购、汇率、申赎状态等因素。

## Windows + VSCode 启动

推荐 Python 3.11 或 3.12。

```powershell
cd 你的项目目录
py -3.11 -m venv .venv

# 如果 PowerShell 不让激活，先执行这一句：
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

## 跑 159509 示例

```powershell
python src\fetch_data.py --symbol 159509 --start 20230101
python src\build_dataset.py --symbol 159509
python src\backtest.py --symbol 159509 --buy-premium 0.15 --sell-premium 0.20
```

输出文件：

```text
data/raw/
data/processed/
reports/
```

## 跑 159632 示例

```powershell
python src\fetch_data.py --symbol 159632 --start 20230101
python src\build_dataset.py --symbol 159632
python src\backtest.py --symbol 159632 --buy-premium 0.02 --sell-premium 0.05
```

## 策略逻辑

默认策略：

买入条件：

```text
溢价 <= buy_premium
QQQ 收盘价 > QQQ MA20
ETF 收盘价 > ETF MA20
```

卖出条件：

```text
溢价 >= sell_premium
或 QQQ 跌破 MA20
或 ETF 跌破 MA20
```

因为官方基金净值通常不是盘中实时可用，本回测默认使用保守模式：

```text
D 日收盘后得到信号
D+1 收盘执行
D+2 开始吃到收益
```

这个比真实“看实时估值盘中操作”更保守，但可以避免偷看未来。

## 下一步可以加

- 参数扫描：批量测试 buy_premium / sell_premium / MA 窗口
- 159509 vs 159632 vs 513100 对比
- 使用实时估算净值做更接近实盘的模型
- Streamlit 看板
- 因子衰减监控：滚动观察因子的收益、Sharpe、回撤与信号有效性，识别因子生命周期和策略失效风险

## 历史回测结果（历史记录，未经重新复现）

以下三组指标整理自此前保存的历史回测记录，**本次仅补充 README，未重新运行回测或复核原始数据与交易明细**。这些数值不是实盘收益，也不代表未来表现。

| 策略 | 累计收益率 | 年化收益率 | 夏普比率（Sharpe） | 最大回撤（MDD） |
| --- | ---: | ---: | ---: | ---: |
| 159509 溢价策略 | +120.64% | 35.59% | 1.16 | -32.09% |
| 159632 溢价策略 | +188.65% | 39.70% | 1.82 | -20.12% |
| 交叉信号策略（159632 产生信号 → 159509 执行交易） | +176.02% | 47.79% | 1.49 | -25.37% |

**说明与限制：**

- 表中数据为历史研究记录的摘要；本次没有重新复现，也没有验证它们是否能由当前仓库版本及 README 中的示例命令直接重现。
- 三组回测的具体起止日期、参数、交易成本及数据版本未在此核实；不应据此认定三组结果具备严格可比性。
- 年化收益率、夏普比率和最大回撤均为此前记录的数值，未经本次独立计算或审计。
- 这些结果仅用于展示策略研究过程，不应视为样本外验证、实盘业绩或未来收益保证。
