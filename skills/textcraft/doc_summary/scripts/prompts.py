#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_summary skill 的 prompt 模板(从 summary_taxonomy 生成,类目变化自动生效)。"""

import json

from .summary_taxonomy import SUMMARY_TEMPLATES, SUBTYPE_HINTS, extension_for

_OUTPUT_RULES = """要求:
- 只输出 JSON 本体,不要输出 ```json 代码块标记,不要输出任何额外解释
- 信息只来自文档内容,不要编造;文中确实没有的信息,字符串字段填"文中未提及",列表字段填空列表"""

# generate_summary 的兜底:doc_category 缺失时做"一级-only"分类
# (不复制 doc_classify 完整 taxonomy,保持 skill 解耦)
FALLBACK_CLASSIFY_PROMPT = """你是一个文档分类器。请判断以下文档片段的功能目的,从下面 5 类中选一类:
- informational 信息传递型:客观传达事实、数据、知识
- narrative 故事叙述型:叙述故事、经历、人物,以情节或情感为主线
- persuasive 观点说服型:论证观点、说服读者、发表评价与呼吁
- instructional 步骤指令型:给出操作步骤、规则、指引
- general 其他:不属于以上任何一类

只回复一个英文单词(informational / narrative / persuasive / instructional / general),不要输出任何其他内容。

文档片段:
---
{text}
---"""


def _type_line(category, subtype=None) -> str:
    label = SUMMARY_TEMPLATES[category]["label"]
    subtype_label = SUBTYPE_HINTS.get(category, {}).get(subtype, {}).get("label") \
        if subtype else None
    return f"{label}" + (f"·{subtype_label}" if subtype_label else "")


def _hint_line(category, subtype) -> str:
    if not subtype:
        return ""
    hint = SUBTYPE_HINTS.get(category, {}).get(subtype, {}).get("hint")
    return f"该文体的提炼要点:{hint}\n" if hint else ""


def _base_schema(category) -> str:
    lines = ["{"]
    for name, spec in SUMMARY_TEMPLATES[category]["fields"].items():
        d = spec["d"]
        lines.append(f'  "{name}": ["{d}1", "{d}2"],' if spec.get("list")
                     else f'  "{name}": "{d}",')
    lines.append("}")
    return "\n".join(lines)


def _extension_block(category, subtype) -> str:
    ext = extension_for(category, subtype)
    if not ext:
        return ""
    lines = [f"基础字段之外还要输出以下附加字段(本类文体为「{ext['label']}」):", "{"]
    for name, spec in ext["fields"].items():
        d = spec["d"]
        lines.append(f'  "{name}": ["{d}1", "{d}2"],' if spec.get("list")
                     else f'  "{name}": "{d}",')
    lines.append("}")
    return "\n".join(lines)


def _focus_line(focus) -> str:
    return (f"用户特别关注的方面:{focus}(请在摘要中有所侧重)\n"
            if focus and focus.strip() else "")


def build_summary_prompt(category: str, subtype: str | None, document_text: str,
                         focus: str = "") -> str:
    """单 pass 摘要 prompt:一级 base schema + 二级扩展字段(声明时)+ 文体 hint。"""
    hint = _hint_line(category, subtype)
    ext = _extension_block(category, subtype)
    return f"""你是一个专业的文档摘要助手。
{_focus_line(focus)}请为下面的文档生成结构化摘要。文档类型:{_type_line(category, subtype)}
{hint}
输出 JSON 字段如下:
{_base_schema(category)}
{ext}
{_OUTPUT_RULES}

文档全文:
---
{document_text}
---"""


def build_block_summary_prompt(index: int, total: int, chunk: str) -> str:
    """Map 阶段:对第 index 块(共 total 块)提取要点。"""
    return f"""你是文档摘要助手。下面是一篇长文档的第 {index + 1}/{total} 块(全文拆成 {total} 块),请提取本块要点:
只输出一个 JSON 对象,不要任何其他文字:
{{"index": {index}, "summary": "本块要点(150-300字,保留关键事实、数据、人名、时间、结论,不展开评论)"}}

块内容:
---
{chunk}
---"""


def build_merge_prompt(category: str, subtype: str | None,
                       block_summaries: list[str], focus: str = "") -> str:
    """Reduce 阶段:把各块要点归并成整篇文档的结构化摘要。"""
    blocks = "\n\n".join(f"[块 {i + 1}]\n{s}" for i, s in enumerate(block_summaries))
    hint = _hint_line(category, subtype)
    ext = _extension_block(category, subtype)
    return f"""你是专业的文档摘要助手。
{_focus_line(focus)}一篇长文档已按顺序拆成 {len(block_summaries)} 个分块,下面是各分块的要点摘要:
{blocks}

请把这些分块要点合并成整篇文档的结构化摘要。文档类型:{_type_line(category, subtype)}
{hint}
输出 JSON 字段如下:
{_base_schema(category)}
{ext}
{_OUTPUT_RULES}"""


def build_revise_prompt(summary: dict, revision_request: str,
                        document_text: str | None, category: str | None) -> str:
    """修订 prompt:category 合法 → base schema;不合法 → 保持原字段结构。
    长文不带原文,明示不得虚构。"""
    if category:
        schema_block = (f"""输出 JSON 字段如下:
{_base_schema(category)}
保持与现有摘要相同的字段结构;若现有摘要含基础字段之外的附加字段,请保留并同步更新。""")
    else:
        schema_block = "保持与现有摘要相同的字段结构,不要新增或删除字段。"
    if document_text:
        text_block = f"""
文档原文(供核对修改依据):
---
{document_text}
---"""
    else:
        text_block = """
(本文档较长,本次修订不提供原文:仅基于现有摘要修改,不得虚构原文没有的事实)"""
    existing = json.dumps(summary, ensure_ascii=False, indent=2)
    return f"""你是专业的文档摘要助手。请根据用户的修改要求,修订这份文档的结构化摘要。
用户修改要求:
---
{revision_request}
---
现有摘要:
{existing}
{text_block}
{schema_block}
要求:
- 只输出修订后的完整 JSON(不是增量,是完整摘要),不要 ``` 代码块标记
- 只修改与要求相关的部分,其余内容保持原样;信息只来自现有摘要{"和原文" if document_text else ""},不要编造"""
