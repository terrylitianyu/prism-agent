#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill Loader v2: Adapter-based skill registration.

Architecture:
  - SKILL.yaml: Pure interface declaration (input/output types, handler paths, descriptions)
  - SkillAdapter: Agent-side class that maps DataStore ↔ skill params + declares LLM params
  - SkillContext: Runtime context passed to adapters (session_id, store, session ref)
  - This loader: Reads SKILL.yaml, resolves handlers, uses adapter to build wrappers

Flow:
  1. Scan skills/ for SKILL.yaml
  2. For each skill, look up its adapter from SKILL_ADAPTERS registry
  3. Build wrapper: adapter.resolve_inputs(ctx) → handler(**inputs) → adapter.write_output(ctx, result)
  4. Register wrapper into TOOL_HANDLERS
  5. Auto-generate OpenAI tool schemas from SKILL.yaml descriptions + adapter.get_tool_params()
"""

import importlib
import inspect
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from .skill_context import SkillAdapter, SkillContext
from .client import SkillLLM

logger = logging.getLogger(__name__)


class SkillToolDef:
    """Parsed tool definition from SKILL.yaml."""

    def __init__(self, name: str, handler_path: str, description: str = "",
                 inputs: dict = None, output: str = None, pass_kwargs: bool = True):
        self.name = name
        self.handler_path = handler_path  # e.g. "handlers.run_episode_planning"
        self.description = description    # Tool description (for LLM tool schema)
        self.inputs = inputs or {}        # {param_name: type_hint} (for documentation only)
        self.output = output              # output type hint (for documentation only)
        self.pass_kwargs = pass_kwargs    # If True, forward orchestrator kwargs


class SkillManifest:
    """Parsed SKILL.yaml for one skill."""

    def __init__(self, name: str, skill_dir: Path, tools: list = None,
                 config_file: str = None, description: str = ""):
        self.name = name
        self.skill_dir = skill_dir
        self.tools = tools or []          # List[SkillToolDef]
        self.config_file = config_file
        self.description = description


def load_skill_yaml(yaml_path: Path) -> Optional[SkillManifest]:
    """Parse a SKILL.yaml file into a SkillManifest."""
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load {yaml_path}: {e}")
        return None

    if not data or not isinstance(data, dict):
        return None

    skill_dir = yaml_path.parent
    name = data.get("name", skill_dir.name)
    config_file = data.get("config")
    description = data.get("description", "")

    tools = []
    for td in data.get("tools", []):
        if not isinstance(td, dict):
            continue
        tool_def = SkillToolDef(
            name=td.get("name", ""),
            handler_path=td.get("handler", ""),
            description=td.get("description", ""),
            inputs=td.get("inputs", {}),
            output=td.get("output"),
            pass_kwargs=td.get("pass_kwargs", True),
        )
        tools.append(tool_def)

    return SkillManifest(
        name=name,
        skill_dir=skill_dir,
        tools=tools,
        config_file=config_file,
        description=description,
    )


def _resolve_handler(skill_dir: Path, handler_path: str) -> Optional[Callable]:
    """
    Resolve "handlers.func_name" to an actual callable.

    Module path is derived from skill_dir relative to project root (WORKDIR).
    Follows Anthropic Skill convention: prefer <skill>/scripts/<module>.py,
    fall back to <skill>/<module>.py for legacy flat layouts.

    Examples:
      handler_path="handlers.foo" + skill_dir=skills/x/y →
        try skills.x.y.scripts.handlers.foo, then skills.x.y.handlers.foo
      handler_path="scripts.handlers.foo" (explicit) → resolved as-is
    """
    parts = handler_path.rsplit(".", 1)
    if len(parts) != 2:
        logger.error(f"Invalid handler path: {handler_path} (expected 'module.function')")
        return None

    module_name, func_name = parts

    # Build module path from skill_dir relative to WORKDIR (project root, always on sys.path)
    from .core import WORKDIR
    try:
        rel_path = skill_dir.resolve().relative_to(WORKDIR.resolve())
        # Convert path separators to dots: skills/dm_agent/modification → skills.dm_agent.modification
        package_path = ".".join(rel_path.parts)
    except ValueError:
        # Fallback: use old style
        package_path = f"skills.{skill_dir.name}"

    # Try scripts/ first (Anthropic-style), then flat (legacy).
    # If the user already wrote "scripts.xxx" explicitly, the first candidate
    # becomes "<pkg>.scripts.scripts.xxx" (which will fail) and we fall through
    # to "<pkg>.scripts.xxx" naturally.
    candidates = []
    if not module_name.startswith("scripts."):
        candidates.append(f"{package_path}.scripts.{module_name}")
    candidates.append(f"{package_path}.{module_name}")

    last_error = None
    for full_module in candidates:
        try:
            mod = importlib.import_module(full_module)
        except ImportError as e:
            last_error = e
            continue
        handler = getattr(mod, func_name, None)
        if handler is None:
            logger.error(f"Function '{func_name}' not found in module '{full_module}'")
            return None
        return handler

    logger.error(
        f"Failed to import handler '{handler_path}' from {skill_dir} "
        f"(tried: {candidates}). Last error: {last_error}"
    )
    return None


def _load_config(skill_dir: Path, config_file: str) -> dict:
    """Load skill config from the skill's own directory."""
    if not config_file:
        return {}
    path = skill_dir / config_file
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load config {path}: {e}")
    return {}


def build_tool_wrapper(
    tool_def: SkillToolDef,
    adapter: SkillAdapter,
    get_context: Callable,
    handler: Callable,
    llm_params: set = None,
    skill_name: str = "",
) -> Callable:
    """
    Build a wrapper that:
    1. Uses adapter.resolve_inputs(ctx) to get skill inputs from DataStore
    2. Calls the pure handler function (with an injected `llm` handle)
    3. Uses adapter.write_output(ctx, result) to persist output to DataStore
    4. Returns a JSON string for the orchestrator

    Args:
        get_context: Callable that returns a SkillContext instance at call time.
        llm_params: Set of param names that LLM provides. These override adapter inputs.
        skill_name: Skill name from SKILL.yaml; bound to the injected SkillLLM handle.
    """
    llm_params = llm_params or set()

    # 只在 handler 能接收时才注入 llm(显式声明 llm 参数,或带 **kw 吸收):
    # 严格签名的确定性 handler(不调 LLM,无 **kw)不多塞参数,避免 TypeError。
    # 构建期内省一次即可,每次调用不重复开销。
    try:
        _sig_params = inspect.signature(handler).parameters
        accepts_llm = (
            "llm" in _sig_params
            or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _sig_params.values())
        )
    except (TypeError, ValueError):
        accepts_llm = False  # 不可内省的对象(如部分 builtin)保持注入前行为

    def wrapper(**orchestrator_kwargs) -> str:
        # Get current SkillContext at call time (not at registration time!)
        ctx = get_context()

        # 1. Adapter resolves inputs from DataStore via ctx
        try:
            inputs = adapter.resolve_inputs(ctx)
        except Exception as e:
            logger.error(
                f"Adapter {type(adapter).__name__}.resolve_inputs failed: {e}",
                exc_info=True,
            )
            return json.dumps({
                "status": "error",
                "message": f"adapter resolve_inputs failed: {e}",
            }, ensure_ascii=False)

        # 2. Validate inputs
        try:
            error = adapter.validate_inputs(inputs)
        except Exception as e:
            logger.error(
                f"Adapter {type(adapter).__name__}.validate_inputs failed: {e}",
                exc_info=True,
            )
            return json.dumps({
                "status": "error",
                "message": f"adapter validate_inputs failed: {e}",
            }, ensure_ascii=False)
        if error:
            return json.dumps({"status": "error", "message": error}, ensure_ascii=False)

        # 3. Only pass the inputs that the handler declares (from SKILL.yaml)
        kwargs = {}
        for param_name in tool_def.inputs:
            if param_name in inputs:
                kwargs[param_name] = inputs[param_name]

        # 4. LLM-provided params override adapter inputs
        for k, v in orchestrator_kwargs.items():
            if k in llm_params:
                kwargs[k] = v
            elif tool_def.pass_kwargs and k not in kwargs:
                kwargs[k] = v

        # 4.5 Inject the skill's LLM handle (reserved kwarg: injected AFTER the
        #     override step, so an LLM-passed param named "llm" cannot replace it;
        #     skipped entirely for handlers that can't accept it)
        if accepts_llm:
            kwargs["llm"] = SkillLLM(skill_name)

        # 5. Call the handler
        try:
            result = handler(**kwargs)
        except Exception as e:
            logger.error(f"Skill tool '{tool_def.name}' failed: {e}", exc_info=True)
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

        # 6. Extract output data and write to DataStore via adapter
        #    持久化失败不影响返回给 LLM 的结果（数据已经算出来了）：
        #    落 error 日志 + 在结果里附加 _persistence_warning 提醒 orchestrator
        persistence_warning = ""
        if tool_def.output and result is not None:
            try:
                output_data = _extract_output_data(result)
                if output_data is not None:
                    adapter.write_output(ctx, output_data)
            except Exception as e:
                logger.error(
                    f"Adapter {type(adapter).__name__}.write_output failed "
                    f"(result NOT persisted): {e}",
                    exc_info=True,
                )
                persistence_warning = (
                    f"write_output failed, result was NOT persisted to DataStore: {e}"
                )

        # 7. Let adapter format the result for orchestrator LLM
        try:
            formatted = adapter.format_llm_response(tool_def.name, result)
        except Exception as e:
            logger.error(
                f"Adapter {type(adapter).__name__}.format_llm_response failed: {e}; "
                f"falling back to raw result.",
                exc_info=True,
            )
            formatted = result

        if persistence_warning:
            formatted = _attach_persistence_warning(formatted, persistence_warning)

        if isinstance(formatted, str):
            return formatted
        return json.dumps(formatted, ensure_ascii=False, default=str)

    wrapper.__name__ = tool_def.name
    wrapper.__doc__ = f"Auto-wrapped skill tool: {tool_def.name}"
    return wrapper


def _extract_output_data(result) -> Any:
    """
    Extract actual payload from handler return value.
    Convention: handler returns a dict/JSON with '_output_data' key
    to explicitly mark what should be persisted.
    """
    if result is None:
        return None

    # Already a dict/list with explicit marker
    if isinstance(result, (dict, list)):
        if isinstance(result, dict) and "_output_data" in result:
            return result["_output_data"]
        # If no status envelope, treat entire thing as output
        if isinstance(result, dict) and "status" not in result:
            return result
        return None

    # JSON string
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and "_output_data" in parsed:
                return parsed["_output_data"]
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _attach_persistence_warning(formatted: Any, warning: str) -> Any:
    """把持久化警告附加到返回给 orchestrator 的结果上（dict / JSON str / 普通 str 均可）。"""
    if isinstance(formatted, dict):
        return {**formatted, "_persistence_warning": warning}
    if isinstance(formatted, str):
        try:
            parsed = json.loads(formatted)
            if isinstance(parsed, dict):
                parsed["_persistence_warning"] = warning
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return f"{formatted}\n[_persistence_warning] {warning}"
    return formatted


class SkillLoaderV2:
    """
    Unified skill loader: driven by agent_dir (adapters/<agent>/).

    Reads agent.yaml for skill_dirs config, auto-discovers adapters from agent_dir,
    then scans skill directories for SKILL.md and SKILL.yaml.

    - SKILL.md: Loaded for on-demand injection into LLM context via load().
    - SKILL.yaml + adapter: Auto-registers tool handlers with session wiring.
    - Skills with SKILL.md only (no adapter): available via load() but tools not registered.

    Usage:
        loader = SkillLoaderV2(agent_dir=ADAPTERS_DIR / "dm_agent", get_context=_get_context)
        handlers = loader.get_tool_handlers()
        schemas = loader.get_tool_schemas()
        loader.load("modification")  # returns SKILL.md content
    """

    def __init__(self, agent_dir: Path, get_context: Callable,
                 default_adapter: 'SkillAdapter' = None):
        """初始化 SkillLoaderV2，从 agent_dir 读取配置、发现 adapter、扫描 skill 目录。"""
        self.agent_dir = Path(agent_dir)
        self.get_context = get_context  # callable that returns SkillContext
        self.default_adapter = default_adapter
        self.manifests: Dict[str, SkillManifest] = {}
        self._tool_handlers: Dict[str, Callable] = {}
        self._skill_docs: Dict[str, dict] = {}  # {name: {description, body}}
        self._system_prompt: str = ""  # SYSTEM.md content
        self._system_adapter: Optional[SkillAdapter] = None  # adapter for resolve_prompt_context

        # 1. Load agent config (agent.yaml)
        self._agent_config = self._load_agent_config()

        # 2. Resolve skill_dirs from config (relative to project root)
        from .core import WORKDIR
        raw_dirs = self._agent_config.get("skill_dirs", [])
        self.skill_dirs: List[Path] = [WORKDIR / d for d in raw_dirs]

        # 3. Discover adapters from agent_dir/*.py
        self.adapters = self._discover_adapters()

        # 4. Scan skill directories
        self._scan()

    def _load_agent_config(self) -> dict:
        """读取 agent_dir/agent.yaml 配置。"""
        config_path = self.agent_dir / "agent.yaml"
        if not config_path.exists():
            logger.warning(f"[SkillLoaderV2] agent.yaml not found at {config_path}")
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"[SkillLoaderV2] Failed to load agent.yaml: {e}")
            return {}

    def _discover_adapters(self) -> Dict[str, SkillAdapter]:
        """扫描 agent_dir/*.py 自动发现 SkillAdapter 子类。"""
        adapters = {}
        if not self.agent_dir.exists():
            return adapters
        for py_file in sorted(self.agent_dir.glob("*.py")):
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue
            # Build module path relative to CWD
            try:
                rel_path = py_file.resolve().relative_to(Path.cwd().resolve())
                module_path = ".".join(rel_path.with_suffix("").parts)
            except ValueError:
                module_path = f"adapters.{self.agent_dir.name}.{py_file.stem}"
            try:
                mod = importlib.import_module(module_path)
            except Exception as e:
                logger.warning(f"[SkillLoaderV2] Failed to import adapter {module_path}: {e}")
                continue
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if issubclass(obj, SkillAdapter) and obj is not SkillAdapter:
                    skill_name = getattr(obj, "skill_name", py_file.stem)
                    adapters[skill_name] = obj()
                    logger.debug(f"[SkillLoaderV2] Discovered adapter: {skill_name} -> {name}")
        return adapters

    def _scan(self):
        """遍历所有 skill 目录，触发扫描和注册。"""
        for skills_dir in self.skill_dirs:
            if not skills_dir.exists():
                continue
            self._scan_dir(skills_dir)

    def _scan_dir(self, skills_dir: Path):
        """扫描单个目录：加载 SYSTEM.md/SKILL.md 文档，解析 SKILL.yaml 并注册有 adapter 的工具。"""
        # 0. Scan SYSTEM.md (for system prompt)
        for system_md in skills_dir.rglob("SYSTEM.md"):
            try:
                self._system_prompt = system_md.read_text(encoding="utf-8")
                # The adapter for this skill becomes the system adapter
                skill_name = system_md.parent.name
                if skill_name in self.adapters:
                    self._system_adapter = self.adapters[skill_name]
                logger.info(f"[SkillLoaderV2] Loaded SYSTEM.md from {system_md.parent.name}")
            except Exception as e:
                logger.warning(f"Failed to load SYSTEM.md {system_md}: {e}")

        # 1. Scan SKILL.md files (for load_skill)
        for skill_md in skills_dir.rglob("SKILL.md"):
            try:
                content = skill_md.read_text(encoding="utf-8")
                meta, body = self._parse_md(content)
                name = meta.get("name", skill_md.parent.name)
                self._skill_docs[name] = {
                    "name": name,
                    "description": meta.get("description", ""),
                    "body": body,
                }
            except Exception as e:
                logger.warning(f"Failed to load SKILL.md {skill_md}: {e}")

        # 2. Scan SKILL.yaml files (for tool auto-registration)
        for yaml_path in skills_dir.rglob("SKILL.yaml"):
            manifest = load_skill_yaml(yaml_path)
            if not manifest:
                continue

            # Only register tools if an adapter exists
            adapter = self.adapters.get(manifest.name)
            if not adapter and self.default_adapter:
                adapter = self.default_adapter
            if not adapter:
                logger.debug(f"[SkillLoaderV2] No adapter for skill '{manifest.name}', "
                           f"tools not auto-registered (manual or doc-only)")
                continue

            self.manifests[manifest.name] = manifest
            self._register_tools(manifest, adapter)
            logger.info(f"[SkillLoaderV2] Registered skill: {manifest.name} "
                       f"({len(manifest.tools)} tools, adapter={type(adapter).__name__})")

    @staticmethod
    def _parse_md(content: str) -> tuple:
        """Parse YAML frontmatter + body from SKILL.md."""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1].strip()
                body = parts[2].strip()
                meta = {}
                for line in frontmatter.split("\n"):
                    if ":" in line:
                        key, val = line.split(":", 1)
                        meta[key.strip()] = val.strip()
                return meta, body
        return {}, content

    def load(self, name: str) -> str:
        """Load a skill's SKILL.md content into context (for LLM injection)."""
        s = self._skill_docs.get(name)
        if not s:
            return f"Skill '{name}' not found. Available: {list(self._skill_docs.keys())}"
        return f'<skill name="{name}">\n{s["body"]}\n</skill>'

    def descriptions(self) -> str:
        """One-line descriptions of all discovered skills (from SKILL.md) for system prompt."""
        lines = []
        for name, info in self._skill_docs.items():
            if info["description"]:
                lines.append(f"- {name}: {info['description']}")
        return "\n".join(lines)

    def build_system_prompt(self) -> str:
        """构建完整 system prompt = SYSTEM.md + skill 列表 + 动态上下文。"""
        parts = []
        if self._system_prompt:
            parts.append(self._system_prompt)
        # Append skill descriptions
        desc = self.descriptions()
        if desc:
            parts.append(f"\n## Available Skills (call load_skill(\"<name>\") for details)\n{desc}\n")
        # Append dynamic context from system adapter
        if self._system_adapter:
            try:
                ctx = self.get_context()
                extra = self._system_adapter.resolve_prompt_context(ctx)
                if extra:
                    parts.append(f"\n{extra}\n")
            except Exception as e:
                logger.warning(f"[SkillLoaderV2] resolve_prompt_context failed: {e}")
        return "\n".join(parts)

    def _register_tools(self, manifest: SkillManifest, adapter: SkillAdapter):
        """Create wrappers for all tools in a skill manifest."""
        # Get LLM-exposed params from adapter
        tool_params = adapter.get_tool_params()

        for tool_def in manifest.tools:
            handler = _resolve_handler(manifest.skill_dir, tool_def.handler_path)
            if not handler:
                logger.warning(f"[SkillLoaderV2] Skipping tool '{tool_def.name}': handler not found")
                continue

            # Determine which params are LLM-provided for this tool
            llm_params = set(tool_params.get(tool_def.name, {}).keys())

            wrapper = build_tool_wrapper(
                tool_def, adapter, self.get_context, handler, llm_params,
                skill_name=manifest.name,
            )
            self._tool_handlers[tool_def.name] = wrapper

    def get_tool_handlers(self) -> Dict[str, Callable]:
        """Get all auto-registered tool handlers."""
        return dict(self._tool_handlers)

    def get_tool_schemas(self) -> List[dict]:
        """
        Auto-generate OpenAI function-calling tool schemas from SKILL.yaml + adapter.

        Returns a list of tool schema dicts in OpenAI format:
        [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
        """
        schemas = []
        for skill_name, manifest in self.manifests.items():
            adapter = self.adapters.get(skill_name)
            if not adapter:
                continue

            # Get LLM params declared by adapter
            tool_params = adapter.get_tool_params()

            for tool_def in manifest.tools:
                # Build parameters schema from adapter's get_tool_params()
                params_def = tool_params.get(tool_def.name, {})

                if params_def:
                    # Has LLM-exposed parameters
                    properties = {}
                    required = []
                    for param_name, param_spec in params_def.items():
                        properties[param_name] = {
                            "type": param_spec.get("type", "string"),
                            "description": param_spec.get("description", ""),
                        }
                        if param_spec.get("required", False):
                            required.append(param_name)

                    parameters = {
                        "type": "object",
                        "properties": properties,
                    }
                    if required:
                        parameters["required"] = required
                else:
                    # Zero parameters
                    parameters = {"type": "object", "properties": {}}

                schema = {
                    "type": "function",
                    "function": {
                        "name": tool_def.name,
                        "description": tool_def.description or f"Skill tool: {tool_def.name}",
                        "parameters": parameters,
                    }
                }
                schemas.append(schema)

        return schemas