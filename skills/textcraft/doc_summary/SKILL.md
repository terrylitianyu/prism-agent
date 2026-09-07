---
name: doc_summary
description: 文档摘要:按功能目的型分类生成结构化摘要(长文自动分块),支持按用户要求修订
---

# Doc Summary Skill

## Capabilities

| Tool | Description |
|------|-------------|
| generate_summary | 按文档类型生成结构化摘要(可选 focus 侧重;长文自动分块) |
| revise_summary  | 按用户要求修订已生成的摘要 |

## Tool Instructions

### 结构化摘要
用户要求总结/摘要时,调用 `generate_summary`。
- 可选参数 `focus`:用户想侧重的方面(如"研究方法""人物关系"),没有则省略
- 类型识别由 doc_classify 负责;未分类时本工具会自动做一级兜底分类
- 调用前必须先有文档;若用户还没上传,引导用户先上传

### 修订摘要
用户要求修改已有摘要时,调用 `revise_summary`(参数 `revision_request` 必填)。
文档内容未变化时优先修订而不是重新生成。

## 类型与输出结构(一级模板)

| doc_category | 中文 | 结构化摘要字段(必填加 *) |
|--------------|------|--------------------------|
| informational | 信息传递型 | title* / topic / key_information* / data_and_figures / conclusion / tldr* |
| narrative | 故事叙述型 | title* / genre / main_characters / plot_summary* / themes / tldr* |
| persuasive | 观点说服型 | title* / core_claim* / key_arguments / evidence / conclusion / tldr* |
| instructional | 步骤指令型 | title* / goal / requirements / steps* / notes / tldr* |
| general | 其他 | title* / key_points* / tldr* |

二级文体(如合同、新闻、菜谱等)在一级模板之上有附加字段(如 parties/amount、source/date、servings/time),由系统自动按文体注入。
