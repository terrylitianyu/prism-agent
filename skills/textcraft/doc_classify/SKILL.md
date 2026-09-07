---
name: doc_classify
description: 文档分类:功能目的型一级分类 + 二级文体细分,输出 JSON 与置信度
---

# Doc Classify Skill

## Capabilities

| Tool | Description |
|------|-------------|
| classify_document | 识别文档类型(采样分类,低成本,输出一级/二级/置信度) |

## Tool Instructions

### 类型识别
用户上传或粘贴新文档、且未给出明确指令时,调用 `classify_document`(无参数)。
调用后:用一句话告知用户识别出的类型(一级·二级),并询问用户接下来想做什么(生成摘要?还是其他)。

### 类型体系
一级按"功能目的"分 5 类(含兜底 general),二级按文体细分 20 类(见下表);
识别不出或把握不足(置信 < 0.6)时兜底 general。

| 一级 | 二级 |
|------|------|
| informational 信息传递型 | news_report 新闻报道 / academic_paper 学术论文 / meeting_minutes 会议纪要 / research_report 研究报告 / encyclopedia_entry 百科词条 / contract 合同协议 / legal_document 法律文书 |
| narrative 故事叙述型 | novel 小说 / prose 散文 / biography 传记 / screenplay 剧本 |
| persuasive 观点说服型 | editorial 时评社论 / review 书评影评 / speech 演讲稿 / marketing_copy 营销文案 / opinion_piece 观点随笔 |
| instructional 步骤指令型 | tutorial 教程指南 / manual 用户手册 / recipe 菜谱 / regulation 规章制度 |
| general 其他 | (无二级) |
