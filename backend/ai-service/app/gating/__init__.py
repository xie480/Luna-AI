"""
Luna AI 权限网关（Gating）模块。

做什么：Phase 13 权限治理与前端 Gating 的后端核心实现。
        提供工具调用拦截、用户审批工作流、超时处理、状态恢复等能力。
        是 AI 主动行为的安全闸门，确保所有高危操作必须经过用户显式确认。

为什么这样做：根据 agent.md 6.4 安全与治理规范：
    1. AI 主动发起的任何涉及修改/删除文件、网络请求等高风险动作，
       Python 必须强行挂起任务并等待用户授权。
    2. Python 是唯一的 Single Source of Truth，前端仅作为投影视图，
       不持有任何审批状态。
    3. 所有关键链路必须可审计，记录完整的审批生命周期。

核心模块：
    - types.py:     权限请求/响应的类型定义与枚举
    - service.py:   核心 GatingService（拦截、审批、恢复、超时处理）
    - scheduler.py: 后台超时检测与清理调度器
"""

from app.gating.service import GatingService
from app.gating.types import (
    AuthAction,
    AuthRequestPayload,
    AuthResponsePayload,
    AuthStatus,
    GatingEventType,
)

__all__ = [
    "GatingService",
    "AuthAction",
    "AuthRequestPayload",
    "AuthResponsePayload",
    "AuthStatus",
    "GatingEventType",
]
