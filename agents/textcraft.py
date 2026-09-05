#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""textcraft agent 入口:初始化 DataStore 并装配框架。

除 init(data_dir) 外,本模块可选声明两个 UI 交互钩子(约定即协议,面向任意交互端):
  - handle_upload(session_id, store, filename, text) -> dict
    存在该函数 = 该 agent 支持上传(前端据此显示上传入口,/api/upload 据此放行)。
    返回 dict 可含 "auto_message"(前端收到后自动作为用户消息发送)。
  - get_state(session_id, store) -> {"chips": [{"label", "value", "on"}, ...]}
    存在该函数 = 该 agent 有状态 chip 区(交互端据此渲染右上角状态)。
"""

from pathlib import Path

from prism import agent
from prism.core import ADAPTERS_DIR
from prism.data_store import SQLiteDataStore


def init(data_dir: Path):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteDataStore(str(data_dir / "textcraft.db"))
    agent.init_agent(agent_dir=ADAPTERS_DIR / "textcraft", store=store)
    return store


def handle_upload(session_id, store, filename, text):
    """上传后行为:写入 document_text、清旧状态;自动发消息复现"上传无指令"场景。"""
    store.set_field(session_id, "document_text", text)
    for field in ("doc_type", "doc_type_label", "summary"):  # 清旧状态
        store.delete_field(session_id, field)
    return {"auto_message": "我上传了一份文档"}


def get_state(session_id, store):
    """右上角状态 chip:文档字符数 / 类型识别 / 摘要状态。"""
    doc = store.get_field(session_id, "document_text") or ""
    doc_type = store.get_field(session_id, "doc_type")
    has_summary = bool(store.get_field(session_id, "summary"))
    return {"chips": [
        {"label": "文档", "value": f"{len(doc)} 字符" if doc else "未上传", "on": bool(doc)},
        {"label": "类型", "value": store.get_field(session_id, "doc_type_label") or "未识别",
         "on": bool(doc_type)},
        {"label": "摘要", "value": "已摘要" if has_summary else "未摘要", "on": has_summary},
    ]}
