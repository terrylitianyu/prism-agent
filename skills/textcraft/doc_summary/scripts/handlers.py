#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_summary skill handlers —— 纯函数,不 import session / store。"""

import json
import logging

from json_repair import repair_json

from client import call_llm, get_model
from .prompts import CLASSIFY_PROMPT, TYPE_LABELS, build_summary_prompt

logger = logging.getLogger(__name__)

DOC_TYPES = tuple(TYPE_LABELS.keys())  # ("paper", "novel", "news", "general")
CLASSIFY_SAMPLE_CHARS = 3000  # 分类只需采样,不用全文(与摘要成本分层)


def _classify(document_text: str) -> str:
    """用轻量模型对文档采样分类。

    任何失败(异常 / 无法解析 / LLM 错误文本)一律兜底 "general"——
    分类是廉价可重试步骤,不阻断主流程。
    """
    try:
        resp = call_llm(
            messages=[{
                "role": "user",
                "content": CLASSIFY_PROMPT.format(text=document_text[:CLASSIFY_SAMPLE_CHARS]),
            }],
            model=get_model("doc_summary"),
            temperature=0.0,
            max_tokens=1024,  # 推理模型的 reasoning tokens 会占额度,留足
        )
        raw = (resp.get("content") or "").strip().lower()
        if raw.startswith("[llm error"):
            logger.warning(f"classify got LLM error: {raw}")
            return "general"
        for t in DOC_TYPES:
            if t in raw:
                return t
        logger.warning(f"classify unparsable reply: {raw[:100]}")
    except Exception as e:
        logger.warning(f"classify raised: {e}")
    return "general"


def tool_classify_document(document_text: str = "", **kw) -> str:
    """识别文档类型并落库,供 generate_summary 及未来其他工具复用。"""
    if not document_text:
        return json.dumps({"status": "error", "message": "empty document_text"}, ensure_ascii=False)

    doc_type = _classify(document_text)
    label = TYPE_LABELS[doc_type]
    return json.dumps({
        "status": "success",
        "doc_type": doc_type,
        "doc_type_label": label,
        "_output_data": {"doc_type": doc_type, "doc_type_label": label},
        "instant_reply": f"📄 已识别文档类型:{label}",
    }, ensure_ascii=False)


def tool_generate_summary(document_text: str = "", doc_type: str = "",
                          focus: str = "", **kw) -> str:
    """按文档类型生成结构化摘要;doc_type 缺失时先内联分类兜底。"""
    if not document_text:
        return json.dumps({"status": "error", "message": "empty document_text"}, ensure_ascii=False)

    # 兜底:用户上传后直接要求摘要(未走 classify_document)→ 内联分类
    if doc_type not in DOC_TYPES:
        doc_type = _classify(document_text)

    resp = call_llm(
        messages=[{
            "role": "user",
            "content": build_summary_prompt(doc_type, document_text, focus),
        }],
        model=get_model("doc_summary"),
        temperature=0.3,
        max_tokens=4096,
    )
    content = (resp.get("content") or "").strip()
    if content.startswith("[LLM Error:"):
        return json.dumps({"status": "error", "message": content}, ensure_ascii=False)

    summary = repair_json(content, return_objects=True)
    if not isinstance(summary, dict) or not summary:
        return json.dumps({
            "status": "error",
            "message": "summary output is not valid JSON",
            "raw": content[:500],
        }, ensure_ascii=False)

    label = TYPE_LABELS[doc_type]
    return json.dumps({
        "status": "success",
        "doc_type": doc_type,
        "summary": summary,
        "_output_data": {"summary": summary, "doc_type": doc_type, "doc_type_label": label},
        "instant_reply": f"✅ 摘要已生成({label})",
    }, ensure_ascii=False)
