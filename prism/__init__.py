#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prism Agent 框架内核。

模块划分:
  agent           AgentEngine(模型表/工具集/DataStore/loop 配置实例隔离)
                  + Agent Loop 内核(LLM 循环、工具并行、上下文压缩);
                  init_agent()/agent_loop_stream() 是单 agent 进程的兼容薄壳
  client          LLM 客户端(LLMClient / SkillLLM / DEFAULT_MODELS,调用台账落盘)
  core            常量:WORKDIR / SESSION_DIR / SKILLS_DIR / ADAPTERS_DIR
  data_store      DataStore 抽象 + SQLiteDataStore 实现
  session         BaseSession(对话历史、chat_events、turn_count)
  session_context 通过 contextvars 传递当前 session
  skill_context   SkillContext / SkillAdapter / BizProxy / PassthroughAdapter
  skill_loader    SkillLoaderV2:扫描 SKILL.yaml、装配 adapter、注入 llm、生成 tool schema

项目根 = 本包所在目录的上一级(见 core.WORKDIR)。
"""
