#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrator adapter:仅为 resolve_prompt_context 存在。

SYSTEM.md 所在的 skill(orchestrator)没有自己的 tool,这个 adapter 不接线
任何数据,只负责把当前会话状态(当前股票/已有数据/图表/报告)注入 system prompt。
"""

from typing import Any, Dict

from prism.skill_context import SkillAdapter, SkillContext


class OrchestratorAdapter(SkillAdapter):
    skill_name = "orchestrator"

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        return {}

    def write_output(self, ctx: SkillContext, result: Any):
        pass

    def resolve_prompt_context(self, ctx: SkillContext) -> str:
        current = ctx.store.get_field(ctx.session_id, "current_symbol") or "未设置"
        history = ctx.store.get_field(ctx.session_id, "stock_history")
        hot_rank = ctx.store.get_field(ctx.session_id, "hot_rank")
        news = ctx.store.get_field(ctx.session_id, "market_news")
        chart = ctx.store.get_field(ctx.session_id, "chart_path")
        reports = [name for name in ("tech_report", "hot_analysis", "fundamental_report")
                   if ctx.store.get_field(ctx.session_id, name)]

        lines = ["## 当前会话状态", f"- 当前股票: {current}"]
        if history:
            lines.append(
                f"- 历史行情: {history.get('name') or ''}({history.get('symbol')}) "
                f"[{history.get('start')}~{history.get('end')}],{len(history.get('rows', []))} 行")
        if hot_rank:
            lines.append(f"- 人气榜: {len(hot_rank.get('rows', []))} 行(抓取于 {hot_rank.get('ts', '')})")
        if news:
            lines.append(f"- 市场快讯: {len(news.get('items', []))} 条(抓取于 {news.get('ts', '')})")
        if chart:
            lines.append(f"- K线图: {chart}")
        if reports:
            lines.append(f"- 已生成报告: {'、'.join(reports)}(多轮追问可直接引用,不必重新生成)")
        return "\n".join(lines)
