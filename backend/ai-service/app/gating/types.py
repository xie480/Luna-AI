"""
Luna AI Gating 模块类型定义。

做什么：定义权限网关模块涉及的所有 Pydantic 模型、枚举和事件类型。
        包括权限请求载荷、用户响应载荷、审批状态枚举等。
        所有类型集中在此模块管理，避免与业务模块耦合。

为什么这样做：严格遵循 agent.md 6.1 第2条"所有枚举与常量集中管理"的规范。
             Gating 相关的类型独立于 workflow 状态模型，便于独立维护和版本化。

边界条件：
    - AuthAction 枚举值对应前端 Gating 文档中的 APPROVE / REJECT。
    - AuthStatus 跟踪审批生命周期：PENDING → APPROVED / REJECTED / TIMEOUT。
    - GatingEventType 定义前后端通信的事件类型常量。
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ============================================================
# 审批行为枚举
# ============================================================


class AuthAction(str, Enum):
    """用户审批行为枚举。

    做什么：定义用户在 Gating 弹窗中可执行的操作。
    为什么这样做：前端发送审批响应时必须明确标识 APPROVE 或 REJECT，
                 后端据此决定放行或阻断工具调用。
    边界条件：
        - APPROVE：用户同意执行工具调用。
        - REJECT：用户拒绝工具调用（可附带反馈理由）。
    """
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ============================================================
# 审批状态枚举
# ============================================================


class AuthStatus(str, Enum):
    """审批请求状态枚举。

    做什么：跟踪每个权限请求的生命周期状态。
    为什么这样做：后端需要根据状态判断请求是否待处理、已通过、已拒绝或超时。
                 前端在断线重连后通过此状态重建队列。
    边界条件：
        - PENDING：等待用户审批中。这是初始状态，也是超时检测的目标状态。
        - APPROVED：用户已批准，工具可以继续执行。
        - REJECTED：用户已拒绝，工具执行被阻断。
        - TIMEOUT：等待超时，系统自动拒绝。
    """
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"


# ============================================================
# SSE 事件类型常量
# ============================================================


class GatingEventType(str, Enum):
    """Gating 模块 SSE 事件类型枚举。

    做什么：定义 Gating 模块向前端推送的事件类型。
            与 frontend/docs/plans/phase13_frontend_gating_plan.md 中
            前端定义的 WebSocket 事件名保持一致。
    为什么这样做：前后端通过约定的事件类型进行通信，保证消息路由的正确性。
    """
    # 后端向前端推送：工具调用需要用户审批（挂起 DAG）
    EVT_TOOL_AUTH_REQUIRED = "EVT_TOOL_AUTH_REQUIRED"

    # 前端向后端发送：用户审批结果（APPROVE / REJECT）
    CMD_TOOL_AUTH_RESPONSE = "CMD_TOOL_AUTH_RESPONSE"

    # 前端请求同步当前所有 PENDING 状态
    CMD_SYNC_INIT_STATE = "CMD_SYNC_INIT_STATE"

    # 后端回复：当前所有 PENDING 请求列表
    EVT_INIT_STATE = "EVT_INIT_STATE"


# ============================================================
# 权限请求载荷模型
# ============================================================


class AuthRequestPayload(BaseModel):
    """权限审批请求载荷。

    做什么：当 MCP 执行网关检测到高危工具（L2/L3）时，
            封装此载荷并推送到前端，触发 Gating 弹窗。
    为什么这样做：前端 Gating 弹窗需要展示完整的工具信息、风险等级、
                 参数载荷等，使用户做出知情决策。此模型确保所有
                 必要字段在推送前已完整填写。
    边界条件：
        - audit_log_id 是雪花算法生成的唯一审计记录 ID，用于防重和追溯。
        - tool_id 对应 MCPToolRegistry 中的工具唯一名称。
        - risk_level 对应 ToolRiskLevel 枚举（L0/L1/L2/L3）。
        - arguments 是工具调用的原始参数，必须如实透传，
          前端必须逐字展示给用户，禁止前端隐藏参数明细（见 agent.md）。
        - trace_id / task_id 用于后端追踪和审计日志关联。
        - timestamp 由后端生成，单位毫秒。
    """

    audit_log_id: str = Field(
        ..., description="审计日志记录 ID（雪花算法生成），用于防重和追溯。"
    )
    tool_id: str = Field(
        ..., description="工具唯一标识（如 mcp.local_fs.write_file）。"
    )
    tool_name: str = Field(
        ..., description="工具友好显示名称，用于 UI 展示。"
    )
    risk_level: str = Field(
        ..., description="风险等级（L0/L1/L2/L3）。"
    )
    reason: str = Field(
        ..., description="后端策略引擎生成的拦截原因，向用户解释为何需要审批。"
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="工具调用的参数载荷。必须如实传递，"
                    "前端将以格式化 JSON 展示给用户。",
    )
    goal: str = Field(
        default="", description="当前 Agent 执行的 Goal 描述。"
    )
    skill_info: dict[str, Any] | None = Field(
        default=None, description="关联 Skill 的元数据信息。"
    )
    agent_output: str = Field(
        default="",
        description="Agent 执行阶段的输出信息。当前 Agent 思考的内容。",
    )
    trace_id: str = Field(
        ..., description="全链路追踪 ID，用于关联日志和审计。"
    )
    task_id: str = Field(
        ..., description="关联的 DAG 任务 ID。"
    )
    timestamp: int = Field(
        ..., ge=0, description="请求发生时间戳（毫秒）。"
    )

    # ---- 服务端内部字段 ----
    status: AuthStatus = Field(
        default=AuthStatus.PENDING,
        description="审批状态。创建时默认为 PENDING。"
                       "后续由 GatingService 推进。",
    )
    created_at: int = Field(
        default=0, ge=0, description="记录创建时间戳（毫秒）。"
    )
    updated_at: int = Field(
        default=0, ge=0, description="记录最后更新时间戳（毫秒）。"
    )


# ============================================================
# 审批响应载荷模型
# ============================================================


class AuthResponsePayload(BaseModel):
    """用户审批响应载荷。

    做什么：前端将用户审批结果通过 WebSocket/SSE 发送给后端时使用的模型。
    为什么这样做：后端收到此响应后，根据 action 决定放行或阻断工具调用，
                 并更新审计日志状态。
    边界条件：
        - audit_log_id 必须对应一个存在的 PENDING 状态请求。
        - action 只能是 APPROVE 或 REJECT（由 AuthAction 枚举约束）。
        - user_feedback 可选，用户可提供拒绝原因或修改意见。
        - trace_id 和 task_id 用于关联原有请求。
    """

    audit_log_id: str = Field(
        ..., description="对应的审计日志记录 ID，必须匹配一个 PENDING 请求。"
    )
    action: AuthAction = Field(
        ..., description="用户审批行为：APPROVE 放行 / REJECT 拒绝。"
    )
    user_feedback: str = Field(
        default="",
        description="用户的反馈理由或修改意见（可选），"
                    "拒绝时建议填写以便 Agent 调整行为。",
    )
    trace_id: str = Field(
        default="",
        description="链路追踪 ID。用于关联审计日志。"
    )
    task_id: str = Field(
        default="",
        description="关联的 DAG 任务 ID。"
    )
    timestamp: int = Field(
        default=0, ge=0, description="响应时间戳（毫秒）。"
    )


# ============================================================
# 状态同步响应模型
# ============================================================


class SyncInitStatePayload(BaseModel):
    """状态同步初始化响应载荷。

    做什么：当前端断线重连或应用重启后，后端返回当前所有 PENDING 状态
            的审批请求列表，供前端重建弹窗队列。
    为什么这样做：根据前端 Gating 方案 6.3 节，断线重连后前端必须
                 clearAll() 然后重新入队，以此消除状态撕裂问题。
    边界条件：
        - pending_requests 只包含 status=PENDING 的请求。
        - 如果当前无挂起请求，返回空列表。
    """
    pending_requests: list[AuthRequestPayload] = Field(
        default_factory=list,
        description="当前所有 PENDING 状态的审批请求列表。"
    )
    sync_timestamp: int = Field(
        default=0, ge=0, description="同步时间戳（毫秒）。"
    )
