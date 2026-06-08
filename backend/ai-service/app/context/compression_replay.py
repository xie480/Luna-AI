"""
上下文压缩回放聚合器。

做什么：从既有审计日志和 Span 记录中聚合同一链路下的上下文压缩动作，生成前端可直接消费的列表与回放结构。
为什么这样做：压缩查询和回放必须复用现有 telemetry 表，而不是新建平行存储；
            同时前端不应自行解析 details JSON 来推导阶段语义。
输入输出：
    - parse_compression_audit_payload(): 解析单条 audit_logs.details。
    - build_compression_replay_response(): 基于压缩审计与 Span 聚合回放详情。
边界条件：
    - details 不是合法压缩审计 JSON 时直接跳过。
    - Span attributes 允许是非法 JSON，此时降级为原始字符串。
异常行为：
    - 单条数据解析失败不影响整体聚合，调用方可安全继续返回其他记录。
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from app.context.compression_types import (
    CompressionAuditPayload,
    CompressionReplayResponse,
    CompressionReplaySummary,
)
from app.logger import logger
from app.types.constants import COMPRESSION_AUDIT_SCHEMA_VERSION


def parse_compression_audit_payload(details: str) -> CompressionAuditPayload | None:
    """
    解析单条压缩审计载荷。

    做什么：从 audit_logs.details 中解析出 CompressionAuditPayload。
    为什么这样做：既有审计链路只保存 JSON 字符串，查询层必须先完成结构化反序列化。
    输入输出：输入 details 文本，输出 CompressionAuditPayload；非压缩审计返回 None。
    边界条件：details 为空、不是 JSON、schema_version 不匹配时都返回 None。
    异常行为：解析异常只记录 debug/warning，不向上抛出破坏列表查询。
    """
    if not details:
        return None
    try:
        raw = json.loads(details)
    except json.JSONDecodeError:
        logger.warning("压缩审计 details 解析失败，已跳过无效 JSON 记录")
        return None

    if not isinstance(raw, dict):
        return None
    if raw.get("schema_version") != COMPRESSION_AUDIT_SCHEMA_VERSION:
        return None

    try:
        return CompressionAuditPayload.model_validate(raw)
    except Exception as exc:
        logger.warning(f"压缩审计载荷校验失败，已跳过记录 error={exc}")
        return None


def build_compression_audit_list_payload(
    audit_payloads: Iterable[CompressionAuditPayload],
    *,
    total: int,
) -> dict[str, Any]:
    """
    构建压缩审计列表响应数据。

    做什么：把结构化压缩审计列表转换为统一的列表接口响应结构。
    为什么这样做：前端需要稳定字段，不应直接消费数据库模型或原始 JSON 字符串。
    输入输出：输入审计载荷迭代器与总数，输出列表接口的 data 对象。
    边界条件：payload 列表可为空。
    异常行为：本函数不主动抛业务异常。
    """
    items = [payload.model_dump(mode="json") for payload in audit_payloads]
    return {
        "total": total,
        "items": items,
    }


def build_compression_replay_response(
    audit_payloads: Iterable[CompressionAuditPayload],
    spans: Iterable[Any],
) -> CompressionReplayResponse:
    """
    构建单条 trace_id 的压缩回放详情。

    做什么：将同一链路下的压缩动作按时间排序，并输出总览、事件列表、快照列表和对应 Span。
    为什么这样做：前端调试页需要后端直接给出完整时间线，而不是前端二次聚合数据库记录。
    输入输出：输入压缩审计载荷列表和 Span ORM/字典列表，输出 CompressionReplayResponse。
    边界条件：无审计动作时返回空摘要结构，trace_id/session_id/message_id 为空字符串。
    异常行为：单条 Span attributes 解析失败时保留原始字符串，不中断整体回放构建。
    """
    ordered_payloads = sorted(audit_payloads, key=lambda item: item.timestamp_ms)
    if not ordered_payloads:
        return CompressionReplayResponse(trace_id="")

    first_payload = ordered_payloads[0]
    raw_tokens = sum(payload.raw_tokens for payload in ordered_payloads)
    final_tokens = ordered_payloads[-1].final_tokens
    total_compression_ratio = ordered_payloads[-1].total_compression_ratio
    summary = CompressionReplaySummary(
        raw_tokens=raw_tokens,
        final_tokens=final_tokens,
        total_compression_ratio=total_compression_ratio,
        final_strategy=ordered_payloads[-1].stage.value,
    )

    normalized_spans = []
    for span in spans:
        if isinstance(span, dict):
            raw_attributes = span.get("attributes", "{}")
            span_id = span.get("span_id", "")
            name = span.get("name", "")
            service = span.get("service", "")
            duration_ms = span.get("duration_ms", 0)
            status = span.get("status", "")
            start_time = span.get("start_time")
            end_time = span.get("end_time")
        else:
            raw_attributes = getattr(span, "attributes", "{}")
            span_id = getattr(span, "span_id", "")
            name = getattr(span, "name", "")
            service = getattr(span, "service", "")
            duration_ms = getattr(span, "duration_ms", 0)
            status = getattr(span, "status", "")
            start_time = getattr(span, "start_time", None)
            end_time = getattr(span, "end_time", None)

        try:
            parsed_attributes = json.loads(raw_attributes) if isinstance(raw_attributes, str) else raw_attributes
        except json.JSONDecodeError:
            parsed_attributes = {"raw": raw_attributes}

        normalized_spans.append(
            {
                "span_id": span_id,
                "name": name,
                "service": service,
                "duration_ms": duration_ms,
                "status": status,
                "start_time": start_time.isoformat() if hasattr(start_time, "isoformat") else start_time,
                "end_time": end_time.isoformat() if hasattr(end_time, "isoformat") else end_time,
                "attributes": parsed_attributes,
            }
        )

    return CompressionReplayResponse(
        trace_id=first_payload.trace_id,
        session_id=first_payload.session_id,
        message_id=first_payload.message_id,
        summary=summary,
        events=ordered_payloads,
        snapshots=[payload.snapshot for payload in ordered_payloads],
        spans=normalized_spans,
    )
