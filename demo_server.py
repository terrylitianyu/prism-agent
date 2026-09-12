#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web demo server (Flask) —— 通用 Agent 交互端

运行: python demo_server.py  →  http://127.0.0.1:5057

URL 结构: / 为首页(选 agent + 发首轮消息),/s/<sid> 为具体会话页(可刷新/分享)。
首页首轮消息才创建会话,/api/chat 在流首事件发出 {"event":"session",...} 告知新 id。

本 demo 是"通用交互端":agent 由 agents/*.py 自动发现;上传与状态 chip 不是
交互端的固有功能,而是 agent 的可选声明(见 agents/textcraft.py 模块 docstring):
  - handle_upload(session_id, store, filename, text) -> dict  存在 = 支持上传
  - get_state(session_id, store) -> {"chips": [...]}          存在 = 有状态 chip 区
未声明的 agent 在 Web 端就是纯净聊天界面。

会话(session):支持按 agent 隔离的多个内存会话(/api/sessions 新建/列举,
左侧栏跨 agent 汇总显示全部会话,每条带 agent 标签;当前对话属于哪个
agent 由对话页 header 标注)。每个会话 = 一个框架 BaseSession——对话历史互相隔离,
DataStore 字段按 session_id 隔离,chat/state/upload 均由请求携带 session_id,
服务端用 ContextVar 绑定(见 prism/session_context.py),并行不串扰。
会话持久化在 .data/sessions/<agent>/<sid>/state.json(框架 BaseSession.save/load),
服务重启后自动恢复会话列表与历史,最后使用的会话自动激活。
agent 没有会话时列表为空(不预置默认会话),首轮消息才创建会话。

会话锁定规则(前端执行):会话已有对话记录后,agent 选择框变为锁定标注、
不能再切换;新建会话后恢复可选。服务端保持宽松,仅由前端约束交互。

多 agent:每个 agent 首次选中时装配一个 prism.agent.AgentEngine 并缓存进
_engines(双检锁),之后切换只是 _current 指针替换,不再重建。进行中的
流式请求持有自己 engine 的引用、并显式携带 session(见 api_chat),此刻
切换 agent 不会污染在途请求;engine 内部再把 session 绑进 ContextVar,
供工具 wrapper / 并行执行沿链解析(见 prism/agent.py agent_loop_stream)。
"""

import importlib
import json
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from prism.agent import AgentEngine
from prism.core import WORKDIR
from prism.session import BaseSession

DATA_DIR = Path(".data")
SESSIONS_ROOT = DATA_DIR / "sessions"  # 会话持久化目录:<agent>/<sid>/state.json
WEB_DIR = WORKDIR / "demo_web"

app = Flask(__name__)

# agent 名 -> (agent 模块, 装配好的 AgentEngine);首次选中时装配,之后切换只是指针替换
_engines = {}
_engines_lock = threading.Lock()  # 并发首请求同一 agent 时只装配一次
# 当前选中的 agent(只是名字指针;mod/engine/store 一律经 _engines[name] 快照取)
_current = {"agent": None}
# 会话注册表:{agent_name: {session_id: BaseSession}};_active 记录各 agent 最后使用的会话
_sessions = {}
_active = {}
# (agent, sid) -> 最后落盘时间,用于会话列表排序与重启后恢复激活
_updated = {}


def _available_agents():
    agents_dir = WORKDIR / "agents"
    return sorted(
        p.stem for p in agents_dir.glob("*.py") if not p.stem.startswith("_")
    )


def _session_dir(name, sid):
    return SESSIONS_ROOT / name / sid


def _save_session(name, sess):
    """持久化会话到 .data/sessions/<agent>/<sid>/state.json。"""
    sess.save(_session_dir(name, sess.session_id))
    _updated[(name, sess.session_id)] = time.time()


def _ensure_sessions(name):
    """确保当前 agent 的会话注册表已加载;首次进入从磁盘恢复持久化会话。
    没有任何会话时返回空 dict——不预置默认会话,首轮消息才创建。"""
    if name in _sessions:
        return _sessions[name]
    loaded = {}
    root = SESSIONS_ROOT / name
    if root.is_dir():
        for state_file in sorted(root.glob("*/state.json")):
            sid = state_file.parent.name
            sess = BaseSession(session_id=sid)
            try:
                sess.load(json.loads(state_file.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 单个坏文件不应拖垮整个恢复
                continue
            loaded[sid] = sess
            _updated[(name, sid)] = state_file.stat().st_mtime
    _sessions[name] = loaded
    _active[name] = max(loaded, key=lambda s: _updated[(name, s)]) if loaded else None
    return loaded


def _session_title(sess):
    """会话标题 = 第一条用户消息(截断 16 字符)。"""
    for h in sess.history:
        if h["role"] == "user" and h["content"].strip():
            t = h["content"].strip().replace("\n", " ")
            return t[:16] + ("…" if len(t) > 16 else "")
    return "新会话"


def _resolve_session(name, sid):
    """校验会话 id 属于指定 agent,返回 BaseSession 或 None。
    name 用调用方已有的局部变量,不回读 _current——并发 select 在两次读之间
    翻转时,会话解析仍落在本请求自己的 agent 上。"""
    if not name or not sid:
        return None
    return _ensure_sessions(name).get(sid)


def _find_session(sid):
    """跨 agent 定位会话:先查已加载注册表,再扫磁盘持久化目录。
    返回 (agent_name, sess) 或 (None, None)。"""
    for name, sessions in _sessions.items():
        if sid in sessions:
            return name, sessions[sid]
    if SESSIONS_ROOT.is_dir():
        for agent_dir in SESSIONS_ROOT.iterdir():
            if (agent_dir / sid / "state.json").is_file():
                return agent_dir.name, _ensure_sessions(agent_dir.name).get(sid)
    return None, None


def _sid_from_request(name):
    """取请求指定的会话 id(query/form 参数,缺省用该 agent 最后使用的会话)。"""
    return request.args.get("session_id") or request.form.get("session_id") \
        or _active.get(name)


def _select_agent(name):
    """选中指定 agent:首次装配并缓存 engine(双检锁,并发首请求只建一次),
    之后切换只是指针替换(不重建)。"""
    if name not in _engines:
        with _engines_lock:
            if name not in _engines:
                mod = importlib.import_module(f"agents.{name}")
                engine = mod.init(DATA_DIR)
                if not isinstance(engine, AgentEngine):
                    raise TypeError(
                        f"agents.{name}.init() 应返回 prism.agent.AgentEngine;"
                        f"老契约(返回 DataStore)已随 AgentEngine 重构废弃,见 README"
                    )
                _engines[name] = (mod, engine)
    _current["agent"] = name
    _ensure_sessions(name)  # 预载该 agent 的会话注册表(含 _active 恢复)
    return _engines[name][1]


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/s/<sid>")
def session_page(sid):
    """会话页:同一个 SPA,由前端解析路径渲染对应会话。"""
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


@app.get("/api/sessions")
def api_sessions():
    """全部 agent 的会话列表(跨 agent 汇总,最近有活动的在前)。
    每条带 agent 归属;当前对话属于哪个 agent 由前端 header 标注显示。"""
    items = []
    for name in _available_agents():
        for sid, s in _ensure_sessions(name).items():
            items.append((_updated.get((name, sid), 0), {
                "id": sid, "agent": name,
                "title": _session_title(s), "messages": len(s.history),
            }))
    items.sort(key=lambda kv: kv[0], reverse=True)
    return jsonify({"agent": _current["agent"], "sessions": [it for _, it in items]})


@app.post("/api/sessions")
def api_sessions_new():
    """新建会话(自动设为当前会话,并立即落盘)。"""
    if _current["agent"] is None:
        return jsonify({"error": "请先选择 agent"}), 400
    name = _current["agent"]
    sid = "s" + uuid.uuid4().hex[:6]
    sessions = _ensure_sessions(name)
    sessions[sid] = BaseSession(session_id=sid)
    _save_session(name, sessions[sid])
    _active[name] = sid
    return jsonify({"ok": True, "id": sid})


@app.get("/api/sessions/<sid>/history")
def api_session_history(sid):
    """会话历史 + 归属 agent(深链用:服务端自动切换到该 agent)。"""
    agent_name, sess = _find_session(sid)
    if sess is None:
        return jsonify({"error": f"unknown session: {sid}"}), 400
    if _current["agent"] != agent_name:
        _select_agent(agent_name)
    return jsonify({
        "id": sid,
        "agent": agent_name,
        "history": [{"role": h["role"], "content": h["content"]} for h in sess.history],
    })


@app.post("/api/upload")
def api_upload():
    """上传代理:仅当当前 agent 声明了 handle_upload 时可用。"""
    name = _current["agent"]
    if name is None:
        return jsonify({"error": "请先选择 agent"}), 400
    mod, engine = _engines[name]  # 一次快照:两次读之间 select 翻转也不会撕裂
    handler = getattr(mod, "handle_upload", None)
    if handler is None:
        return jsonify({"error": "当前 agent 不支持上传"}), 400
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    sid = _sid_from_request(name)
    if _resolve_session(name, sid) is None:
        return jsonify({"error": f"unknown session: {sid}"}), 400
    text = f.read().decode("utf-8", errors="replace")
    result = handler(sid, engine.store, f.filename, text) or {}
    return jsonify({"ok": True, "filename": f.filename, "chars": len(text), **result})


@app.get("/api/state")
def api_state():
    """状态代理:当前 agent 的 chip 列表与上传能力,由 agent 的 get_state 决定。"""
    name = _current["agent"]
    if name is None:
        return jsonify({"agent": None})
    mod, engine = _engines[name]  # 一次快照,同 api_upload
    sid = _sid_from_request(name)
    if _resolve_session(name, sid) is None:
        return jsonify({"error": f"unknown session: {sid}"}), 400
    provider = getattr(mod, "get_state", None)
    state = provider(sid, engine.store) or {} \
        if provider else {}
    return jsonify({
        "agent": name,
        "upload": getattr(mod, "handle_upload", None) is not None,
        "chips": state.get("chips", []),
    })


@app.post("/api/chat")
def api_chat():
    if _current["agent"] is None:
        return jsonify({"error": "请先选择 agent"}), 400
    body = request.get_json(force=True) or {}
    message = body.get("message", "")
    if not message.strip():
        return jsonify({"error": "empty message"}), 400

    # 可选 agent:首页首轮消息会带上;不带则沿用当前 agent
    agent_name = body.get("agent") or _current["agent"]
    if agent_name not in _available_agents():
        return jsonify({"error": f"unknown agent: {agent_name}"}), 400
    if agent_name != _current["agent"]:
        _select_agent(agent_name)

    # 无 session_id = 首轮消息,此时才创建会话(并立即落盘)
    created = False
    sid = body.get("session_id")
    if not sid:
        sid = "s" + uuid.uuid4().hex[:6]
        sessions = _ensure_sessions(agent_name)
        sessions[sid] = BaseSession(session_id=sid)
        _save_session(agent_name, sessions[sid])
        _active[agent_name] = sid
        created = True

    sess = _resolve_session(agent_name, sid)
    if sess is None:
        return jsonify({"error": f"unknown session: {sid}"}), 400

    _active[agent_name] = sid
    # 捕获本请求自己的 engine:流式输出期间用户切换到别的 agent 时,
    # 在途请求仍用自己的 engine(模型表/工具集/store),不被污染
    engine = _engines[agent_name][1]

    def stream():
        if created:
            # 流首事件:告知前端新会话 id(前端据此跳转 /s/<sid>)
            yield f"data: {json.dumps({'event': 'session', 'data': {'id': sid}}, ensure_ascii=False)}\n\n"
        try:
            # 会话显式随请求传入;落盘统一由 finally 负责(覆盖客户端断开),
            # 故不再传 session_dir 让 engine 落盘
            for event in engine.agent_loop_stream(message, conversation_history=[], session=sess):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            # 无论正常结束还是客户端断开,都落盘会话状态
            _save_session(agent_name, sess)

    return Response(stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    _select_agent("textcraft")  # 默认选中,省去手动 /api/select
    app.run(host="127.0.0.1", port=5057, debug=False)
