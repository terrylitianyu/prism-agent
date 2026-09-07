---
name: fundamental
description: A股基本面财务分析：估值快照 + 近两年财务指标 + 基本面分析报告
---

# Fundamental Skill（基本面财务分析）

## Capabilities

| Tool | Description |
|------|-------------|
| get_valuation | 估值快照：PE(TTM)/PE(静)/PB/PS/PEG/总市值/流通市值 |
| get_financials | 近两年季度财务指标：EPS/ROE/营收增速/净利增速/负债率/毛利率 |
| generate_fundamental_report | 生成基本面分析报告（估值评估/成长性/资产负债/结论） |

## 推荐调用流程（基本面深研）

1. 调用 get_valuation —— 估值快照；股票代码可省略。
2. 调用 get_financials —— 近两年财务指标；股票代码可省略。
3. 调用 generate_fundamental_report —— 生成报告（使用已落库的估值与财务数据）。

## 参数与数据约定

- `symbol` 支持 `000001` / `000001.SZ` / `SZ000001` 等写法；没有当前股票时报错（会提示先提供代码）。
- **缓存与复用**：估值与财务数据落库后，同轮对话内重复调用自动复用（TTL 缓存）；财报数据按季度更新，同一季度内数据不变。
- **数据时效**：财务指标为最近披露的报告期数据，部分最新季度字段可能为 null（未披露），报告会如实注明，不要编造。
- 估值接口返回的是历史序列的最新一行（含估值日期），非交易日为最近交易日数据。

## 输出说明

- 估值/财务/报告全文都落库，多轮对话可直接复用。
- `generate_fundamental_report` 返回的结论摘要用于编排与回复；给用户的最终结论应基于其报告全文组织。
- 用户同时关心技术面与基本面时，先跑本 skill，再把结论与 tech_analysis 的结论合并输出。
