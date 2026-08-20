#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hot_search skill 的 LLM prompt 模板(零框架依赖)。"""

import json


def build_hot_topics_prompt(rank_rows, news_items) -> str:
    """构造热点分析 prompt,要求只输出固定 schema 的 JSON。

    只喂入截断后的榜单与快讯,并明确禁止编造未提供的数据。
    """
    rank_text = json.dumps(rank_rows[:15], ensure_ascii=False, indent=1)
    news_text = json.dumps(news_items[:20], ensure_ascii=False, indent=1)

    return f"""你是A股市场热点分析师。请基于以下数据(全部来自 AkShare 公开接口)分析当前市场热点。

【个股人气榜(前15)】
{rank_text}

【市场快讯(财联社电报,最新20条)】
{news_text}

【要求】
1. 只基于以上提供的数据分析,**不得编造任何未提供的数据**(如具体股价走势、成交量)。
2. 只输出一个 JSON 对象,不要任何其他文字,不要 markdown 代码块围栏。字段(全中文内容):
   {{
     "market_summary": "对当前市场情绪的一句话总述",
     "hot_topics": [
       {{
         "topic": "热点主题名",
         "heat_evidence": "从榜单/快讯中找到的热度证据",
         "related_sectors": ["相关行业/概念板块"],
         "beneficiary_types": ["受益的股票类型/公司类型"],
         "opportunity": "潜在机会点",
         "risk": "相关风险提示"
       }}
     ]
   }}
3. hot_topics 给 3~5 个主题,按热度排序;数据不足以支撑的主题不要硬凑。
"""
