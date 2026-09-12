# Prism Agent

> **English** | [中文](README.md)

An application-agnostic agent framework skeleton: Agent Loop + DataStore + Skill/Adapter assembly layer.
The repo ships the framework kernel plus a complete, runnable example agent (textcraft — demo below). Run it, then follow the guide to plug in your own business.

---

## Why Prism Agent

- **Skill ↔ data decoupling that actually holds up** — many frameworks claim it; here you can verify it: in the textcraft demo the LLM literally issues `classify_document({})`, a zero-argument call. The LLM only decides *whether* to call — the document never passes through the LLM context; data flows between tools via the DataStore. Swap the Adapter and the same Skill runs on a different store.
- **Declarative contracts (SKILL.yaml)** — every tool's inputs / outputs / parameter sources are explicitly declared. The interface is the documentation; the LLM never guesses parameters — the prerequisite for platform-level skill validation and auto-wiring.
- **Anthropic Skill-compatible** — not "yet another LangGraph": a runtime wiring layer for the standard skill format (`SKILL.md` + `scripts/`). External skills drop in with zero changes to `scripts/`; strip the Adapter and a local skill exports as a pure Anthropic Skill.
- **Lightweight but not a toy** — the kernel lives in the [prism/](prism/) package: ~1,800 lines across 8 modules with only 4 runtime dependencies, readable in an afternoon — yet with production-grade fallbacks built in (three-level context-compression degradation, full exception boundaries around the Adapter layer), plus a complete runnable textcraft demo (CLI + web).

---

## Why not LangChain?

If you've had enough of stacked abstractions and "magic tuning", this is the opposite extreme. Prism Agent's core assumption is simple:

> **A Skill is pure business logic** — it shouldn't know it's being invoked by an agent, and shouldn't know Session or DataStore exist: inputs arrive as parameters, outputs leave as return values, and even the LLM handle (`llm.complete(...)`) is injected by the framework as a parameter — not a single framework import in skill code.
>
> The loop, session, and DataStore are infrastructure; Skills are pure functions; the Adapter is the only glue.

| Dimension | LangChain / LangGraph | Prism Agent |
|-----------|-----------------------|-------------|
| Positioning | Full-featured orchestration framework / graph runtime | Lightweight skeleton: loop + DataStore + assembly layer |
| Abstraction | Layer upon layer (Chain / Runnable / LCEL...); behavior hides inside the framework | A ~1,800-line kernel straight to the LLM API — readable in an afternoon, no magic |
| Skill shape | Tools scattered in code, coupled to the framework | Directory-level skills (`SKILL.md` + `scripts/`) aligned with Anthropic's format — lift the whole directory out as-is |
| Data flow | State passed implicitly between chain/graph nodes | Explicit DataStore + Adapter wiring; the LLM context is never a data bus |
| Dependencies | A large dependency tree | 4 runtime dependencies |

This isn't "LangChain is bad" — it's a reasonable choice when you need its ecosystem integrations. Prism Agent is for people who want **full control over the agent loop** and want skills to be **portable assets**.

---

## Table of Contents

- [Why Prism Agent](#why-prism-agent)
- [Why not LangChain?](#why-not-langchain)
- [Core Concepts](#core-concepts)
- [Project Layout](#project-layout)
- [Installation & Configuration](#installation--configuration)
- [Quickstart: Wire Up a New Agent in 5 Minutes](#quickstart-wire-up-a-new-agent-in-5-minutes)
- [Example Agent: textcraft Demo](#example-agent-textcraft-demo)
- [Skill Directory Conventions (Anthropic Skill-Compatible)](#skill-directory-conventions-anthropic-skill-compatible)
- [The Adapter Layer in Detail](#the-adapter-layer-in-detail)
- [SKILL.yaml / SKILL.md / SYSTEM.md Conventions](#skillyaml--skillmd--systemmd-conventions)
- [Handler Conventions](#handler-conventions)
- [Full Example: Building an Article-Summary Agent from Scratch](#full-example-building-an-article-summary-agent-from-scratch)
- [Runtime Data Flow](#runtime-data-flow)
- [FAQ](#faq)

---

## Core Concepts

The framework consists of four roles with strictly separated responsibilities:

| Role | Location | Responsibility |
|------|----------|----------------|
| **Agent kernel** | the [prism/](prism/) package (8 modules) | Generic loop: LLM calls, tool orchestration, context compression, session management. Knows nothing about business. |
| **Skill** | [skills/&lt;agent&gt;/&lt;skill&gt;/](skills/) | Pure business functions (handlers) + declarative interface (`SKILL.yaml`) + usage docs (`SKILL.md`). No dependency on session, store, or framework. |
| **Adapter** | [adapters/&lt;agent&gt;/&lt;skill&gt;.py](adapters/) | Pulls the skill's inputs from the DataStore and writes its outputs back; declares which parameters the LLM may fill. |
| **Agent instance** | [agents/&lt;agent&gt;.py](agents/) | A single entry function: initializes the DataStore and assembles an `AgentEngine` (the return value of `agent.init_agent(agent_dir, store)`). |

In one sentence: **a Skill is a portable, reusable capability; an Adapter is the glue that lets a Skill grow onto your agent.**

---

## Project Layout

```
prism_agent/
├── prism/                # framework kernel package (8 modules, ~1,800 lines)
│   ├── agent.py              # AgentEngine (per-instance models/tools/DataStore) + agent loop kernel
│   ├── client.py             # LLM client (call_llm / SkillLLM / DEFAULT_MODELS)
│   ├── core.py               # Constants: WORKDIR / SESSION_DIR / SKILLS_DIR / ADAPTERS_DIR
│   ├── data_store.py         # DataStore abstraction + SQLiteDataStore (wide table + dynamic columns)
│   ├── session.py            # BaseSession (conversation history, chat_events, turn_count)
│   ├── session_context.py    # Propagates the current session via contextvars
│   ├── skill_context.py      # SkillContext / SkillAdapter / BizProxy / PassthroughAdapter
│   └── skill_loader.py       # SkillLoaderV2: scans SKILL.yaml, assembles adapters, injects llm, generates tool schemas
├── requirements.txt
├── .env.example          # API endpoint config template (copy to .env and fill in)
├── demo_cli.py           # example: textcraft interactive CLI
├── demo_server.py        # example: textcraft web demo backend (Flask)
├── demo_web/             # example: textcraft single-page frontend
│
├── adapters/             # One subdirectory per agent: agent.yaml + <skill>.py adapters
│   ├── __init__.py
│   └── textcraft/        # example agent's adapters + agent.yaml
├── agents/               # One <agent>.py per agent, exposing an init() entry
│   ├── __init__.py
│   └── textcraft.py      # example agent entry
├── skills/               # One subdirectory per agent, holding one subdirectory per skill
│   ├── __init__.py
│   └── textcraft/        # example: doc_summary skill + orchestrator
└── common_skills/        # shared pool of agent-agnostic skills (picked per leaf directory in skill_dirs)
    ├── __init__.py
    └── doc_classify/     # example: document classification skill, used by textcraft
```

---

## Installation & Configuration

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Only four runtime dependencies: `openai` (LLM calls), `pyyaml` (SKILL.yaml / agent.yaml parsing), `json-repair` (tolerant parsing of LLM JSON output), `python-dotenv` (.env config loading). `requirements.txt` additionally lists `flask` — only used by the web demo ([demo_server.py](demo_server.py)), not by the framework kernel.

### 2. Configure the LLM endpoint

The framework reads API credentials from environment variables (OpenAI-compatible protocol — self-hosted proxies, OpenRouter, or the official API all work). Copy `.env.example` to `.env` and fill in your endpoint:

```bash
cp .env.example .env
```

```ini
# .env
API_BASE=https://your-llm-endpoint/v1
API_KEY=your-api-key
```

You can also `export` system environment variables instead — existing variables take precedence over the `.env` file.

Model aliases can be overridden per agent in the `models` section of `agent.yaml`: the framework ships the `orchestrator` fallback, and a skill may declare its own alias by name — see [The Adapter Layer in Detail](#the-adapter-layer-in-detail) and the FAQ.

---

## Quickstart: Wire Up a New Agent in 5 Minutes

Suppose you want a `my_agent` with a `translate` skill.

### 1. Create the skill

```
skills/my_agent/translate/
├── __init__.py           # empty file
├── SKILL.yaml            # tool interface declaration
├── SKILL.md              # usage docs for the LLM (optional but recommended)
└── scripts/              # ← Anthropic Skill style: all .py implementations live here
    ├── __init__.py
    ├── handlers.py       # pure-function handlers
    └── prompts.py        # prompt templates (optional)
```

> The directory layout follows the [Anthropic Skill format](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills) (`SKILL.md` + `scripts/`), so external skills can be migrated in with almost zero changes. See [Skill Directory Conventions](#skill-directory-conventions-anthropic-skill-compatible).

[skills/my_agent/translate/SKILL.yaml](skills/):

```yaml
name: translate
description: "Translation: translate source text into the target language"

tools:
  - name: run_translate
    handler: handlers.tool_translate   # resolved under scripts/ automatically (no need to write scripts.handlers)
    description: "Translate source text into the target language"
    inputs:
      source_text: str
      target_lang: str
    output: dict
```

[skills/my_agent/translate/scripts/handlers.py](skills/):

```python
import json


def tool_translate(source_text: str = "", target_lang: str = "en", llm=None, **kw) -> str:
    """Pure function: no session/store/client imports. Data arrives via parameters;
    LLM capability arrives via the framework-injected llm handle."""
    if not source_text:
        return json.dumps({"status": "error", "message": "empty source_text"}, ensure_ascii=False)

    try:
        translated = llm.complete(
            messages=[{"role": "user", "content": f"Translate to {target_lang}:\n\n{source_text}"}],
            temperature=0.3,
            max_tokens=2048,
        )
    except Exception as e:
        return json.dumps({"status": "error", "message": f"LLM call failed: {e}"}, ensure_ascii=False)
    return json.dumps({
        "status": "success",
        "translated": translated,
        "_output_data": {"translation": translated},   # written back to the DataStore by the adapter
    }, ensure_ascii=False)
```

### 2. Create the adapter

```
adapters/my_agent/
├── __init__.py           # empty file (skill_loader auto-discovers *.py in this directory)
├── agent.yaml            # agent-level config
└── translate.py          # adapter for the translate skill
```

[adapters/my_agent/agent.yaml](adapters/):

```yaml
name: my_agent

skill_dirs:
  - skills/my_agent
  # - common_skills/doc_classify  # optional: pull from the shared skill pool — each entry may point at a single skill's leaf directory; unlisted skills are not loaded

models:
  orchestrator: "deepseek-v4-flash"        # global fallback model
  # <skill_name>: "deepseek-v4-flash"      # optional: per-skill model, automatically bound to the llm handle injected into that skill's handlers

loop:
  max_iterations: 10
  temperature: 0.3
  max_tokens: 4096
  # summary_model: "deepseek-v4-flash"   # optional: model for context-compression summaries (defaults to models.orchestrator)
```

[adapters/my_agent/translate.py](adapters/):

```python
from typing import Any, Dict
from prism.skill_context import SkillAdapter, SkillContext


class TranslateAdapter(SkillAdapter):
    skill_name = "translate"   # must match the `name` in SKILL.yaml

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        # Read the skill's inputs from the DataStore
        return {
            "source_text": ctx.store.get_field(ctx.session_id, "source_text") or "",
        }

    def write_output(self, ctx: SkillContext, result: Any):
        # The skill's `_output_data` is passed in automatically
        if isinstance(result, dict) and "translation" in result:
            ctx.store.set_field(ctx.session_id, "translation", result["translation"])

    def get_tool_params(self) -> Dict[str, dict]:
        # Declare parameters the LLM must fill itself (not sourced from the DataStore)
        return {
            "run_translate": {
                "target_lang": {
                    "type": "string",
                    "description": "Target language, e.g. en/zh/ja",
                    "required": True,
                },
            }
        }
```

### 3. Create the agent entry

[agents/my_agent.py](agents/):

```python
from pathlib import Path

from prism import agent
from prism.core import ADAPTERS_DIR
from prism.data_store import SQLiteDataStore


def init(data_dir: Path):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteDataStore(str(data_dir / "my_agent.db"))
    return agent.init_agent(
        agent_dir=ADAPTERS_DIR / "my_agent",
        store=store,
    )
```

`init_agent` returns the assembled **AgentEngine**: model table, tool set, DataStore and loop config are all instance-scoped. A single-agent process can keep using the module-level `agent.agent_loop_stream(...)` (a thin shell that forwards to this engine); to host multiple agents in one process, construct `agent.AgentEngine(agent_dir, store)` per agent and hold the references (that's what demo_server does) — they never interfere. The engine is agent-level runtime; the session is request-level state: multi-session hosts pass each request's session explicitly via `agent_loop_stream(..., session=sess)` (see demo_server's api_chat) instead of relying on thread-local state.

### 4. Run it

```python
from pathlib import Path
from agents.my_agent import init

engine = init(Path(".data"))
store = engine.store

# Grab the default session and write business data into the store
sess = engine.default_session
sess.session_id = "demo-session"
store.set_field(sess.session_id, "source_text", "你好，世界")

# Run one agent loop
for event in engine.agent_loop_stream("Please translate it to English", conversation_history=[]):
    print(event)
```

That's a minimal working agent. The next section explains the Adapter layer in depth.

---

## Example Agent: textcraft Demo

The repo ships a complete, runnable example agent **textcraft** (document processing: type classification + type-specific structured summaries) that exercises every convention in this README:

```
common_skills/doc_classify/       # classification skill (sampled classify, cheap model; generic capability, lives in the shared pool)
skills/textcraft/doc_summary/     # summary skill (structured summaries + revision; long docs chunked)
skills/textcraft/orchestrator/    # SYSTEM.md (orchestration instructions)
adapters/textcraft/               # agent.yaml (per-skill models; skill_dirs pulls doc_classify from common_skills) + three adapters
agents/textcraft.py               # agent entry
demo_cli.py                       # interactive CLI
demo_server.py + demo_web/        # web demo (Flask + single-page frontend)
```

Design notes:
- **Two-level classification**: level 1 is by *purpose* — informational / narrative / persuasive / instructional / general; level 2 refines by genre — 20 subtypes (papers, news, contracts, legal documents, novels, speeches, recipes, ...). `classify_document` classifies a **sample** (first 2000 + last 1000 chars, cheap model) and persists `doc_category` / `doc_subtype` / confidence; confidence below 0.6 falls back to "general" instead of guessing.
- **Layered summary templates**: `generate_summary` applies a JSON schema per level-1 category (required fields validated, one retry), and level-2 subtypes add fields on demand (contracts → parties/amount/term; news → source/date/location; recipes → servings/time...). Long documents are chunked and summarized with a parallel Map-Reduce once the estimated token count exceeds the single-call budget (language-aware: ~30k chars for Chinese, ~150k for English); missing fields are retried, then defaulted.
- **Revision & hash reuse**: `revise_summary` edits the existing summary per the user's request instead of regenerating it (cost-saving); uploads are deduplicated by content md5 — re-uploading the same document keeps all state and skips re-classification/re-summary.
- **PDF uploads**: the entry layer (`agents/textcraft.read_document`) extracts the PDF text layer page-by-page with pypdf; txt/md etc. are read as UTF-8 text — file-format knowledge lives in the agent entry layer, never in the framework core. Scanned (image-only) PDFs need OCR and are out of scope.
- If the user uploads without giving an instruction, the agent only reports the detected type and asks what to do next — it does not summarize unprompted.

**Run the CLI**:

```bash
python demo_cli.py
# then: /upload your_doc.txt   → the agent reports the type and asks your intent
# then: give me a summary      → structured summary
# (/state shows the DataStore, /new starts a fresh session, /quit exits)
```

**Run the web demo** (requires flask):

```bash
python demo_server.py   # → http://127.0.0.1:5057
# pick an agent, click to upload, chat with streamed events
```

---

## Skill Directory Conventions (Anthropic Skill-Compatible)

Our skill layout mirrors the [Anthropic Agent Skills format](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills), with `SKILL.yaml` added for a strict interface declaration. Benefits:

- **External skills drop straight in** — anything following the `SKILL.md` + `scripts/` structure only needs a `SKILL.yaml` + adapter to join this framework
- **Local skills can be exported** — strip the `SKILL.yaml` / adapter and the skill works as a pure Anthropic Skill
- **Normalized layering** — declarations (yaml/md) are separated from implementations (scripts), keeping diffs clean

### Recommended layout

```
skills/<agent>/<skill>/
├── SKILL.md          # [recommended] Natural-language docs (with YAML frontmatter), loaded into the LLM context on demand
├── SKILL.yaml        # [required*] Tool interface declaration (*required if the skill exposes tools)
├── __init__.py
├── scripts/          # [recommended] All executable code (handlers, internal helpers, prompt templates)
│   ├── __init__.py
│   ├── handlers.py
│   └── prompts.py
├── references/       # [optional] Reference docs the LLM reads when needed (Anthropic convention; not auto-loaded by this framework)
└── assets/           # [optional] Static resources: images, templates, JSON data, etc.
```

Except for `SKILL.md`, `SKILL.yaml`, `SYSTEM.md`, and `__init__.py`, every `.py` file should live under `scripts/`.

### Handler path resolution

A `handler: <module>.<function>` entry in SKILL.yaml is resolved in this order (see [prism/skill_loader.py:_resolve_handler](prism/skill_loader.py#L100)):

1. **First try `<skill>/scripts/<module>.py`** ← recommended: `handler: handlers.tool_x`
2. Then `<skill>/<module>.py` (legacy flat layout)

You may also write the full path explicitly: `handler: scripts.handlers.tool_x` — same result.

### Differences from a pure Anthropic Skill

| Feature | Anthropic Skill | This framework |
|---------|-----------------|----------------|
| SKILL.md (with YAML frontmatter) | ✓ | ✓ |
| scripts/ directory | ✓ | ✓ |
| references/ directory | ✓ read on demand | Location reserved, not auto-scanned (read it yourself in a handler) |
| assets/ directory | ✓ | Same as above |
| Tool entry point | LLM decides by reading SKILL.md | **Explicitly** declared in `SKILL.yaml` + data wired by an Adapter |
| Session/Store integration | None (each skill manages its own) | Uniformly bridged to the DataStore by `SkillAdapter` |

In short: **the structure matches Anthropic's; the wiring is reinforced by `SKILL.yaml` + Adapters — compatibility and controllability at the same time.**

---

## The Adapter Layer in Detail

The Adapter is the layer you most need to understand when writing a new agent. It subclasses `SkillAdapter` from [prism/skill_context.py:98](prism/skill_context.py#L98) and has 5 methods (2 required, 3 optional overrides).

### Method overview

| Method | Required | When the framework calls it | Purpose |
|--------|----------|-----------------------------|---------|
| `skill_name` (class attribute) | **required** | At startup, while scanning adapters | Matches the adapter to a `SKILL.yaml` |
| `resolve_inputs(ctx)` | **required** | Before every tool call | Reads the skill's inputs from the DataStore |
| `write_output(ctx, result)` | **required** | After the handler returns | Writes `_output_data` back to the DataStore |
| `validate_inputs(inputs)` | optional | After `resolve_inputs` | Validates inputs; returning a non-empty string short-circuits with an error |
| `get_tool_params()` | optional | When generating the OpenAI tool schema | Declares fields the LLM must fill itself |
| `resolve_prompt_context(ctx)` | optional | When building the system prompt each turn | Injects dynamic session state into the system prompt |
| `format_llm_response(name, r)` | optional | After the handler returns (before the orchestrator sees it) | Trims the result sent back to the LLM |

### 1. `skill_name` (class attribute)

Must exactly match the `name` in the corresponding `SKILL.yaml`. The framework uses it to pair adapters with skills.

```python
class SummaryAdapter(SkillAdapter):
    skill_name = "summary"  # ← matches name: summary in skills/writer_agent/summary/SKILL.yaml
```

### 2. `resolve_inputs(ctx) -> Dict[str, Any]`

Reads the skill's inputs from the DataStore. **Only return keys matching the `inputs` field names in `SKILL.yaml`** — extra keys are ignored.

```python
def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
    return {
        "article_text": ctx.store.get_field(ctx.session_id, "article_text"),
        "summary":      ctx.store.get_field(ctx.session_id, "summary"),
        "user_query":   ctx.last_user_message(),    # read the session history directly
    }
```

`ctx` is a [SkillContext](prism/skill_context.py#L61) with three entry points:

- `ctx.store` — the DataStore instance (`get_field/set_field/delete_field/ensure_field`)
- `ctx.session_id` — the current session id
- `ctx.session` — the BaseSession object (`history`, `chat_events`, `turn_count`)
- `ctx.biz["key"]` — syntactic sugar for `ctx.store.get_field(ctx.session_id, "key")`
- `ctx.last_user_message()` — convenience method: the most recent user message

### 3. `write_output(ctx, result)`

If the handler's return value contains an `_output_data` field, the framework extracts it and passes it in as `result`. You persist it to the DataStore.

```python
def write_output(self, ctx: SkillContext, result: Any):
    if isinstance(result, dict) and "summary" in result:
        ctx.store.set_field(ctx.session_id, "summary", result["summary"])
```

### 4. `validate_inputs(inputs) -> str` (optional)

Pre-flight validation before the handler is invoked. Returning a non-empty string short-circuits the call with an error status — the handler is never called.

```python
def validate_inputs(self, inputs: Dict[str, Any]) -> str:
    if not inputs.get("article_text"):
        return "Required input 'article_text' is None (please upload the article first)"
    return ""
```

### 5. `get_tool_params() -> Dict[str, dict]` (optional)

**This method directly determines which parameters the LLM can see.** Three cases:

**(a) Zero parameters**: all inputs come from the DataStore; the LLM only decides *whether* to call. No override needed, or return `{}`.

```yaml
# The tool in SKILL.yaml is presented as:
{"type": "function", "function": {"name": "generate_summary", "parameters": {"type": "object", "properties": {}}}}
```

**(b) Partial parameters**: some inputs from the DataStore, some filled by the LLM (e.g. ad-hoc text like "the user's revision request").

```python
def get_tool_params(self) -> Dict[str, dict]:
    return {
        "revise_summary": {
            "revision_request": {
                "type": "string",
                "description": "The user's specific revision request for the summary",
                "required": True,
            }
        }
    }
```

Framework rules (see [prism/skill_loader.py:245-250](prism/skill_loader.py#L245-L250)):
- Fields declared in `get_tool_params` → the LLM's value **overrides** the `resolve_inputs` value
- Other fields the LLM passes are forwarded to the handler if `pass_kwargs=True` (the default)

**(c) Composite parameters**: multiple fields filled by the LLM. Just declare multiple keys.

### 6. `resolve_prompt_context(ctx) -> str` (optional; only called on the adapter of the skill that hosts SYSTEM.md)

Appends dynamic state to the end of the system prompt. Typical use: tell the LLM "which stage is complete" or "what the current summary is".

```python
def resolve_prompt_context(self, ctx: SkillContext) -> str:
    summary = ctx.store.get_field(ctx.session_id, "summary")
    if not summary:
        return "## Current Stage\nNo summary yet."
    return f"## Current Summary\n```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```"
```

Only the adapter of the skill hosting `SYSTEM.md` is called (see [prism/skill_loader.py:523-542](prism/skill_loader.py#L523-L542)) — usually the `orchestrator` skill.

### 7. `format_llm_response(tool_name, result)` (optional)

A "slimming" hook on the handler's return value before it reaches the orchestrator LLM. The default implementation **automatically strips `_output_data`** (it has already been persisted via `write_output`; no need to spend tokens showing it to the LLM). You rarely need to override this.

---

## SKILL.yaml / SKILL.md / SYSTEM.md Conventions

### SKILL.yaml — tool interface declaration

```yaml
name: summary                     # matched against the adapter's skill_name
description: "Article summarization skill"

tools:
  - name: generate_summary        # the `name` for OpenAI function calling
    handler: handlers.tool_generate_summary   # <module>.<function>, module relative to the skill dir
    description: "Generate the initial summary (read by the LLM)"
    inputs:                       # documentation + determines which fields the handler receives
      article_text: str
      style: str
    output: dict
    # pass_kwargs: true            # default true: whether LLM params not declared in get_tool_params are forwarded
```

Key rules:
- `handler` must be `<relative module>.<function>`. The framework looks under `scripts/` first, then falls back to the skill root. So `handlers.tool_generate_summary` → preferably resolved as `skills/<agent>/<skill>/scripts/handlers.py::tool_generate_summary`
- Field names in `inputs` must match the handler's signature
- If the handler's return value contains `_output_data`, the framework uses it for persistence
- One skill may declare multiple tools (e.g. `generate_summary` + `revise_summary`)

### SKILL.md — detailed docs loaded on demand

```markdown
---
name: summary
description: Article summary generation and revision
---

# Summary Skill

## Capabilities
| Tool | Description |
|------|-------------|
| generate_summary | Initial generation |
| revise_summary   | Revise based on user feedback |

## Tool Instructions
### Generation
When the user asks for a summary, call generate_summary; optional param `style` carries the user's style request (omit when absent).
...
```

The SKILL.md **description** (frontmatter) appears in the orchestrator's system prompt skill list; the **body** is only injected when the LLM actively calls `load_skill("summary")`, keeping the system prompt short.

### SYSTEM.md — the orchestrator's main system prompt

Placed in the orchestrator skill's directory (e.g. `skills/<agent>/orchestrator/SYSTEM.md`). It becomes the body of the system prompt and is loaded automatically at startup:

```
SYSTEM.md content
+
## Available Skills (call load_skill("<name>") for details)
- summary: Article summary generation and revision
- translate: Translation
+
(whatever the orchestrator adapter's resolve_prompt_context returns, e.g. dynamic state)
```

An agent should have exactly **one** `SYSTEM.md`.

---

## Handler Conventions

Handlers are pure functions: no session, store, or client imports. All inputs arrive via parameters — **including LLM capability**: the framework injects an `llm` handle before every call (`llm.complete(messages, temperature=..., max_tokens=...) -> str`, raising `LLMError` on failure), with the model automatically routed by skill name.

```python
def tool_translate(source_text: str = "", target_lang: str = "en", llm=None, **kw) -> str:
    if not source_text:
        return json.dumps({"status": "error", "message": "empty"}, ensure_ascii=False)

    # ... business logic (use llm.complete(...) when you need the LLM) ...

    return json.dumps({
        "status": "success",
        "translation": translated,          # shown to the LLM
        "_output_data": {                   # ← extracted by write_output and persisted to the DataStore
            "translation": translated,
        },
        # optional:
        # "instant_reply": "Done ✅",       # pushed to the frontend as an SSE instant_reply event
    }, ensure_ascii=False)
```

Conventions:

- Return type: `str` (JSON) or `dict`
- **`status`**: `"success"` / `"error"` (the LLM relies on it to tell whether the call succeeded)
- **`_output_data`**: content to persist. Absent means the skill is read-only
- **`instant_reply`** (optional): a one-liner pushed to the frontend immediately (no need to wait for the LLM's reply)
- **`llm`** (reserved word): the framework-injected LLM handle, bound to the same-named key in the `models` section of `agent.yaml` (falls back to `orchestrator` when unconfigured). It does not come from SKILL.yaml inputs, the DataStore, or LLM parameters. When calling a handler directly (e.g. in unit tests), pass your own stub — handler unit tests no longer need an API key. Deterministic handlers that don't need the LLM simply omit the `llm` parameter: the framework inspects the signature and injects **on demand** — strict-signature handlers (no `**kw`) never receive an extra argument
- Parameters not declared in `SKILL.yaml` `inputs` (e.g. `**kw`) are forwarded when `pass_kwargs=True`, for compatibility with extra keys the orchestrator may pass

---

## Full Example: Building an Article-Summary Agent from Scratch

A minimal working `writer_agent`: generates a summary from an uploaded article and supports revising it based on user feedback. It follows this skeleton's layout and conventions exactly.

**Layout**:
```
adapters/writer_agent/
├── agent.yaml
├── __init__.py
└── summary.py         # ← Adapter

skills/writer_agent/
├── __init__.py
└── summary/
    ├── __init__.py
    ├── SKILL.yaml
    ├── SKILL.md
    └── scripts/       # ← Anthropic Skill aligned
        ├── __init__.py
        ├── handlers.py    # pure-function handlers
        └── prompts.py
```

**adapters/writer_agent/agent.yaml**:

```yaml
name: writer_agent
skill_dirs:
  - skills/writer_agent
models:
  orchestrator: "deepseek-v4-flash"        # global fallback model
  # <skill_name>: "deepseek-v4-flash"      # optional: per-skill model, automatically bound to the llm handle injected into that skill's handlers
loop:
  max_iterations: 15
  temperature: 0.3
  max_tokens: 4096
  # summary_model: "deepseek-v4-flash"   # optional: model for context-compression summaries (defaults to models.orchestrator)
```

**adapters/writer_agent/summary.py**:

```python
from typing import Any, Dict
from prism.skill_context import SkillAdapter, SkillContext


class SummaryAdapter(SkillAdapter):
    skill_name = "summary"

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        return {
            "article_text": ctx.store.get_field(ctx.session_id, "article_text"),
            "user_query":   ctx.last_user_message(),
            "summary":      ctx.store.get_field(ctx.session_id, "summary"),
        }

    def write_output(self, ctx: SkillContext, result: Any):
        if isinstance(result, dict):
            payload = result.get("summary", result)
            ctx.store.set_field(ctx.session_id, "summary", payload)

    def validate_inputs(self, inputs: Dict[str, Any]) -> str:
        if not inputs.get("article_text"):
            return "Required input 'article_text' is None (please upload or paste the article first)"
        return ""

    def get_tool_params(self) -> Dict[str, dict]:
        return {
            "revise_summary": {
                "revision_request": {
                    "type": "string",
                    "description": "The user's revision request (e.g. 'make it shorter', 'use a livelier tone')",
                    "required": True,
                }
            }
        }
```

**skills/writer_agent/summary/SKILL.yaml**:

```yaml
name: summary
description: "Article summary: generate / revise a summary (title, key points, abstract)"

tools:
  - name: generate_summary
    handler: handlers.tool_generate_summary
    description: "Generate a summary (from the saved article). The user must upload or paste the article first."
    inputs:
      article_text: str
      user_query: str
    output: dict

  - name: revise_summary
    handler: handlers.tool_revise_summary
    description: "Revise the current summary based on the revision request in the user's latest message"
    inputs:
      article_text: str
      summary: dict
      revision_request: str
    output: dict
```

**skills/writer_agent/summary/scripts/handlers.py**:

```python
import json
from .prompts import SUMMARY_GENERATE_PROMPT


def tool_generate_summary(article_text=None, user_query="", llm=None, **kw) -> str:
    # ... extract title / key points / abstract via the injected llm handle (omitted) ...
    result = {"title": "...", "bullets": ["...", "..."], "abstract": "..."}
    return json.dumps({
        "status": "success",
        "summary": result,
        "_output_data": {"summary": result},
    }, ensure_ascii=False)


def tool_revise_summary(summary=None, revision_request="", llm=None, **kw) -> str:
    # Note: revision_request is provided by the LLM via get_tool_params,
    # summary is pulled from the DataStore by SummaryAdapter.resolve_inputs,
    # and llm is injected by the framework
    # ... omitted ...
    return json.dumps({"status": "success", "summary": summary, "_output_data": {"summary": summary}}, ensure_ascii=False)
```

**agents/writer_agent.py**:

```python
from pathlib import Path
from prism import agent
from prism.core import ADAPTERS_DIR
from prism.data_store import SQLiteDataStore


def init(data_dir: Path):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteDataStore(str(data_dir / "writer_agent.db"))
    return agent.init_agent(agent_dir=ADAPTERS_DIR / "writer_agent", store=store)
```

---

## Runtime Data Flow

Using a `revise_summary` call as the example (the moment the LLM decides to call the tool):

```
1. The LLM decides to call revise_summary(revision_request="make the tone livelier")
                           │
2. The framework picks the SummaryAdapter whose skill_name="summary"
                           │
3. SummaryAdapter.resolve_inputs(ctx)
     → reads article_text, summary from the DataStore
     → reads user_query via ctx.last_user_message()
                           │
4. Validation: SummaryAdapter.validate_inputs(inputs)   [optional]
                           │
5. Fields filtered by SKILL.yaml inputs + LLM param override, then the framework injects the llm handle
     kwargs = {
         "article_text": "...",
         "summary": {...},
         "revision_request": "make the tone livelier",   # ← provided by the LLM
         "llm": SkillLLM("summary"),                     # ← injected by the framework (bound to the same-named model in models)
     }
                           │
6. tool_revise_summary(**kwargs) → returns JSON
                           │
7. Extract _output_data → SummaryAdapter.write_output(ctx, output_data)
                           │
8. SummaryAdapter.format_llm_response(...)  → strips _output_data → back to the orchestrator
                           │
9. The orchestrator LLM gets the tool result and continues the loop / generates the user reply
```

---

## FAQ

**Q: Does every skill need an adapter?**
A: It needs one if you want its tools to be *callable by the LLM*. Documentation-only skills (whose SKILL.md provides instructions for other skills) can skip the adapter — they just won't be registered as tools. You can also use the framework-provided `PassthroughAdapter` ([prism/skill_context.py:182](prism/skill_context.py#L182)) as a `default_adapter`, which passes the `SkillContext` directly to the handler.

**Q: Can one skill have multiple adapters?**
A: Not recommended — the convention is one adapter per skill. If different tools need different data sources, branch on the tool name inside one adapter: `if tool_name == "xxx": ...`. Usually, though, splitting into two skills is the better design.

**Q: Do I need to create tables for the DataStore in advance?**
A: No. `SQLiteDataStore` automatically runs `ALTER TABLE ADD COLUMN` the first time you call `set_field(session_id, "any_field", value)` (see [prism/data_store.py:86](prism/data_store.py#L86)). All field values are stored as JSON strings.

**Q: How do I configure the model aliases?**
A: The framework ships exactly one built-in alias: the `orchestrator` fallback (see `client.DEFAULT_MODELS`, read-only). Convention: **a skill uses its own name as its alias** — a same-named key in the `models` section of `agent.yaml` becomes that skill's dedicated model, and the framework binds it to the `llm` handle injected into the handler, so handlers never pick models themselves (unconfigured aliases fall back to `orchestrator`). Each `AgentEngine` merges the section into **its own instance's** model table at startup (copied from DEFAULT_MODELS), so multiple agents in one process never overwrite each other. See [adapters/textcraft/agent.yaml](adapters/textcraft/agent.yaml).

**Q: When does context compression trigger?**
A: At the start of every loop iteration the framework estimates tokens; beyond `core.TOKEN_THRESHOLD` (default 80k) it (1) prunes oversized tool outputs, then (2) summarizes the middle messages with a lightweight model. No manual intervention needed.

**Q: How does a frontend consume the events?**
A: `agent.agent_loop_stream(...)` is a generator that yields SSE events one by one: `tool_call` / `tool_result` / `instant_reply` / `done` / `error` / `usage`. Wrap it as `text/event-stream` with Flask/FastAPI and you're done (the web framework dependency belongs to your app, not the framework kernel).

**Q: How do I reuse someone else's skill?**
A: If it follows the Anthropic style (`SKILL.md` + `scripts/`), copy the skill directory into `skills/<my_agent>/`, then: (1) add a `SKILL.yaml` at the skill root declaring the tool interface; (2) add a matching adapter under `adapters/<my_agent>/` wired to your DataStore fields. Zero changes to the original `scripts/` code.

---

## License

[MIT](LICENSE)
