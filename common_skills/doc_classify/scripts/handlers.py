#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_classify skill handlers —— 纯函数,零框架 import。

不 import session / store / client:数据由 Adapter 经参数传入,
LLM 能力由框架注入的 llm 句柄(llm.complete)提供。
"""

import json
import logging
import math

from json_repair import repair_json

from .classify_prompts import build_classify_prompt
from .taxonomy import (category_label, is_valid_category, is_valid_subtype,
                       subtype_label)

logger = logging.getLogger(__name__)

SAMPLE_HEAD_CHARS = 2000   # 分类只需采样,不用全文(与摘要成本分层)
SAMPLE_TAIL_CHARS = 1000
CONFIDENCE_THRESHOLD = 0.6  # < 0.6 视为不可靠(恰好 0.6 通过)


def sample_text(text: str, head: int = SAMPLE_HEAD_CHARS,
                tail: int = SAMPLE_TAIL_CHARS) -> str:
    """采样:≤ head+tail 返回全文;否则头 head + 省略标记 + 尾 tail(纯函数)。"""
    if len(text) <= head + tail:
        return text
    return f"{text[:head]}\n……(中间省略 {len(text) - head - tail} 字符)……\n{text[-tail:]}"


def _fallback() -> dict:
    return {"category": "general", "subtype": None, "confidence": 0.0, "fallback": True}


def _parse_confidence(value) -> float | None:
    """容忍 "0.9" 字符串;NaN/inf 视为无效。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _classify(document_text: str, filename: str, llm) -> dict:
    """分类核心:采样 → LLM → 校验链,永不抛异常。

    任何失败(异常 / 不可解析 / 非法类别 / 低置信)一律兜底 general + fallback;
    category 合法但 subtype 非法时保留 category、subtype=None(二级只是 hint)。
    """
    if not document_text.strip():
        return _fallback()  # 空文档不调 LLM
    try:
        content = llm.complete(
            messages=[{
                "role": "user",
                "content": build_classify_prompt(filename, sample_text(document_text)),
            }],
            temperature=0.0,
            max_tokens=1024,  # 推理模型的 reasoning tokens 会占额度,留足
        )
    except Exception as e:
        logger.warning(f"classify llm raised: {e}")
        return _fallback()

    result = repair_json(content, return_objects=True)
    if not isinstance(result, dict) or not result:
        logger.warning(f"classify unparsable reply: {str(content)[:100]}")
        return _fallback()

    category = str(result.get("category") or "").strip().lower()
    if not is_valid_category(category):
        logger.warning(f"classify invalid category: {category!r}")
        return _fallback()

    confidence = _parse_confidence(result.get("confidence"))
    if confidence is None or confidence < CONFIDENCE_THRESHOLD:
        logger.warning(f"classify low confidence: {result.get('confidence')!r}")
        return _fallback()

    subtype = str(result.get("subtype") or "").strip().lower() or None
    if category == "general":
        subtype = None
    elif not is_valid_subtype(category, subtype):
        # 二级只是 hint:丢弃拼错的二级,不击穿分类
        logger.warning(f"classify invalid subtype {subtype!r} for {category}; keep category")
        subtype = None
    return {"category": category, "subtype": subtype,
            "confidence": confidence, "fallback": False}


def tool_classify_document(document_text: str = "", filename: str = "", llm=None, **kw) -> str:
    """识别文档类型(二级分类)并落库,供 generate_summary 及未来其他工具复用。"""
    if not document_text.strip():
        return json.dumps({"status": "error", "message": "empty document_text"}, ensure_ascii=False)

    r = _classify(document_text, filename, llm)
    data = {
        "doc_category": r["category"],
        "doc_category_label": category_label(r["category"]),
        "doc_subtype": r["subtype"],
        "doc_subtype_label": subtype_label(r["category"], r["subtype"]),
        "classification_confidence": r["confidence"],
        "classification_fallback": r["fallback"],
    }
    pct = int(round(r["confidence"] * 100))
    if r["fallback"]:
        reply = "🤔 未能可靠识别文档类型,先按'其他文档'处理"
    elif r["subtype"]:
        reply = (f"📄 已识别文档类型:{data['doc_category_label']}"
                 f"·{data['doc_subtype_label']}(置信 {pct}%)")
    else:
        reply = f"📄 已识别文档类型:{data['doc_category_label']}(置信 {pct}%)"
    return json.dumps({
        "status": "success",
        **data,
        "_output_data": data,
        "instant_reply": reply,
    }, ensure_ascii=False)
