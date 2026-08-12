#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared constants and utilities for the Agent framework
"""

from pathlib import Path


# =============================================================
# Constants & Config
# =============================================================

WORKDIR = Path(__file__).resolve().parent.parent  # 项目根 = prism/ 包的上一级
SESSION_DIR = WORKDIR / ".sessions"
SKILLS_DIR = WORKDIR / "skills"
ADAPTERS_DIR = WORKDIR / "adapters"

TOKEN_THRESHOLD = 80_000
MAX_TOOL_OUTPUT = 50_000
