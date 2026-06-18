from __future__ import annotations

from datetime import datetime
from typing import Any

from app.logger import logger
from app.repository.chat_history_redis import Interaction
from app.types.constants import Role, WS_MSG_TYPE_CHAT_STREAM
from app.workflow.constants import (
    CHAT_STREAM_TYPE_EMOTION_UPDATE,
    CHAT_STREAM_TYPE_REPLY_CHUNK,
    CHAT_STREAM_TYPE_THOUGHT_CONTENT,
    ChatWorkflowNodeType,
    ChatWorkflowSchemaVersion,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.events import ChatStreamChunkPayload, ChatUnifiedResponsePayload, ChatWorkflowEventPublisher


def format_recent_history(history: list[dict[str, Any]] | list[Interaction]) -> str:
    """把 Redis 短期窗口转换为 Prompt 可读文本。"""
    parts: list[str] = []
    for index, item in enumerate(history):
        # 兼容 dict 和 Interaction 对象
        user_content = item.get("userContent", "") if isinstance(item, dict) else getattr(item, "userContent", "")
        assistant_content = item.get("assistantContent", "") if isinstance(item, dict) else getattr(item, "assistantContent", "")
        thought = item.get("thought", "") if isinstance(item, dict) else getattr(item, "thought", "")
        emotion = item.get("emotion", "") if isinstance(item, dict) else getattr(item, "emotion", "")
        error = item.get("error", "") if isinstance(item, dict) else getattr(item, "error", "")
        timestamp = item.get("timestamp", 0) if isinstance(item, dict) else getattr(item, "timestamp", 0)

        parts.append(f"[对话 {index + 1}]\n")
        parts.append(f"用户: {user_content}\n")
        if assistant_content:
            parts.append(f"Luna: {assistant_content}\n")
        if thought:
            parts.append(f"(内心独白: {thought})\n")
        if emotion:
            parts.append(f"(心情: {emotion})\n")
        if error:
            parts.append(f"(错误: {error})\n")
        if timestamp:
            timestamp_text = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S %A")
            parts.append(f"(时间: {timestamp_text})\n")
        parts.append("\n")
    return "".join(parts)


def split_key_facts(value: str) -> list[str]:
    """把摘要中的关键事实文本拆成列表。"""
    return [line.strip() for line in value.splitlines() if line.strip()]


def first_reason(reasons: list[str], fallback: str) -> str:
    """读取首个非空路由原因。"""
    for reason in reasons:
        if reason:
            return reason
    return fallback


def history_to_model_messages(history: list[dict[str, Any]] | list[Interaction]) -> list[dict[str, str]]:
    """把历史 Interaction 转为 LLM 对话上下文。"""
    messages: list[dict[str, str]] = []
    for item in history:
        # 兼容 dict 和 Interaction 对象
        user_content = item.get("userContent", "") if isinstance(item, dict) else getattr(item, "userContent", "")
        error = item.get("error", "") if isinstance(item, dict) else getattr(item, "error", "")
        assistant_content = item.get("assistantContent", "") if isinstance(item, dict) else getattr(item, "assistantContent", "")
        
        messages.append({"role": Role.USER.value, "content": user_content})
        messages.append({"role": Role.ASSISTANT.value, "content": error or assistant_content})
    return messages


async def handle_stream_piece(
    state: ChatWorkflowState,
    msg_type: str,
    content: str,
    is_finished: bool,
    event_publisher: ChatWorkflowEventPublisher | None,
) -> None:
    """处理 StreamParser 输出的结构化片段并转发给前端。"""
    if msg_type == CHAT_STREAM_TYPE_REPLY_CHUNK:
        state.generation_state.full_text += content
    elif msg_type == CHAT_STREAM_TYPE_THOUGHT_CONTENT:
        state.generation_state.thought_text += content
    elif msg_type == CHAT_STREAM_TYPE_EMOTION_UPDATE:
        state.generation_state.emotion = content
    if msg_type != CHAT_STREAM_TYPE_THOUGHT_CONTENT:
        await publish_stream_payload(state, msg_type, content, is_finished, event_publisher)


async def publish_stream_payload(
    state: ChatWorkflowState,
    msg_type: str,
    content: str,
    is_finished: bool,
    event_publisher: ChatWorkflowEventPublisher | None,
    *,
    error: str = "",
    audio_uri: str | None = None,
    is_sentence_chunk: bool = False,
) -> None:
    """发布兼容既有 CHAT_STREAM 的流式载荷。"""
    if not event_publisher:
        return
    from app.api.sse import sse_manager

    payload = ChatStreamChunkPayload(
        type=msg_type,
        chunk=content,
        is_finished=is_finished,
        node_id=state.generation_state.assistant_message_id,
        error=error,
        audio_uri=audio_uri,
        is_sentence_chunk=is_sentence_chunk,
        interaction_id=state.runtime.interaction_id,
        assistant_message_id=state.generation_state.assistant_message_id,
        plan_preset_id=state.runtime.plan_preset_id,
        current_node_type=ChatWorkflowNodeType.MAIN_CHAT_LLM,
        citations=[item.model_dump(mode="json") for item in state.generation_state.citations],
        is_final_chunk=is_finished,
    )
    await sse_manager.publish(
        {
            "type": WS_MSG_TYPE_CHAT_STREAM,
            "trace_id": state.runtime.trace_id,
            "payload": payload.model_dump(mode="json"),
        }
    )
    logger.debug(
        "Chat Workflow 流式载荷已推送 trace_id={} interaction_id={} type={} is_finished={}",
        state.runtime.trace_id,
        state.runtime.interaction_id,
        msg_type,
        is_finished,
    )


async def publish_unified_response(
    state: ChatWorkflowState,
    full_text: str,
    thought_text: str,
    emotion: str,
    audio_uri: str | None,
    finish_reason: str,
    event_publisher: ChatWorkflowEventPublisher | None,
    *,
    error: str = "",
) -> None:
    """推送非流式统一响应包到前端。

    做什么：将 LLM 完整回复、内心独白、情绪、TTS 音频 URI 和元数据打包为单次 SSE 事件下发。
    为什么这样做：前端收到此事件后，自行负责语义切分、气泡渲染和音画同步。
    输入输出：
        - 输入：state 工作流状态、full_text 完整回复、thought_text 内心独白、
                emotion 情绪、audio_uri 音频地址、finish_reason 结束原因、
                event_publisher 事件发布器
        - 输出：通过 SSE 广播给前端
    边界条件：
        - audio_uri 为 None 时前端不播放音频（纯文本模式）
        - thought_text 或 emotion 为空时前端不渲染对应区域
    异常行为：
        - event_publisher 为 None 时静默跳过，不抛异常
    """
    if not event_publisher:
        return
    from app.api.sse import sse_manager

    payload = ChatUnifiedResponsePayload(
        reply_text=full_text,
        thought_text=thought_text,
        emotion=emotion,
        audio_uri=audio_uri,
        schema_version=ChatWorkflowSchemaVersion.CHAT_WORKFLOW_V1,
        interaction_id=state.runtime.interaction_id,
        assistant_message_id=state.generation_state.assistant_message_id,
        finish_reason=finish_reason,
        e2e_latency_ms=state.generation_state.e2e_latency_ms,
        citations=[item.model_dump(mode="json") for item in state.generation_state.citations],
        error=error,
    )
    await sse_manager.publish(
        {
            "type": WS_MSG_TYPE_CHAT_STREAM,
            "trace_id": state.runtime.trace_id,
            "payload": payload.model_dump(mode="json"),
        }
    )
    logger.info(
        "[TraceID:{}] 非流式统一响应已推送 interaction_id={} e2e_latency_ms={} audio_uri={}",
        state.runtime.trace_id,
        state.runtime.interaction_id,
        state.generation_state.e2e_latency_ms,
        audio_uri or "None",
    )
