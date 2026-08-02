#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_summary skill 的 prompt 模板(纯数据,无逻辑)。"""

CLASSIFY_PROMPT = """你是一个文档分类器。请判断以下文档片段属于哪种类型:

- paper:学术论文、技术报告、研究文档(通常含摘要、方法、实验、参考文献等结构)
- novel:小说、故事、剧本等虚构叙事文本(有人物和情节)
- news:新闻报道、资讯快讯(对时间、地点、事件的客观报道)
- general:不属于以上三类的其他文档

只回复一个英文单词(paper / novel / news / general),不要输出任何其他内容。

文档片段:
---
{text}
---"""

TYPE_LABELS = {
    "paper": "论文",
    "novel": "小说",
    "news": "新闻",
    "general": "其他文档",
}

_SUMMARY_INSTRUCTIONS = {
    "paper": """请以 JSON 输出该论文的结构化摘要,字段如下:
{
  "title": "论文标题",
  "research_question": "研究问题(一句话)",
  "methodology": "研究方法(一两句话)",
  "key_findings": ["关键发现1", "关键发现2"],
  "limitations": "局限性(若文中未提及则填'文中未提及')",
  "tldr": "三句话以内的总结"
}""",
    "novel": """请以 JSON 输出该小说的结构化摘要,字段如下:
{
  "title": "作品名(若无法判断则填'未知')",
  "genre": "题材类型",
  "main_characters": ["主要人物1", "主要人物2"],
  "plot_summary": "情节梗概(三五句话)",
  "themes": ["主题1", "主题2"],
  "tldr": "三句话以内的总结"
}""",
    "news": """请以 JSON 输出该新闻的结构化摘要,字段如下:
{
  "title": "标题",
  "who": "涉及的人物/机构",
  "what": "发生了什么",
  "when": "时间",
  "where": "地点",
  "why": "原因/背景(若文中未提及则填'文中未提及')",
  "key_facts": ["关键事实1", "关键事实2"],
  "tldr": "三句话以内的总结"
}""",
    "general": """请以 JSON 输出该文档的结构化摘要,字段如下:
{
  "title": "文档主题(一句话)",
  "key_points": ["要点1", "要点2", "要点3"],
  "tldr": "三句话以内的总结"
}""",
}


def build_summary_prompt(doc_type: str, document_text: str, focus: str = "") -> str:
    """按文档类型拼摘要 prompt;focus 非空时注入用户侧重点。"""
    instruction = _SUMMARY_INSTRUCTIONS.get(doc_type, _SUMMARY_INSTRUCTIONS["general"])
    focus_line = f"\n用户特别关注的方面:{focus}(请在摘要中有所侧重)\n" if focus.strip() else ""
    return f"""你是一个专业的文档摘要助手。{focus_line}
{instruction}

要求:只输出 JSON 本体,不要输出 ```json 代码块标记,不要输出任何额外解释。

文档全文:
---
{document_text}
---"""
