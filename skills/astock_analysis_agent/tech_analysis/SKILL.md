---
name: tech_analysis
description: A股单股技术分析：历史行情（自动附MA5/MA20）+ 实时行情 + 行业趋势 + K线图 + 技术分析报告
---

# Tech Analysis Skill（单股技术分析）

## Capabilities

| Tool | Description |
|------|-------------|
| get_stock_history | 前复权历史日K（默认近一年），自动附 MA5/MA20；已落库数据自动复用 |
| get_stock_realtime | 实时快照（最新价/涨跌幅/估值等，含数据源与时间戳） |
| get_sector_trend | 所属行业 + 行业指数 1d/5d/20d 涨跌幅 |
| plot_kline_chart | 用已获取的行情画 K线图（含 MA5/MA20、成交量），存 PNG |
| generate_tech_report | 生成结构化技术分析报告（Markdown 全文落库） |

## 推荐调用流程（单股深研）

1. 调用 get_stock_history（需提供股票代码）—— 一切分析的前提；可选参数 start_date/end_date（YYYY-MM-DD 或 YYYYMMDD），缺省最近一年。返回最新收盘、MA5/MA20、近5日收盘/成交量等紧凑摘要。
2. 调用 get_stock_realtime —— 补充最新盘中快照；股票代码可省略。
3. 调用 get_sector_trend —— 行业归属与行业指数涨跌，判断个股相对行业强弱；股票代码可省略。
4. 调用 plot_kline_chart —— 生成K线图 PNG。用户明确要求图表时执行。
5. 调用 generate_tech_report —— 生成技术分析报告。

## 参数与数据约定

- `symbol` 支持 `000001` / `000001.SZ` / `SZ000001` / `sh600519` 等写法；600/601/603/688 开头为沪市，000/002/300 为深市，4/8 开头为北交所（数据源可能不支持，报错时如实转达）。
- **缓存与复用**：同一股票同一日期范围的历史行情已落库，重复调用会自动复用（返回 `from_cache: true`），不要重复抓取。实时行情**不落库**，每次调用都是当时值。
- **数据时效**：历史行情以最新交易日为准；非交易日实时快照显示上一交易日数据。取数可能较慢（全市场快照 20~70 秒），失败会自动重试并降级到备用数据源，仍失败会给中文错误，直接转达用户即可。
- **行业降级**：行业指数涨跌幅可能不可用（`note` 字段会说明），此时报告仅基于个股行情，不要编造行业数据。

## 输出说明

- `get_stock_history` 的行情全文与 `generate_tech_report` 的报告全文都会落库，多轮对话可直接复用，不必重复生成。
- `plot_kline_chart` 的图片路径落库，报告与最终回复中引用该路径。
- 各工具返回的紧凑摘要用于编排与回复；给用户的最终结论应基于 `generate_tech_report` 的报告内容组织。
