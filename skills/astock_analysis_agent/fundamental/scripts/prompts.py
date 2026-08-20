#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fundamental skill 的 LLM prompt 模板(零框架依赖)。"""

import json


def build_fundamental_report_prompt(symbol: str, name: str, valuation: dict,
                                    financials: dict) -> str:
    """构造基本面分析报告 prompt,要求只输出固定 schema 的 JSON。

    只喂入估值快照与近两年财务指标,并明确禁止编造未提供的数据。
    """
    val_text = json.dumps({k: valuation.get(k) for k in (
        "date", "price", "pct_chg", "pe_ttm", "pe_static", "pb", "ps", "peg",
        "total_mv", "float_mv")}, ensure_ascii=False, indent=1)
    fin_text = json.dumps(financials.get("periods", []), ensure_ascii=False, indent=1)

    return f"""你是A股基本面分析师。请基于以下数据(全部来自 AkShare 公开接口)对 {name}({symbol}) 做基本面分析。

【估值快照】
{val_text}

【近两年财务指标(按季度,部分字段可能为 null,如实说明)】
{fin_text}

【要求】
1. 只基于以上提供的数据分析,**不得编造任何未提供的数据**(如未提供的行业对比、机构预测)。
2. 只输出一个 JSON 对象,不要任何其他文字,不要 markdown 代码块围栏。字段(全中文内容):
   {{
     "valuation_assessment": "估值水平评估(结合PE/PB/PS的绝对水平与历史变化)",
     "growth_quality": "成长性与盈利质量(营收/净利增速、毛利率、ROE的变化趋势)",
     "balance_sheet": "资产负债状况(负债率水平与变化)",
     "conclusion": "基本面结论(3句话以内,含主要亮点与关注点)"
   }}
3. 数据为 null 的指标不要编造,报告中注明该数据缺失。
"""
