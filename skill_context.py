#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill Context & Adapter: The bridge between portable skills and the host agent.

Architecture:
  - Skill: Pure business logic. Declares inputs/outputs as typed interface (SKILL.yaml).
           Does NOT know about session, stage, or any framework concept.
  - SkillContext: Runtime context passed to adapters. Encapsulates:
           - session_id: current session identifier
           - store: DataStore instance for reading/writing stage data
           - session reference: for accessing conversation history
           - biz: BizProxy for reading/writing business fields via DataStore
  - SkillAdapter: Written by the agent integrator (not the skill developer).
           Knows how to:
           1. resolve_inputs(ctx): read from DataStore → skill inputs
           2. write_output(ctx, result): skill outputs → DataStore
           3. get_tool_params: which params to expose to LLM (optional)
  - SkillLoaderV2: Uses adapter to wire everything together at runtime.

Skill developer writes:
    def run_episode_planning(understanding: dict, brief: dict) -> list: ...

Agent integrator writes:
    class PlanningAdapter(SkillAdapter):
        def resolve_inputs(self, ctx: SkillContext) -> dict:
            return {
                "understanding": ctx.store.get_field(ctx.session_id, "understanding"),
                "brief": ctx.store.get_field(ctx.session_id, "brief"),
            }
        def write_output(self, ctx: SkillContext, result):
            ctx.store.set_field(ctx.session_id, "planning", result)
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

logger = logging.getLogger(__name__)


class BizProxy:
    """通过 DataStore 访问业务字段的轻量代理。

    adapter/handler 通过 ctx.biz["field"] 读写业务数据，
    底层直接调用 store.get_field / store.set_field。
    """

    def __init__(self, store, session_id: str):
        self._store = store
        self._sid = session_id

    def __getitem__(self, key):
        return self._store.get_field(self._sid, key)

    def __setitem__(self, key, value):
        self._store.set_field(self._sid, key, value)


class SkillContext:
    """Adapter 运行时上下文：封装 store、session_id、会话元信息。

    这是 adapter 与外部世界交互的唯一入口。adapter 不应直接持有 session 或 store 引用，
    而是通过 ctx 统一访问。
    """

    def __init__(self, session_id: str, store, session):
        """
        Args:
            session_id: 当前会话 ID
            store: DataStore 实例（用于读写阶段产出数据）
            session: BaseSession 实例（用于访问会话历史等框架级字段）
        """
        self.session_id = session_id
        self.store = store
        self._session = session

    def last_user_message(self) -> str:
        """获取最新一条用户消息。"""
        if self._session.history:
            for msg in reversed(self._session.history):
                if msg.get("role") == "user":
                    return msg.get("content", "")
        return ""

    @property
    def biz(self):
        """业务数据访问代理：读写走 DataStore。"""
        return BizProxy(self.store, self.session_id)

    @property
    def session(self):
        """访问 BaseSession 对象（history, chat_events, turn_count 等框架级字段）。"""
        return self._session


class SkillAdapter(ABC):
    """
    Base class for wiring a skill to a specific agent's data layer.

    The agent integrator subclasses this to define:
    - How to extract skill inputs from DataStore (resolve_inputs)
    - How to write skill outputs back to DataStore (write_output)
    - Which parameters to expose to LLM in tool schema (get_tool_params)

    One adapter per skill (or per tool if fine-grained control needed).
    """

    @abstractmethod
    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        """
        Extract the skill's required inputs from the DataStore via ctx.

        Args:
            ctx: SkillContext with store, session_id, and session reference

        Returns:
            Dict mapping parameter names to values.
            e.g. {"understanding": ctx.store.get_field(ctx.session_id, "understanding")}
        """

    @abstractmethod
    def write_output(self, ctx: SkillContext, result: Any):
        """
        Write the skill's output to the DataStore via ctx.

        Args:
            ctx: SkillContext with store and session_id
            result: The skill's return value (after _output_data extraction)
        """

    def validate_inputs(self, inputs: Dict[str, Any]) -> str:
        """
        Optional: validate that resolved inputs are sufficient.
        Returns error message string if invalid, empty string if OK.
        Override to add custom validation.
        """
        return ""

    def get_tool_params(self) -> Dict[str, dict]:
        """
        Declare which parameters to expose to LLM for each tool.

        Override this to let the LLM fill specific simple parameters.
        Tools not listed here → zero parameters (all inputs from DataStore).

        Returns:
            {tool_name: {param_name: {"type": str, "description": str, "required": bool}}}
        """
        return {}

    def resolve_prompt_context(self, ctx: 'SkillContext') -> str:
        """
        Optional: return dynamic context to append to system prompt.
        Only called on the adapter associated with SYSTEM.md (system adapter).
        Override to provide session state, progress info, etc.
        """
        return ""

    def format_llm_response(self, tool_name: str, result: Any) -> Any:
        """
        将 handler 返回值转为给 orchestrator LLM 看的精简结果。

        默认实现：剥离 _output_data 字段（持久化数据不回传，省 token）。
        业务可覆写：自定义返回摘要、只返回状态码等。
        """
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "_output_data" in parsed:
                    del parsed["_output_data"]
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
            return result
        if isinstance(result, dict) and "_output_data" in result:
            return {k: v for k, v in result.items() if k != "_output_data"}
        return result


class PassthroughAdapter(SkillAdapter):
    """Default adapter for self-contained skills (no DataStore wiring).

    Used as default_adapter for common/shared skills that manage their own I/O.
    Injects SkillContext directly; write_output is a no-op.
    """

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        return {"ctx": ctx}

    def write_output(self, ctx: SkillContext, result: Any):
        pass