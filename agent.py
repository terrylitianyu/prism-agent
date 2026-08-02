#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generic Agent Framework: Agent Loop + DataStore + SkillLoaderV2.

This module is application-agnostic. Specific agents (e.g. dm_agent) configure
it at startup via init_agent().
"""

import json
import logging
import logging.handlers
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import contextvars

from json_repair import repair_json

from core import (
    WORKDIR, SESSION_DIR, SKILLS_DIR, ADAPTERS_DIR,
    TOKEN_THRESHOLD, MAX_TOOL_OUTPUT,
)
from client import call_llm, call_llm_with_tools, MODELS

logger = logging.getLogger(__name__)

# Agent loop dedicated logger — logs full LLM input/output for the orchestrator
_LOOP_LOG_DIR = WORKDIR / "logs"
_LOOP_LOG_DIR.mkdir(parents=True, exist_ok=True)
_loop_logger = logging.getLogger("agent.loop")
_loop_handler = logging.handlers.TimedRotatingFileHandler(
    _LOOP_LOG_DIR / "agent_loop.log", when="H", interval=1,
    backupCount=72, encoding="utf-8"
)
_loop_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
_loop_handler.suffix = "%Y%m%d_%H"
_loop_logger.addHandler(_loop_handler)
_loop_logger.setLevel(logging.DEBUG)


# =============================================================================
# SECTION: Session
# =============================================================================

from session import BaseSession
from session_context import set_current_session, get_current_session
from skill_context import SkillContext

# Module-level state — set by init_agent()
_default_session = None
_store = None
SKILLS = None
TOOLS = None
TOOL_HANDLERS = None

# Agent loop config — set by init_agent() from agent.yaml
_loop_config = {
    "max_iterations": 15,
    "temperature": 0.3,
    "max_tokens": 4096,
}


# =============================================================================
# SECTION: Initialization
# =============================================================================

def init_agent(agent_dir: Path, store=None):
    """Initialize the Agent framework. Called by the application at startup.

    Args:
        agent_dir: Path to the agent's adapter directory (e.g. ADAPTERS_DIR / "dm_agent")
        store: DataStore instance for persistence

    Reads agent.yaml from agent_dir for:
    - skill_dirs: which skill directories to scan
    - models: LLM model mapping (overrides client.MODELS)
    - loop: agent loop parameters (max_iterations, temperature, max_tokens)
    """
    global _default_session, _store, SKILLS, TOOLS, TOOL_HANDLERS, _loop_config

    if store:
        _store = store

    # Create default session (always BaseSession — no subclasses)
    _default_session = BaseSession()
    set_current_session(_default_session)

    # Load agent.yaml config for models and loop params
    import yaml
    config_path = agent_dir / "agent.yaml"
    agent_config = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                agent_config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load agent.yaml: {e}")

    # Configure MODELS from agent.yaml
    models_config = agent_config.get("models")
    if models_config:
        from client import configure_models
        configure_models(models_config)

    # Configure loop params from agent.yaml
    loop_config = agent_config.get("loop")
    if loop_config and isinstance(loop_config, dict):
        _loop_config.update(loop_config)

    # Initialize SkillLoaderV2
    from skill_loader import SkillLoaderV2
    SKILLS = SkillLoaderV2(agent_dir=agent_dir, get_context=_get_context)

    # Build TOOLS and TOOL_HANDLERS
    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "load_skill",
                "description": "加载指定skill的详细步骤说明到上下文中。当需要执行某个skill时，先调用此工具获取该skill的详细指令。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "skill名称"}
                    },
                    "required": ["name"]
                }
            }
        },
    ]

    TOOL_HANDLERS = {
        "load_skill": lambda **kw: _tool_load_skill(**kw),
    }

    # Merge all skill tool handlers + schemas from SkillLoaderV2
    for _name, _handler in SKILLS.get_tool_handlers().items():
        if _name not in TOOL_HANDLERS:
            TOOL_HANDLERS[_name] = _handler
            logger.info(f"[V2] Registered tool from SKILL.yaml: {_name}")
        else:
            logger.warning(f"[V2] Tool '{_name}' already in TOOL_HANDLERS, keeping manual version")

    TOOLS.extend(SKILLS.get_tool_schemas())
    logger.info(f"[V2] Auto-generated {len(SKILLS.get_tool_schemas())} tool schemas from SKILL.yaml")


# =============================================================================
# SECTION: Context & Helpers
# =============================================================================

def _get_session():
    """Get session from current context. Falls back to default."""
    return get_current_session() or _default_session


def _get_context() -> SkillContext:
    """Build a SkillContext from current module state (for SkillLoaderV2)."""
    session = _get_session()
    sid = getattr(session, "session_id", None)
    return SkillContext(session_id=sid, store=_store, session=session)


def _tool_load_skill(name: str = "", **kw) -> str:
    """Load a skill's knowledge into context."""
    return SKILLS.load(name)


def _build_system_prompt() -> str:
    """Build system prompt via SkillLoaderV2 (delegates to SYSTEM.md + adapter)."""
    return SKILLS.build_system_prompt()


# =============================================================================
# SECTION: Agent Loop
# =============================================================================

def estimate_tokens(text: str) -> int:
    """Rough token estimate (Chinese ~1.5 tokens/char)."""
    return int(len(text) * 1.5)


# =============================================================================
# SECTION: Context Compression
# =============================================================================

def _find_tail_boundary(history: list, rounds: int) -> int:
    """从后往前找 N 个 user 消息，返回 tail 的起始索引。"""
    user_count = 0
    for i in range(len(history) - 1, 0, -1):
        if history[i].get("role") == "user":
            user_count += 1
            if user_count >= rounds:
                return i
    return 1  # fallback: 只保留 system prompt 作为 head


class _SummarizeFailed(Exception):
    """摘要生成失败的内部信号，触发 _compress_context 的降级通道。"""


def _summarize_messages(messages: list) -> str:
    """调用轻量模型对中间消息生成结构化摘要。"""
    # 构建摘要输入
    summary_input = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if role == "tool":
            # 工具结果只保留前200字符避免摘要输入过大
            content = content[:200] + ("..." if len(content) > 200 else "")
        if content:
            summary_input.append(f"[{role}]: {content}")

    summary_text = "\n".join(summary_input)
    # 限制摘要输入长度
    if len(summary_text) > 10000:
        summary_text = summary_text[:10000] + "\n...(truncated)"

    prompt = [
        {"role": "system", "content": (
            "你是一个对话摘要助手。请将以下对话历史压缩为简洁的结构化摘要。\n"
            "格式要求：\n"
            "- 关键决策：列出已做的决定\n"
            "- 当前状态：当前进度和中间结果\n"
            "- 待处理：尚未完成的事项\n"
            "用中文回复，尽量精简。"
        )},
        {"role": "user", "content": summary_text},
    ]

    # 摘要模型可在 agent.yaml 的 loop.summary_model 配置，默认用轻量模型
    summary_model = _loop_config.get("summary_model") or MODELS.get("intent", MODELS["orchestrator"])
    try:
        resp = call_llm(
            messages=prompt,
            model=summary_model,
            temperature=0.2,
            max_tokens=1024,
        )
    except Exception as e:
        # call_llm 自身的 try 覆盖不到的路径（如客户端构造失败）
        raise _SummarizeFailed(f"call_llm raised: {e}")

    content = (resp.get("content") or "").strip()
    # call_llm 失败时不抛异常，而是把 "[LLM Error: ...]" 放在 content 里返回，
    # 必须显式检测——否则错误文本会被当成摘要注入上下文（静默污染）
    if not content or content.startswith("[LLM Error:"):
        raise _SummarizeFailed(content or "empty summary returned")
    return content


def _compress_context(conversation_history: list) -> list:
    """压缩对话历史：tool output 裁剪 + middle 摘要替换。"""
    total_tokens = sum(
        estimate_tokens(m.get("content", "")) for m in conversation_history
    )
    if total_tokens < TOKEN_THRESHOLD:
        return conversation_history

    _loop_logger.debug(
        f"[COMPRESS] Token estimate {total_tokens} >= {TOKEN_THRESHOLD}, compressing..."
    )

    # Step 1: Tool output 预裁剪
    for msg in conversation_history:
        if msg.get("role") == "tool" and len(msg.get("content", "")) > 2000:
            content = msg["content"]
            msg["content"] = content[:500] + "\n...[truncated]...\n" + content[-500:]

    # Re-check after pruning
    total_tokens = sum(
        estimate_tokens(m.get("content", "")) for m in conversation_history
    )
    if total_tokens < TOKEN_THRESHOLD:
        _loop_logger.debug("[COMPRESS] Under threshold after tool output pruning.")
        return conversation_history

    # Step 2: Head-Middle-Tail split
    head = conversation_history[:1]  # system prompt
    tail_start = _find_tail_boundary(conversation_history, 4)
    tail = conversation_history[tail_start:]
    middle = conversation_history[1:tail_start]

    if not middle:
        # 无 middle 可压，但仍可能超限 —— 跳过摘要，直接进入 Step 4 兜底截断
        compressed = conversation_history
    else:
        # Step 3: 优先 LLM 摘要；失败则降级为"丢弃 middle + 占位说明"（双通道降级）
        _loop_logger.debug(
            f"[COMPRESS] Summarizing {len(middle)} middle messages "
            f"(keeping {len(tail)} tail messages)."
        )
        try:
            summary = _summarize_messages(middle)
            note = f"[Context Summary]\n{summary}"
        except _SummarizeFailed as e:
            _loop_logger.warning(
                f"[COMPRESS] Summarization failed ({e}); "
                f"falling back to dropping middle messages."
            )
            logger.warning(f"Context summarization failed, degraded to dropping middle: {e}")
            note = "[Context Summary]\n(早期对话因上下文超限被省略，摘要生成失败)"
        compressed = head + [{"role": "system", "content": note}] + tail

    # Step 4: 兜底——压缩后仍超阈值时，从最老的 tail 消息开始丢弃
    new_tokens = sum(estimate_tokens(m.get("content") or "") for m in compressed)
    if new_tokens >= TOKEN_THRESHOLD:
        _loop_logger.warning(
            f"[COMPRESS] Still over threshold ({new_tokens} >= {TOKEN_THRESHOLD}); "
            f"hard-truncating oldest messages."
        )
        compressed = _hard_truncate_oldest(compressed)
        new_tokens = sum(estimate_tokens(m.get("content") or "") for m in compressed)

    _loop_logger.debug(f"[COMPRESS] Done: {total_tokens} -> {new_tokens} tokens.")
    return compressed


def _hard_truncate_oldest(messages: list) -> list:
    """最终兜底：保留头部（system + 摘要说明）和最新消息，从最老的 tail 消息开始丢，
    直到估算 tokens 低于阈值。不抛异常；最少保留 3 条（system、摘要说明、最新一条）。"""
    result = list(messages)
    while len(result) > 3 and sum(
        estimate_tokens(m.get("content") or "") for m in result
    ) >= TOKEN_THRESHOLD:
        del result[2]  # 丢弃最老的 tail 消息（0=system prompt, 1=摘要说明）
    return result


# =============================================================================
# SECTION: Tool Parallel Execution
# =============================================================================

_tool_executor = ThreadPoolExecutor(max_workers=8)


def _execute_tools_parallel(tool_calls, tool_handlers):
    """并行执行多个 tool calls，返回有序结果列表 [(func_name, args, result), ...]。"""
    results = [None] * len(tool_calls)

    def _run(idx, tc):
        func_name = tc.function.name
        args, arg_warning = _parse_tool_args(tc.function.arguments)
        resolved_name, name_error = _resolve_tool_name(func_name, tool_handlers)

        if not resolved_name:
            return idx, func_name, args, name_error

        handler = tool_handlers[resolved_name]
        try:
            result = handler(**args)
        except Exception as e:
            result = json.dumps({"error": str(e)})
            logger.error(f"Tool {resolved_name} failed: {e}", exc_info=True)

        if arg_warning:
            result = arg_warning + "\n" + result
        return idx, func_name, args, result

    # 每个 future 独立 copy 一份 Context，避免多线程并发进入同一个 Context 时
    # 抛 "cannot enter context: ... is already entered"
    futures = {}
    for i, tc in enumerate(tool_calls):
        ctx = contextvars.copy_context()
        futures[_tool_executor.submit(ctx.run, _run, i, tc)] = i
    for future in as_completed(futures):
        idx, func_name, args, result = future.result()
        results[idx] = (func_name, args, result)
    return results


# =============================================================================
# SECTION: Tool Error Recovery
# =============================================================================

def _resolve_tool_name(func_name: str, handlers: dict):
    """校验工具名是否存在，返回 (resolved_name_or_None, error_or_empty)."""
    if func_name in handlers:
        return func_name, ""
    available = ", ".join(sorted(handlers.keys()))
    return None, json.dumps({
        "error": f"Tool '{func_name}' does not exist.",
        "available_tools": available,
        "hint": "Please use one of the available tools listed above."
    }, ensure_ascii=False)


def _parse_tool_args(arguments: str):
    """宽容解析 JSON 参数，返回 (args_dict, warning_or_empty)."""
    if not arguments:
        return {}, ""
    try:
        return json.loads(arguments), ""
    except json.JSONDecodeError:
        try:
            repaired = repair_json(arguments, return_objects=True)
            if isinstance(repaired, dict):
                _loop_logger.debug(f"[TOOL_ARGS] Auto-repaired JSON: {arguments[:100]}")
                return repaired, "[Warning: JSON args auto-repaired]"
            return {}, f"[Error: json_repair result is not a dict. Original: {arguments[:200]}]"
        except Exception:
            return {}, f"[Error: Failed to parse JSON arguments. Original: {arguments[:200]}]"


def agent_loop_stream(user_message: str, conversation_history: list, session_dir: Path = None):
    """
    Generator that yields SSE events during the agent loop.
    Events: tool_call, tool_result, instant_reply, error, done, usage, state
    """
    session = _get_session()
    system_prompt = _build_system_prompt()
    conversation_history.clear()
    conversation_history.append({"role": "system", "content": system_prompt})
    for h in session.get_recent_history(20):
        conversation_history.append({"role": h["role"], "content": h["content"]})

    # Add current user message
    conversation_history.append({"role": "user", "content": user_message})
    session.add_turn("user", user_message)
    session.chat_events.append({"event": "user", "data": user_message})

    # Token usage tracking
    usage_log = []

    max_iterations = _loop_config["max_iterations"]
    for iteration in range(max_iterations):
        # Context compression — reduce token count if over threshold
        conversation_history = _compress_context(conversation_history)

        # Log agent loop input
        _loop_logger.debug(
            f"\n{'='*80}\n[ITERATION {iteration}] INPUT messages "
            f"({len(conversation_history)} msgs):\n{'='*80}"
        )
        for i, msg in enumerate(conversation_history):
            role = msg.get("role", "?")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls")
            _loop_logger.debug(f"\n--- messages[{i}] role={role} ---\n{content}")
            if tool_calls:
                _loop_logger.debug(
                    f"  tool_calls: {json.dumps(tool_calls, ensure_ascii=False)}"
                )

        try:
            resp = call_llm_with_tools(
                messages=conversation_history,
                tools=TOOLS,
                model=MODELS["orchestrator"],
                temperature=_loop_config["temperature"],
                max_tokens=_loop_config["max_tokens"],
            )
        except Exception as e:
            yield {"event": "error", "data": f"LLM调用失败: {e}"}
            return

        choice = resp.choices[0]
        message = choice.message

        # Log output
        _loop_logger.debug(
            f"\n{'='*80}\n[ITERATION {iteration}] OUTPUT:\n{'='*80}"
        )
        _loop_logger.debug(f"  content: {message.content or '(empty)'}")
        if message.tool_calls:
            for tc in message.tool_calls:
                _loop_logger.debug(
                    f"  tool_call: {tc.function.name}({tc.function.arguments})"
                )
        else:
            _loop_logger.debug("  (no tool_calls — final response)")
        _loop_logger.debug(
            f"  usage: prompt_tokens="
            f"{resp.usage.prompt_tokens if resp.usage else 0}, "
            f"completion_tokens={resp.usage.completion_tokens if resp.usage else 0}"
        )

        if resp.usage:
            usage_log.append({
                "iteration": iteration,
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            })

        # No tool calls — final response
        if not message.tool_calls:
            final_text = message.content or ""
            session.add_turn("assistant", final_text)
            session.chat_events.append({"event": "done", "data": final_text})
            yield {"event": "done", "data": final_text}
            # Token usage summary
            total_prompt = sum(u["prompt_tokens"] for u in usage_log)
            total_completion = sum(u["completion_tokens"] for u in usage_log)
            usage_data = {
                "iterations": usage_log,
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_tokens": total_prompt + total_completion,
            }
            session.chat_events.append({"event": "usage", "data": usage_data})
            yield {"event": "usage", "data": usage_data}
            if session_dir:
                session.save(session_dir)
            return

        # Process tool calls
        conversation_history.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in message.tool_calls
            ]
        })

        # Execute tools — parallel if multiple, serial if single
        if len(message.tool_calls) >= 2:
            # Parallel execution
            _loop_logger.debug(
                f"[PARALLEL] Executing {len(message.tool_calls)} tools in parallel"
            )
            parallel_results = _execute_tools_parallel(message.tool_calls, TOOL_HANDLERS)

            for i, (func_name, args, result) in enumerate(parallel_results):
                tc = message.tool_calls[i]
                # Truncate if too long
                if len(result) > MAX_TOOL_OUTPUT:
                    result = result[:MAX_TOOL_OUTPUT] + "...(truncated)"

                _loop_logger.debug(f"\n  [TOOL RESULT] {func_name} -> {result}")

                yield {"event": "tool_call", "data": {"name": func_name, "args": args}}
                session.chat_events.append(
                    {"event": "tool_call", "data": {"name": func_name, "args": args}}
                )
                yield {
                    "event": "tool_result",
                    "data": {"name": func_name, "result": result[:500]},
                }
                session.chat_events.append(
                    {"event": "tool_result", "data": {"name": func_name, "result": result[:500]}}
                )

                # instant_reply check
                _check_instant_reply(result, session)
                for evt in _yield_instant_reply(result):
                    yield evt

                # Append tool result to conversation
                conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            # Serial execution (single tool call)
            tc = message.tool_calls[0]
            func_name = tc.function.name
            args, arg_warning = _parse_tool_args(tc.function.arguments)
            resolved_name, name_error = _resolve_tool_name(func_name, TOOL_HANDLERS)

            yield {"event": "tool_call", "data": {"name": func_name, "args": args}}
            session.chat_events.append(
                {"event": "tool_call", "data": {"name": func_name, "args": args}}
            )

            if not resolved_name:
                result = name_error
            else:
                handler = TOOL_HANDLERS[resolved_name]
                try:
                    result = handler(**args)
                except Exception as e:
                    result = json.dumps({"error": str(e)})
                    logger.error(f"Tool {resolved_name} failed: {e}", exc_info=True)

                if arg_warning:
                    result = arg_warning + "\n" + result

            # Truncate if too long
            if len(result) > MAX_TOOL_OUTPUT:
                result = result[:MAX_TOOL_OUTPUT] + "...(truncated)"

            _loop_logger.debug(f"\n  [TOOL RESULT] {func_name} -> {result}")

            yield {
                "event": "tool_result",
                "data": {"name": func_name, "result": result[:500]},
            }
            session.chat_events.append(
                {"event": "tool_result", "data": {"name": func_name, "result": result[:500]}}
            )

            # instant_reply check
            for evt in _yield_instant_reply(result):
                yield evt

            # Append tool result to conversation
            conversation_history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # Max iterations reached
    session.chat_events.append(
        {"event": "done", "data": "处理完成（达到最大迭代次数）"}
    )
    yield {"event": "done", "data": "处理完成（达到最大迭代次数）"}
    total_prompt = sum(u["prompt_tokens"] for u in usage_log)
    total_completion = sum(u["completion_tokens"] for u in usage_log)
    usage_data = {
        "iterations": usage_log,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
    }
    session.chat_events.append({"event": "usage", "data": usage_data})
    yield {"event": "usage", "data": usage_data}
    if session_dir:
        session.save(session_dir)


def _yield_instant_reply(result: str):
    """Check tool result for instant_reply field, yield event if found."""
    try:
        result_data = json.loads(result)
        instant_reply = (
            result_data.get("instant_reply")
            if isinstance(result_data, dict)
            else None
        )
        if instant_reply:
            yield {"event": "instant_reply", "data": instant_reply}
    except (json.JSONDecodeError, TypeError):
        pass


def _check_instant_reply(result: str, session):
    """Append instant_reply to session chat_events if present."""
    try:
        result_data = json.loads(result)
        instant_reply = (
            result_data.get("instant_reply")
            if isinstance(result_data, dict)
            else None
        )
        if instant_reply:
            session.chat_events.append(
                {"event": "instant_reply", "data": instant_reply}
            )
    except (json.JSONDecodeError, TypeError):
        pass