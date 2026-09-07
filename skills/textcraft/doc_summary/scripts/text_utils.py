#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_summary 的文本工具(纯函数):长文分块与 md5。"""

import hashlib
import re

CHUNK_SIZE = 4000
LONG_DOC_THRESHOLD = 20000  # 字符数严格 > 该阈值才走分块 Map-Reduce

_SENTENCE_SPLIT = re.compile(r"([^。！？!?;；…\n]+[。！？!?;；…]?)")


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
