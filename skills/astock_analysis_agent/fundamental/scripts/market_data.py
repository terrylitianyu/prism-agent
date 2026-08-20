#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AkShare 数据获取(fundamental 专用,自包含)。

本 skill 内唯一 import akshare 的模块:重试 + TTL 缓存 + 列别名映射 +
DataFrame→JSON 清洗。估值与财务列名集中在别名表中,防接口漂移。

数据源(实测确认):
- 估值: 东财 stock_value_em(PE(TTM)/PE(静)/PB/PS/PEG/市值) → 东财个股信息降级
- 财务: 东财 stock_financial_analysis_indicator → 东财 stock_financial_abstract 降级
"""

import logging
import math
import threading
import time
from datetime import datetime

from .symbols import normalize_symbol

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
    """numpy/NaN → JSON 安全类型(DataStore 为纯 JSON)。"""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):  # numpy 标量
        return _clean(v.item())
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


@ttl_cache(86400)
def get_stock_name(code):
    """个股简称(巨潮公司概况,日级稳定);取不到返回 None(非致命)。"""
    try:
        import akshare as ak
        df = fetch_with_retry(ak.stock_profile_cninfo, symbol=code,
                              what=f"{code} 公司概况(巨潮)", retries=1)
        recs = df_to_records(df)
        if recs:
            return _pick(recs[0], "A股简称", "公司名称")
    except AkshareError as e:
        logger.warning("获取股票简称失败(不影响主流程): %s", e)
    return None


# ---------------------------------------------------------------------------
# 估值
# ---------------------------------------------------------------------------

# 财务指标列别名:东财指标列名(接口漂移时在此补充同义词)
_FIN_ALIASES = {
    "date": ("日期", "报告期"),
    "eps": ("摊薄每股收益(元)", "基本每股收益(元)", "每股收益"),
    "roe": ("净资产收益率(%)", "ROE"),
    "revenue_growth": ("主营业务收入增长率(%)", "营业收入增长率(%)"),
    "profit_growth": ("净利润增长率(%)"),
    "debt_ratio": ("资产负债率(%)"),
    "gross_margin": ("销售毛利率(%)", "毛利率"),
}


@ttl_cache(300)
def _valuation_from_value_em(code):
    """东财估值历史序列(取最新一行)。"""
    import akshare as ak
    df = fetch_with_retry(ak.stock_value_em, symbol=code, what=f"{code} 估值(东方财富)")
    recs = df_to_records(df)
    if not recs:
        return None
    r = recs[-1]
    return {
        "date": str(_pick(r, "数据日期") or ""),
        "price": _pick(r, "当日收盘价"),
        "pct_chg": _pick(r, "当日涨跌幅"),
        "pe_ttm": _pick(r, "PE(TTM)"),
        "pe_static": _pick(r, "PE(静)"),
        "pb": _pick(r, "市净率"),
        "ps": _pick(r, "市销率"),
        "peg": _pick(r, "PEG值"),
        "total_mv": _pick(r, "总市值"),
        "float_mv": _pick(r, "流通市值"),
        "source": "eastmoney",
    }


def _valuation_from_info_em(code):
    """降级源:东财个股信息(仅总市值/流通市值)。"""
    import akshare as ak
    df = fetch_with_retry(ak.stock_individual_info_em, symbol=code,
                          what=f"{code} 个股信息(东方财富)", retries=1)
    out = {}
    for rec in df_to_records(df):
        item = str(_pick(rec, "item", "index") or "")
        if item == "总市值":
            out["total_mv"] = _pick(rec, "value")
        elif item == "流通市值":
            out["float_mv"] = _pick(rec, "value")
    if not out:
        return None
    out.update({"date": "", "price": None, "pct_chg": None, "pe_ttm": None,
                "pe_static": None, "pb": None, "ps": None, "peg": None,
                "source": "eastmoney-info"})
    return out


def get_valuation(symbol):
    """估值快照:PE(TTM)/PE(静)/PB/PS/PEG/总市值/流通市值。"""
    full_symbol, _ = normalize_symbol(symbol)
    code = full_symbol.split(".")[0]
    try:
        r = _valuation_from_value_em(code)
    except AkshareError as e:
        logger.warning("东财估值失败,降级个股信息: %s", e)
        r = None
    if not r:
        r = _valuation_from_info_em(code)
    if not r:
        raise AkshareError(f"获取 {symbol} 估值失败(代码不存在或数据源不可用)")
    r.update({"symbol": full_symbol, "name": get_stock_name(code) or ""})
    return r


# ---------------------------------------------------------------------------
# 财务指标(近两年,季度)
# ---------------------------------------------------------------------------

@ttl_cache(300)
def _financials_from_indicator(code):
    """东财财务分析指标(近两年季度,列走别名表)。"""
    import akshare as ak
    year = datetime.now().year
    df = fetch_with_retry(ak.stock_financial_analysis_indicator, symbol=code,
                          start_year=str(year - 3), what=f"{code} 财务指标(东方财富)")
    periods = []
    for rec in df_to_records(df)[-8:]:  # 近两年(8个季度),接口按日期升序
        date = str(_pick(rec, *_FIN_ALIASES["date"]) or "")
        periods.append({
            "date": f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else date,
            "eps": _pick(rec, *_FIN_ALIASES["eps"]),
            "roe": _pick(rec, *_FIN_ALIASES["roe"]),
            "revenue_growth": _pick(rec, *_FIN_ALIASES["revenue_growth"]),
            "profit_growth": _pick(rec, *_FIN_ALIASES["profit_growth"]),
            "debt_ratio": _pick(rec, *_FIN_ALIASES["debt_ratio"]),
            "gross_margin": _pick(rec, *_FIN_ALIASES["gross_margin"]),
        })
    return [p for p in periods if p["date"]]


def _financials_from_abstract(code):
    """降级源:东财财务摘要(选项/指标 × 报告期,转置为按报告期聚合)。"""
    import akshare as ak
    df = fetch_with_retry(ak.stock_financial_abstract, symbol=code,
                          what=f"{code} 财务摘要(东方财富)", retries=1)
    recs = df_to_records(df)
    date_cols = [c for c in recs[0].keys() if str(c).isdigit()][:8] if recs else []

    def row_values(key, target_names):
        for rec in recs:
            name = str(_pick(rec, "指标") or "")
            if any(t in name for t in target_names):
                return {c: rec.get(c) for c in date_cols}
        return {}

    maps = {
        "eps": ("摊薄每股收益", "每股收益"),
        "roe": ("净资产收益率",),
        "revenue_growth": ("主营业务收入增长率", "营业收入增长率"),
        "profit_growth": ("净利润增长率",),
        "debt_ratio": ("资产负债率",),
        "gross_margin": ("销售毛利率", "毛利率"),
    }
    periods = []
    for c in date_cols:
        date = f"{c[:4]}-{c[4:6]}-{c[6:]}"
        p = {"date": date}
        for key, names in maps.items():
            p[key] = _pick(row_values(key, names), c)
        if any(v is not None for v in list(p.values())[1:]):
            periods.append(p)
    return periods


def get_financials(symbol):
    """近两年核心财务指标(按季度,日期升序):eps/roe/营收增速/净利增速/负债率/毛利率。"""
    full_symbol, _ = normalize_symbol(symbol)
    code = full_symbol.split(".")[0]
    try:
        periods = _financials_from_indicator(code)
        source = "eastmoney"
    except AkshareError as e:
        logger.warning("东财财务指标失败,降级财务摘要: %s", e)
        periods, source = _financials_from_abstract(code), "eastmoney-abstract"
    if not periods:
        raise AkshareError(f"获取 {symbol} 财务数据失败(代码不存在或数据源不可用)")
    return {
        "symbol": full_symbol,
        "name": get_stock_name(code) or "",
        "source": source,
        "periods": periods,
    }
