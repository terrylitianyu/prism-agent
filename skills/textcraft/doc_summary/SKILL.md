---
name: doc_summary
description: 文档摘要：类型识别（论文/小说/新闻/其他）+ 按类型的结构化摘要提取
---

# Doc Summary Skill

## Capabilities

| Tool | Description |
|------|-------------|
| classify_document | 识别文档类型（采样分类，低成本） |
| generate_summary  | 按类型生成结构化摘要（可选 focus 侧重） |

## Tool Instructions

### 类型识别
用户上传或粘贴新文档、且未给出明确指令时，调用 `classify_document`（无参数）。
调用后：用一句话告知用户识别出的类型，并询问用户接下来想做什么（生成摘要？还是其他）。

### 结构化摘要
用户要求总结/摘要时，调用 `generate_summary`。
- 可选参数 `focus`：用户想侧重的方面（如"研究方法""人物关系"），没有则省略
- 已识别过类型的文档**不要**重复调用 `classify_document`；未分类时本工具会自动先分类
- 调用前必须先有文档；若用户还没上传，引导用户先上传

## 类型与输出结构

| doc_type | 中文 | 结构化摘要字段 |
|----------|------|----------------|
| paper | 论文 | title / research_question / methodology / key_findings / limitations / tldr |
| novel | 小说 | title / genre / main_characters / plot_summary / themes / tldr |
| news | 新闻 | title / who / what / when / where / why / key_facts / tldr |
| general | 其他 | title / key_points / tldr |
