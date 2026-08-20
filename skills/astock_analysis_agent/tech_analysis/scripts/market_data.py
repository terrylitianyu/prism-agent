#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AkShare 数据获取(tech_analysis 专用,自包含)。

本 skill 内唯一 import akshare 的模块:重试 + TTL 缓存 + 列别名映射 +
DataFrame→JSON 清洗都集中在这里,handlers 只消费纯 dict 结果。

数据源容错链(实测确认):
- 历史行情: 东财 stock_zh_a_hist → 新浪 stock_zh_a_daily
- 实时行情: 东财 stock_zh_a_spot_em → 新浪 stock_zh_a_spot → 历史最新日线兜底
- 行业归属: 东财 stock_individual_info_em → 巨潮 stock_profile_cninfo
- 行业指数: 东财 stock_board_industry_hist_em → 新浪行业板块 1 日涨跌降级
"""

import logging
import math
import threading
import time
from datetime import datetime, timedelta

from .symbols import normalize_symbol

logger = logging.getLogger(__name__)


class AkshareError(RuntimeError):
    """AkShare 取数失败(含重试),消息为中文、面向用户。"""


# ---------------------------------------------------------------------------
# 通用骨架:重试 / TTL 缓存 / DataFrame 清洗
# ---------------------------------------------------------------------------

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


def _yyyymmdd(d):
    """'YYYY-MM-DD'/'YYYYMMDD' → 'YYYYMMDD';非法抛 ValueError(中文)。"""
    s = str(d).strip().replace("-", "")
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"无效的日期: {d!r}(应为 YYYY-MM-DD 或 YYYYMMDD)")
    return s


def _round2(v):
    return round(v, 2) if v is not None else None


def _now():
    return datetime.now().isoformat(timespec="seconds")


def resolve_range(start_date="", end_date=""):
    """'YYYY-MM-DD'/'YYYYMMDD'/'' → ('YYYYMMDD', 'YYYYMMDD');缺省最近一年。"""
    end_ymd = _yyyymmdd(end_date) if end_date else datetime.now().strftime("%Y%m%d")
    start_ymd = _yyyymmdd(start_date) if start_date else (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    if start_ymd > end_ymd:
        raise ValueError(f"开始日期 {start_ymd} 晚于结束日期 {end_ymd}")
    return start_ymd, end_ymd


# ---------------------------------------------------------------------------
# 历史行情
# ---------------------------------------------------------------------------

def _rows_from_em(code, start_ymd, end_ymd):
    """东财历史日线(前复权) → 统一行格式。失败抛异常,由调用方决定降级。"""
    import akshare as ak

    df = fetch_with_retry(
        ak.stock_zh_a_hist, symbol=code, period="daily",
        start_date=start_ymd, end_date=end_ymd, adjust="qfq",
        what=f"{code} 历史行情(东方财富)",
    )
    rows = []
    for rec in df_to_records(df):
        rows.append({
            "date": str(rec["日期"]),
            "open": _pick(rec, "开盘"),
            "close": _pick(rec, "收盘"),
            "high": _pick(rec, "最高"),
            "low": _pick(rec, "最低"),
            "volume": _pick(rec, "成交量"),      # 单位:手
            "amount": _pick(rec, "成交额"),       # 单位:元
            "pct_chg": _pick(rec, "涨跌幅"),
            "turnover": _pick(rec, "换手率"),     # 单位:%
        })
    return rows


def _rows_from_sina(code, exchange, start_ymd, end_ymd):
    """新浪历史日线(前复权) → 统一行格式。北交所新浪无数据,抛异常。"""
    if exchange == "BJ":
        raise AkshareError("新浪行情源不支持北交所代码")
    import akshare as ak

    prefix = "sh" if exchange == "SH" else "sz"
    df = fetch_with_retry(
        ak.stock_zh_a_daily, symbol=f"{prefix}{code}",
        start_date=start_ymd, end_date=end_ymd, adjust="qfq",
        what=f"{code} 历史行情(新浪)",
    )
    rows = []
    prev_close = None
    for rec in df_to_records(df):
        close = _pick(rec, "close")
        pct = None
        if prev_close and close:
            pct = _round2((close - prev_close) / prev_close * 100)
        prev_close = close
        rows.append({
            "date": str(rec["date"]),
            "open": _pick(rec, "open"),
            "close": close,
            "high": _pick(rec, "high"),
            "low": _pick(rec, "low"),
            "volume": round(rec["volume"] / 100) if rec.get("volume") else None,  # 股→手
            "amount": _pick(rec, "amount"),
            "pct_chg": pct,
            "turnover": _round2(rec["turnover"] * 100) if rec.get("turnover") else None,  # 比率→%
        })
    return rows


@ttl_cache(300)
def _history_raw(code, exchange, start_ymd, end_ymd):
    """带 TTL 的原始取数:东财优先,失败降级新浪。"""
    try:
        rows = _rows_from_em(code, start_ymd, end_ymd)
        if rows:
            return rows, "eastmoney"
        logger.warning("东财历史行情为空,降级新浪: %s", code)
    except AkshareError as e:
        logger.warning("东财历史行情失败,降级新浪: %s", e)
    return _rows_from_sina(code, exchange, start_ymd, end_ymd), "sina"


def get_stock_history(symbol, start_date="", end_date=""):
    """历史日线(前复权),统一行格式,按日期升序。

    start_date/end_date 缺省为最近一年;返回 {symbol, exchange, name, start, end, rows, source}。
    """
    full_symbol, exchange = normalize_symbol(symbol)
    code = full_symbol.split(".")[0]
    start_ymd, end_ymd = resolve_range(start_date, end_date)

    rows, source = _history_raw(code, exchange, start_ymd, end_ymd)
    if not rows:
        raise AkshareError(f"未获取到 {symbol} 的历史行情(代码不存在、已退市或该区间无交易日)")

    return {
        "symbol": full_symbol,
        "exchange": exchange,
        "name": get_stock_name(code) or "",
        "start": start_ymd,
        "end": end_ymd,
        "source": source,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 个股名称(巨潮公司概况,日级稳定数据)
# ---------------------------------------------------------------------------

@ttl_cache(86400)
def get_stock_name(code):
    """个股简称;取不到返回 None(非致命)。"""
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
# 实时行情
# ---------------------------------------------------------------------------

@ttl_cache(60)
def _em_spot_df():
    """东财全市场实时快照(含市盈率/市净率/市值)。全量拉取较慢,TTL 60s。"""
    import akshare as ak
    return fetch_with_retry(ak.stock_zh_a_spot_em, what="全市场实时行情(东方财富)")


@ttl_cache(60)
def _sina_spot_df():
    """新浪全市场实时快照(无估值列)。"""
    import akshare as ak
    return fetch_with_retry(ak.stock_zh_a_spot, what="全市场实时行情(新浪)")


def _realtime_from_em(code):
    rec = next((r for r in df_to_records(_em_spot_df()) if str(r.get("代码")) == code), None)
    if not rec or _pick(rec, "最新价") is None:
        return None
    return {
        "price": _pick(rec, "最新价"),
        "pct_chg": _pick(rec, "涨跌幅"),
        "volume": _pick(rec, "成交量"),
        "amount": _pick(rec, "成交额"),
        "turnover": _pick(rec, "换手率"),
        "amplitude": _pick(rec, "振幅"),
        "high": _pick(rec, "最高"),
        "low": _pick(rec, "最低"),
        "open": _pick(rec, "今开"),
        "prev_close": _pick(rec, "昨收"),
        "pe": _pick(rec, "市盈率-动态"),
        "pb": _pick(rec, "市净率"),
        "total_mv": _pick(rec, "总市值"),
        "float_mv": _pick(rec, "流通市值"),
        "name": _pick(rec, "名称"),
        "source": "eastmoney",
        "is_realtime": True,
    }


def _realtime_from_sina(code, exchange):
    if exchange == "BJ":
        return None
    prefix = "sh" if exchange == "SH" else "sz"
    rec = next((r for r in df_to_records(_sina_spot_df())
                if str(r.get("代码")).lower() == f"{prefix}{code}"), None)
    if not rec or _pick(rec, "最新价") is None:
        return None
    return {
        "price": _pick(rec, "最新价"),
        "pct_chg": _pick(rec, "涨跌幅"),
        "volume": round(rec["成交量"] / 100) if rec.get("成交量") else None,  # 股→手
        "amount": _pick(rec, "成交额"),
        "turnover": None,
        "amplitude": None,
        "high": _pick(rec, "最高"),
        "low": _pick(rec, "最低"),
        "open": _pick(rec, "今开"),
        "prev_close": _pick(rec, "昨收"),
        "pe": None,
        "pb": None,
        "total_mv": None,
        "float_mv": None,
        "name": _pick(rec, "名称"),
        "quote_time": _pick(rec, "时间戳"),
        "source": "sina",
        "is_realtime": True,
    }


def _realtime_from_daily(code, exchange):
    """兜底:取历史最新日线(非盘中实时)。"""
    try:
        hist = get_stock_history(f"{code}.{exchange}")
        row = hist["rows"][-1]
        return {
            "price": row.get("close"),
            "pct_chg": row.get("pct_chg"),
            "volume": row.get("volume"),
            "amount": row.get("amount"),
            "turnover": row.get("turnover"),
            "amplitude": None,
            "high": row.get("high"),
            "low": row.get("low"),
            "open": row.get("open"),
            "prev_close": None,
            "pe": None,
            "pb": None,
            "total_mv": None,
            "float_mv": None,
            "name": hist.get("name"),
            "quote_date": row.get("date"),
            "source": "daily",
            "is_realtime": False,
        }
    except AkshareError as e:
        logger.warning("实时行情日线兜底失败: %s", e)
        return None


def get_realtime(symbol):
    """实时行情:东财 → 新浪 → 最新日线兜底。含来源与时间戳,不落库(易失)。"""
    full_symbol, exchange = normalize_symbol(symbol)
    code = full_symbol.split(".")[0]
    for fetcher in (
        lambda: _realtime_from_em(code),
        lambda: _realtime_from_sina(code, exchange),
    ):
        try:
            r = fetcher()
        except AkshareError as e:
            logger.warning("实时行情源失败,尝试下一源: %s", e)
            r = None
        if r:
            r.update({"symbol": full_symbol, "updated_at": _now()})
            return r
    r = _realtime_from_daily(code, exchange)
    if not r:
        raise AkshareError(f"获取 {symbol} 实时行情失败(代码不存在、停牌或所有行情源不可用)")
    r.update({"symbol": full_symbol, "updated_at": _now()})
    return r


# ---------------------------------------------------------------------------
# 行业归属与行业指数
# ---------------------------------------------------------------------------

def get_industry_name(code):
    """所属行业名:东财 → 巨潮;两者都失败返回 None(非致命)。"""
    try:
        import akshare as ak
        df = fetch_with_retry(ak.stock_individual_info_em, symbol=code,
                              what=f"{code} 个股信息(东方财富)", retries=1)
        for rec in df_to_records(df):
            item = _pick(rec, "item", "index")
            if str(item).strip() == "行业":
                return _pick(rec, "value")
    except AkshareError as e:
        logger.warning("东财行业信息失败,降级巨潮: %s", e)
    try:
        import akshare as ak
        df = fetch_with_retry(ak.stock_profile_cninfo, symbol=code,
                              what=f"{code} 公司概况(巨潮)", retries=1)
        recs = df_to_records(df)
        if recs:
            return _pick(recs[0], "所属行业")
    except AkshareError as e:
        logger.warning("巨潮行业信息失败: %s", e)
    return None


def _pct_over_days(closes, days):
    """近 days 个交易日收盘涨跌幅(%)。数据不足返回 None。"""
    if len(closes) <= days:
        return None
    prev = float(closes[-days - 1])
    cur = float(closes[-1])
    return _round2((cur - prev) / prev * 100) if prev else None


@ttl_cache(300)
def _industry_trend_from_em(industry):
    """东财行业指数日k → 1d/5d/20d 涨跌幅。"""
    import akshare as ak
    end_ymd = datetime.now().strftime("%Y%m%d")
    start_ymd = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
    df = fetch_with_retry(
        ak.stock_board_industry_hist_em, symbol=industry, period="日k",
        start_date=start_ymd, end_date=end_ymd, adjust="",
        what=f"{industry} 行业指数(东方财富)",
    )
    recs = df_to_records(df)
    if not recs:
        return None
    closes = [r["收盘"] for r in recs if r.get("收盘") is not None]
    return {
        "pct_1d": _pick(recs[-1], "涨跌幅"),
        "pct_5d": _pct_over_days(closes, 5),
        "pct_20d": _pct_over_days(closes, 20),
        "source": "eastmoney",
    }


def _industry_trend_from_sina(industry):
    """新浪行业板块:只有当日涨跌幅(1d),5d/20d 降级为 None。"""
    import akshare as ak
    df = fetch_with_retry(ak.stock_sector_spot, indicator="新浪行业",
                          what="行业板块行情(新浪)", retries=1)
    for rec in df_to_records(df):
        board = str(_pick(rec, "板块") or "")
        # 宽松匹配:东财行业名(如"银行")/证监会行业名(如"货币金融服务")与新浪板块名
        if board == industry or industry in board or board in industry:
            return {
                "pct_1d": _pick(rec, "涨跌幅"),
                "pct_5d": None,
                "pct_20d": None,
                "source": "sina",
            }
    return None


def get_industry_trend(industry):
    """行业指数 1d/5d/20d 涨跌幅:东财 → 新浪 1 日降级 → None。"""
    if not industry:
        return None
    try:
        trend = _industry_trend_from_em(industry)
        if trend:
            return trend
        logger.warning("东财行业指数为空,降级新浪: %s", industry)
    except AkshareError as e:
        logger.warning("东财行业指数失败,降级新浪: %s", e)
    try:
        return _industry_trend_from_sina(industry)
    except AkshareError as e:
        logger.warning("新浪行业板块失败: %s", e)
        return None
