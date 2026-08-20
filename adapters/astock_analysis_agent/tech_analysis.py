#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tech_analysis 的 Adapter:把 skill 接到 astock_analysis_agent 的 DataStore 字段上。

字段约定:
- current_symbol: 当前会话股票(多工具省略 symbol 时的兜底)
- stock_history:  历史行情(含MA列)大段数据,cached_history/stock_history 均指向它
- stock_sector:   行业归属+行业指数涨跌
- chart_path:     最近生成的K线图路径
- tech_report:    技术分析报告(全文+结构化)
"""

from typing import Any, Dict

from prism.skill_context import SkillAdapter, SkillContext


class TechAnalysisAdapter(SkillAdapter):
    skill_name = "tech_analysis"

    _FIELDS = ("current_symbol", "stock_history", "stock_sector", "chart_path", "tech_report")

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        history = ctx.store.get_field(ctx.session_id, "stock_history")
        return {
            "current_symbol": ctx.store.get_field(ctx.session_id, "current_symbol"),
            # 同一个字段按工具用途注入两次:cached_history 供 fetch 工具判断缓存命中,
            # stock_history 供 plot/report 工具直接消费
            "cached_history": history,
            "stock_history": history,
            "stock_sector": ctx.store.get_field(ctx.session_id, "stock_sector"),
            "chart_path": ctx.store.get_field(ctx.session_id, "chart_path"),
        }

    def write_output(self, ctx: SkillContext, result: Any):
        if isinstance(result, dict):
            for field in self._FIELDS:
                if field in result:
                    ctx.store.set_field(ctx.session_id, field, result[field])

    def validate_inputs(self, inputs: Dict[str, Any]) -> str:
        # 代码合法性等校验在 handler 内做(本方法看不到 LLM 传参)
        return ""

    def get_tool_params(self) -> Dict[str, dict]:
        return {
            "get_stock_history": {
                "symbol": {
                    "type": "string",
                    "description": "6位A股代码,如 600519 / 000001(支持 000001.SZ、SZ000001 等写法)",
                    "required": True,
                },
                "start_date": {
                    "type": "string",
                    "description": "开始日期 YYYY-MM-DD 或 YYYYMMDD,缺省近一年",
                    "required": False,
                },
                "end_date": {
                    "type": "string",
                    "description": "结束日期 YYYY-MM-DD 或 YYYYMMDD,缺省今天",
                    "required": False,
                },
            },
            "get_stock_realtime": {
                "symbol": {
                    "type": "string",
                    "description": "6位A股代码;缺省用当前会话股票",
                    "required": False,
                },
            },
            "get_sector_trend": {
                "symbol": {
                    "type": "string",
                    "description": "6位A股代码;缺省用当前会话股票",
                    "required": False,
                },
            },
        }
