#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hot_search skill handlers —— 纯函数,零框架 import。

数据由 Adapter 经参数注入(hot_rank/market_news),LLM 能力由框架注入的
llm 句柄提供。所有接口异常统一转为 status:error 的中文消息,不裸抛。
"""

import json
import logging

from json_repair import repair_json

from . import market_data, prompts

logger = logging.getLogger(__name__)


def _err(message: str) -> str:
    return json.dumps({"status": "error", "message": message}, ensure_ascii=False)


def _ok(payload: dict) -> str:
    return json.dumps({"status": "success", **payload}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 1:人气榜
# ---------------------------------------------------------------------------

def tool_get_hot_search_rank(top_n: int = 10, llm=None, **kw) -> str:
    """东财人气榜前 N(5~30);落库带时间戳,供热点分析工具消费。"""
    try:
        top_n = max(5, min(int(top_n), 30))
        rows = market_data.get_hot_rank()
    except (ValueError, market_data.AkshareError) as e:
        return _err(str(e))

    top = rows[:top_n]
    return _ok({
        "top": [{k: r.get(k) for k in ("rank", "name", "code", "pct_chg")} for r in top],
        "total": len(rows),
        "ts": market_data._now(),
        "note": "榜单部分股票可能缺少代码(降级数据源仅提供名称)" if any(r.get("code") is None for r in top) else "",
        "_output_data": {"hot_rank": {"rows": rows, "ts": market_data._now()}},
    })


# ---------------------------------------------------------------------------
# 工具 2:市场快讯
# ---------------------------------------------------------------------------

def tool_get_market_news(count: int = 20, llm=None, **kw) -> str:
    """财联社电报最近 N 条(5~50);落库带时间戳,供热点分析工具消费。"""
    try:
        count = max(5, min(int(count), 50))
        items = market_data.get_market_news(limit=count)
    except (ValueError, market_data.AkshareError) as e:
        return _err(str(e))

    latest = items[0] if items else {}
    return _ok({
        "count": len(items),
        "latest_time": f"{latest.get('date', '')} {latest.get('time', '')}".strip(),
        "sample_titles": [i.get("title") for i in items[:5]],
        "ts": market_data._now(),
        "_output_data": {"market_news": {"items": items, "ts": market_data._now()}},
    })


# ---------------------------------------------------------------------------
# 工具 3:热点分析
# ---------------------------------------------------------------------------

def tool_analyze_hot_topics(hot_rank: dict = None, market_news: dict = None,
                            llm=None, **kw) -> str:
    """基于已落库的人气榜与快讯生成热点主题分析(JSON schema → Markdown 落库)。"""
    if not hot_rank or not hot_rank.get("rows"):
        return _err("暂无人气榜数据:请先调用 get_hot_search_rank")
    if not market_news or not market_news.get("items"):
        return _err("暂无市场快讯数据:请先调用 get_market_news")

    try:
        content = llm.complete(
            messages=[{
                "role": "user",
                "content": prompts.build_hot_topics_prompt(
                    hot_rank["rows"], market_news["items"]),
            }],
            temperature=0.3,
            max_tokens=4096,
        )
    except Exception as e:
        return _err(f"LLM 调用失败: {e}")

    try:
        structured = repair_json(content, return_objects=True)
    except Exception as e:
        return _err(f"热点分析输出不是有效 JSON,无法解析: {e}")
    if not isinstance(structured, dict) or not structured:
        return _err("热点分析输出不是有效 JSON,无法解析")
    topics = structured.get("hot_topics") or []
    if not topics or not structured.get("market_summary"):
        return _err("热点分析 JSON 缺少字段: market_summary 或 hot_topics")

    lines = [
        f"# 市场热点分析\n",
        f"**数据时间**: 人气榜 {hot_rank.get('ts', '')} / 快讯 {market_news.get('ts', '')}\n",
        f"## 市场总述\n{structured['market_summary']}\n",
    ]
    for i, t in enumerate(topics, 1):
        lines.append(f"## {i}. {t.get('topic', '')}\n")
        lines.append(f"- **热度证据**: {t.get('heat_evidence', '')}")
        lines.append(f"- **相关板块**: {'、'.join(t.get('related_sectors', [])) or '—'}")
        lines.append(f"- **受益类型**: {'、'.join(t.get('beneficiary_types', [])) or '—'}")
        lines.append(f"- **机会**: {t.get('opportunity', '')}")
        lines.append(f"- **风险**: {t.get('risk', '')}\n")
    lines.append("> 数据来源:AkShare 公开接口(东方财富人气榜/财联社电报)。本报告由 AI 生成,仅供参考,不构成投资建议。\n")
    report_md = "\n".join(lines)

    return _ok({
        "topics": [{"topic": t.get("topic"), "related_sectors": t.get("related_sectors")}
                   for t in topics[:5]],
        "summary": structured["market_summary"],
        "report_len": len(report_md),
        "_output_data": {
            "hot_analysis": {
                "ts": market_data._now(),
                "report_md": report_md,
                "structured": structured,
            },
        },
    })
