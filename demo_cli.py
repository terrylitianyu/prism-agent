#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
textcraft 交互式 CLI demo

用法: python demo_cli.py
命令:
  /upload <文件路径>   上传文档(写入 DataStore),并自动开始一轮"无指令"对话
  /state              查看 DataStore 当前状态
  /new                新会话(清空文档状态与对话历史)
  /quit               退出
  其余输入            作为消息发送给 agent
"""

import json
import time
from pathlib import Path

from prism import agent
from agents.textcraft import handle_upload, init as init_textcraft

DATA_DIR = Path(".data")

store = None
session = None


def run_turn(message: str):
    """跑一轮 agent loop 并渲染事件流。"""
    for event in agent.agent_loop_stream(message, conversation_history=[]):
        ev, data = event.get("event"), event.get("data")
        if ev == "instant_reply":
            print(f"  ⚡ {data}")
        elif ev == "tool_call":
            args = json.dumps(data.get("args", {}), ensure_ascii=False)
            print(f"  🔧 {data.get('name')}({args})")
        elif ev == "tool_result":
            snippet = str(data.get("result"))[:150]
            print(f"  ↳ {snippet}")
        elif ev == "done":
            print(f"\ntextcraft: {data}\n")
        elif ev == "error":
            print(f"  ❌ {data}")
        elif ev == "usage":
            print(f"  [usage] total={data.get('total_tokens')} "
                  f"(prompt={data.get('total_prompt_tokens')}, "
                  f"completion={data.get('total_completion_tokens')})")


def cmd_upload(path_str: str):
    p = Path(path_str).expanduser()
    if not p.exists():
        print(f"  文件不存在: {p}")
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    # 与 Web 端同一条上传路径:hash 复用 / 清旧状态 / auto_message 都由 handle_upload 决定
    result = handle_upload(session.session_id, store, p.name, text) or {}
    print(f"  已上传 {p.name}({len(text)} 字符)")
    run_turn(result.get("auto_message") or "我上传了一份文档")


def cmd_state():
    sid = session.session_id
    doc = store.get_field(sid, "document_text") or ""
    print("  --- DataStore ---")
    preview = f" | {doc[:60].strip()}..." if doc else ""
    print(f"  document_text: {len(doc)} 字符{preview}")
    doc_hash = store.get_field(sid, "document_hash")
    print(f"  document_hash: {doc_hash[:8]}…" if doc_hash else "  document_hash: -")
    print(f"  document_filename: {store.get_field(sid, 'document_filename') or '-'}")
    cat = store.get_field(sid, "doc_category")
    if cat:
        print(f"  doc_category: {cat} ({store.get_field(sid, 'doc_category_label')})")
        print(f"  doc_subtype: {store.get_field(sid, 'doc_subtype')} "
              f"({store.get_field(sid, 'doc_subtype_label')})")
        print(f"  classification: 置信 {store.get_field(sid, 'classification_confidence')} "
              f"| fallback {store.get_field(sid, 'classification_fallback')}")
    else:
        print("  doc_category/subtype: (未识别)")
    src_hash = store.get_field(sid, "summary_source_hash")
    print(f"  summary_source_hash: {src_hash[:8]}…" if src_hash else "  summary_source_hash: -")
    summary = store.get_field(sid, "summary")
    if summary:
        print(f"  summary:\n{json.dumps(summary, ensure_ascii=False, indent=2)}")
    else:
        print("  summary: (未生成)")


def cmd_new():
    session.history.clear()
    session.chat_events.clear()
    session.turn_count = 0
    session.session_id = f"cli-{int(time.time())}"
    print(f"  新会话: {session.session_id}")


def main():
    global store, session
    store = init_textcraft(DATA_DIR)
    session = agent._default_session
    session.session_id = "cli-default"
    print(__doc__)
    while True:
        try:
            line = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break
        if not line:
            continue
        if line == "/quit":
            break
        elif line == "/state":
            cmd_state()
        elif line == "/new":
            cmd_new()
        elif line.startswith("/upload"):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("  用法: /upload <文件路径>")
            else:
                cmd_upload(parts[1])
        elif line.startswith("/"):
            print("  未知命令(支持 /upload /state /new /quit)")
        else:
            run_turn(line)


if __name__ == "__main__":
    main()
