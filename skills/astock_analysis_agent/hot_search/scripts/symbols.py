#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票代码解析(hot_search 精简版,自包含)—— 纯函数,零依赖。

人气榜接口返回的代码形如 "SH603095"/"SZ300059",本模块只做前缀剥离。
"""

import re


def strip_prefix(code: str) -> str:
    """'SH603095' / 'sz000001' / '603095.SH' → '603095'。"""
    if not isinstance(code, str):
        raise ValueError(f"无效的股票代码: {code!r}")
    s = code.strip()
    s = re.sub(r"[.\s]", "", s)  # '000001.SZ' → '000001SZ', 'SH 600519' → 'SH600519'
    m = re.match(r"^(?:sz|sh|bj)?(\d{6})(?:sz|sh|bj)?$", s, re.IGNORECASE)
    if not m:
        raise ValueError(f"无效的股票代码: {code!r}(应为6位数字,如 603095)")
    return m.group(1)
