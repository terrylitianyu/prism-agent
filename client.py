#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM client for the Agent framework.
Single endpoint: all models via the same proxy.

MODELS dict is initialized with defaults and can be overridden by agent.yaml
via configure_models() at startup.
"""

import os
import time

from dotenv import load_dotenv
from openai import OpenAI

from core import WORKDIR

# 从项目根目录的 .env 加载配置(已存在的系统环境变量优先,不会被 .env 覆盖)
load_dotenv(WORKDIR / ".env")


# =============================================================================
# Config
# =============================================================================

API_BASE = os.environ.get("API_BASE", "")
API_KEY = os.environ.get("API_KEY", "")

# Default model mapping — overridden by agent.yaml `models` section at init time
MODELS = {
    "orchestrator": "deepseek-v4-flash",
    "intent": "deepseek-v4-flash",
}


def configure_models(models_config: dict):
    """Override MODELS with agent-specific configuration (from agent.yaml)."""
    global MODELS
    if models_config:
        MODELS.update(models_config)


# =============================================================================
# Client (lazy-initialized)
# =============================================================================

_client = None


def _get_client():
    """获取或创建 OpenAI 客户端单例。"""
    global _client
    if _client is None:
        if not API_KEY:
            raise RuntimeError(
                "API_KEY 未配置:请在项目根目录创建 .env 并设置 "
                "API_BASE / API_KEY(参考 .env.example),或使用系统环境变量"
            )
        _client = OpenAI(
            api_key=API_KEY,
            base_url=API_BASE,
            timeout=600,
        )
    return _client


# =============================================================================
# LLM Functions
# =============================================================================

def call_llm(messages: list, model: str = None, temperature: float = 0.7,
             max_tokens: int = 4096, max_retries: int = 3) -> dict:
    """Call LLM via OpenAI-compatible API. Returns {content, usage}."""
    model = model or MODELS["orchestrator"]
    client = _get_client()

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            choice = resp.choices[0]
            content = choice.message.content or ""
            if not content.strip() and attempt < max_retries - 1:
                time.sleep(2)
                continue
            return {
                "content": content,
                "usage": {
                    "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                    "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                },
            }
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return {"content": f"[LLM Error: {e}]", "usage": {}}


def call_llm_with_tools(messages: list, tools: list, model: str = None,
                        temperature: float = 0.7, max_tokens: int = 4096):
    """Call LLM with tool definitions. Returns the raw response object."""
    model = model or MODELS["orchestrator"]
    client = _get_client()
    resp = client.chat.completions.create(
        model=model, messages=messages, tools=tools,
        temperature=temperature, max_tokens=max_tokens,
    )
    return resp