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
        doc = ctx.store.get_field(ctx.session_id, "document_text") or ""
        filename = ctx.store.get_field(ctx.session_id, "document_filename") or ""
        if doc:
            doc_line = (f"已上传 ({filename}, {len(doc)} 字符)" if filename
                        else f"已上传 ({len(doc)} 字符)")
        else:
            doc_line = "未上传"

        category_label = ctx.store.get_field(ctx.session_id, "doc_category_label")
        if category_label:
            subtype_label = ctx.store.get_field(ctx.session_id, "doc_subtype_label")
            confidence = ctx.store.get_field(ctx.session_id, "classification_confidence")
            fallback = ctx.store.get_field(ctx.session_id, "classification_fallback")
            label = category_label + (f"·{subtype_label}" if subtype_label else "")
            if fallback:
                type_line = f"{label} (低置信兜底)"
            elif isinstance(confidence, (int, float)):
                type_line = f"{label} (置信 {int(round(confidence * 100))}%)"
            else:
                type_line = label
        else:
            type_line = "未识别"

        summary = ctx.store.get_field(ctx.session_id, "summary")
        doc_hash = ctx.store.get_field(ctx.session_id, "document_hash")
        src_hash = ctx.store.get_field(ctx.session_id, "summary_source_hash")
        if not summary:
            summary_line = "未生成"
        elif doc_hash and src_hash:  # 两者齐全才判定一致性;缺任一 → 只显示"已生成"
            summary_line = ("已生成(与当前文档一致)" if doc_hash == src_hash
                            else "已生成(文档已更新,需重新生成)")
        else:
            summary_line = "已生成"

        return (
            "## Current State\n"
            f"- 文档: {doc_line}\n"
            f"- 类型: {type_line}\n"
            f"- 摘要: {summary_line}"
        )
