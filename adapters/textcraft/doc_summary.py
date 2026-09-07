#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_summary 的 Adapter:把摘要 skill 接到 textcraft 的 DataStore 字段上。"""

from typing import Any, Dict

from prism.skill_context import SkillAdapter, SkillContext


class DocSummaryAdapter(SkillAdapter):
    skill_name = "doc_summary"

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        return {
            "document_text": ctx.store.get_field(ctx.session_id, "document_text"),
            "doc_category": ctx.store.get_field(ctx.session_id, "doc_category"),
            "doc_subtype": ctx.store.get_field(ctx.session_id, "doc_subtype"),
            "summary": ctx.store.get_field(ctx.session_id, "summary"),
        }

    def write_output(self, ctx: SkillContext, result: Any):
        if isinstance(result, dict):
            for field in ("summary", "summary_source_hash", "summary_category",
                          "doc_category", "doc_category_label",
                          "doc_subtype", "doc_subtype_label"):
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
            },
            "revise_summary": {
                "revision_request": {
                    "type": "string",
                    "description": "用户对现有摘要的修改要求(必填)",
                    "required": True,
                }
            },
        }
