#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_classify 的分类体系(纯数据):一级 = 功能目的型,二级 = 文体细分。

增删类目只改这份数据,不改任何逻辑(校验规则与提示词均从 TAXONOMY 生成)。
"""

TAXONOMY = {
    "informational": {
        "label": "信息传递型",
        "definition": "客观传达事实、数据、知识",
        "subtypes": {
            "news_report":        {"label": "新闻报道",   "hint": "确保 5W1H 完整;注明信息来源与时效"},
            "academic_paper":     {"label": "学术论文",   "hint": "覆盖研究问题、方法、关键发现;结论与局限写入 conclusion"},
            "meeting_minutes":    {"label": "会议纪要",   "hint": "按议题分组;单独列出决议与待办事项"},
            "research_report":    {"label": "研究报告",   "hint": "突出数据支撑的分析结论与建议"},
            "encyclopedia_entry": {"label": "百科词条",   "hint": "先给定义与基本信息,再列关键属性"},
            "contract":           {"label": "合同协议",   "hint": "提炼签约双方、核心条款(权利义务/金额/期限/标的)、违约与争议解决条款"},
            "legal_document":     {"label": "法律文书",   "hint": "提炼当事人、案由、裁判/请求要点与依据;判决书需注明判决结果"},
        },
    },
    "narrative": {
        "label": "故事叙述型",
        "definition": "叙述故事、经历、人物,以情节或情感为主线",
        "subtypes": {
            "novel":      {"label": "小说", "hint": "交代人物关系与情节主线;主题用 themes 提炼"},
            "prose":      {"label": "散文", "hint": "梳理情感线索与核心意象;写作风格一句话概括"},
            "biography":  {"label": "传记", "hint": "按时间线提炼生平关键节点与重要贡献"},
            "screenplay": {"label": "剧本", "hint": "概述场景结构与核心冲突;标注主要角色与结局"},
        },
    },
    "persuasive": {
        "label": "观点说服型",
        "definition": "论证观点、说服读者、发表评价与呼吁",
        "subtypes": {
            "editorial":      {"label": "时评社论",   "hint": "先提炼核心立场;论据链与对反方观点的回应要完整"},
            "review":         {"label": "书评影评",   "hint": "给出评价对象与总体结论,再列理由与例证"},
            "speech":         {"label": "演讲稿",     "hint": "注明目标听众与核心呼吁;保留修辞亮点"},
            "marketing_copy": {"label": "营销文案",   "hint": "提炼核心卖点、目标人群与行动号召"},
            "opinion_piece":  {"label": "观点随笔",   "hint": "提炼作者核心观点与个人化论证风格"},
        },
    },
    "instructional": {
        "label": "步骤指令型",
        "definition": "给出操作步骤、规则、指引",
        "subtypes": {
            "tutorial":   {"label": "教程指南", "hint": "步骤按顺序完整列出;前置条件与常见问题要覆盖"},
            "manual":     {"label": "用户手册", "hint": "按功能或操作流程组织;注意事项单独列出"},
            "recipe":     {"label": "菜谱",     "hint": "完整列出食材(requirements)与步骤(steps);关键火候/时间要保留"},
            "regulation": {"label": "规章制度", "hint": "提炼适用范围、核心条款与执行要求"},
        },
    },
    "general": {"label": "其他", "definition": "不属于以上任何一类", "subtypes": {}},
}

CATEGORY_KEYS = tuple(TAXONOMY.keys())


def is_valid_category(category) -> bool:
    return category in TAXONOMY


def is_valid_subtype(category, subtype) -> bool:
    return bool(subtype) and subtype in TAXONOMY.get(category, {}).get("subtypes", {})


def category_label(category) -> str | None:
    return TAXONOMY[category]["label"] if is_valid_category(category) else None


def subtype_label(category, subtype) -> str | None:
    if not is_valid_subtype(category, subtype):
        return None
    return TAXONOMY[category]["subtypes"][subtype]["label"]
