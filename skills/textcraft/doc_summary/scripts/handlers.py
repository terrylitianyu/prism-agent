#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_summary skill handlers —— 纯函数,零框架 import。

不 import session / store / client:数据由 Adapter 经参数传入,
LLM 能力由框架注入的 llm 句柄(llm.complete)提供。
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from json_repair import repair_json

from .prompts import (FALLBACK_CLASSIFY_PROMPT, build_block_summary_prompt,
                      build_merge_prompt, build_revise_prompt,
                      build_summary_prompt)
from .summary_taxonomy import (SUMMARY_TEMPLATES, SUBTYPE_HINTS, extension_for,
                               field_default, required_fields, resolve_category,
                               valid_subtype_or_none)
from .text_utils import chunk_text, is_long_doc, md5_of

logger = logging.getLogger(__name__)

INLINE_SAMPLE_CHARS = 2000  # 内联兜底分类的采样长度
_BLOCK_PLACEHOLDER = "(本块内容无法提取)"
_MAP_WORKERS = 4  # 分块 Map 的并发度:块间无依赖,并发换取总时延(推理模型单块约 6~8s)


def _error(message: str, **extra) -> str:
    return json.dumps({"status": "error", "message": message, **extra}, ensure_ascii=False)


def _inline_classify(document_text: str, llm) -> str:
    """doc_category 缺失时的兜底:一级-only 分类,不复制 doc_classify 完整 taxonomy。

    任何失败一律兜底 "general"——分类是廉价可重试步骤,不阻断主流程。
    """
    try:
        raw = llm.complete(
            messages=[{
                "role": "user",
                "content": FALLBACK_CLASSIFY_PROMPT.format(
                    text=document_text[:INLINE_SAMPLE_CHARS]),
            }],
            temperature=0.0,
            max_tokens=1024,
        ).strip().lower()
        for key in ("informational", "narrative", "persuasive", "instructional", "general"):
            if key in raw:
                return key
        logger.warning(f"inline classify unparsable reply: {raw[:100]}")
    except Exception as e:
        logger.warning(f"inline classify raised: {e}")
    return "general"


def _generate_with_validation(category: str | None, subtype: str | None,
                              build_prompt, llm,
                              temperature: float = 0.3, max_tokens: int = 4096
                              ) -> tuple[dict, str]:
    """校验-重试-补默认链。返回 (summary, note);硬失败抛 ValueError。

    - 非 dict → 重试一次(追加"不是有效 JSON")→ 仍坏 → ValueError
    - 缺 required(仅一级 required)→ 重试一次(追加"缺少字段:xxx")→ 仍缺 → 补默认 + note
    - 基础可选字段/扩展字段缺失 → 不重试、不提示,随补默认一步填空(结构稳定)
    """
    def _call() -> dict | None:
        content = llm.complete(
            messages=[{"role": "user", "content": build_prompt()}],
            temperature=temperature, max_tokens=max_tokens,
        )
        obj = repair_json(content, return_objects=True)
        return obj if isinstance(obj, dict) and obj else None

    summary = _call()
    if summary is None:
        original = build_prompt()
        build_prompt = lambda: (f"{original}\n\n注意:你上次的输出不是有效的 JSON,"
                                f"请只输出 JSON 对象。")  # noqa: E731
        summary = _call()
        if summary is None:
            raise ValueError("summary output is not valid JSON")

    missing = [f for f in required_fields(category) if f not in summary]
    if missing:
        original = build_prompt()
        build_prompt = lambda: (f"{original}\n\n注意:你上次的输出缺少字段:"
                                f"{', '.join(missing)},请输出包含全部字段的完整 JSON。")  # noqa: E731
        retried = _call()
        if retried is not None:
            summary = retried
        missing = [f for f in required_fields(category) if f not in summary]

    note = ""
    if missing:
        for f in missing:
            summary[f] = field_default(category, f)
        note = f"提示:以下字段未能从文档中提取,已填默认值:{', '.join(missing)}"

    # 基础可选字段 + 扩展字段缺失 → 静默补默认,保证摘要结构稳定
    tmpl = SUMMARY_TEMPLATES.get(category)
    if tmpl:
        ext = extension_for(category, subtype)
        declared = set(tmpl["fields"]) | set((ext or {}).get("fields", {}))
        for f in declared:
            if f not in summary:
                summary[f] = field_default(category, f)
    return summary, note


def _summarize_block(index: int, total: int, chunk: str, llm) -> str:
    """Map 阶段单块:repair 失败/LLM 异常重试一次,仍失败记占位文案,归并不中断。"""
    prompt = build_block_summary_prompt(index, total, chunk)
    for attempt in range(2):
        if attempt:
            prompt += (f"\n\n注意:上次输出不是有效 JSON,"
                       f'请只输出 {{"index": {index}, "summary": "..."}}。')
        try:
            # max_tokens 要给足:推理模型(如 deepseek-v4-flash)会先把预算烧在
            # reasoning_content 上,512 会被思维链吃光导致 content 为空(实测
            # finish_reason=length, reasoning_tokens=512)。4096 足够思考+输出。
            content = llm.complete(messages=[{"role": "user", "content": prompt}],
                                   temperature=0.3, max_tokens=4096)
        except Exception as e:
            logger.warning(f"block {index} llm raised: {e}")
            continue
        obj = repair_json(content, return_objects=True)
        if isinstance(obj, dict) and obj.get("summary"):
            return str(obj["summary"])
    return _BLOCK_PLACEHOLDER


def _map_reduce_summary(category: str, subtype: str | None, document_text: str,
                        focus: str, llm) -> tuple[dict, str]:
    """长文分块摘要:并行逐块提取要点(Map)→ 归并成结构化摘要(Reduce)。"""
    chunks = chunk_text(document_text)
    # Map 并行:块之间无依赖,每块一次 LLM 调用是纯网络等待,并发把总时延
    # 从 N×单块时延压到约 N/worker×单块时延。线程安全:llm 句柄共享只读
    # (框架 client 是进程级单例,OpenAI SDK 并发安全),_summarize_block 内部
    # 自捕获异常(失败返回占位文案,不外抛)。executor.map 保序,归并顺序不受影响。
    with ThreadPoolExecutor(max_workers=_MAP_WORKERS) as pool:
        block_summaries = list(pool.map(
            lambda item: _summarize_block(item[0], len(chunks), item[1], llm),
            enumerate(chunks)))
    merge_prompt = build_merge_prompt(category, subtype, block_summaries, focus)
    # 归并走同一校验链;temperature 0.2(格式合规优先)
    return _generate_with_validation(category, subtype, lambda: merge_prompt, llm,
                                     temperature=0.2)


def tool_generate_summary(document_text: str = "", doc_category: str = "",
                          doc_subtype: str = "", focus: str = "", llm=None, **kw) -> str:
    """按文档类型生成结构化摘要;doc_category 缺失时内联分类兜底;长文自动分块。"""
    if not document_text.strip():
        return _error("empty document_text")

    inline: dict = {}
    degraded = ""  # 降级提示:仅"分类结果存在但模板不支持"的分化场景出现(缺失/无二级为正常路径)
    category = resolve_category(doc_category)
    if category is None:
        # 兜底:用户上传后直接要求摘要(未走 classify_document)→ 内联一级分类
        if doc_category:
            logger.warning(f"doc_category '{doc_category}' unknown to summary "
                           f"templates, inline re-classify")
            degraded = f"文档分类({doc_category})未被摘要模板识别,已重新识别"
        category = _inline_classify(document_text, llm)
        subtype = None
        inline = {"doc_category": category,
                  "doc_category_label": SUMMARY_TEMPLATES[category]["label"]}
        if degraded:
            degraded += f"为{SUMMARY_TEMPLATES[category]['label']}"
    else:
        subtype = valid_subtype_or_none(category, doc_subtype)
        if doc_subtype and subtype is None:
            logger.warning(f"subtype '{doc_subtype}' unknown for category "
                           f"'{category}', dropped")
            degraded = (f"二级分类({doc_subtype})未被摘要模板识别,已按一级分类"
                        f"({SUMMARY_TEMPLATES[category]['label']})生成")

    try:
        if is_long_doc(document_text):
            summary, note = _map_reduce_summary(category, subtype, document_text, focus, llm)
        else:
            summary, note = _generate_with_validation(
                category, subtype,
                lambda: build_summary_prompt(category, subtype, document_text, focus),
                llm)
    except ValueError as e:
        return _error(str(e))
    except Exception as e:
        return _error(f"LLM call failed: {e}")

    if degraded:
        note = f"{degraded}。{note}" if note else degraded
    subtype_label = SUBTYPE_HINTS.get(category, {}).get(subtype, {}).get("label") \
        if subtype else None
    output = {
        "summary": summary,
        "summary_source_hash": md5_of(document_text),
        "summary_category": category,
        **inline,
    }
    type_text = SUMMARY_TEMPLATES[category]["label"] \
        + (f"·{subtype_label}" if subtype_label else "")
    return json.dumps({
        "status": "success",
        "summary": summary,
        "note": note,
        "_output_data": output,
        "instant_reply": f"✅ 摘要已生成({type_text})",
    }, ensure_ascii=False)


def tool_revise_summary(summary=None, revision_request: str = "", document_text: str = "",
                        doc_category: str = "", llm=None, **kw) -> str:
    """按用户要求修订现有摘要;不动 summary_source_hash(修订不改变摘要与文档的对应关系)。"""
    if not isinstance(summary, dict) or not summary:
        return _error("missing summary (请先生成摘要)")
    if not revision_request.strip():
        return _error("missing revision_request")

    category = resolve_category(doc_category)
    degraded = ""
    if doc_category and category is None:
        logger.warning(f"doc_category '{doc_category}' unknown, revise keeps "
                       f"original field structure")
        degraded = "提示:文档分类未被摘要模板识别,已保持原摘要字段结构"
    include_text = bool(document_text) and not is_long_doc(document_text)
    prompt = build_revise_prompt(summary, revision_request,
                                 document_text if include_text else None, category)
    try:
        new_summary, note = _generate_with_validation(category, None, lambda: prompt, llm)
    except ValueError as e:
        return _error(str(e))
    except Exception as e:
        return _error(f"LLM call failed: {e}")

    if degraded:
        note = f"{degraded}。{note}" if note else degraded
    return json.dumps({
        "status": "success",
        "summary": new_summary,
        "note": note,
        "_output_data": {"summary": new_summary},
        "instant_reply": "✏️ 摘要已按要求修订",
    }, ensure_ascii=False)
