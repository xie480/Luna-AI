"""
上下文压缩审计与 Span 辅助工具。

做什么：提供上下文压缩链路统一复用的模型信息提取、比例计算、审计落盘与 Span 落盘能力。
为什么这样做：短摘要压缩、长期压缩、memory 槽位治理和消息级裁剪都需要统一口径，不能各自拼装 JSON。
输入输出：
    - create_compression_audit_payload(): 生成标准审计载荷。
    - record_compression_audit_payload(): 将审计载荷异步投递到既有 telemetry worker。
    - record_compression_span(): 将压缩 Span 异步投递到既有 telemetry worker。
边界条件：
    - telemetry worker 不可用时只写日志，不阻断主链路。
    - 模型配置缺失时返回空 provider/base_url 并使用已有默认 model_id。
异常行为：
    - 审计与 Span 投递异常只记录警告，由调用方继续主业务流程。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from time import time
from typing import Iterable
from urllib.parse import urlparse

from app.config.settings import global_config_container, settings
from app.context.compression_types import (
    CompressionActionEvent,
    CompressionAuditPayload,
    CompressionReplaySnapshot,
)
from app.logger import logger
from app.telemetry.redaction import redact_preview_text
from app.telemetry.worker import get_worker
from app.types.constants import (
    COMPRESSION_AUDIT_ACTION_TYPE,
    COMPRESSION_SPAN_NAME,
    COMPRESSION_SPAN_SERVICE,
    COMPRESSION_STATUS_FAILED,
    COMPRESSION_STATUS_SKIPPED,
    COMPRESSION_STATUS_SUCCESS,
    CompressionScope,
    CompressionStage,
    CompressionTriggerReason,
    ModelSize,
)
from app.utils.snowflake import generate_string_id


def current_timestamp_ms() -> int:
    """
    获取当前毫秒时间戳。

    做什么：为压缩审计与回放统一生成毫秒级时间戳。
    为什么这样做：审计查询和回放时间线都依赖毫秒粒度排序。
    输入输出：无输入，输出当前 UTC 毫秒时间戳。
    边界条件：无。
    异常行为：本函数不主动抛业务异常。
    """
    return int(time() * 1000)


def timestamp_ms_to_iso(timestamp_ms: int) -> str:
    """
    毫秒时间戳转 ISO 字符串。

    做什么：把审计内部统一使用的毫秒时间戳转换为 UTC ISO 时间文本。
    为什么这样做：前端和开发者查看日志时需要可读时间，同时保留原始毫秒值。
    输入输出：输入毫秒时间戳，输出 ISO 8601 字符串。
    边界条件：timestamp_ms 必须为 Unix Epoch 毫秒值。
    异常行为：非法数值由 Python datetime 抛错，调用方负责记录上下文。
    """
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def compute_compression_ratio(before_tokens: int, after_tokens: int) -> float:
    """
    计算压缩率。

    做什么：统一计算 after / before 的压缩率，并保留 6 位小数。
    为什么这样做：各阶段需要同口径的压缩收益统计，避免出现前后端展示不一致。
    输入输出：输入压缩前后 Token 数，输出浮点压缩率。
    边界条件：before_tokens 小于等于 0 时返回 0.0。
    异常行为：本函数不抛业务异常。
    """
    if before_tokens <= 0:
        return 0.0
    return round(after_tokens / before_tokens, 6)


def build_compression_model_info() -> tuple[str, str, str]:
    """
    读取当前压缩模型信息。

    做什么：从动态模型配置中获取小模型的 base_url 与 model_id，并推导 provider。
    为什么这样做：上下文压缩、摘要压缩和回放展示都需要记录真实调用的模型来源。
    输入输出：无输入，输出 (provider, base_url, model_id)。
    边界条件：配置缺失时使用客户端默认模型名；provider 推导失败时返回空字符串。
    异常行为：配置读取异常时记录警告并返回空 provider/base_url 与默认 model_id。
    """
    try:
        config = global_config_container.get_model_config(ModelSize.SMALL)
        base_url = str(config.get("base_url") or "")
        model_id = str(config.get("model_id") or "gpt-4o-mini")
        parsed = urlparse(base_url)
        provider = parsed.netloc or parsed.path.split("/")[0] if base_url else ""
        return provider, base_url, model_id
    except Exception as exc:
        logger.warning(f"读取压缩模型信息失败 error={exc}")
        return "", "", "gpt-4o-mini"


def create_replay_snapshot(
    *,
    trace_id: str,
    session_id: str,
    message_id: str,
    memory_id: str,
    stage: CompressionStage,
    scope: CompressionScope,
    source_keys: list[str],
    before_text: str,
    after_text: str,
    raw_tokens: int,
    final_tokens: int,
    is_success: bool,
    failure_reason: str,
    timestamp_ms: int,
) -> CompressionReplaySnapshot:
    """
    创建压缩回放快照。

    做什么：基于原始文本和结果文本生成最小必要的脱敏前后预览与元数据。
    为什么这样做：审计日志 details 需要内嵌最小快照，供后续按 trace_id 直接重建回放。
    输入输出：输入压缩动作上下文，输出 CompressionReplaySnapshot。
    边界条件：preview 长度严格受 settings.compression_replay_preview_max_chars 限制。
    异常行为：脱敏或字段校验异常向上抛出，由调用方记录当前压缩动作上下文。
    """
    preview_limit = settings.compression_replay_preview_max_chars
    return CompressionReplaySnapshot(
        snapshot_id=generate_string_id(),
        trace_id=trace_id,
        session_id=session_id,
        message_id=message_id,
        memory_id=memory_id,
        stage=stage,
        scope=scope,
        source_keys=source_keys,
        preview_before=redact_preview_text(before_text, preview_limit),
        preview_after=redact_preview_text(after_text, preview_limit),
        raw_tokens=raw_tokens,
        final_tokens=final_tokens,
        is_success=is_success,
        failure_reason=failure_reason,
        created_at_ms=timestamp_ms,
    )


def create_compression_audit_payload(
    *,
    trace_id: str,
    session_id: str,
    message_id: str = "",
    memory_id: str = "",
    stage: CompressionStage,
    scope: CompressionScope,
    trigger_reason: CompressionTriggerReason,
    source_keys: list[str],
    before_text: str,
    after_text: str,
    raw_tokens: int,
    after_trim_tokens: int = 0,
    after_summary_tokens: int = 0,
    final_tokens: int,
    is_success: bool,
    failure_reason: str = "",
    timestamp_ms: int | None = None,
    events: Iterable[CompressionActionEvent] | None = None,
) -> CompressionAuditPayload:
    """
    创建统一压缩审计载荷。

    做什么：把压缩阶段的 Token 指标、模型信息、脱敏快照和事件时间线组装为标准审计对象。
    为什么这样做：所有压缩动作都要写入既有 audit_logs.details，必须复用同一构造逻辑。
    输入输出：输入压缩动作上下文与结果，输出 CompressionAuditPayload。
    边界条件：after_trim_tokens/after_summary_tokens 允许为 0，表示该阶段不涉及对应步骤。
    异常行为：字段校验异常向上抛出，由业务链路决定是否跳过审计写入。
    """
    actual_timestamp_ms = timestamp_ms or current_timestamp_ms()
    provider, base_url, model_id = build_compression_model_info()
    snapshot = create_replay_snapshot(
        trace_id=trace_id,
        session_id=session_id,
        message_id=message_id,
        memory_id=memory_id,
        stage=stage,
        scope=scope,
        source_keys=source_keys,
        before_text=before_text,
        after_text=after_text,
        raw_tokens=raw_tokens,
        final_tokens=final_tokens,
        is_success=is_success,
        failure_reason=failure_reason,
        timestamp_ms=actual_timestamp_ms,
    )
    payload_events = list(events or [])
    return CompressionAuditPayload(
        trace_id=trace_id,
        session_id=session_id,
        message_id=message_id,
        memory_id=memory_id,
        stage=stage,
        scope=scope,
        trigger_reason=trigger_reason,
        source_keys=source_keys,
        raw_tokens=raw_tokens,
        after_trim_tokens=after_trim_tokens,
        after_summary_tokens=after_summary_tokens,
        final_tokens=final_tokens,
        total_compression_ratio=compute_compression_ratio(raw_tokens, final_tokens),
        stage_compression_ratio=compute_compression_ratio(
            after_trim_tokens or after_summary_tokens or raw_tokens,
            final_tokens,
        ),
        model_provider=provider,
        model_base_url=base_url,
        model_id=model_id,
        is_success=is_success,
        failure_reason=failure_reason,
        timestamp_ms=actual_timestamp_ms,
        timestamp_iso=timestamp_ms_to_iso(actual_timestamp_ms),
        preview_before=snapshot.preview_before,
        preview_after=snapshot.preview_after,
        replay_snapshot_id=snapshot.snapshot_id,
        snapshot=snapshot,
        events=payload_events,
    )


def record_compression_audit_payload(payload: CompressionAuditPayload, status: str | None = None) -> None:
    """
    投递压缩审计日志到 telemetry worker。

    做什么：把压缩审计载荷写入既有 audit_logs 队列，复用现有异步落盘链路。
    为什么这样做：本轮要求复用已有审计基础设施，而不是再新建平行存储。
    输入输出：输入 CompressionAuditPayload 和可选状态字符串，无返回值。
    边界条件：worker 不存在或审计开关关闭时只写日志并返回。
    异常行为：投递失败只记录警告，不阻断主链路。
    """
    if not settings.compression_audit_enabled:
        return
    worker = get_worker()
    if worker is None:
        logger.warning(
            f"上下文压缩审计未写入：Telemetry Worker 不可用 trace_id={payload.trace_id} stage={payload.stage.value}"
        )
        return

    final_status = status or (
        COMPRESSION_STATUS_SUCCESS if payload.is_success else COMPRESSION_STATUS_FAILED
    )
    if final_status not in {
        COMPRESSION_STATUS_SUCCESS,
        COMPRESSION_STATUS_FAILED,
        COMPRESSION_STATUS_SKIPPED,
    }:
        raise ValueError(f"非法压缩审计状态 status={final_status}")

    try:
        worker.record_audit_log_async(
            {
                "id": generate_string_id(),
                "trace_id": payload.trace_id,
                "action_type": COMPRESSION_AUDIT_ACTION_TYPE,
                "status": final_status,
                "details": json.dumps(payload.model_dump(mode="json"), ensure_ascii=False),
                "error_msg": payload.failure_reason or None,
                "timestamp": datetime.now(timezone.utc),
            }
        )
    except Exception as exc:
        logger.warning(
            f"上下文压缩审计投递失败 trace_id={payload.trace_id} stage={payload.stage.value} error={exc}"
        )


def record_compression_span(
    payload: CompressionAuditPayload,
    *,
    duration_ms: int,
    status: str | None = None,
) -> None:
    """
    投递压缩 Span 到 telemetry worker。

    做什么：为每个压缩动作补一条 Span，便于在 trace 查询里观察耗时。
    为什么这样做：审计只能回答“发生了什么”，Span 才能回答“耗时多少”。
    输入输出：输入审计载荷和耗时，无返回值。
    边界条件：worker 不存在或审计关闭时直接返回。
    异常行为：Span 投递失败只记录警告，不阻断主链路。
    """
    if not settings.compression_audit_enabled:
        return
    worker = get_worker()
    if worker is None:
        logger.warning(
            f"上下文压缩 Span 未写入：Telemetry Worker 不可用 trace_id={payload.trace_id} stage={payload.stage.value}"
        )
        return

    final_status = status or (
        COMPRESSION_STATUS_SUCCESS if payload.is_success else COMPRESSION_STATUS_FAILED
    )
    end_time = datetime.now(timezone.utc)
    start_time = datetime.fromtimestamp(
        max(0, payload.timestamp_ms - duration_ms) / 1000,
        tz=timezone.utc,
    )
    attributes = {
        "stage": payload.stage.value,
        "scope": payload.scope.value,
        "trigger_reason": payload.trigger_reason.value,
        "raw_tokens": payload.raw_tokens,
        "after_trim_tokens": payload.after_trim_tokens,
        "after_summary_tokens": payload.after_summary_tokens,
        "final_tokens": payload.final_tokens,
        "compression_ratio": payload.total_compression_ratio,
        "model_provider": payload.model_provider,
        "model_base_url": payload.model_base_url,
        "model_id": payload.model_id,
        "is_success": payload.is_success,
        "failure_reason": payload.failure_reason,
        "session_id": payload.session_id,
        "message_id": payload.message_id,
        "memory_id": payload.memory_id,
        "source_keys": payload.source_keys,
    }
    try:
        worker.record_span_async(
            {
                "trace_id": payload.trace_id,
                "span_id": generate_string_id(),
                "name": COMPRESSION_SPAN_NAME,
                "service": COMPRESSION_SPAN_SERVICE,
                "start_time": start_time,
                "end_time": end_time,
                "duration_ms": duration_ms,
                "status": final_status,
                "attributes": json.dumps(attributes, ensure_ascii=False),
            }
        )
    except Exception as exc:
        logger.warning(
            f"上下文压缩 Span 投递失败 trace_id={payload.trace_id} stage={payload.stage.value} error={exc}"
        )
