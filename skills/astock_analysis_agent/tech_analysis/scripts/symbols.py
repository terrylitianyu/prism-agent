#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票代码解析 —— 纯函数,零依赖。

支持输入形式: "000001" / "000001.SZ" / "SZ000001" / "sh600519" / "600519.SH"
输出带交易所后缀的代码与交易所标记。
"""

import re

# 后缀规则(按首字符判断,注意 68 开头属科创板须先于 6 判断):
#   68 → SH(科创板);4/8 → BJ(北交所);6 → SH(沪主板);0/2/3 → SZ(深市)
_EXCHANGE_RULES = (
    (("68",), "SH"),
    (("4", "8"), "BJ"),
    (("6",), "SH"),
    (("0", "2", "3"), "SZ"),
)

_PREFIX_RE = re.compile(r"^(?:sz|sh|bj)?[.\s]?", re.IGNORECASE)


def strip_prefix(code: str) -> str:
    """去掉可能的前缀/后缀格式,提取纯 6 位数字。如 'SZ000001'/'000001.SZ' → '000001'。"""
    if not isinstance(code, str):
        raise ValueError(f"无效的股票代码: {code!r}(应为6位数字字符串)")
    s = code.strip()
    s = re.sub(r"[.\s]", "", s)  # '000001.SZ' → '000001SZ', 'SH 600519' → 'SH600519'
    m = re.match(r"^(?:sz|sh|bj)?(\d{6})(?:sz|sh|bj)?$", s, re.IGNORECASE)
    if not m:
        raise ValueError(f"无效的股票代码: {code!r}(应为6位数字,如 000001)")
    return m.group(1)


def exchange_of(code: str) -> str:
    """6 位纯数字代码 → 交易所标记('SZ'/'SH'/'BJ')。"""
    for prefixes, exchange in _EXCHANGE_RULES:
        if code.startswith(prefixes):
            return exchange
    raise ValueError(f"无法识别的股票代码: {code}(无法判断所属交易所)")


def normalize_symbol(code: str):
    """任意形式输入 → ('000001.SZ', 'SZ')。非法输入抛 ValueError(中文消息)。"""
    digits = strip_prefix(code)
    exchange = exchange_of(digits)
    return f"{digits}.{exchange}", exchange


def is_valid_code(code: str) -> bool:
    """是否为合法的 6 位 A 股代码。"""
    try:
        normalize_symbol(code)
        return True
    except ValueError:
        return False
