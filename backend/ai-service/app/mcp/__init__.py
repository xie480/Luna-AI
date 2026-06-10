"""
MCP（Model Context Protocol）工具协议模块。

做什么：提供 MCP 工具注册、Schema 校验、三阶段路由执行网关以及内置工具的实现。
        该模块是 Python 控制面下所有工具调用的唯一入口，禁止模型直调。
为什么这样做：Phase 12 要求工具调用必须经过 Python 控制面，确保权限审核和审计可追溯。
             同时将工具注册、检索（供 Agent 1 初筛）和执行统一在该模块下管理。
边界条件：
    - 本模块仅支持 Tool 级别 MCP 能力接入，不涉及 Skill 与 Resource。
    - 所有工具的最终风险等级审核由 Phase 13 的 Gating 模块负责。
"""

from __future__ import annotations
