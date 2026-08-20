#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hot_search 的 Adapter:把 skill 接到 astock_analysis_agent 的 DataStore 字段上。

字段约定:
- hot_rank:      人气榜大段数据(带 ts 时间戳)
- market_news:   市场快讯大段数据(带 ts 时间戳)
- hot_analysis:  热点分析报告(全文+结构化)
"""

from typing import Any, Dict

from prism.skill_context import SkillAdapter, SkillContext


class HotSearchAdapter(SkillAdapter):
    skill_name = "hot_search"

    _FIELDS = ("hot_rank", "market_news", "hot_analysis")

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        return {
            "hot_rank": ctx.store.get_field(ctx.session_id, "hot_rank"),
            "market_news": ctx.store.get_field(ctx.session_id, "market_news"),
        }

    def write_output(self, ctx: SkillContext, result: Any):
        if isinstance(result, dict):
            for field in self._FIELDS:
                if field in result:
                    ctx.store.set_field(ctx.session_id, field, result[field])

    def validate_inputs(self, inputs: Dict[str, Any]) -> str:
        # 参数范围等校验在 handler 内做
        return ""

    def get_tool_params(self) -> Dict[str, dict]:
        return {
            "get_hot_search_rank": {
                "top_n": {
                    "type": "integer",
                    "description": "返回前 N 名(5~30),缺省 10",
                    "required": False,
                },
            },
            "get_market_news": {
                "count": {
                    "type": "integer",
                    "description": "返回最近 N 条(5~50),缺省 20",
                    "required": False,
                },
            },
        }
