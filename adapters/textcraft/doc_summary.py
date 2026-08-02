#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_summary 的 Adapter:把 skill 接到 textcraft 的 DataStore 字段上。"""

from typing import Any, Dict

from skill_context import SkillAdapter, SkillContext


class DocSummaryAdapter(SkillAdapter):
    skill_name = "doc_summary"

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        return {
            "document_text": ctx.store.get_field(ctx.session_id, "document_text"),
            "doc_type": ctx.store.get_field(ctx.session_id, "doc_type"),
        }

    def write_output(self, ctx: SkillContext, result: Any):
        if isinstance(result, dict):
            for field in ("doc_type", "doc_type_label", "summary"):
                if field in result:
                    ctx.store.set_field(ctx.session_id, field, result[field])

    def validate_inputs(self, inputs: Dict[str, Any]) -> str:
        if not inputs.get("document_text"):
            return "Required input 'document_text' is None (请先上传或粘贴文档)"
        return ""

    def get_tool_params(self) -> Dict[str, dict]:
        return {
            "generate_summary": {
                "focus": {
                    "type": "string",
                    "description": "用户想侧重的方面(如'研究方法''人物关系');没有则省略",
                    "required": False,
                }
            }
        }
