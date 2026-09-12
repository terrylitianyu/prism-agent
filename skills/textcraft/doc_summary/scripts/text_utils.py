#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_summary 的文本工具(纯函数):长文分块与 md5。"""

import hashlib
import re

CHUNK_SIZE = 4000
LONG_DOC_TOKEN_THRESHOLD = 45_000  # 估算 token 严格 > 该值才走分块 Map-Reduce

# 语言感知的 token 估算:CJK 1.5 token/字(与框架 estimate_tokens 对齐),
# ASCII 0.3 token/字(英文约 4 字符/token),其余字符(假名/emoji/符号)按 1.0 保守估
_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")
_ASCII_RE = re.compile(r"[\x20-\x7e\t\n]")

_SENTENCE_SPLIT = re.compile(r"([^。！？!?;；…\n]+[。！？!?;；…]?)")


def estimate_doc_tokens(text: str) -> int:
    """估算文档 token 数(语言感知)。

    字符数阈值对中英文不公平:同一字符量,中文 token 数是英文的约 5 倍——
    中文可能撑爆单次调用上下文,英文却远未饱和。改用 token 口径后,
    阈值语义是"单次摘要调用的输入预算",而非文档长度。
    """
    text = text or ""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    ascii_ = len(_ASCII_RE.findall(text))
    other = len(text) - cjk - ascii_
    return int(cjk * 1.5 + ascii_ * 0.3 + other * 1.0)


def is_long_doc(text: str) -> bool:
    """文档是否走分块 Map-Reduce:估算 token 超过单次调用输入预算。"""
    return estimate_doc_tokens(text) > LONG_DOC_TOKEN_THRESHOLD


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """把长文档切成 ≤ chunk_size 的块,降级链保证收敛:
    1) 空行段落边界贪心聚合;2) 单段超长按句子边界切;3) 单句仍超硬切 chunk_size。"""
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= chunk_size:
            current = _aggregate(current, para, chunk_size, chunks)
            continue
        # 单段超长:按句子边界切
        for sent in _SENTENCE_SPLIT.findall(para):
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) <= chunk_size:
                current = _aggregate(current, sent, chunk_size, chunks)
            else:
                # 单句仍超:先冲刷 current,再硬切该句
                if current:
                    chunks.append(current)
                    current = ""
                for i in range(0, len(sent), chunk_size):
                    chunks.append(sent[i:i + chunk_size])
    if current:
        chunks.append(current)
    return chunks


def _aggregate(current: str, piece: str, chunk_size: int, chunks: list[str]) -> str:
    """把 piece 并入 current;放不下则先冲刷 current 再另起。piece 必 ≤ chunk_size。"""
    if not current:
        return piece
    if len(current) + 1 + len(piece) <= chunk_size:
        return f"{current}\n{piece}"
    chunks.append(current)
    return piece


def md5_of(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()
