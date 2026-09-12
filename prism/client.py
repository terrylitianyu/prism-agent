#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM client for the Agent framework.
Single endpoint: all models via the same proxy.

模型表按 AgentEngine 实例隔离:DEFAULT_MODELS 是内置兜底,agent.yaml 的
models 段在 engine 构建时合并成该实例自己的 models(见 agent.AgentEngine)——
不再有进程级 MODELS 全局表,多 agent 同进程互不覆盖。
"""

import json
import logging
import logging.handlers
import os
import time

from dotenv import load_dotenv
from openai import OpenAI

from .core import WORKDIR

# 从项目根目录的 .env 加载配置(已存在的系统环境变量优先,不会被 .env 覆盖)
load_dotenv(WORKDIR / ".env")

# =============================================================================
# LLM call ledger —— 所有 LLM 调用(orchestrator + skill 内)统一落盘
# =============================================================================
# 每条调用记一行台账(模型/tokens/输出预览),完整 prompt 走 DEBUG。
# LLMClient 构造时绑定日志子目录(调用方通常传 session_id):
# 空串落默认 logs/llm_call.log,非空落 logs/<子目录>/llm_call.log。
_LLM_LOG_ROOT = WORKDIR / "logs"
_LLM_LOG_ROOT.mkdir(parents=True, exist_ok=True)
# 子目录名 -> logger:key 即 log_subdir(实际为 session_id,空串=默认目录)。
# 每目录只在首次出现时建一个 handler 并缓存,避免同文件多 handler 重复写/抢轮转。
_llm_loggers: dict = {}


def _logger_for(log_subdir: str) -> logging.Logger:
    """按日志子目录取 logger(懒建,缓存)。空串使用默认日志目录。"""
    key = log_subdir or ""
    if key not in _llm_loggers:
        log_dir = _LLM_LOG_ROOT / log_subdir if log_subdir else _LLM_LOG_ROOT
        log_dir.mkdir(parents=True, exist_ok=True)
        lg = logging.getLogger("llm.call").getChild(log_subdir or "default")
        handler = logging.handlers.TimedRotatingFileHandler(
            log_dir / "llm_call.log", when="H", interval=1,
            backupCount=72, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        handler.suffix = "%Y%m%d_%H"
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
        _llm_loggers[key] = lg
    return _llm_loggers[key]


class LLMClient:
    """带台账的 LLM 调用器:构造时绑定日志子目录与用途标签,每条调用自动落盘。

    call_llm / call_llm_with_tools 每次实际 API 调用记一行台账
    (INFO:skill/model/tokens/预览,DEBUG:完整 prompt),重试耗尽记 ERROR。
    实例是轻量包装(两个字符串 + 模型表引用 + 缓存的 logger),不持有连接:
    OpenAI 连接仍是模块级懒建单例(_get_client),所有实例共享。
    models 缺省为 DEFAULT_MODELS 的拷贝;AgentEngine 场景传入该 engine 的实例模型表。
    """

    def __init__(self, log_subdir: str = "", label: str = "", models: dict = None):
        self.log_subdir = log_subdir or ""
        self.label = label
        if models is not None and "orchestrator" not in models:
            # 显式传表但缺兜底键:补上默认 orchestrator(拷贝而非原地改调用方的表)
            models = {**models, "orchestrator": DEFAULT_MODELS["orchestrator"]}
        # 未传表时也拷贝一份,不持全局表的活引用:DEFAULT_MODELS 只读靠约定,
        # 拷贝后即便有人原地改全局表,已构造的 client 也不受影响
        self.models = models if models is not None else dict(DEFAULT_MODELS)
        self.logger = _logger_for(self.log_subdir)

    def _record(self, model: str, messages: list, temperature: float,
                max_tokens: int, content: str, usage, attempt: int):
        n_chars = sum(len(str(m.get("content") or "")) for m in messages)
        pt = usage.get("prompt_tokens", 0) if usage else 0
        ct = usage.get("completion_tokens", 0) if usage else 0
        preview = (content or "").replace("\n", " ")[:120]
        self.logger.info(
            f"[LLM] subdir={self.log_subdir or '-'} skill={self.label or '-'} "
            f"model={model} temp={temperature} max_tokens={max_tokens} "
            f"msgs={len(messages)} prompt_chars={n_chars} tokens={pt}+{ct} "
            f"attempt={attempt} preview={preview!r}")
        self.logger.debug("[LLM PROMPT]\n%s", json.dumps(messages, ensure_ascii=False))

    def call_llm(self, messages: list, model: str = None, temperature: float = 0.7,
                 max_tokens: int = 4096, max_retries: int = 3) -> dict:
        """Call LLM via OpenAI-compatible API. Returns {content, usage}."""
        model = model or self.models["orchestrator"]
        client = _get_client()

        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=model, messages=messages,
                    temperature=temperature, max_tokens=max_tokens,
                )
                choice = resp.choices[0]
                content = choice.message.content or ""
                usage = {
                    "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                    "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                }
                # 每次实际 API 调用记一行(空内容的重试同样计费)
                self._record(model, messages, temperature, max_tokens,
                             content, usage, attempt + 1)
                if not content.strip() and attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return {"content": content, "usage": usage}
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                self.logger.error(
                    f"[LLM ERROR] subdir={self.log_subdir or '-'} "
                    f"skill={self.label or '-'} model={model} "
                    f"attempt={attempt + 1} error={e!r}")
                return {"content": f"[LLM Error: {e}]", "usage": {}}

    def call_llm_with_tools(self, messages: list, tools: list, model: str = None,
                            temperature: float = 0.7, max_tokens: int = 4096):
        """Call LLM with tool definitions. Returns the raw response object."""
        model = model or self.models["orchestrator"]
        try:
            resp = _get_client().chat.completions.create(
                model=model, messages=messages, tools=tools,
                temperature=temperature, max_tokens=max_tokens,
            )
        except Exception as e:
            self.logger.error(
                f"[LLM ERROR] subdir={self.log_subdir or '-'} "
                f"skill={self.label or '-'} model={model} error={e!r}")
            raise
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
        }
        self._record(model, messages, temperature, max_tokens,
                     resp.choices[0].message.content or "", usage, 1)
        return resp


# =============================================================================
# Config
# =============================================================================

API_BASE = os.environ.get("API_BASE", "")
API_KEY = os.environ.get("API_KEY", "")

# 内置兜底模型表(只读语义,请勿原地修改):AgentEngine 构建时拷贝此表,
# 再按 agent.yaml 的 models 段合并成实例模型表——无跨 agent 的 merge 残留。
# 约定:orchestrator 是全局兜底模型;skill 以自己的名字作为别名(见 get_model),
# 在 agent.yaml 的 models 段配置同名 key,即为该 skill 的专用模型。
DEFAULT_MODELS = {
    "orchestrator": "deepseek-v4-flash",
}


def get_model(alias: str, models: dict = None) -> str:
    """按别名取模型;未配置时兜底 orchestrator。skill 约定用自己的名字作别名。

    models 缺省用 DEFAULT_MODELS(裸 LLMClient / 测试场景);
    AgentEngine 场景传该实例的模型表。
    """
    m = models if models is not None else DEFAULT_MODELS
    return m.get(alias) or m["orchestrator"]


class LLMError(Exception):
    """LLM 调用失败(SkillLLM.complete 抛出,替代 [LLM Error: 文本标记约定)。"""


class SkillLLM(LLMClient):
    """注入给 skill handler 的 LLM 句柄,按 alias 惰性路由模型。

    框架在每次工具调用前构造并注入(kwargs["llm"]),handler 不 import client。
    模型在每次调用时经 get_model(alias, self.models) 解析;models 由所属
    AgentEngine 经 wrapper 传入(每 engine 一份,多 agent 互不串扰)。
    台账 label 固定为 alias(即 skill 名),日志子目录由构造方传入。
    """

    def __init__(self, alias: str, log_subdir: str = "", models: dict = None):
        super().__init__(log_subdir=log_subdir, label=alias, models=models)
        self.alias = alias

    def complete(self, messages: list, temperature: float = 0.7,
                 max_tokens: int = 4096) -> str:
        """调用 alias 绑定的模型,返回 content 文本;失败抛 LLMError。"""
        resp = self.call_llm(
            messages,
            model=get_model(self.alias, self.models),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = (resp.get("content") or "").strip()
        if not content or content.startswith("[LLM Error:"):
            raise LLMError(content or "empty response")
        return content


# =============================================================================
# OpenAI client (lazy-initialized)
# =============================================================================
# 进程级连接单例:LLMClient 实例是轻量包装,不持有连接;此处懒建一次全局复用。

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