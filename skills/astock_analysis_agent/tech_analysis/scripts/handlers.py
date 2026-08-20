#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tech_analysis skill handlers —— 纯函数,零框架 import。

数据由 Adapter 经参数注入(current_symbol/cached_history/stock_history/
stock_sector/chart_path),LLM 能力由框架注入的 llm 句柄提供。
所有接口异常统一转为 status:error 的中文消息,不裸抛。
"""

import json
import logging

from json_repair import repair_json

from . import charts, indicators, market_data, prompts
from .symbols import normalize_symbol

logger = logging.getLogger(__name__)

REQUIRED_REPORT_FIELDS = ("title", "summary", "trend", "support_resistance", "signal", "risk")


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
    raise ValueError("未指定股票代码:请提供 6 位代码(如 600519),或先调用 get_stock_history 设置当前股票")


# ---------------------------------------------------------------------------
# 工具 1:历史行情(自动附 MA5/MA20;命中已落库缓存时跳过抓取)
# ---------------------------------------------------------------------------

def tool_get_stock_history(symbol: str = "", start_date: str = "",
                           end_date: str = "", current_symbol: str = "",
                           cached_history: dict = None, llm=None, **kw) -> str:
    """拉取前复权日K并附 MA5/MA20;同 symbol 且日期范围被缓存覆盖时直接复用。"""
    try:
        symbol = _resolve_symbol(symbol, current_symbol)
        full_symbol, exchange = normalize_symbol(symbol)
        start_ymd, end_ymd = market_data.resolve_range(start_date, end_date)
    except ValueError as e:
        return _err(str(e))

    name, source, from_cache = "", "", False
    rows = []

    cached = cached_history or {}
    if (cached.get("symbol") == full_symbol
            and str(cached.get("start", "99999999")) <= start_ymd
            and str(cached.get("end", "00000000")) >= end_ymd):
        # 缓存覆盖:按请求区间过滤后重算均线(最新均线值与全量计算一致)
        rows = [r for r in cached.get("rows", [])
                if start_ymd <= str(r.get("date", "")).replace("-", "") <= end_ymd]
        name, source, from_cache = cached.get("name", ""), "cache", True
        logger.info("history 缓存命中: %s [%s~%s]", full_symbol, start_ymd, end_ymd)

    if not rows:
        try:
            hist = market_data.get_stock_history(full_symbol, start_date, end_date)
            rows, name, source = hist["rows"], hist.get("name", ""), hist.get("source", "")
        except (market_data.AkshareError, ValueError) as e:
            return _err(str(e))
        if not rows:
            return _err(f"未获取到 {full_symbol} 的历史行情(代码不存在、已退市或该区间无交易日)")

    ma_rows = indicators.add_ma(rows)
    latest = indicators.latest_indicators(ma_rows)
    return _ok({
        "symbol": full_symbol,
        "name": name,
        "rows": len(ma_rows),
        "range": f"{start_ymd}~{end_ymd}",
        "source": source,
        "from_cache": from_cache,
        "latest": {
            "date": latest.get("date"), "close": latest.get("close"),
            "pct_chg": latest.get("pct_chg_latest"),
        },
        "ma": {
            "ma5": latest.get("ma5"), "ma20": latest.get("ma20"),
            "ma5_gt_ma20": latest.get("ma5_gt_ma20"),
        },
        "recent_closes": latest.get("recent_closes", []),
        "recent_volumes": latest.get("recent_volumes", []),
        "_output_data": {
            "current_symbol": full_symbol,
            "stock_history": {
                "symbol": full_symbol, "name": name,
                "start": start_ymd, "end": end_ymd,
                "source": source, "rows": ma_rows,
            },
        },
    })


# ---------------------------------------------------------------------------
# 工具 2:实时行情(易失数据,不落库)
# ---------------------------------------------------------------------------

def tool_get_stock_realtime(symbol: str = "", current_symbol: str = "",
                            llm=None, **kw) -> str:
    """实时快照(最新价/涨跌幅/估值等)。不落库:每次调用都是当时值。"""
    try:
        symbol = _resolve_symbol(symbol, current_symbol)
        r = market_data.get_realtime(symbol)
    except (ValueError, market_data.AkshareError) as e:
        return _err(str(e))
    return _ok(r)  # 注意:不含 _output_data(易失数据不落库)


# ---------------------------------------------------------------------------
# 工具 3:行业趋势
# ---------------------------------------------------------------------------

def tool_get_sector_trend(symbol: str = "", current_symbol: str = "",
                          llm=None, **kw) -> str:
    """所属行业 + 行业指数 1d/5d/20d 涨跌幅;行业源不可达时降级返回仅行业名。"""
    try:
        symbol = _resolve_symbol(symbol, current_symbol)
        full_symbol, _ = normalize_symbol(symbol)
    except ValueError as e:
        return _err(str(e))

    code = full_symbol.split(".")[0]
    industry = market_data.get_industry_name(code)
    trend = market_data.get_industry_trend(industry) if industry else None

    payload = {
        "symbol": full_symbol,
        "industry": industry,
        "pct_1d": (trend or {}).get("pct_1d"),
        "pct_5d": (trend or {}).get("pct_5d"),
        "pct_20d": (trend or {}).get("pct_20d"),
        "note": "",
        "_output_data": {
            "stock_sector": {
                "symbol": full_symbol,
                "industry": industry,
                "pct_1d": (trend or {}).get("pct_1d"),
                "pct_5d": (trend or {}).get("pct_5d"),
                "pct_20d": (trend or {}).get("pct_20d"),
                "ts": market_data._now(),
            },
        },
    }
    if industry is None:
        payload["note"] = "行业归属暂不可用(行情源不可达),报告将仅基于个股行情"
    elif trend is None:
        payload["note"] = "行业指数涨跌幅暂不可用,仅返回行业归属"
    return _ok(payload)


# ---------------------------------------------------------------------------
# 工具 4:K线图
# ---------------------------------------------------------------------------

def tool_plot_kline_chart(stock_history: dict = None, llm=None, **kw) -> str:
    """用已落库的行情数据画 K线+MA5/MA20+成交量 PNG,路径落库供报告引用。"""
    if not stock_history or not stock_history.get("rows"):
        return _err("暂无行情数据:请先调用 get_stock_history 获取历史行情")
    try:
        path = charts.plot_kline(
            symbol=stock_history.get("symbol", ""),
            name=stock_history.get("name", ""),
            rows=stock_history["rows"],
        )
    except charts.MatplotlibMissing as e:
        return _err(str(e))
    except (ValueError, OSError) as e:
        return _err(f"生成K线图失败: {e}")
    return _ok({
        "chart_path": path,
        "instant_reply": f"📈 K线图已保存: {path}",
        "_output_data": {"chart_path": path},
    })


# ---------------------------------------------------------------------------
# 工具 5:技术分析报告
# ---------------------------------------------------------------------------

def tool_generate_tech_report(stock_history: dict = None, stock_sector: dict = None,
                              chart_path: str = "", llm=None, **kw) -> str:
    """基于注入的行情/行业/图表生成技术分析报告(指标在 handler 内即时派生)。"""
    if not stock_history or not stock_history.get("rows"):
        return _err("暂无行情数据:请先调用 get_stock_history 获取历史行情")

    symbol = stock_history.get("symbol", "")
    name = stock_history.get("name", "")
    latest = indicators.latest_indicators(stock_history["rows"])

    try:
        content = llm.complete(
            messages=[{
                "role": "user",
                "content": prompts.build_tech_report_prompt(
                    symbol, name, latest, sector=stock_sector, chart_path=chart_path),
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

    chart_line = f"\n**K线图**: `{chart_path}`\n" if chart_path else ""
    report_md = (
        f"# {structured['title']}\n\n"
        f"**标的**: {name}({symbol})  |  **数据日期**: {latest.get('date')}\n"
        f"{chart_line}\n"
        f"## 结论概述\n{structured['summary']}\n\n"
        f"## 趋势判断\n{structured['trend']}\n\n"
        f"## 支撑与压力\n{structured['support_resistance']}\n\n"
        f"## 技术信号\n{structured['signal']}\n\n"
        f"## 风险提示\n{structured['risk']}\n\n"
        "> 数据来源:AkShare 公开行情(前复权日K)。本报告由 AI 生成,仅供参考,不构成投资建议。\n"
    )

    return _ok({
        "title": structured["title"],
        "summary": structured["summary"],
        "report_len": len(report_md),
        "chart_path": chart_path,
        "_output_data": {
            "tech_report": {
                "symbol": symbol,
                "name": name,
                "date": latest.get("date"),
                "report_md": report_md,
                "structured": structured,
            },
        },
    })
