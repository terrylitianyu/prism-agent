#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_classify 的 prompt 构建(从 TAXONOMY 生成,增删类目自动生效)。"""

from .taxonomy import TAXONOMY

_OUTPUT_CONTRACT = """输出契约(严格遵守):
只输出一个 JSON 对象,不要任何其他文字、不要 ``` 代码块标记:
{"category": "一级分类key", "subtype": "二级分类key或null", "confidence": 0.0~1.0}
confidence 是你对判断的把握程度;没把握时填低分,不要硬猜。"""


def build_classify_prompt(filename: str, sampled_text: str) -> str:
    """拼分类 prompt:角色句 → 一级列表 → 二级列表 → 输出契约 → 文件名弱特征 → 采样文本。"""
    cat_lines = [f"- {key} {info['label']}:{info['definition']}"
                 for key, info in TAXONOMY.items()]
    subtype_lines = []
    for key, info in TAXONOMY.items():
        if not info["subtypes"]:
            continue
        items = [f"{skey} {sval['label']}({sval['hint']})"
                 for skey, sval in info["subtypes"].items()]
        subtype_lines.append(f"- {key} 下: {'、'.join(items)}")
    filename_line = (f"\n文件名(辅助参考,可能不准确):{filename}"
                     if filename and filename.strip() else "")
    return f"""你是一个文档分类器。先按"功能目的"判断文档的一级分类,再按文体细分到二级分类。

一级分类(按功能目的):
{chr(10).join(cat_lines)}

二级分类(在一级之下细分文体;若归为 general 则 subtype 填 null):
{chr(10).join(subtype_lines)}
{_OUTPUT_CONTRACT}{filename_line}

文档内容:
---
{sampled_text}
---"""
