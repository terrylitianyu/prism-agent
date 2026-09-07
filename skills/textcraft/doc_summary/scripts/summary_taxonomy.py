#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_summary 的摘要模板(纯数据):一级大类模板 + 二级按需扩展字段。

分层设计:
  - 一级(功能目的型)每类一个 base schema,含 required 校验;
  - 二级(文体)只为需要结构化字段的文体声明 extensions,缺失不触发重试、
    随"补默认值"一步填空,保持摘要结构稳定。
"""

SUMMARY_TEMPLATES = {
    "informational": {
        "label": "信息传递型",
        "fields": {
            "title":           {"d": "标题或主题(一句话)"},
            "topic":           {"d": "核心主题(一句话)"},
            "key_information": {"d": "关键信息/事实", "list": True},
            "data_and_figures": {"d": "关键数据", "list": True},
            "conclusion":      {"d": "结论(若文中未给出则填'文中未提及')"},
            "tldr":            {"d": "三句话以内的总结"},
        },
        "required": ["title", "key_information", "tldr"],
        "extensions": {
            "news_report": {"label": "新闻报道", "fields": {
                "source":       {"d": "信息来源(媒体/机构;文中未注明则填'文中未提及')"},
                "publish_date": {"d": "发布或事发时间"},
                "location":     {"d": "事发地点"},
            }},
            "academic_paper": {"label": "学术论文", "fields": {
                "research_question": {"d": "研究问题(一句话)"},
                "methods":           {"d": "研究方法(一两句话)"},
                "key_findings":      {"d": "关键发现", "list": True},
            }},
            "meeting_minutes": {"label": "会议纪要", "fields": {
                "decisions":    {"d": "决议事项", "list": True},
                "action_items": {"d": "待办事项(负责人/期限)", "list": True},
            }},
            "research_report": {"label": "研究报告", "fields": {
                "recommendations": {"d": "行动建议", "list": True},
            }},
            "contract": {"label": "合同协议", "fields": {
                "parties":        {"d": "签约双方(甲方/乙方)"},
                "subject_matter": {"d": "合同标的"},
                "amount":         {"d": "金额与支付条款(如涉及)"},
                "term":           {"d": "合同期限"},
                "breach_terms":   {"d": "违约与争议解决条款"},
            }},
            "legal_document": {"label": "法律文书", "fields": {
                "parties":         {"d": "当事人"},
                "cause_of_action": {"d": "案由"},
                "ruling":          {"d": "裁判/请求结果"},
                "legal_basis":     {"d": "法律依据"},
            }},
        },
    },
    "narrative": {
        "label": "故事叙述型",
        "fields": {
            "title":           {"d": "作品名(若无法判断则填'未知')"},
            "genre":           {"d": "题材类型"},
            "main_characters": {"d": "主要人物", "list": True},
            "plot_summary":    {"d": "情节梗概(三五句话)"},
            "themes":          {"d": "主题", "list": True},
            "tldr":            {"d": "三句话以内的总结"},
        },
        "required": ["title", "plot_summary", "tldr"],
        "extensions": {
            "biography": {"label": "传记", "fields": {
                "timeline": {"d": "生平关键节点(按时间)", "list": True},
            }},
        },
    },
    "persuasive": {
        "label": "观点说服型",
        "fields": {
            "title":         {"d": "标题或主题(一句话)"},
            "core_claim":    {"d": "核心论点/立场(一句话)"},
            "key_arguments": {"d": "核心论据", "list": True},
            "evidence":      {"d": "支撑证据/例证", "list": True},
            "conclusion":    {"d": "结论或呼吁"},
            "tldr":          {"d": "三句话以内的总结"},
        },
        "required": ["title", "core_claim", "tldr"],
        "extensions": {
            "review": {"label": "书评影评", "fields": {
                "reviewed_work": {"d": "评价对象(作品名)"},
            }},
            "speech": {"label": "演讲稿", "fields": {
                "target_audience": {"d": "目标听众"},
                "call_to_action":  {"d": "核心呼吁"},
            }},
            "marketing_copy": {"label": "营销文案", "fields": {
                "target_audience": {"d": "目标人群"},
                "selling_points":  {"d": "核心卖点", "list": True},
                "call_to_action":  {"d": "行动号召"},
            }},
        },
    },
    "instructional": {
        "label": "步骤指令型",
        "fields": {
            "title":        {"d": "标题或主题(一句话)"},
            "goal":         {"d": "目标(要完成什么)"},
            "requirements": {"d": "前置条件/所需材料", "list": True},
            "steps":        {"d": "操作步骤(按顺序)", "list": True},
            "notes":        {"d": "注意事项", "list": True},
            "tldr":         {"d": "三句话以内的总结"},
        },
        "required": ["title", "steps", "tldr"],
        "extensions": {
            "recipe": {"label": "菜谱", "fields": {
                "servings":   {"d": "分量/人数"},
                "time":       {"d": "烹饪时间"},
                "difficulty": {"d": "难度"},
            }},
        },
    },
    "general": {
        "label": "其他",
        "fields": {
            "title":      {"d": "文档主题(一句话)"},
            "key_points": {"d": "要点", "list": True},
            "tldr":       {"d": "三句话以内的总结"},
        },
        "required": ["title", "key_points", "tldr"],
        "extensions": {},
    },
}

# 与 doc_classify 的 TAXONOMY 同内容但独立维护(skill 可剥离外发,不互相 import);
# hint/扩展键一致性由测试 F8 兜底
SUBTYPE_HINTS = {
    "informational": {
        "news_report":        {"label": "新闻报道",   "hint": "确保 5W1H 完整;注明信息来源与时效"},
        "academic_paper":     {"label": "学术论文",   "hint": "覆盖研究问题、方法、关键发现;结论与局限写入 conclusion"},
        "meeting_minutes":    {"label": "会议纪要",   "hint": "按议题分组;单独列出决议与待办事项"},
        "research_report":    {"label": "研究报告",   "hint": "突出数据支撑的分析结论与建议"},
        "encyclopedia_entry": {"label": "百科词条",   "hint": "先给定义与基本信息,再列关键属性"},
        "contract":           {"label": "合同协议",   "hint": "提炼签约双方、核心条款(权利义务/金额/期限/标的)、违约与争议解决条款"},
        "legal_document":     {"label": "法律文书",   "hint": "提炼当事人、案由、裁判/请求要点与依据;判决书需注明判决结果"},
    },
    "narrative": {
        "novel":      {"label": "小说", "hint": "交代人物关系与情节主线;主题用 themes 提炼"},
        "prose":      {"label": "散文", "hint": "梳理情感线索与核心意象;写作风格一句话概括"},
        "biography":  {"label": "传记", "hint": "按时间线提炼生平关键节点与重要贡献"},
        "screenplay": {"label": "剧本", "hint": "概述场景结构与核心冲突;标注主要角色与结局"},
    },
    "persuasive": {
        "editorial":      {"label": "时评社论",   "hint": "先提炼核心立场;论据链与对反方观点的回应要完整"},
        "review":         {"label": "书评影评",   "hint": "给出评价对象与总体结论,再列理由与例证"},
        "speech":         {"label": "演讲稿",     "hint": "注明目标听众与核心呼吁;保留修辞亮点"},
        "marketing_copy": {"label": "营销文案",   "hint": "提炼核心卖点、目标人群与行动号召"},
        "opinion_piece":  {"label": "观点随笔",   "hint": "提炼作者核心观点与个人化论证风格"},
    },
    "instructional": {
        "tutorial":   {"label": "教程指南", "hint": "步骤按顺序完整列出;前置条件与常见问题要覆盖"},
        "manual":     {"label": "用户手册", "hint": "按功能或操作流程组织;注意事项单独列出"},
        "recipe":     {"label": "菜谱",     "hint": "完整列出食材(requirements)与步骤(steps);关键火候/时间要保留"},
        "regulation": {"label": "规章制度", "hint": "提炼适用范围、核心条款与执行要求"},
    },
}

# 已知字段的缺省值;其余按字段声明推断(list → [],str → "")
FIELD_DEFAULTS = {
    "title": "未提取到标题",
    "tldr": "未能生成总结",
}


def resolve_category(doc_category: str) -> str | None:
    """doc_category 在 SUMMARY_TEMPLATES 中 → 原样返回;否则 None → 调用方内联分类兜底。
    (无 legacy 兼容:旧库直接清空重建)"""
    return doc_category if doc_category in SUMMARY_TEMPLATES else None


def valid_subtype_or_none(category, subtype) -> str | None:
    """subtype 合法(属于该 category)→ 原样返回;否则 None(二级只是 hint,丢弃即可)。"""
    if subtype and subtype in SUBTYPE_HINTS.get(category, {}):
        return subtype
    return None


def extension_for(category, subtype) -> dict | None:
    """返回该文体声明的扩展字段块;未声明 → None。"""
    if not subtype:
        return None
    return SUMMARY_TEMPLATES.get(category, {}).get("extensions", {}).get(subtype)


def required_fields(category) -> list[str]:
    tmpl = SUMMARY_TEMPLATES.get(category)
    return list(tmpl["required"]) if tmpl else []


def field_spec(category, name) -> dict | None:
    """在基础字段与全部扩展字段中找 name 的声明(用于推断默认值类型)。"""
    tmpl = SUMMARY_TEMPLATES.get(category)
    if not tmpl:
        return None
    if name in tmpl["fields"]:
        return tmpl["fields"][name]
    for ext in tmpl["extensions"].values():
        if name in ext["fields"]:
            return ext["fields"][name]
    return None


def field_default(category, name):
    """字段缺省值:已知字段按表取,其余按声明推断(list → [],str → "")。"""
    if name in FIELD_DEFAULTS:
        return FIELD_DEFAULTS[name]
    spec = field_spec(category, name)
    return [] if spec and spec.get("list") else ""
