"""
上下文压缩领域模型定义。

做什么：集中定义上下文压缩治理、审计、回放所需的结构化数据模型。
为什么这样做：避免压缩链路中的审计字段、回放字段和治理结果字段分散在多个模块中，
            保证聊天主链路、记忆压缩链路与遥测查询链路使用同一套契约。
输入输出：
    - CompressionAuditPayload：单次压缩动作的统一审计载荷。
    - CompressionReplaySnapshot：用于回放展示的最小脱敏快照。
    - CompressionGovernanceResult：memory 槽位治理返回结果。
边界条件：
    - 所有跨层结构均携带 schema_version。
    - 所有列表字段默认使用 default_factory，避免共享可变对象。
异常行为：
    - 字段校验失败时由 Pydantic 抛出异常，调用方负责记录业务上下文。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.types.constants import (
    COMPRESSION_AUDIT_SCHEMA_VERSION,
    COMPRESSION_EVENT_SCHEMA_VERSION,
    COMPRESSION_REPLAY_SCHEMA_VERSION,
    CompressionScope,
    CompressionStage,
    CompressionTriggerReason,
)


class CompressionActionEvent(BaseModel):
    """
    压缩动作中的单个阶段事件。

    做什么：记录一次压缩动作内部的阶段性事件，用于回放时间线重建。
    为什么这样做：仅有最终结果不足以定位失败点，必须保留触发、测量、执行、应用的阶段痕迹。
    输入输出：输入为事件类型、时间戳和附加说明；输出为可序列化的结构化对象。
    边界条件：payload 仅保存最小必要结构化信息，避免 details 体积失控。
    异常行为：字段不合法时由 Pydantic 抛出校验异常。
    """

    schema_version: str = COMPRESSION_EVENT_SCHEMA_VERSION
    event_type: str
    timestamp_ms: int
    detail: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class CompressionReplaySnapshot(BaseModel):
    """
    压缩回放最小快照。

    做什么：保存一次压缩动作回放所需的最小脱敏前后预览与关键元数据。
    为什么这样做：满足“可解释、可定位问题”与“不保存完整敏感原文”两类要求。
    输入输出：由压缩动作执行端生成，并作为审计载荷中的结构化子对象被消费。
    边界条件：preview_before / preview_after 必须已经脱敏且长度受控。
    异常行为：字段校验失败时由 Pydantic 抛出异常。
    """

    schema_version: str = COMPRESSION_REPLAY_SCHEMA_VERSION
    snapshot_id: str
    trace_id: str
    session_id: str
    message_id: str = ""
    memory_id: str = ""
    stage: CompressionStage
    scope: CompressionScope
    source_keys: list[str] = Field(default_factory=list)
    preview_before: str = ""
    preview_after: str = ""
    raw_tokens: int = 0
    final_tokens: int = 0
    is_success: bool
    failure_reason: str = ""
    created_at_ms: int


class CompressionAuditPayload(BaseModel):
    """
    上下文压缩统一审计载荷。

    做什么：定义写入审计日志 details 字段的 JSON 结构，承载单次压缩动作的完整结果。
    为什么这样做：项目当前复用 audit_logs.details JSON 落盘，必须保证字段统一、可查询、可回放。
    输入输出：输入为压缩动作执行结果，输出为可直接 JSON 序列化的 Pydantic 模型。
    边界条件：所有 Token 指标都必须在真实执行节点采集；ratio 字段允许为 0 以表示无压缩收益。
    异常行为：字段校验失败时由 Pydantic 抛出异常。
    """

    schema_version: str = COMPRESSION_AUDIT_SCHEMA_VERSION
    trace_id: str
    session_id: str
    message_id: str = ""
    memory_id: str = ""
    stage: CompressionStage
    scope: CompressionScope
    trigger_reason: CompressionTriggerReason
    source_keys: list[str] = Field(default_factory=list)
    raw_tokens: int
    after_trim_tokens: int = 0
    after_summary_tokens: int = 0
    final_tokens: int
    total_compression_ratio: float
    stage_compression_ratio: float
    model_provider: str = ""
    model_base_url: str = ""
    model_id: str = ""
    is_success: bool
    failure_reason: str = ""
    timestamp_ms: int
    timestamp_iso: str
    preview_before: str = ""
    preview_after: str = ""
    replay_snapshot_id: str = ""
    snapshot: CompressionReplaySnapshot
    events: list[CompressionActionEvent] = Field(default_factory=list)


class CompressionActionRecord(BaseModel):
    """
    memory 槽位治理阶段内部动作记录。

    做什么：保存治理编排期间产生的压缩动作结果，供调用方统一写入审计与回放。
    为什么这样做：治理链路可能包含多个阶段动作，必须先结构化收集，再统一交由遥测模块落盘。
    输入输出：输入为单个阶段的审计载荷和状态；输出供 Governor 聚合使用。
    边界条件：status 只表示该动作在当前链路中的业务状态，不替代数据库 audit_logs.status 字段语义。
    异常行为：字段校验失败时由 Pydantic 抛出异常。
    """

    payload: CompressionAuditPayload
    status: str


class CompressionGovernanceResult(BaseModel):
    """
    memory 槽位压缩治理结果。

    做什么：返回治理后的 Prompt 变量映射及动作审计结果。
    为什么这样做：聊天主链路需要在组装最终 Prompt 前拿到治理后的变量，同时把动作记录交给遥测链路。
    输入输出：输入为待治理变量，输出为治理结果与审计动作数组。
    边界条件：若 skipped 为 True，updated_variables 仍应保持可直接注入 Prompt 的完整映射。
    异常行为：字段校验失败时由 Pydantic 抛出异常。
    """

    updated_variables: dict[str, str] = Field(default_factory=dict)
    action_records: list[CompressionActionRecord] = Field(default_factory=list)
    before_tokens: int = 0
    after_tokens: int = 0
    skipped: bool = False
    final_strategy: str = ""


class CompressionReplaySummary(BaseModel):
    """
    压缩回放总览摘要。

    做什么：聚合同一链路下多个压缩动作的总览信息。
    为什么这样做：前端详情页首先需要总量摘要，再展示阶段时间线。
    输入输出：输入为压缩动作列表，输出为摘要结构。
    边界条件：无动作时所有数值归零，final_strategy 为空字符串。
    异常行为：字段校验失败时由 Pydantic 抛出异常。
    """

    raw_tokens: int = 0
    final_tokens: int = 0
    total_compression_ratio: float = 0.0
    final_strategy: str = ""


class CompressionReplayResponse(BaseModel):
    """
    压缩回放详情响应结构。

    做什么：封装基于 trace_id 聚合后的压缩回放详情。
    为什么这样做：为前端提供无需二次推导的稳定接口结构。
    输入输出：输入为聚合后的审计记录和 Span，输出为标准响应体的 data 部分。
    边界条件：message_id 允许为空，表示该链路是会话级或记忆级压缩而非单消息压缩。
    异常行为：字段校验失败时由 Pydantic 抛出异常。
    """

    trace_id: str
    session_id: str = ""
    message_id: str = ""
    summary: CompressionReplaySummary = Field(default_factory=CompressionReplaySummary)
    events: list[CompressionAuditPayload] = Field(default_factory=list)
    snapshots: list[CompressionReplaySnapshot] = Field(default_factory=list)
    spans: list[dict[str, Any]] = Field(default_factory=list)
