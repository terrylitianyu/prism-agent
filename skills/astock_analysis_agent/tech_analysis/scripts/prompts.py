#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tech_analysis skill 的 LLM prompt 模板(零框架依赖)。"""


def build_tech_report_prompt(symbol: str, name: str, indicators: dict,
                             sector: dict = None, chart_path: str = "") -> str:
    """构造技术分析报告 prompt,要求只输出固定 schema 的 JSON。

    只喂入派生指标摘要(非原始行情),并明确禁止编造未提供的数据。
    """
    sector_text = ""
    if sector:
        sector_text = (
            f"- 所属行业: {sector.get('industry', '未知')}\n"
            f"- 行业指数近5日涨跌幅: {sector.get('pct_5d')}%\n"
            f"- 行业指数近20日涨跌幅: {sector.get('pct_20d')}%\n"
        )
    chart_text = f"- 已生成K线图: {chart_path}\n" if chart_path else ""

    return f"""你是A股技术分析师。请基于以下数据(全部来自 AkShare 公开行情)对 {name}({symbol}) 做技术分析。

【最新指标】
- 日期: {indicators.get('date')}
- 最新收盘价: {indicators.get('close')}
- 当日涨跌幅: {indicators.get('pct_chg_latest')}%
- MA5: {indicators.get('ma5')}
- MA20: {indicators.get('ma20')}
- MA5是否在MA20上方: {indicators.get('ma5_gt_ma20')}
- 近5日涨跌幅: {indicators.get('pct_5d')}%
- 近20日涨跌幅: {indicators.get('pct_20d')}%
- 最近5日收盘: {indicators.get('recent_closes')}
- 最近5日成交量: {indicators.get('recent_volumes')}
{sector_text}
{chart_text}
【要求】
1. 只基于以上提供的数据分析,**不得编造任何未提供的数据**(如其他技术指标、消息面)。
2. 只输出一个 JSON 对象,不要任何其他文字,不要 markdown 代码块围栏。字段(全中文内容):
   {{
     "title": "报告标题",
     "summary": "3句话以内的结论概述",
     "trend": "趋势判断(结合价格与MA5/MA20位置关系)",
     "support_resistance": "基于近期高低点的支撑位与压力位判断",
     "signal": "技术信号(偏多/偏空/中性,并说明依据)",
     "risk": "主要风险提示"
   }}
3. 数据不充分时(如均线为 null)如实说明,不要猜测。
"""
