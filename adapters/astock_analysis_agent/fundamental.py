#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fundamental 的 Adapter:把 skill 接到 astock_analysis_agent 的 DataStore 字段上。

字段约定:
- stock_valuation:    估值快照(PE/PB/PS/市值等)
- stock_financials:   近两年季度财务指标
- fundamental_report: 基本面分析报告(全文+结构化)
"""

from typing import Any, Dict

from prism.skill_context import SkillAdapter, SkillContext


class FundamentalAdapter(SkillAdapter):
    skill_name = "fundamental"

    _FIELDS = ("stock_valuation", "stock_financials", "fundamental_report")

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        return {
            "current_symbol": ctx.store.get_field(ctx.session_id, "current_symbol"),
            "stock_valuation": ctx.store.get_field(ctx.session_id, "stock_valuation"),
            "stock_financials": ctx.store.get_field(ctx.session_id, "stock_financials"),
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
        symbol_param = {
            "symbol": {
                "type": "string",
                "description": "6位A股代码;缺省用当前会话股票",
                "required": False,
            },
        }
        return {
            "get_valuation": symbol_param,
            "get_financials": symbol_param,
        }
