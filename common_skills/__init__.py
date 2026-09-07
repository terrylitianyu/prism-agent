#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common_skills:跨 agent 复用的通用 skill 池。

agent 通过 agent.yaml 的 skill_dirs 逐个叶子目录引入需要的 skill,如:
  skill_dirs:
    - skills/<agent>
    - common_skills/doc_classify
"""
