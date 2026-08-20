#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技术指标计算 —— 纯 Python,零依赖(不 import pandas/numpy,便于离线单测)。

输入 rows 为按日期升序的 dict 列表,每行至少含 close/volume。
指标只在需要时即时派生,不落库。
"""


def add_ma(rows, windows=(5, 20)):
    """为每行追加 ma5/ma20 列(滚动均值;窗口不足时为 None)。返回新列表,不改原数据。"""
    out = [dict(r) for r in rows]
    for w in windows:
        key = f"ma{w}"
        acc = 0.0
        for i, r in enumerate(out):
            acc += float(r["close"])
            if i >= w:
                acc -= float(out[i - w]["close"])
            r[key] = round(acc / w, 3) if i >= w - 1 else None
    return out


def compute_pct_change(rows, days):
    """近 days 个交易日的收盘涨跌幅(%)。rows 升序;数据不足返回 None。"""
    if len(rows) <= days:
        return None
    prev = float(rows[-days - 1]["close"])
    cur = float(rows[-1]["close"])
    if prev == 0:
        return None
    return round((cur - prev) / prev * 100, 2)


def latest_indicators(rows):
    """由行情 rows 即时派生最新指标摘要(不落库,报告/紧凑返回用)。

    返回: {date, close, pct_chg_latest, ma5, ma20, ma5_gt_ma20,
           pct_5d, pct_20d, recent_closes, recent_volumes}
    """
    if not rows:
        return {}
    ma_rows = add_ma(rows)
    latest = ma_rows[-1]
    ma5 = latest.get("ma5")
    ma20 = latest.get("ma20")
    return {
        "date": latest.get("date", ""),
        "close": latest.get("close"),
        "pct_chg_latest": latest.get("pct_chg"),
        "ma5": ma5,
        "ma20": ma20,
        "ma5_gt_ma20": (ma5 > ma20) if (ma5 is not None and ma20 is not None) else None,
        "pct_5d": compute_pct_change(rows, 5),
        "pct_20d": compute_pct_change(rows, 20),
        "recent_closes": [r.get("close") for r in rows[-5:]],
        "recent_volumes": [r.get("volume") for r in rows[-5:]],
    }
