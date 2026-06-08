"""
上下文压缩后端能力测试。

做什么：验证上下文压缩治理、审计写入、回放聚合与遥测查询接口的关键闭环。
为什么这样做：本轮新增能力覆盖聊天主链路、短摘要压缩、长期摘要压缩和遥测回放，
            必须通过真实单元与接口测试确保触发、记录、读取、回放全部打通。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.http_api import _trigger_compression
from app.api.routers import telemetry as telemetry_router
from app.context.compression_audit import create_compression_audit_payload, record_compression_audit_payload
from app.context.compression_replay import build_compression_replay_response, parse_compression_audit_payload
from app.llm.client import LLMClient
from app.llm.context_manager import ContextTrimMetrics
from app.memory.manager import Manager as MemoryManager
from app.repository.chat_history_redis import ChatSummary, Interaction
from app.telemetry.redaction import redact_preview_text
from app.types.constants import (
    COMPRESSION_AUDIT_ACTION_TYPE,
    COMPRESSION_SPAN_NAME,
    CompressionScope,
    CompressionStage,
    CompressionTriggerReason,
)


def _build_payload(
    *,
    trace_id: str = "trace-1",
    session_id: str = "session-1",
    message_id: str = "msg-1",
    memory_id: str = "",
    stage: CompressionStage = CompressionStage.SHORT_SUMMARY,
    scope: CompressionScope = CompressionScope.SESSION_HISTORY,
    trigger_reason: CompressionTriggerReason = CompressionTriggerReason.REDIS_WINDOW_OVERFLOW,
    before_text: str = "原始上下文",
    after_text: str = "压缩结果",
    raw_tokens: int = 100,
    after_trim_tokens: int = 0,
    after_summary_tokens: int = 60,
    final_tokens: int = 60,
    is_success: bool = True,
    failure_reason: str = "",
):
    """构造测试用压缩审计载荷。"""
    return create_compression_audit_payload(
        trace_id=trace_id,
        session_id=session_id,
        message_id=message_id,
        memory_id=memory_id,
        stage=stage,
        scope=scope,
        trigger_reason=trigger_reason,
        source_keys=["TEST_SOURCE"],
        before_text=before_text,
        after_text=after_text,
        raw_tokens=raw_tokens,
        after_trim_tokens=after_trim_tokens,
        after_summary_tokens=after_summary_tokens,
        final_tokens=final_tokens,
        is_success=is_success,
        failure_reason=failure_reason,
    )


def test_redact_preview_text_masks_sensitive_content() -> None:
    """验证审计预览会脱敏邮箱、密钥和 URL 查询参数。"""
    text = (
        "联系人 foo@example.com ，Bearer sk-secret-token-12345678 ，"
        "访问 https://example.com/api?token=abc123&email=foo@example.com"
    )
    preview = redact_preview_text(text, 300)
    assert "foo@example.com" not in preview
    assert "sk-secret-token-12345678" not in preview
    assert "abc123" not in preview
    assert "[REDACTED_EMAIL]" in preview
    assert "[REDACTED_SECRET]" in preview
    assert "[REDACTED_QUERY]" in preview


def test_record_compression_audit_payload_writes_json_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证压缩审计会被写入既有 telemetry worker 队列。"""
    captured: list[dict] = []

    class FakeWorker:
        def record_audit_log_async(self, audit: dict) -> None:
            captured.append(audit)

    monkeypatch.setattr("app.context.compression_audit.get_worker", lambda: FakeWorker())
    payload = _build_payload()
    record_compression_audit_payload(payload)

    assert len(captured) == 1
    written = captured[0]
    assert written["action_type"] == COMPRESSION_AUDIT_ACTION_TYPE
    details = json.loads(written["details"])
    assert details["schema_version"] == "compression.audit.v1"
    assert details["stage"] == CompressionStage.SHORT_SUMMARY.value


def test_parse_and_build_compression_replay_response() -> None:
    """验证压缩审计 JSON 可解析并重建回放结构。"""
    payload = _build_payload(
        trace_id="trace-replay",
        stage=CompressionStage.HISTORICAL_CONTEXT_MERGE,
        scope=CompressionScope.HISTORICAL_CONTEXT,
        trigger_reason=CompressionTriggerReason.MEMORY_SLOT_TOKEN_OVER_LIMIT,
        before_text="很长的原始历史背景",
        after_text="更短的历史背景",
        raw_tokens=120,
        after_summary_tokens=40,
        final_tokens=40,
    )
    parsed = parse_compression_audit_payload(json.dumps(payload.model_dump(mode="json"), ensure_ascii=False))
    assert parsed is not None
    assert parsed.trace_id == "trace-replay"

    replay = build_compression_replay_response(
        [parsed],
        [
            {
                "span_id": "span-1",
                "name": COMPRESSION_SPAN_NAME,
                "service": "python_ai",
                "duration_ms": 18,
                "status": "SUCCESS",
                "start_time": "2026-01-01T00:00:00+00:00",
                "end_time": "2026-01-01T00:00:00+00:00",
                "attributes": json.dumps({"stage": CompressionStage.HISTORICAL_CONTEXT_MERGE.value}),
            }
        ],
    )
    assert replay.trace_id == "trace-replay"
    assert replay.summary.final_strategy == CompressionStage.HISTORICAL_CONTEXT_MERGE.value
    assert replay.summary.final_tokens == 40
    assert replay.snapshots[0].preview_after
    assert replay.spans[0]["name"] == COMPRESSION_SPAN_NAME


@pytest.mark.asyncio
async def test_stream_chat_with_context_records_message_trim() -> None:
    """验证消息级裁剪会写入压缩审计。"""
    audit_payloads = []
    span_payloads = []

    async def fake_stream_chat(self, prompt: str, trace_id: str, current_message: str, **kwargs):
        yield {"chunk": "你好", "is_finished": True, "finish_reason": "stop", "error": None}

    with patch("app.llm.client.measure_truncate_context") as mock_measure, \
         patch("app.llm.client.format_messages_for_api") as mock_format, \
         patch("app.llm.client.record_compression_audit_payload") as mock_record_audit, \
         patch("app.llm.client.record_compression_span") as mock_record_span, \
         patch.object(LLMClient, "stream_chat", fake_stream_chat):
        mock_measure.return_value = ContextTrimMetrics(
            before_tokens=120,
            after_tokens=80,
            removed_history_count=2,
            reserved_output_tokens=2048,
            max_context_tokens=4096,
            is_over_limit_after_trim=False,
        )
        mock_format.return_value = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "保留历史"},
            {"role": "user", "content": "当前消息"},
        ]
        mock_record_audit.side_effect = lambda payload, status=None: audit_payloads.append((payload, status))
        mock_record_span.side_effect = lambda payload, duration_ms, status=None: span_payloads.append((payload, duration_ms, status))

        client = LLMClient()
        chunks = [
            chunk
            async for chunk in client.stream_chat_with_context(
                system_prompt="system",
                history=[{"role": "user", "content": "h1"}, {"role": "assistant", "content": "h2"}],
                current_message="当前消息",
                trace_id="trace-trim",
                session_id="session-trim",
                message_id="msg-trim",
            )
        ]

    assert chunks[-1]["is_finished"] is True
    assert len(audit_payloads) == 1
    payload, status = audit_payloads[0]
    assert payload.stage == CompressionStage.MESSAGE_TRIM
    assert payload.trace_id == "trace-trim"
    assert status == "SUCCESS"
    assert span_payloads[0][0].stage == CompressionStage.MESSAGE_TRIM


@pytest.mark.asyncio
async def test_trigger_compression_records_short_summary_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证短期摘要压缩会写入压缩审计。"""
    redis_repo = MagicMock()
    redis_repo.get_context = AsyncMock(
        return_value=(
            ChatSummary(core_summary="旧摘要", key_facts="旧事实"),
            [
                Interaction(msgId="1", userContent="u1", assistantContent="a1", timestamp=1),
                Interaction(msgId="2", userContent="u2", assistantContent="a2", thought="t2", timestamp=2),
            ],
        )
    )
    redis_repo.update_summary_and_trim = AsyncMock()
    prompt_mgr = MagicMock()
    prompt_mgr.assemble_prompt = AsyncMock(return_value="short prompt")
    recorded = []

    monkeypatch.setattr("app.repository.chat_history_redis.MEM_WORKING_WINDOW_SIZE", 1)
    monkeypatch.setattr("app.repository.chat_history_redis.MEM_COMPRESS_BATCH_SIZE", 1)
    monkeypatch.setattr(
        "app.api.http_api.record_compression_audit_payload",
        lambda payload, status=None: recorded.append((payload, status)),
    )
    monkeypatch.setattr("app.api.http_api.record_compression_span", lambda *args, **kwargs: None)

    with patch("app.api.internal_service.internal_service") as mock_internal:
        mock_internal.short_summarize = AsyncMock(return_value=("新摘要", "新事实"))
        await _trigger_compression(
            session_id="session-short",
            trace_id="trace-short",
            redis_repo=redis_repo,
            prompt_mgr=prompt_mgr,
            user_profile_service=None,
        )

    assert redis_repo.update_summary_and_trim.await_count == 1
    assert len(recorded) == 1
    payload, status = recorded[0]
    assert payload.stage == CompressionStage.SHORT_SUMMARY
    assert payload.scope == CompressionScope.SESSION_HISTORY
    assert payload.trace_id == "trace-short"
    assert status == "SUCCESS"


@pytest.mark.asyncio
async def test_compress_and_commit_records_long_summary_audit() -> None:
    """验证长期历史压缩会写入压缩审计。"""
    redis_repo = MagicMock()
    redis_repo.get_context = AsyncMock(
        return_value=(
            ChatSummary(core_summary="核心摘要", key_facts="关键事实"),
            [Interaction(msgId="1", userContent="u1", assistantContent="a1", timestamp=1)],
        )
    )
    ltm_pg_repo = MagicMock()
    ltm_pg_repo.save = AsyncMock()
    ltm_qdrant_repo = MagicMock()
    ltm_qdrant_repo.save_with_vector = AsyncMock()
    prompt_mgr = MagicMock()
    prompt_mgr.assemble_prompt = AsyncMock(return_value="long prompt")
    inference_svc = MagicMock()
    inference_svc.get_embedding_vector = AsyncMock(return_value=[0.1, 0.2])
    manager = MemoryManager(
        redis_repo=redis_repo,
        ltm_pg_repo=ltm_pg_repo,
        ltm_qdrant_repo=ltm_qdrant_repo,
        prompt_mgr=prompt_mgr,
        qdrant_client=MagicMock(),
        inference_svc=inference_svc,
        retrieval_top_k=5,
    )
    recorded = []

    with patch("app.api.internal_service.internal_service") as mock_internal, \
         patch("app.memory.manager.record_compression_audit_payload") as mock_record_audit, \
         patch("app.memory.manager.record_compression_span") as mock_record_span:
        mock_internal.long_summarize = AsyncMock(return_value="压缩后的长期摘要")
        mock_record_audit.side_effect = lambda payload, status=None: recorded.append((payload, status))
        mock_record_span.side_effect = lambda *args, **kwargs: None
        await manager._compress_and_commit("session-long")

    assert ltm_pg_repo.save.await_count == 1
    assert ltm_qdrant_repo.save_with_vector.await_count == 1
    assert len(recorded) == 1
    payload, status = recorded[0]
    assert payload.stage == CompressionStage.LONG_SUMMARY
    assert payload.trace_id
    assert status == "SUCCESS"


def test_telemetry_routes_return_compression_audits_and_replay() -> None:
    """验证压缩审计列表与回放详情接口返回结构化结果。"""
    payload = _build_payload(trace_id="trace-route", session_id="session-route", message_id="msg-route")
    fake_log = SimpleNamespace(details=json.dumps(payload.model_dump(mode="json"), ensure_ascii=False))

    app = FastAPI()
    app.include_router(telemetry_router.router)
    client = TestClient(app)

    with patch.object(telemetry_router, "_query_audit_logs", new=AsyncMock(return_value=(1, [fake_log]))), \
         patch.object(
             telemetry_router,
             "_query_trace_spans",
             new=AsyncMock(return_value=(1, [{"span_id": "span-1", "name": COMPRESSION_SPAN_NAME, "service": "python_ai", "duration_ms": 7, "status": "SUCCESS", "start_time": None, "end_time": None, "attributes": "{}"}])),
         ):
        audits_response = client.get("/api/v1/telemetry/compression_audits")
        replay_response = client.get("/api/v1/telemetry/compression_replays/trace-route")

    assert audits_response.status_code == 200
    audits_data = audits_response.json()["data"]
    assert audits_data["total"] == 1
    assert audits_data["items"][0]["trace_id"] == "trace-route"
    assert audits_data["items"][0]["stage"] == CompressionStage.SHORT_SUMMARY.value

    assert replay_response.status_code == 200
    replay_data = replay_response.json()["data"]
    assert replay_data["trace_id"] == "trace-route"
    assert replay_data["session_id"] == "session-route"
    assert replay_data["message_id"] == "msg-route"
    assert replay_data["summary"]["final_strategy"] == CompressionStage.SHORT_SUMMARY.value
    assert len(replay_data["events"]) == 1
    assert len(replay_data["snapshots"]) == 1
    assert replay_data["spans"][0]["name"] == COMPRESSION_SPAN_NAME
