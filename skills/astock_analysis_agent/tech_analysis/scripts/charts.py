#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K线图绘制 —— matplotlib,Agg 后端,输出 PNG。

自包含:不 import 框架;输出目录用模块级 OUT_DIR(中性默认),
agent 入口可一行覆盖(如指向该 agent 的 data 目录)。
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 中性默认输出目录;agent 入口应覆盖为本 agent 的数据目录(如 data_dir/<agent>/charts)
OUT_DIR = Path.cwd() / ".data" / "charts"

# A股惯例配色:红涨绿跌;MA5/MA20 用固定类别色
COLOR_UP = "#c4342d"
COLOR_DOWN = "#0a7a3c"
COLOR_MA5 = "#2a78d6"
COLOR_MA20 = "#c44f01"
COLOR_GRID = "#9aa4b2"


class MatplotlibMissing(Exception):
    """matplotlib 未安装时抛出(handler 转为 status:error 友好提示)。"""


def ensure_chinese_font():
    """macOS 常见中文字体回退链;防止图内中文豆腐块。"""
    try:
        import matplotlib
        matplotlib.use("Agg")  # 无显示环境输出 PNG 必需
        from matplotlib import rcParams
    except ImportError as e:
        raise MatplotlibMissing(
            f"matplotlib 未安装,无法生成图表(请安装: pip install matplotlib): {e}"
        ) from e

    rcParams["font.sans-serif"] = [
        "PingFang SC", "Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "sans-serif",
    ]
    rcParams["axes.unicode_minus"] = False
    rcParams["font.size"] = 10
    return rcParams


def plot_kline(symbol: str, name: str, rows, out_dir: Path = None) -> str:
    """绘制日K线 + MA5/MA20 + 成交量,保存 PNG 并返回绝对路径。

    rows: 按日期升序的 dict 列表,含 date/open/close/high/low/volume/ma5/ma20。
    不引入 mplfinance:手绘蜡烛实体(Rectangle)+ 影线(Line2D)。
    """
    ensure_chinese_font()
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    from matplotlib.patches import Rectangle

    if not rows:
        raise ValueError("无行情数据,无法绘图")

    out_dir = Path(out_dir) if out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    n = len(rows)
    x = list(range(n))
    dates = [r.get("date", "") for r in rows]
    closes = [float(r["close"]) for r in rows]

    fig = plt.figure(figsize=(12, 7))
    gs = GridSpec(3, 1, height_ratios=[3, 1, 0], hspace=0.05, top=0.93)
    ax = fig.add_subplot(gs[0])
    ax_vol = fig.add_subplot(gs[1], sharex=ax)

    for i, r in enumerate(rows):
        o, c = float(r["open"]), float(r["close"])
        h, l = float(r["high"]), float(r["low"])
        up = c >= o
        color = COLOR_UP if up else COLOR_DOWN
        # 影线
        ax.plot([i, i], [l, h], color=color, linewidth=0.7, zorder=2)
        # 实体(涨:空心;跌:实心 —— 红绿之外的次级编码)
        body_bottom, body_h = (o, c - o) if up else (c, o - c)
        if body_h == 0:
            body_h = max(closes) * 0.0005  # 十字星画可见细线
        rect = Rectangle((i - 0.38, body_bottom), 0.76, body_h,
                         facecolor="none" if up else color,
                         edgecolor=color, linewidth=0.8, zorder=3)
        ax.add_patch(rect)

    ax.plot(x, [r.get("ma5") for r in rows], color=COLOR_MA5, linewidth=1.1, label="MA5")
    ax.plot(x, [r.get("ma20") for r in rows], color=COLOR_MA20, linewidth=1.1, label="MA20")

    # 最右端直接标注最新 MA 值
    last = rows[-1]
    for key, color in (("ma5", COLOR_MA5), ("ma20", COLOR_MA20)):
        v = last.get(key)
        if v is not None:
            ax.annotate(f"{key.upper()} {v}", xy=(n - 1, v), xytext=(6, 0),
                        textcoords="offset points", color=color, fontsize=9,
                        va="center")

    # 成交量(跟随涨跌色,弱化透明度)
    vol_colors = [COLOR_UP if float(r["close"]) >= float(r["open"]) else COLOR_DOWN for r in rows]
    ax_vol.bar(x, [float(r["volume"]) for r in rows], width=0.7, color=vol_colors, alpha=0.45)
    ax_vol.set_ylabel("成交量")
    ax_vol.grid(axis="y", color=COLOR_GRID, alpha=0.3, linestyle="--", linewidth=0.6)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
        ax_vol.spines[spine].set_visible(False)

    # x 轴刻度:自动稀疏到 ~8 个
    step = max(1, n // 8)
    ticks = x[::step]
    if ticks[-1] != x[-1]:
        ticks = list(ticks) + [x[-1]]
    ax.set_xticks(ticks)
    ax_vol.set_xticklabels([dates[t] for t in ticks], rotation=30, ha="right", fontsize=8)

    ax.grid(axis="y", color=COLOR_GRID, alpha=0.3, linestyle="--", linewidth=0.6)
    ax.set_ylabel("价格(前复权)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
    title = f"{name}({symbol}) 日K线 + MA5/MA20" if name else f"{symbol} 日K线 + MA5/MA20"
    ax.set_title(title)
    plt.setp(ax.get_xticklabels(), visible=False)

    path = out_dir / f"{symbol}_kline.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"K线图已保存: {path}")
    return str(path.resolve())
