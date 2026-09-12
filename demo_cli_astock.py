#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
astock_analysis_agent 交互式 CLI demo(基于 AkShare 的 A 股分析)

注意:
  - 需要网络(行情接口)与 .env 中的 LLM 配置
  - 首次调用 akshare 导入较慢(约 2~5 秒);全市场实时快照可能耗时 20~70 秒
  - 图表输出目录: .data/astock_analysis_agent/charts/

用法: python demo_cli_astock.py
命令:
  /code <代码>   设置当前股票并自动走单股技术分析(如 /code 600519)
  /chart         重画当前股票的 K 线图
  /hot           市场热点分析(人气榜 + 快讯)
  /state         查看 DataStore 当前状态(数据/报告/图表)
  /new           新会话(清空状态与对话历史)
  /quit          退出
  其余输入       作为消息发送给 agent(支持自然语言,如"分析一下600519的基本面")
"""

import json
import time
from pathlib import Path

from agents.astock_analysis_agent import init as init_astock

DATA_DIR = Path(".data")

store = None
session = None
engine = None


def run_turn(message: str):
    """跑一轮 agent loop 并渲染事件流。"""
    for event in engine.agent_loop_stream(message, conversation_history=[]):
        ev, data = event.get("event"), event.get("data")
        if ev == "instant_reply":
            print(f"  ⚡ {data}")
        elif ev == "tool_call":
            args = json.dumps(data.get("args", {}), ensure_ascii=False)
            print(f"  🔧 {data.get('name')}({args})")
        elif ev == "tool_result":
            snippet = str(data.get("result"))[:120]
            print(f"  ↳ {snippet}")
        elif ev == "done":
            print(f"\nastock: {data}\n")
        elif ev == "error":
            print(f"  ❌ {data}")
        elif ev == "usage":
            print(f"  [usage] total={data.get('total_tokens')} "
                  f"(prompt={data.get('total_prompt_tokens')}, "
                  f"completion={data.get('total_completion_tokens')})")


def cmd_state():
    sid = session.session_id

    def show(key, label, fmt=None):
        v = store.get_field(sid, key)
        if not v:
            print(f"  {label}: (无)")
            return
        print(f"  {label}: {fmt(v) if fmt else v}")

    def report_preview(key):
        v = store.get_field(sid, key)
        if not v:
            return "(未生成)"
        md = v.get("report_md", "") if isinstance(v, dict) else ""
        return f"{len(md)} 字符 | {md[:80].strip().replace(chr(10), ' ')}..."

    print("  --- DataStore ---")
    show("current_symbol", "current_symbol")
    hist = store.get_field(sid, "stock_history")
    if hist:
        print(f"  stock_history: {hist.get('name') or ''}({hist.get('symbol')}) "
              f"[{hist.get('start')}~{hist.get('end')}] {len(hist.get('rows', []))} 行 "
              f"(source={hist.get('source')})")
    else:
        print("  stock_history: (无)")
    sector = store.get_field(sid, "stock_sector")
    if sector:
        print(f"  stock_sector: {sector.get('industry')} "
              f"1d={sector.get('pct_1d')} 5d={sector.get('pct_5d')} 20d={sector.get('pct_20d')}")
    else:
        print("  stock_sector: (无)")
    show("chart_path", "chart_path")
    for key, label in (("hot_rank", "hot_rank"), ("market_news", "market_news")):
        v = store.get_field(sid, key)
        if v:
            print(f"  {label}: {len(v.get('rows', v.get('items', [])))} 条 (ts={v.get('ts')})")
        else:
            print(f"  {label}: (无)")
    print(f"  tech_report: {report_preview('tech_report')}")
    print(f"  hot_analysis: {report_preview('hot_analysis')}")
    print(f"  fundamental_report: {report_preview('fundamental_report')}")
    v = store.get_field(sid, "stock_valuation")
    if v:
        print(f"  stock_valuation: {v.get('name') or ''}({v.get('symbol')}) "
              f"PE_TTM={v.get('pe_ttm')} PB={v.get('pb')} (date={v.get('date')})")
    else:
        print("  stock_valuation: (无)")
    fin = store.get_field(sid, "stock_financials")
    if fin:
        print(f"  stock_financials: {len(fin.get('periods', []))} 期 "
              f"(source={fin.get('source')})")
    else:
        print("  stock_financials: (无)")


def cmd_new():
    session.history.clear()
    session.chat_events.clear()
    session.turn_count = 0
    session.session_id = f"cli-{int(time.time())}"
    print(f"  新会话: {session.session_id}")


def main():
    global store, session, engine
    engine = init_astock(DATA_DIR)
    store = engine.store
    session = engine.default_session
    session.session_id = "cli-default"
    print(__doc__)
    while True:
        try:
            line = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break
        if not line:
            continue
        if line == "/quit":
            break
        elif line == "/state":
            cmd_state()
        elif line == "/new":
            cmd_new()
        elif line == "/hot":
            run_turn("看看今天市场有什么热点,分析一下热门主题")
        elif line == "/chart":
            run_turn("把当前股票的K线图画出来")
        elif line.startswith("/code"):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("  用法: /code <6位代码>,如 /code 600519")
            else:
                run_turn(f"分析一下 {parts[1]} 这只股票")
        elif line.startswith("/"):
            print("  未知命令(支持 /code /chart /hot /state /new /quit)")
        else:
            run_turn(line)


if __name__ == "__main__":
    main()
