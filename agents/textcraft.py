#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""textcraft agent 入口:初始化 DataStore 并装配框架。

init(data_dir) 返回装配好的 prism.agent.AgentEngine(同时注册为默认 engine,
兼容 agent.init_agent 老调用方);调用方从返回值取 .store / .default_session。

除 init(data_dir) 外,本模块可选声明两个 UI 交互钩子(约定即协议,面向任意交互端):
  - handle_upload(session_id, store, filename, text) -> dict
    存在该函数 = 该 agent 支持上传(前端据此显示上传入口,/api/upload 据此放行)。
    返回 dict 可含 "auto_message"(前端收到后自动作为用户消息发送)。
  - get_state(session_id, store) -> {"chips": [{"label", "value", "on"}, ...]}
    存在该函数 = 该 agent 有状态 chip 区(交互端据此渲染右上角状态)。
"""

import hashlib
from pathlib import Path

from prism import agent
from prism.core import ADAPTERS_DIR
from prism.data_store import SQLiteDataStore

# 上传时写入的字段 / 新内容上传时清空的字段(全部分类 + 摘要状态)
UPLOAD_FIELDS = ("document_text", "document_hash", "document_filename")
RESET_FIELDS = (
    "doc_category", "doc_category_label",
    "doc_subtype", "doc_subtype_label",
    "classification_confidence", "classification_fallback",
    "summary", "summary_source_hash", "summary_category",
)


def init(data_dir: Path):
    """装配 textcraft:建 DataStore,构造 AgentEngine 并返回(engine.store 即上面建的库)。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteDataStore(str(data_dir / "textcraft.db"))
    return agent.init_agent(agent_dir=ADAPTERS_DIR / "textcraft", store=store)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def handle_upload(session_id, store, filename, text):
    """上传后行为:hash 复用——同内容重传保留全部旧状态,新内容清旧状态。"""
    text = text or ""
    if not text.strip():
        return {"auto_message": "我上传的文档是空的"}
    new_hash = _md5(text)
    if new_hash == store.get_field(session_id, "document_hash"):
        return {"auto_message": "我又上传了这份文档,内容和上次完全相同"}
    store.set_field(session_id, "document_text", text)
    store.set_field(session_id, "document_hash", new_hash)
    store.set_field(session_id, "document_filename", filename)
    for field in RESET_FIELDS:  # 新文档 → 清掉旧分类/摘要,防陈旧状态
        store.delete_field(session_id, field)
    return {"auto_message": "我上传了一份文档"}


def get_state(session_id, store):
    """右上角状态 chip:文档(文件名+字符数)/ 类型(二级+置信)/ 摘要(hash 一致性)。"""
    doc = store.get_field(session_id, "document_text") or ""
    filename = store.get_field(session_id, "document_filename") or ""
    if not doc:
        doc_value = "未上传"
    elif filename:
        doc_value = f"{filename}·{len(doc)} 字符"
    else:
        doc_value = f"{len(doc)} 字符"

    category_label = store.get_field(session_id, "doc_category_label")
    if category_label:
        subtype_label = store.get_field(session_id, "doc_subtype_label")
        confidence = store.get_field(session_id, "classification_confidence")
        fallback = store.get_field(session_id, "classification_fallback")
        label = category_label + (f"·{subtype_label}" if subtype_label else "")
        if fallback:
            type_value = f"{label}(低置信)"
        elif isinstance(confidence, (int, float)):
            type_value = f"{label}({int(round(confidence * 100))}%)"
        else:
            type_value = label
    else:
        type_value = "未识别"

    has_summary = bool(store.get_field(session_id, "summary"))
    doc_hash = store.get_field(session_id, "document_hash")
    src_hash = store.get_field(session_id, "summary_source_hash")
    if has_summary and doc_hash and src_hash:
        summary_value = "已摘要(一致)" if doc_hash == src_hash else "已摘要(已更新)"
    else:
        summary_value = "已摘要" if has_summary else "未摘要"

    return {"chips": [
        {"label": "文档", "value": doc_value, "on": bool(doc)},
        {"label": "类型", "value": type_value, "on": bool(category_label)},
        {"label": "摘要", "value": summary_value, "on": has_summary},
    ]}
