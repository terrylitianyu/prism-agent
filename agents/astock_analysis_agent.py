#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""astock_analysis_agent 入口:初始化 DataStore、图表输出目录并装配框架。"""

from pathlib import Path

from prism import agent
from prism.core import ADAPTERS_DIR
from prism.data_store import SQLiteDataStore

# skill 内 charts.OUT_DIR 是中性默认(.data/charts),这里覆盖为本 agent 的数据目录,
# 保证自定义 data_dir 时图表路径一致
from skills.astock_analysis_agent.tech_analysis.scripts import charts


def init(data_dir: Path):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    charts.OUT_DIR = data_dir / "astock_analysis_agent" / "charts"
    store = SQLiteDataStore(str(data_dir / "astock_analysis_agent.db"))
    agent.init_agent(agent_dir=ADAPTERS_DIR / "astock_analysis_agent", store=store)
    return store
