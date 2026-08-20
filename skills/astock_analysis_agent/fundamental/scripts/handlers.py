#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fundamental skill handlers —— 纯函数,零框架 import。

数据由 Adapter 经参数注入(current_symbol/stock_valuation/stock_financials),
LLM 能力由框架注入的 llm 句柄提供。
所有接口异常统一转为 status:error 的中文消息,不裸抛。
"""

import json
import logging

from json_repair import repair_json

from . import market_data, prompts

logger = logging.getLogger(__name__)

REQUIRED_REPORT_FIELDS = ("valuation_assessment", "growth_quality", "balance_sheet", "conclusion")


def _err(message: str) -> str:
    return json.dumps({"status": "error", "message": message}, ensure_ascii=False)


def _ok(payload: dict) -> str:
    return json.dumps({"status": "success", **payload}, ensure_ascii=False)


def _resolve_symbol(symbol: str, current_symbol: str = "") -> str:
    """LLM 传的 symbol 优先,缺省回落到当前会话股票;再没有则抛 ValueError。"""
    if symbol:
        return symbol
    if current_symbol:
        return current_symbol
    raise ValueError("未指定股票代码:请提供 6 位代码(如 600519),或先分析某只股票")


# ---------------------------------------------------------------------------
# 工具 1:估值快照
# ---------------------------------------------------------------------------

def tool_get_valuation(symbol: str = "", current_symbol: str = "", llm=None, **kw) -> str:
    """估值快照(PE/PB/PS/PEG/市值);落库供报告工具消费。"""
    try:
        symbol = _resolve_symbol(symbol, current_symbol)
        v = market_data.get_valuation(symbol)
    except (ValueError, market_data.AkshareError) as e:
        return _err(str(e))

    return _ok({
        "symbol": v.get("symbol"),
        "name": v.get("name"),
        "date": v.get("date"),
        "pe_ttm": v.get("pe_ttm"),
        "pe_static": v.get("pe_static"),
        "pb": v.get("pb"),
        "ps": v.get("ps"),
        "total_mv": v.get("total_mv"),
        "source": v.get("source"),
        "_output_data": {"stock_valuation": v},
    })


# ---------------------------------------------------------------------------
# 工具 2:财务指标
# ---------------------------------------------------------------------------

def tool_get_financials(symbol: str = "", current_symbol: str = "", llm=None, **kw) -> str:
    """近两年核心财务指标(季度);落库供报告工具消费。"""
    try:
        symbol = _resolve_symbol(symbol, current_symbol)
        f = market_data.get_financials(symbol)
    except (ValueError, market_data.AkshareError) as e:
        return _err(str(e))

    recent = f["periods"][-4:]  # 最近4个季度
    return _ok({
        "symbol": f.get("symbol"),
        "name": f.get("name"),
        "periods": [
            {"date": p.get("date"), "roe": p.get("roe"),
             "revenue_growth": p.get("revenue_growth"),
             "profit_growth": p.get("profit_growth"),
             "debt_ratio": p.get("debt_ratio")}
            for p in recent
        ],
        "period_count": len(f["periods"]),
        "source": f.get("source"),
        "_output_data": {"stock_financials": f},
    })


# ---------------------------------------------------------------------------
# 工具 3:基本面报告
# ---------------------------------------------------------------------------

def tool_generate_fundamental_report(stock_valuation: dict = None,
                                     stock_financials: dict = None,
                                     llm=None, **kw) -> str:
    """基于已落库的估值与财务数据生成基本面分析报告(Markdown 落库)。"""
    if not stock_valuation:
        return _err("暂无估值数据:请先调用 get_valuation")
    if not stock_financials or not stock_financials.get("periods"):
        return _err("暂无财务数据:请先调用 get_financials")

    symbol = stock_valuation.get("symbol") or stock_financials.get("symbol", "")
    name = stock_valuation.get("name") or stock_financials.get("name", "")

    try:
        content = llm.complete(
            messages=[{
                "role": "user",
                "content": prompts.build_fundamental_report_prompt(
                    symbol, name, stock_valuation, stock_financials),
            }],
            temperature=0.3,
            max_tokens=4096,
        )
    except Exception as e:
        return _err(f"LLM 调用失败: {e}")

    try:
        structured = repair_json(content, return_objects=True)
    except Exception as e:
        return _err(f"报告输出不是有效 JSON,无法解析: {e}")
    if not isinstance(structured, dict) or not structured:
        return _err("报告输出不是有效 JSON,无法解析")
    missing = [f for f in REQUIRED_REPORT_FIELDS if not structured.get(f)]
    if missing:
        return _err(f"报告 JSON 缺少字段: {', '.join(missing)}")

    report_md = (
        f"# {name}({symbol}) 基本面分析\n\n"
        f"**估值日期**: {stock_valuation.get('date') or '—'}  |  "
        f"PE(TTM) {stock_valuation.get('pe_ttm', '—')} / PB {stock_valuation.get('pb', '—')}\n\n"
        f"## 估值评估\n{structured['valuation_assessment']}\n\n"
        f"## 成长性与盈利质量\n{structured['growth_quality']}\n\n"
        f"## 资产负债状况\n{structured['balance_sheet']}\n\n"
        f"## 结论\n{structured['conclusion']}\n\n"
        "> 数据来源:AkShare 公开接口(东方财富)。本报告由 AI 生成,仅供参考,不构成投资建议。\n"
    )

    return _ok({
        "report_len": len(report_md),
        "summary": structured["conclusion"],
        "_output_data": {
            "fundamental_report": {
                "symbol": symbol,
                "name": name,
                "date": stock_valuation.get("date"),
                "report_md": report_md,
                "structured": structured,
            },
        },
    })
