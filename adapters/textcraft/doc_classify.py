#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_classify 的 Adapter:把分类 skill 接到 textcraft 的 DataStore 字段上。"""

from typing import Any, Dict

from prism.skill_context import SkillAdapter, SkillContext


class DocClassifyAdapter(SkillAdapter):
    skill_name = "doc_classify"

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        return {
            "document_text": ctx.store.get_field(ctx.session_id, "document_text"),
            "filename": ctx.store.get_field(ctx.session_id, "document_filename"),
        }

    def write_output(self, ctx: SkillContext, result: Any):
        if isinstance(result, dict):
            for field in ("doc_category", "doc_category_label",
                          "doc_subtype", "doc_subtype_label",
                          "classification_confidence", "classification_fallback"):
                if field in result:
                    ctx.store.set_field(ctx.session_id, field, result[field])

    def validate_inputs(self, inputs: Dict[str, Any]) -> str:
        if not inputs.get("document_text"):
            return "Required input 'document_text' is None (请先上传或粘贴文档)"
        return ""

    def get_tool_params(self) -> Dict[str, dict]:
        return {}
