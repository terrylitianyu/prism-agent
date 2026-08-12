#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Session Management: BaseSession (framework-level).

BaseSession provides conversation history and turn tracking.
All business data (stage, uploaded_file, etc.) lives in DataStore.
"""

import json
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from .core import SESSION_DIR


class BaseSession:
    """平台通用 Session：管理会话历史、聊天事件、修改记录等通用状态。"""

    def __init__(self, session_id: str = None):
        self.session_id: Optional[str] = session_id
        self.history: List[dict] = []
        self.chat_events: List[dict] = []
        self.turn_count: int = 0

    def add_turn(self, role: str, content: str):
        """添加一轮对话记录到 history，content 截断至 2000 字符。"""
        self.history.append({
            "role": role,
            "content": content[:2000] if content else "",
            "timestamp": datetime.now().isoformat(),
        })
        if role == "user":
            self.turn_count += 1

    def get_recent_history(self, n: int = 14) -> List[dict]:
        """获取最近 n 轮对话记录，默认 14 轮。"""
        return self.history[-n:]

    def to_dict(self) -> dict:
        """序列化为字典（仅通用字段）。"""
        return {
            "session_id": self.session_id,
            "history": self.history,
            "chat_events": self.chat_events[-200:],
            "turn_count": self.turn_count,
        }

    def load(self, data: dict):
        """从字典加载通用字段。"""
        self.history = data.get("history", [])
        self.chat_events = data.get("chat_events", [])
        self.turn_count = data.get("turn_count", 0)

    def save(self, session_dir: Path = None):
        """持久化 session metadata 到磁盘。"""
        save_dir = session_dir or SESSION_DIR
        save_dir.mkdir(parents=True, exist_ok=True)
        state_file = save_dir / "state.json"
        state_data = self.to_dict()
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")