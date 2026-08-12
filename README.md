# Prism Agent

> **[English](README_EN.md)** | 中文

一个应用无关（application-agnostic）的 Agent 框架骨架：Agent Loop + DataStore + Skill/Adapter 装配层。
仓库包含框架内核和一个完整可跑的示例 agent（textcraft，见下文演示），供你跑通后按下面的指引接入自己的业务。

---

## 核心亮点

- **Skill ↔ 数据解耦，真实成立** — 很多框架宣称解耦，这里可以直接验证：textcraft demo 中 LLM 实际发出的是 `classify_document({})` 零参数调用——LLM 只决定"调不调"，文档内容不经过 LLM 上下文，由 DataStore 在工具间接力。同一个 Skill 换个 Adapter 就能接到别的存储。
- **声明式契约（SKILL.yaml）** — 每个工具的 inputs / outputs / 参数来源显式声明，接口即文档，LLM 不用猜参数——这是 Skill 未来可被平台校验、自动接线的前提。
- **Anthropic Skill 兼容** — 不做"又一个 LangGraph"，定位是标准 Skill 格式（`SKILL.md` + `scripts/`）的运行时接线层：外部 Skill 拷进来零改动 `scripts/`，本地 Skill 剥离 Adapter 即可外发。
- **轻量但不玩具** — 内核收在 [prism/](prism/) 包里，8 个模块约 1800 行、运行时依赖仅 4 个，一个下午能读完；同时内置生产级兜底（上下文压缩三级降级、Adapter 全链路异常边界），并附完整可跑的 textcraft 示例（CLI + Web 双 demo）。

---

## 为什么不用 LangChain？

如果你受够了层层封装和"魔幻调参"，这里是另一个极端。Prism Agent 的核心假设很简单：

> **Skill 是纯业务逻辑**——它不该知道自己在被 Agent 调用，不该知道 Session 和 DataStore 的存在：输入从参数进来，输出靠返回值出去，连 LLM 句柄（`llm.complete(...)`）都由框架作为参数注入——Skill 代码里没有一个框架 import。
>
> Agent 的循环（Loop）、会话（Session）、存储（DataStore）是基础设施；Skill 是纯函数；Adapter 是唯一的胶水。

| 维度 | LangChain / LangGraph | Prism Agent |
|------|-----------------------|-------------|
| 定位 | 全功能编排框架 / 图编排运行时 | 轻量骨架：Loop + DataStore + 装配层 |
| 抽象 | 层层封装（Chain / Runnable / LCEL……），行为藏在框架内部 | 内核约 1800 行直通 LLM API，一个下午读完，没有魔法 |
| Skill 形态 | 工具散落在代码里，与框架耦合 | 目录级 Skill（`SKILL.md` + `scripts/`），对齐 Anthropic 官方格式，可整目录搬走 |
| 数据流 | 状态在 Chain / Graph 节点间隐式传递 | 显式 DataStore + Adapter 接线，LLM 上下文不当中转站 |
| 依赖 | 庞大的依赖树 | 4 个运行时依赖 |

这不是说 LangChain 不好——需要它的生态集成时，它是合理选择。Prism Agent 适合想要**完全掌控 Agent 循环**、并希望 Skill 成为**可移植资产**的人。

---

## 目录

- [核心亮点](#核心亮点)
- [为什么不用 LangChain？](#为什么不用-langchain)
- [核心概念](#核心概念)
- [目录结构](#目录结构)
- [安装与配置](#安装与配置)
- [快速上手：5 分钟接入一个新 Agent](#快速上手5-分钟接入一个新-agent)
- [示例 Agent：textcraft 演示](#示例-agenttextcraft-演示)
- [Skill 目录约定（Anthropic Skill 兼容）](#skill-目录约定anthropic-skill-兼容)
- [Adapter 详细指南](#adapter-详细指南)
- [SKILL.yaml / SKILL.md / SYSTEM.md 约定](#skillyaml--skillmd--systemmd-约定)
- [Handler 编写约定](#handler-编写约定)
- [完整示例：从 0 到 1 造一个文章摘要 Agent](#完整示例从-0-到-1-造一个文章摘要-agent)
- [运行时数据流](#运行时数据流)
- [FAQ](#faq)

---

## 核心概念

框架由四类角色组成，各自职责严格分离：

| 角色 | 位置 | 职责 |
|------|------|------|
| **Agent 内核** | [prism/](prism/) 包（8 个模块） | 通用循环：LLM 调用、工具编排、上下文压缩、Session 管理。不关心业务。 |
| **Skill（技能）** | [skills/&lt;agent&gt;/&lt;skill&gt;/](skills/) | 纯业务函数（handler）+ 声明式接口（`SKILL.yaml`）+ 使用说明（`SKILL.md`）。不依赖 session、store、框架。 |
| **Adapter（适配器）** | [adapters/&lt;agent&gt;/&lt;skill&gt;.py](adapters/) | 把 Skill 的入参从 DataStore 里取出来、把出参写回去；声明 LLM 可填哪些参数。 |
| **Agent 实例** | [agents/&lt;agent&gt;.py](agents/) | 一个入口函数：初始化 DataStore 并调用 `agent.init_agent(agent_dir, store)`。 |

一句话总结：**Skill 是可搬的通用能力；Adapter 是让 Skill 长在你这个 Agent 上的胶水。**

---

## 目录结构

```
prism_agent/
├── prism/                # 框架内核包（8 个模块，约 1800 行）
│   ├── agent.py              # Agent Loop 内核（LLM 循环、工具并行、上下文压缩）
│   ├── client.py             # LLM 客户端（call_llm / SkillLLM / MODELS）
│   ├── core.py               # 常量：WORKDIR / SESSION_DIR / SKILLS_DIR / ADAPTERS_DIR
│   ├── data_store.py         # DataStore 抽象 + SQLiteDataStore 实现（宽表 + 动态加列）
│   ├── session.py            # BaseSession（对话历史、chat_events、turn_count）
│   ├── session_context.py    # 通过 contextvars 传递当前 session
│   ├── skill_context.py      # SkillContext / SkillAdapter / BizProxy / PassthroughAdapter
│   └── skill_loader.py       # SkillLoaderV2：扫描 SKILL.yaml、装配 adapter、注入 llm、生成 tool schema
├── requirements.txt
├── .env.example          # API 端点配置模板（复制为 .env 后填入真实值）
├── demo_cli.py           # 示例：textcraft 交互式 CLI
├── demo_server.py        # 示例：textcraft Web demo 后端（Flask）
├── demo_web/             # 示例：textcraft 单页前端
│
├── adapters/             # 每个 agent 一个子目录，里面放 agent.yaml + <skill>.py 适配器
│   ├── __init__.py
│   └── textcraft/        # 示例 agent 的 adapter 与 agent.yaml
├── agents/               # 每个 agent 一个 <agent>.py，提供 init() 入口
│   ├── __init__.py
│   └── textcraft.py      # 示例 agent 入口
└── skills/               # 每个 agent 一个子目录，下辖若干 skill（每 skill 一个子目录）
    ├── __init__.py
    └── textcraft/        # 示例：doc_summary skill + orchestrator
```

---

## 安装与配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

运行时依赖只有四个：`openai`（LLM 调用）、`pyyaml`（SKILL.yaml / agent.yaml 解析）、`json-repair`（LLM JSON 输出容错）、`python-dotenv`（.env 配置加载）。另外 `requirements.txt` 还包含 `flask`——仅供 Web demo（[demo_server.py](demo_server.py)）使用，框架内核不依赖。

### 2. 配置 LLM 端点

框架通过环境变量读取 API 配置（OpenAI 兼容协议，自建代理 / OpenRouter / 官方 API 均可）。复制 `.env.example` 为 `.env` 并填入你的端点：

```bash
cp .env.example .env
```

```ini
# .env
API_BASE=https://your-llm-endpoint/v1
API_KEY=your-api-key
```

也可以直接 `export` 系统环境变量——已存在的环境变量优先于 `.env` 文件。

模型别名在 `agent.yaml` 的 `models` 段按需覆盖：框架内置 `orchestrator` 兜底，skill 可按自己的名字声明专用别名（见下文 [Adapter 详细指南](#adapter-详细指南) 与 FAQ）。

---

## 快速上手：5 分钟接入一个新 Agent

假设你要做一个 `my_agent`，需要一个 `translate` skill。

### 1. 建 skill

```
skills/my_agent/translate/
├── __init__.py           # 空文件
├── SKILL.yaml            # 工具接口声明
├── SKILL.md              # 给 LLM 看的使用说明（可选，但推荐）
└── scripts/              # ← Anthropic Skill 风格：所有 py 实现放这里
    ├── __init__.py
    ├── handlers.py       # 纯函数 handler
    └── prompts.py        # prompt 模板（可选）
```

> 目录约定与 Anthropic Skill 官方格式对齐（`SKILL.md` + `scripts/`），外部 skill 迁移进来时几乎零改动。详见下文 [Skill 目录约定](#skill-目录约定anthropic-skill-兼容)。

[skills/my_agent/translate/SKILL.yaml](skills/):

```yaml
name: translate
description: "翻译：把源文本翻译成目标语言"

tools:
  - name: run_translate
    handler: handlers.tool_translate   # 自动在 scripts/ 下查找（无需写 scripts.handlers）
    description: "翻译源文本到目标语言"
    inputs:
      source_text: str
      target_lang: str
    output: dict
```

[skills/my_agent/translate/scripts/handlers.py](skills/):

```python
import json


def tool_translate(source_text: str = "", target_lang: str = "en", llm=None, **kw) -> str:
    """纯函数：不 import session / store / client。数据来自参数,LLM 能力来自框架注入的 llm 句柄。"""
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
        "_output_data": {"translation": translated},   # 会被 adapter 写回 DataStore
    }, ensure_ascii=False)
```

### 2. 建 adapter

```
adapters/my_agent/
├── __init__.py           # 空文件（skill_loader 会自动发现同目录下的 *.py）
├── agent.yaml            # agent 级配置
└── translate.py          # 对应 skill 的 adapter
```

[adapters/my_agent/agent.yaml](adapters/):

```yaml
name: my_agent

skill_dirs:
  - skills/my_agent

models:
  orchestrator: "deepseek-v4-flash"        # 全局兜底模型
  # <skill_name>: "deepseek-v4-flash"      # 可选:某 skill 的专用模型,自动绑定到注入该 skill handler 的 llm 句柄

loop:
  max_iterations: 10
  temperature: 0.3
  max_tokens: 4096
  # summary_model: "deepseek-v4-flash"   # 可选:上下文压缩用的摘要模型,默认取 models.orchestrator
```

[adapters/my_agent/translate.py](adapters/):

```python
from typing import Any, Dict
from prism.skill_context import SkillAdapter, SkillContext


class TranslateAdapter(SkillAdapter):
    skill_name = "translate"   # 必须与 SKILL.yaml 的 name 一致

    def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
        # 从 DataStore 读取 skill 需要的输入
        return {
            "source_text": ctx.store.get_field(ctx.session_id, "source_text") or "",
        }

    def write_output(self, ctx: SkillContext, result: Any):
        # skill 返回的 _output_data 会被自动传进来
        if isinstance(result, dict) and "translation" in result:
            ctx.store.set_field(ctx.session_id, "translation", result["translation"])

    def get_tool_params(self) -> Dict[str, dict]:
        # 声明 LLM 需要自己填的参数（不来自 DataStore）
        return {
            "run_translate": {
                "target_lang": {
                    "type": "string",
                    "description": "目标语言，如 en/zh/ja",
                    "required": True,
                },
            }
        }
```

### 3. 建 agent 入口

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
    agent.init_agent(
        agent_dir=ADAPTERS_DIR / "my_agent",
        store=store,
    )
    return store
```

### 4. 跑起来

```python
from pathlib import Path
from agents.my_agent import init
from prism import agent

store = init(Path(".data"))

# 从 session 拿到默认 session_id 并写入业务数据
sess = agent._default_session
sess.session_id = "demo-session"
store.set_field(sess.session_id, "source_text", "你好，世界")

# 走一轮 agent loop
for event in agent.agent_loop_stream("请把它翻译成英文", conversation_history=[]):
    print(event)
```

到这里，一个最小可用的 Agent 就跑通了。下一节详细讲 Adapter。

---

## 示例 Agent：textcraft 演示

仓库内置了一个完整可跑的示例 agent **textcraft**（文档处理：类型识别 + 按类型的结构化摘要），覆盖本 README 的全部约定，可直接运行体验：

```
skills/textcraft/doc_summary/     # skill(两个 tool:classify_document / generate_summary)
skills/textcraft/orchestrator/    # SYSTEM.md(编排指令)
adapters/textcraft/               # agent.yaml + 两个 adapter
agents/textcraft.py               # agent 入口
demo_cli.py                       # 交互式 CLI
demo_server.py + demo_web/        # Web demo(Flask + 单页前端)
```

设计要点:用户上传文档后,`classify_document` 只做**采样分类**(前 3000 字符,低成本),识别结果 `doc_type` 落库;`generate_summary` 从 DataStore 读取共享的 `doc_type`,生成类型专属的结构化摘要(论文/小说/新闻/其他),未分类时自动兜底。上传后没有指令时,agent 只告知类型并询问意图,不会直接生成摘要。

**跑 CLI**:

```bash
python demo_cli.py
# 然后输入: /upload your_doc.txt   → agent 识别类型并询问下一步
# 再输入:   帮我生成摘要           → 结构化摘要
# (/state 查看 DataStore,/new 新会话,/quit 退出)
```

**跑 Web**(需要 flask):

```bash
python demo_server.py   # → http://127.0.0.1:5057
# 页面里选 agent、点击上传、流式聊天
```

---

## Skill 目录约定（Anthropic Skill 兼容）

我们的 skill 目录布局对齐 [Anthropic Claude Skill 官方格式](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills)，同时用 `SKILL.yaml` 补充了严格的接口声明。这样做的好处：

- **外部 skill 可平移进来** — 只要它遵循 `SKILL.md + scripts/` 的通用结构，接入本框架时只需补一个 `SKILL.yaml` + `adapter`
- **本地 skill 可外发** — 把 `SKILL.yaml` / adapter 剥离即可作为纯 Claude Skill 使用
- **规范化的分层** — 声明（yaml/md）与实现（scripts）分离，Diff 更清晰

### 推荐目录

```
skills/<agent>/<skill>/
├── SKILL.md          # 【推荐】自然语言说明（含 YAML frontmatter），按需 load 到 LLM 上下文
├── SKILL.yaml        # 【必需*】工具接口声明（*若该 skill 想暴露成 tool）
├── __init__.py
├── scripts/          # 【推荐】所有可执行代码（handler、内部工具函数、prompt 模板）
│   ├── __init__.py
│   ├── handlers.py
│   └── prompts.py
├── references/       # 【可选】参考文档，LLM 需要时再读（对齐 Anthropic 约定，本框架暂不自动加载）
└── assets/           # 【可选】静态资源：图片、模板文件、JSON 数据等
```

除 `SKILL.md`、`SKILL.yaml`、`SYSTEM.md`、`__init__.py` 外，所有 `.py` 都应放在 `scripts/` 下。

### Handler 路径解析规则

`SKILL.yaml` 里 `handler: <module>.<function>` 的解析顺序（见 [prism/skill_loader.py:_resolve_handler](prism/skill_loader.py#L100)）：

1. **先查 `<skill>/scripts/<module>.py`** ← 推荐写法：`handler: handlers.tool_x`
2. 再查 `<skill>/<module>.py`（兼容遗留的平铺布局）

也允许显式写全路径：`handler: scripts.handlers.tool_x`，效果一致。

### 与纯 Anthropic Skill 的差异

| 特性 | Anthropic Skill | 本框架 |
|------|-----------------|--------|
| SKILL.md（含 YAML frontmatter） | ✓ | ✓ |
| scripts/ 目录 | ✓ | ✓ |
| references/ 目录 | ✓ 按需读 | 保留位置，不自动扫描（可自己 handler 里读） |
| assets/ 目录 | ✓ | 同上 |
| 工具入口 | 由 LLM 自主判断（读 SKILL.md） | 通过 `SKILL.yaml` **显式**声明 + Adapter wire 数据 |
| Session/Store 集成 | 无（各 skill 自管） | 由 `SkillAdapter` 统一桥接 DataStore |

一句话：**结构和 Anthropic 对齐，接线通过 `SKILL.yaml` + `Adapter` 补强，兼顾兼容性和可控性。**

---

## Adapter 详细指南

Adapter 是新写 Agent 时最需要理解的一层。它继承自 [prism/skill_context.py:98](prism/skill_context.py#L98) 的 `SkillAdapter`，共 5 个方法（2 个必须实现，3 个可选覆写）。

### 方法总览

| 方法 | 必需 | 何时被框架调用 | 作用 |
|------|------|----------------|------|
| `skill_name`（类属性） | **必需** | 框架启动扫描 adapter 时 | 与 `SKILL.yaml` 的 `name` 匹配 |
| `resolve_inputs(ctx)` | **必需** | 每次工具调用之前 | 从 DataStore 读入 skill 需要的入参 |
| `write_output(ctx, result)` | **必需** | handler 返回后 | 把 `_output_data` 写回 DataStore |
| `validate_inputs(inputs)` | 可选 | `resolve_inputs` 之后 | 校验输入是否齐全，不齐时返回错误字符串 |
| `get_tool_params()` | 可选 | 生成 OpenAI tool schema 时 | 声明 LLM 需要自己填的字段 |
| `resolve_prompt_context(ctx)` | 可选 | 每轮构建 system prompt 时 | 把 session 动态状态塞进 system prompt |
| `format_llm_response(name, r)` | 可选 | handler 返回后（给 orchestrator 之前） | 精简回传给 LLM 的内容 |

### 1. `skill_name`（类属性）

必须与对应 `SKILL.yaml` 里的 `name` 一模一样。框架用它把 adapter 和 skill 配对。

```python
class SummaryAdapter(SkillAdapter):
    skill_name = "summary"  # ← 对应 skills/writer_agent/summary/SKILL.yaml 的 name: summary
```

### 2. `resolve_inputs(ctx) -> Dict[str, Any]`

从 DataStore 里读出 skill 需要的入参。**只需要返回和 `SKILL.yaml` `inputs` 字段名一致的键**，多余的键会被自动忽略。

```python
def resolve_inputs(self, ctx: SkillContext) -> Dict[str, Any]:
    return {
        "article_text": ctx.store.get_field(ctx.session_id, "article_text"),
        "summary":      ctx.store.get_field(ctx.session_id, "summary"),
        "user_query":   ctx.last_user_message(),    # 直接读 session 历史
    }
```

`ctx` 是 [SkillContext](prism/skill_context.py#L61)，提供三个入口：

- `ctx.store` — DataStore 实例（`get_field/set_field/delete_field/ensure_field`）
- `ctx.session_id` — 当前 session id
- `ctx.session` — BaseSession 对象（`history`、`chat_events`、`turn_count`）
- `ctx.biz["key"]` — 语法糖，等价于 `ctx.store.get_field(ctx.session_id, "key")`
- `ctx.last_user_message()` — 便捷方法：拿最近一条 user 消息

### 3. `write_output(ctx, result)`

Handler 返回结构里如果有 `_output_data` 字段，会被框架自动抽出并作为 `result` 传进来。你负责把它写回 DataStore。

```python
def write_output(self, ctx: SkillContext, result: Any):
    if isinstance(result, dict) and "summary" in result:
        ctx.store.set_field(ctx.session_id, "summary", result["summary"])
```

### 4. `validate_inputs(inputs) -> str`（可选）

在 handler 被调用之前做前置校验。返回非空字符串 → 直接以 error 状态短路返回，不再调用 handler。

```python
def validate_inputs(self, inputs: Dict[str, Any]) -> str:
    if not inputs.get("article_text"):
        return "Required input 'article_text' is None (请先上传原文)"
    return ""
```

### 5. `get_tool_params() -> Dict[str, dict]`（可选）

**这个方法直接决定 LLM 能看到什么参数。** 三种情况：

**（a）零参数**：全部输入都来自 DataStore，LLM 只需要决定"是否调用"。此时不用覆写，或返回 `{}`。

```yaml
# SKILL.yaml 里的 tool 会呈现为：
{"type": "function", "function": {"name": "generate_summary", "parameters": {"type": "object", "properties": {}}}}
```

**（b）部分参数**：一部分来自 DataStore、一部分让 LLM 填（如"用户的修改意见"这种即席文本）。

```python
def get_tool_params(self) -> Dict[str, dict]:
    return {
        "revise_summary": {
            "revision_request": {
                "type": "string",
                "description": "用户对摘要的具体修改要求",
                "required": True,
            }
        }
    }
```

框架规则（见 [prism/skill_loader.py:245-250](prism/skill_loader.py#L245-L250)）：
- 在 `get_tool_params` 里声明过的字段 → LLM 传的值**覆盖** `resolve_inputs` 的值
- 其他 LLM 传的字段，若 `pass_kwargs=True`（默认），也会透传给 handler

**（c）复合参数**：多个字段都由 LLM 填。声明多个 key 即可。

### 6. `resolve_prompt_context(ctx) -> str`（可选，仅 SYSTEM.md 所在 skill 的 adapter 会被调用）

用来把动态状态塞到 system prompt 末尾。典型场景：告诉 LLM"当前已完成到哪个阶段""当前摘要是什么"。

```python
def resolve_prompt_context(self, ctx: SkillContext) -> str:
    summary = ctx.store.get_field(ctx.session_id, "summary")
    if not summary:
        return "## Current Stage\nNo summary yet."
    return f"## Current Summary\n```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```"
```

只有承载 `SYSTEM.md` 的那个 skill 对应的 adapter 会被调用（见 [prism/skill_loader.py:523-542](prism/skill_loader.py#L523-L542)），一般是 `orchestrator` skill。

### 7. `format_llm_response(tool_name, result)`（可选）

Handler 返回给编排器 LLM 之前的"瘦身"钩子。默认实现会**自动剥掉 `_output_data` 字段**（因为它已经通过 `write_output` 落库了，没必要再给 LLM 看，省 token）。一般不用覆写。

---

## SKILL.yaml / SKILL.md / SYSTEM.md 约定

### SKILL.yaml — 工具接口声明

```yaml
name: summary                     # 与 adapter 的 skill_name 匹配
description: "文章摘要生成技能"

tools:
  - name: generate_summary        # OpenAI function calling 的 name
    handler: handlers.tool_generate_summary   # <module>.<function>，模块相对 skill 目录
    description: "首次生成摘要（LLM 会读到）"
    inputs:                       # 用作文档 + 决定 handler 收哪些字段
      article_text: str
      style: str
    output: dict
    # pass_kwargs: true            # 默认 true，LLM 未在 get_tool_params 声明的额外参数是否透传
```

关键规则：
- `handler` 必须是 `<相对模块名>.<函数名>`。框架会先在 `scripts/` 下查找，找不到再退回到 skill 根目录。所以写 `handlers.tool_generate_summary` → 优先解析为 `skills/<agent>/<skill>/scripts/handlers.py::tool_generate_summary`
- `inputs` 里的字段名要与 handler 函数签名对得上
- 如果 handler 返回结构里有 `_output_data`，框架会用它做落库
- 一个 skill 可以声明多个 tool（如 `generate_summary` + `revise_summary`）

### SKILL.md — 给 LLM 按需加载的详细说明

```markdown
---
name: summary
description: 文章摘要生成与修改
---

# Summary Skill

## Capabilities
| Tool | Description |
|------|-------------|
| generate_summary | 首次生成 |
| revise_summary   | 基于用户意见修改 |

## Tool Instructions
### 生成
Call `generate_summary` (no parameters).
...
```

`SKILL.md` 的 **description**（frontmatter）会出现在 orchestrator 的 system prompt 的 Skill 列表里；**body** 只在 LLM 主动 `load_skill("summary")` 时才注入到上下文，避免 system prompt 过长。

### SYSTEM.md — 编排 Agent 的主系统提示

放在 orchestrator skill 目录下（如 `skills/&lt;agent&gt;/orchestrator/SYSTEM.md`）。它会被作为 system prompt 的主体。框架启动扫描时会自动加载：

```
SYSTEM.md 内容
+
## Available Skills (call load_skill("<name>") for details)
- summary: 文章摘要生成与修改
- translate: 翻译
+
（orchestrator adapter 的 resolve_prompt_context 返回内容，如动态状态）
```

一个 Agent 只应有**一个** `SYSTEM.md`。

---

## Handler 编写约定

Handler 是纯函数：不 import session、不 import store、不 import client。所有输入都从参数进来——**包括 LLM 能力**：框架在每次调用前注入 `llm` 句柄（`llm.complete(messages, temperature=..., max_tokens=...) -> str`，失败抛 `LLMError`），模型按 skill 名自动路由。

```python
def tool_translate(source_text: str = "", target_lang: str = "en", llm=None, **kw) -> str:
    if not source_text:
        return json.dumps({"status": "error", "message": "empty"}, ensure_ascii=False)

    # ... 业务逻辑(需要 LLM 时用 llm.complete(...)) ...

    return json.dumps({
        "status": "success",
        "translation": translated,          # 给 LLM 看
        "_output_data": {                   # ← 会被 write_output 抽出、写回 DataStore
            "translation": translated,
        },
        # 可选：
        # "instant_reply": "翻译完成 ✅",  # 会作为 SSE instant_reply 事件推给前端
    }, ensure_ascii=False)
```

约定：

- 返回类型：`str`（JSON）或 `dict`
- **`status`**: `"success"` / `"error"`（LLM 靠它判断是否成功）
- **`_output_data`**: 需要落库的内容。没有则表示 skill 是只读的
- **`instant_reply`**（可选）: 立即推送给前端的一句话（无需等 LLM 生成回复）
- **`llm`**（保留字）: 框架注入的 LLM 句柄，绑定 `agent.yaml` models 段里与 skill 同名的 key（未配置则兜底 orchestrator）。不经过 SKILL.yaml inputs / DataStore / LLM 参数。直接调用 handler（如单测）时自行传入 stub 即可——handler 单测不再需要 API key。不需要 LLM 的确定性 handler 不声明 `llm` 即可：框架按签名内省**按需注入**，严格签名（无 `**kw`）的 handler 不会被多塞参数
- 未在 `SKILL.yaml` `inputs` 里声明的参数（如 `**kw`）会由框架按 `pass_kwargs=True` 透传，用于兼容 orchestrator 传的额外键

---

## 完整示例：从 0 到 1 造一个文章摘要 Agent

以下是一个最小可用的 `writer_agent`：根据用户上传的文章生成摘要，并支持基于用户反馈修改摘要。可以直接对照本骨架的目录约定与写法。

**目录**：
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
    └── scripts/       # ← 与 Anthropic Skill 对齐
        ├── __init__.py
        ├── handlers.py    # 纯函数 handler
        └── prompts.py
```

**adapters/writer_agent/agent.yaml**：

```yaml
name: writer_agent
skill_dirs:
  - skills/writer_agent
models:
  orchestrator: "deepseek-v4-flash"        # 全局兜底模型
  # <skill_name>: "deepseek-v4-flash"      # 可选:某 skill 的专用模型,自动绑定到注入该 skill handler 的 llm 句柄
loop:
  max_iterations: 15
  temperature: 0.3
  max_tokens: 4096
  # summary_model: "deepseek-v4-flash"   # 可选:上下文压缩用的摘要模型,默认取 models.orchestrator
```

**adapters/writer_agent/summary.py**：

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
            return "Required input 'article_text' is None (请先上传或粘贴原文)"
        return ""

    def get_tool_params(self) -> Dict[str, dict]:
        return {
            "revise_summary": {
                "revision_request": {
                    "type": "string",
                    "description": "用户对摘要的具体修改要求（如'更精简''换成活泼口吻'）",
                    "required": True,
                }
            }
        }
```

**skills/writer_agent/summary/SKILL.yaml**：

```yaml
name: summary
description: "文章摘要：从原文生成 / 修改摘要（含标题、要点、正文摘要）"

tools:
  - name: generate_summary
    handler: handlers.tool_generate_summary
    description: "生成摘要（基于已保存的原文）。调用前必须先让用户上传或粘贴文章。"
    inputs:
      article_text: str
      user_query: str
    output: dict

  - name: revise_summary
    handler: handlers.tool_revise_summary
    description: "根据用户最新消息中的修改要求，修订当前摘要"
    inputs:
      article_text: str
      summary: dict
      revision_request: str
    output: dict
```

**skills/writer_agent/summary/scripts/handlers.py**：

```python
import json
from .prompts import SUMMARY_GENERATE_PROMPT


def tool_generate_summary(article_text=None, user_query="", llm=None, **kw) -> str:
    # ... 用注入的 llm 句柄抽取标题 / 要点 / 摘要（略）...
    result = {"title": "...", "bullets": ["...", "..."], "abstract": "..."}
    return json.dumps({
        "status": "success",
        "summary": result,
        "_output_data": {"summary": result},
    }, ensure_ascii=False)


def tool_revise_summary(summary=None, revision_request="", llm=None, **kw) -> str:
    # 注意：revision_request 由 LLM 经 get_tool_params 声明传入,
    # summary 由 SummaryAdapter.resolve_inputs 从 DataStore 取出,
    # llm 由框架注入
    # ... 略 ...
    return json.dumps({"status": "success", "summary": summary, "_output_data": {"summary": summary}}, ensure_ascii=False)
```

**agents/writer_agent.py**：

```python
from pathlib import Path
from prism import agent
from prism.core import ADAPTERS_DIR
from prism.data_store import SQLiteDataStore


def init(data_dir: Path):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteDataStore(str(data_dir / "writer_agent.db"))
    agent.init_agent(agent_dir=ADAPTERS_DIR / "writer_agent", store=store)
    return store
```

---

## 运行时数据流

以调用 `revise_summary` 为例（LLM 决定调工具的那一刻）：

```
1. LLM 决定调用 revise_summary(revision_request="把口吻改得更活泼一点")
                           │
2. 框架取出 skill_name="summary" 对应的 SummaryAdapter
                           │
3. SummaryAdapter.resolve_inputs(ctx)
     → 从 DataStore 读 article_text, summary
     → 从 ctx.last_user_message() 读 user_query
                           │
4. 校验：SummaryAdapter.validate_inputs(inputs)   [可选]
                           │
5. 按 SKILL.yaml inputs 过滤字段 + LLM 参数覆盖,框架注入 llm 句柄
     kwargs = {
         "article_text": "...",
         "summary": {...},
         "revision_request": "把口吻改得更活泼一点",   # ← LLM 提供的
         "llm": SkillLLM("summary"),                   # ← 框架注入(绑定 models 段同名模型)
     }
                           │
6. tool_revise_summary(**kwargs) → 返回 JSON
                           │
7. 抽 _output_data → SummaryAdapter.write_output(ctx, output_data)
                           │
8. SummaryAdapter.format_llm_response(...)  → 剥掉 _output_data → 回给 orchestrator
                           │
9. Orchestrator LLM 拿到工具结果，进入下一轮 / 生成用户回复
```

---

## FAQ

**Q: skill 一定要有 adapter 吗？**
A: 想让工具"被 LLM 调用"就必须有。如果只是文档型（SKILL.md 里有指令供别的 skill 参考），可以不写 adapter，就不会被注册为 tool。也可以用框架提供的 `PassthroughAdapter`（[prism/skill_context.py:182](prism/skill_context.py#L182)）作为 default_adapter，把 `SkillContext` 直接传给 handler。

**Q: 一个 skill 可以有多个 adapter 吗？**
A: 不建议。约定一个 skill 一个 adapter。如果不同工具需要不同数据来源，可以在同一个 adapter 里用工具名分支：`if tool_name == "xxx": ...`。但一般更好的做法是拆成两个 skill。

**Q: DataStore 需要提前建表吗？**
A: 不需要。`SQLiteDataStore` 会在你第一次 `set_field(session_id, "any_field", value)` 时自动 `ALTER TABLE ADD COLUMN`（见 [prism/data_store.py:86](prism/data_store.py#L86)）。所有字段值都以 JSON 字符串存储。

**Q: MODELS 里的模型别名怎么改？**
A: 框架只内置一个兜底别名 `orchestrator`。约定：**skill 用自己的名字作别名**——在 `agent.yaml` 的 `models` 段配置同名 key，即为该 skill 的专用模型；框架把它绑定到注入 handler 的 `llm` 句柄上，handler 不需要自己选模型（未配置时自动兜底 orchestrator）。`init_agent` 启动时调 `client.configure_models(...)` 把 models 段合并进 MODELS 表。参考 [adapters/textcraft/agent.yaml](adapters/textcraft/agent.yaml)。

**Q: 上下文压缩怎么触发？**
A: 每轮 loop 开始前会估算 tokens，超过 `core.TOKEN_THRESHOLD`（默认 80k）就会：(1) 裁剪超长 tool output；(2) 用轻量模型对中间消息做结构化摘要。你不需要手动干预。

**Q: 前端怎么消费事件？**
A: `agent.agent_loop_stream(...)` 是 generator，逐个 yield SSE 事件：`tool_call` / `tool_result` / `instant_reply` / `done` / `error` / `usage`。用 Flask/FastAPI 包装成 `text/event-stream` 即可。

**Q: 想复用别人的 skill 怎么办？**
A: 如果对方是 Anthropic 风格的 skill（`SKILL.md` + `scripts/`），直接把 skill 目录拷进 `skills/<my_agent>/`，然后：(1) 在 skill 根加一个 `SKILL.yaml` 声明 tool 接口；(2) 在 `adapters/<my_agent>/` 下加一个对应的 adapter，wire 到你自己的 DataStore 字段。零改动原 `scripts/` 代码。

---

## License

[MIT](LICENSE)