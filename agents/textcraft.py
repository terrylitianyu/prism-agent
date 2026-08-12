#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""textcraft agent 入口:初始化 DataStore 并装配框架。"""

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
