#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Store: Abstract interface and SQLite implementation for stage data persistence.

Provides a clean abstraction over storage backends. Each Agent uses its own
database file for physical isolation. The SQLite implementation supports
dynamic column addition (ensure_field) so new data fields are auto-created.
"""

import json
import sqlite3
import threading
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class DataStore(ABC):
    """数据存储抽象接口。宽表模型，每个字段独立列，通过 session_id 定位。"""

    @abstractmethod
    def get_field(self, session_id: str, field: str) -> Optional[Any]:
        """读取指定 session 的某个字段数据，返回反序列化后的 Python 对象。"""
        ...

    @abstractmethod
    def set_field(self, session_id: str, field: str, data: Any) -> None:
        """写入/更新指定 session 的某个字段数据。"""
        ...

    @abstractmethod
    def delete_field(self, session_id: str, field: str) -> None:
        """清除指定 session 的某个字段（置 NULL）。"""
        ...

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """删除 session 的所有数据。"""
        ...

    @abstractmethod
    def ensure_field(self, field: str) -> None:
        """确保字段（列）存在，不存在则动态创建。"""
        ...


class SQLiteDataStore(DataStore):
    """SQLite 宽表实现。线程安全（threading.local），WAL 模式，支持动态加列。"""

    def __init__(self, db_path: str, table_name: str = "session_stage_data"):
        self._db_path = db_path
        self._table = table_name
        self._local = threading.local()
        self._known_columns: set = set()
        self._col_lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接（每线程独立）。"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        """初始化数据库：建表（仅主键 + 时间戳）+ 缓存已有列名。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS [{self._table}] (
                session_id TEXT PRIMARY KEY,
                updated_at TEXT DEFAULT (datetime('now')),
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        cursor = conn.execute(f"PRAGMA table_info([{self._table}])")
        self._known_columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        logger.info(f"SQLiteDataStore initialized: {self._db_path} (table={self._table}, columns={len(self._known_columns)})")

    def ensure_field(self, field: str) -> None:
        """确保列存在，不存在则 ALTER TABLE ADD COLUMN。"""
        if field in self._known_columns:
            return
        with self._col_lock:
            if field in self._known_columns:
                return
            conn = self._get_conn()
            try:
                conn.execute(f"ALTER TABLE [{self._table}] ADD COLUMN [{field}] TEXT")
                conn.commit()
                self._known_columns.add(field)
                logger.info(f"Dynamic column added: {field}")
            except sqlite3.OperationalError:
                # Column already exists (race condition with another thread)
                self._known_columns.add(field)

    def get_field(self, session_id: str, field: str) -> Optional[Any]:
        """读取指定 session 的某个字段，返回反序列化的 Python 对象。"""
        self.ensure_field(field)
        conn = self._get_conn()
        cursor = conn.execute(
            f"SELECT [{field}] FROM [{self._table}] WHERE session_id=?",
            (session_id,)
        )
        row = cursor.fetchone()
        if row and row[0] is not None:
            return json.loads(row[0])
        return None

    def set_field(self, session_id: str, field: str, data: Any) -> None:
        """写入/更新指定 session 的某个字段（UPSERT）。"""
        self.ensure_field(field)
        json_str = json.dumps(data, ensure_ascii=False)
        conn = self._get_conn()
        conn.execute(
            f"""INSERT INTO [{self._table}] (session_id, [{field}], updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(session_id) DO UPDATE SET [{field}]=?, updated_at=datetime('now')""",
            (session_id, json_str, json_str)
        )
        conn.commit()

    def delete_field(self, session_id: str, field: str) -> None:
        """清除指定 session 的某个字段（置 NULL）。"""
        self.ensure_field(field)
        conn = self._get_conn()
        conn.execute(
            f"UPDATE [{self._table}] SET [{field}]=NULL, updated_at=datetime('now') WHERE session_id=?",
            (session_id,)
        )
        conn.commit()

    def delete_session(self, session_id: str) -> None:
        """删除 session 的所有数据（整行删除）。"""
        conn = self._get_conn()
        conn.execute(f"DELETE FROM [{self._table}] WHERE session_id=?", (session_id,))
        conn.commit()