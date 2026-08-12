#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
textcraft Web demo server (Flask)

运行: python demo_server.py  →  http://127.0.0.1:5057

注意:框架当前是"一进程一 agent"的全局状态设计(见 ROADMAP P2-5)。
本 demo 的 /api/select 采用"选择即重初始化"——切换 agent 会重建全局状态,
仅作演示用途;多 agent 并行是未来的 AgentEngine 方案。
"""

import importlib
import json
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from prism import agent
from prism.core import WORKDIR

DATA_DIR = Path(".data")
WEB_DIR = WORKDIR / "demo_web"

app = Flask(__name__)

_current = {"agent": None, "store": None, "session_id": "web-session"}


def _available_agents():
    agents_dir = WORKDIR / "agents"
    return sorted(
        p.stem for p in agents_dir.glob("*.py") if not p.stem.startswith("_")
    )


def _select_agent(name: str):
    """(重)初始化指定 agent——会替换框架全局状态。"""
    mod = importlib.import_module(f"agents.{name}")
    store = mod.init(DATA_DIR)
    _current["agent"] = name
    _current["store"] = store
    agent._default_session.session_id = _current["session_id"]
    return store


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/agents")
def api_agents():
    return jsonify({"agents": _available_agents(), "current": _current["agent"]})


@app.post("/api/select")
def api_select():
    name = (request.get_json(force=True) or {}).get("agent", "")
    if name not in _available_agents():
        return jsonify({"error": f"unknown agent: {name}"}), 400
    _select_agent(name)
    return jsonify({"ok": True, "current": name})


@app.post("/api/upload")
def api_upload():
    if _current["agent"] is None:
        return jsonify({"error": "请先选择 agent"}), 400
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    text = f.read().decode("utf-8", errors="replace")
    sid, store = _current["session_id"], _current["store"]
    store.set_field(sid, "document_text", text)
    for field in ("doc_type", "doc_type_label", "summary"):  # 清旧状态
        store.delete_field(sid, field)
    return jsonify({"ok": True, "filename": f.filename, "chars": len(text)})


@app.get("/api/state")
def api_state():
    if _current["agent"] is None:
        return jsonify({"agent": None})
    sid, store = _current["session_id"], _current["store"]
    doc = store.get_field(sid, "document_text") or ""
    return jsonify({
        "agent": _current["agent"],
        "document_chars": len(doc),
        "doc_type": store.get_field(sid, "doc_type"),
        "doc_type_label": store.get_field(sid, "doc_type_label"),
        "has_summary": bool(store.get_field(sid, "summary")),
        "summary": store.get_field(sid, "summary"),
    })


@app.post("/api/chat")
def api_chat():
    if _current["agent"] is None:
        return jsonify({"error": "请先选择 agent"}), 400
    message = (request.get_json(force=True) or {}).get("message", "")
    if not message.strip():
        return jsonify({"error": "empty message"}), 400

    def stream():
        for event in agent.agent_loop_stream(message, conversation_history=[]):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return Response(stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    _select_agent("textcraft")  # 默认选中,省去手动 /api/select
    app.run(host="127.0.0.1", port=5057, debug=False)
