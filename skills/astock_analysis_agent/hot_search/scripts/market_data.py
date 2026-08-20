#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AkShare 数据获取(hot_search 专用,自包含)。

本 skill 内唯一 import akshare 的模块:重试 + TTL 缓存 + DataFrame→JSON 清洗。
数据源容错链(实测确认):
- 人气榜: 东财 stock_hot_rank_em → 百度 stock_hot_search_baidu(仅名称+热度,无代码)
- 电报快讯: 财联社 stock_info_global_cls
"""

import logging
import math
import threading
import time
from datetime import date, datetime, time as dtime, timedelta

from .symbols import strip_prefix

logger = logging.getLogger(__name__)


class AkshareError(RuntimeError):
    """AkShare 取数失败(含重试),消息为中文、面向用户。"""


def fetch_with_retry(fn, *args, what="行情数据", retries=2, base_delay=1.5, **kwargs):
    """带指数退避重试调用 akshare 函数;全部失败抛 AkshareError。"""
    last = None
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 网络/接口异常种类繁多,统一转为 AkshareError
            last = e
            if attempt < retries:
                time.sleep(base_delay * (2 ** attempt))
    raise AkshareError(f"获取{what}失败(已重试{retries}次): {type(last).__name__}: {last}")


_cache = {}
_cache_lock = threading.Lock()


def ttl_cache(ttl_seconds):
    """装饰器:同参调用在 TTL 内直接返回缓存结果(仅缓存成功返回)。"""
    def deco(fn):
        def wrapper(*args, **kwargs):
            key = (fn.__name__, args, tuple(sorted(kwargs.items())))
            now = time.time()
            with _cache_lock:
                hit = _cache.get(key)
                if hit and now - hit[0] < ttl_seconds:
                    logger.info("TTL 缓存命中: %s", fn.__name__)
                    return hit[1]
            result = fn(*args, **kwargs)
            with _cache_lock:
                _cache[key] = (now, result)
            return result
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco


def _clean(v):
    """numpy/NaN/datetime → JSON 安全类型(DataStore 为纯 JSON)。"""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):  # numpy 标量
        return _clean(v.item())
    if isinstance(v, date):  # 含 datetime(财联社电报日期列)
        return v.isoformat()
    if isinstance(v, dtime):  # 财联社电报时间列
        return v.strftime("%H:%M:%S")
    return v


def df_to_records(df):
    """DataFrame → JSON 安全 dict 列表。"""
    return [{str(k): _clean(v) for k, v in rec.items()} for rec in df.to_dict("records")]


def _pick(rec, *names, default=None):
    """按别名顺序取第一个非空值(防接口列名漂移)。"""
    for n in names:
        if n in rec and rec[n] is not None:
            return rec[n]
    return default


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _parse_pct(v):
    """'+10.01%'/'-0.56%'/'' → float;不可解析返回 None。"""
    try:
        s = str(v).strip().replace("%", "").replace("+", "")
        if s in ("", "-", "--"):
            return None
        return round(float(s), 2)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 人气榜
# ---------------------------------------------------------------------------

@ttl_cache(300)
def _rank_from_em():
    """东财个股人气榜 top100。代码形如 'SH603095'。"""
    import akshare as ak
    df = fetch_with_retry(ak.stock_hot_rank_em, what="个股人气榜(东方财富)")
    rows = []
    for rec in df_to_records(df):
        code = str(_pick(rec, "代码") or "")
        try:
            pure = strip_prefix(code)
        except ValueError:
            pure = ""
        rows.append({
            "rank": int(rec["当前排名"]) if rec.get("当前排名") is not None else None,
            "code": pure or None,
            "name": _pick(rec, "股票名称"),
            "price": _pick(rec, "最新价"),
            "pct_chg": _pick(rec, "涨跌幅"),
        })
    return rows


def _rank_from_baidu():
    """百度热搜(降级源):只有名称+热度+涨跌幅,无代码。近3天逐日尝试。"""
    import akshare as ak
    for offset in (0, 1, 2):
        day = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = fetch_with_retry(ak.stock_hot_search_baidu, symbol="A股",
                                  date=day, time="今日", what=f"百度热搜({day})", retries=1)
        except AkshareError as e:
            logger.warning("百度热搜 %s 失败: %s", day, e)
            continue
        rows = []
        for i, rec in enumerate(df_to_records(df), start=1):
            name = str(_pick(rec, "名称/代码") or "").strip()
            pct = _parse_pct(_pick(rec, "涨跌幅"))
            if not name or name == "A股" or pct is None:
                continue  # 跳过关键词行与不可解析行
            rows.append({
                "rank": i,
                "code": None,
                "name": name,
                "price": None,
                "pct_chg": pct,
                "heat": int(rec["综合热度"]) if rec.get("综合热度") is not None else None,
            })
        if rows:
            return rows
    return []


def get_hot_rank():
    """人气榜列表:东财优先,失败降级百度。返回 [{'rank','code','name','price','pct_chg'}]。"""
    try:
        rows = _rank_from_em()
        if rows:
            return rows
        logger.warning("东财人气榜为空,降级百度热搜")
    except AkshareError as e:
        logger.warning("东财人气榜失败,降级百度热搜: %s", e)
    rows = _rank_from_baidu()
    if not rows:
        raise AkshareError("获取人气榜失败(东财与百度数据源均不可用),请稍后重试")
    return rows


# ---------------------------------------------------------------------------
# 市场快讯(财联社电报)
# ---------------------------------------------------------------------------

@ttl_cache(300)
def get_market_news(limit=30):
    """财联社电报最近 N 条,内容截断 80 字符。返回 [{'title','content','date','time'}]。"""
    import akshare as ak
    df = fetch_with_retry(ak.stock_info_global_cls, symbol="全部", what="市场快讯(财联社电报)")
    items = []
    for rec in df_to_records(df):
        content = str(_pick(rec, "内容") or "")
        items.append({
            "title": _pick(rec, "标题"),
            "content": content[:80] + ("…" if len(content) > 80 else ""),
            "date": _pick(rec, "发布日期"),
            "time": _pick(rec, "发布时间"),
        })
        if len(items) >= limit:
            break
    if not items:
        raise AkshareError("获取市场快讯失败(接口返回为空)")
    return items
