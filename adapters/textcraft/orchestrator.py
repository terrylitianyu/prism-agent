#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrator adapter:仅为 resolve_prompt_context 存在。

SYSTEM.md 所在的 skill(orchestrator)没有自己的 tool,这个 adapter 不接线
任何数据,只负责把当前会话状态(文档/类型/摘要)注入 system prompt。
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
        has_doc = bool(ctx.store.get_field(ctx.session_id, "document_text"))
        type_label = ctx.store.get_field(ctx.session_id, "doc_type_label")
        has_summary = bool(ctx.store.get_field(ctx.session_id, "summary"))
        return (
            "## Current State\n"
            f"- 文档:{'已上传' if has_doc else '未上传'}\n"
            f"- 类型识别:{type_label or '未识别'}\n"
            f"- 摘要:{'已生成' if has_summary else '未生成'}"
        )
