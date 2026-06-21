"""Chat 主链路 SSE 状态通知发布器。

做什么：定义 ChatStatusEventPayload 载荷模型和 ChatStatusPublisher 发布器，
        为 Chat Workflow 中各 node 提供统一的 EVT_CHAT_STATUS 事件发布能力。
        每个 node 在开始执行和完成执行时各发布一次，前端据此渲染拟人化状态文案。
为什么这样做：状态通知必须由后端按 node 粒度精准触发，前端仅被动接收并按
            session_id / message_id 过滤展示，避免前端猜测当前执行阶段。
边界条件：发布失败被内部捕获并记录中文日志，绝不阻断主链路。多会话并发场景
         由前端按 session_id + message_id 过滤，本模块不做定向投递。
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from app.logger import logger
from app.types.constants import (
    CHAT_STATUS_SCHEMA_VERSION,
    WS_MSG_TYPE_EVT_CHAT_STATUS,
    ChatStatusStage,
    ChatStatusState,
)


class ChatStatusEventPayload(BaseModel):
    """EVT_CHAT_STATUS 事件载荷模型。

    做什么：定义 SSE 事件体中 payload 字段的结构化契约，包含版本、会话标识、
            阶段枚举、状态枚举、前端展示文本、可见性、终结性标志和时间戳。
    为什么这样做：强类型 Pydantic 模型保证序列化一致性，前端可直接按字段
                渲染状态提示而无需二次解析。
    边界条件：
        - schema_version 固定为 chat_status.v1，后续版本升级时前端据此做兼容。
        - is_visible=False 时前端不展示该状态（如阶段跳过的静默通知）。
        - is_terminal=True 时前端可清理该 message_id 之前的所有状态展示。
        - sequence 用于同一 message 内状态防乱序，前端应丢弃小于已处理 sequence 的事件。
    """

    schema_version: str = CHAT_STATUS_SCHEMA_VERSION
    session_id: str = Field(..., min_length=1, max_length=64)
    # 允许空字符串：DAG 引擎内部状态事件在助手消息创建之前运行，此时无 message_id
    message_id: str = Field(..., max_length=64)
    stage: ChatStatusStage
    state: ChatStatusState
    display_text: str = ""
    is_visible: bool = True
    is_terminal: bool = False
    sequence: int = Field(default=0, ge=0)
    timestamp_ms: int = Field(default=0, ge=0)
    error: str = ""


class ChatStatusPublisher:
    """Chat 主链路 SSE 状态事件发布器。

    做什么：为每个 ChatWorkflow node 提供 publish() 方法，封装 SSE 外层信封结构、
            递增 sequence 和毫秒时间戳的自动填充，以及内部异常的静默捕获。
    为什么这样做：将 SSE 发布协议与 node 业务逻辑解耦；node 只需关心调用参数，
                不必处理协议序列化和异常降级。
    异常行为：publish() 内部捕获所有 Exception 并记录中文日志后静默返回，
             绝不向上抛出异常。调用方无需 try/except 包裹。
    """

    def __init__(self) -> None:
        """初始化发布器，序列计数器从 0 开始。"""
        self._sequence_counter: int = 0

    def _next_sequence(self) -> int:
        """获取下一个单调递增的 sequence 值。

        做什么：为每次 publish 分配递增序号，用于前端防乱序和去重。
        为什么这样做：同一 message_id 的状态事件可能因网络乱序到达，
                    前端根据 sequence 丢弃过期事件。
        """
        self._sequence_counter += 1
        return self._sequence_counter

    @staticmethod
    def _current_timestamp_ms() -> int:
        """获取当前毫秒级 Unix 时间戳。"""
        return int(time.time() * 1000)

    async def publish(
        self,
        *,
        trace_id: str,
        session_id: str,
        message_id: str,
        stage: ChatStatusStage,
        state: ChatStatusState,
        display_text: str = "",
        is_visible: bool = True,
        is_terminal: bool = False,
        error: str = "",
    ) -> None:
        """发布一个 EVT_CHAT_STATUS 事件到 SSE 通道。

        参数:
            trace_id: 全链路追踪 ID，透传进 SSE 外层。
            session_id: 会话 ID，前端据此过滤多会话状态。
            message_id: 当前助手消息 ID，前端据此按消息维度管理状态。
            stage: 当前执行阶段，对应 DAG node 类型。
            state: 当前阶段状态（RUNNING / COMPLETED / ERROR / SKIPPED / CANCELLED）。
            display_text: 前端展示的拟人化文本，如"Luna 正在理解中……"。
            is_visible: 是否在前端展示。False 表示静默通知（如跳过或清理）。
            is_terminal: 是否终结状态。True 表示前端可清理该消息的所有状态展示。
            error: 错误详情，仅在 state=ERROR 时有意义。

        异常行为：所有 Exception 内部捕获并记录中文日志，不向上抛出。
        """
        # 构造事件载荷
        payload = ChatStatusEventPayload(
            session_id=session_id,
            message_id=message_id,
            stage=stage,
            state=state,
            display_text=display_text,
            is_visible=is_visible,
            is_terminal=is_terminal,
            sequence=self._next_sequence(),
            timestamp_ms=self._current_timestamp_ms(),
            error=error,
        )

        # 构造 SSE 外层信封
        sse_event: dict[str, Any] = {
            "type": WS_MSG_TYPE_EVT_CHAT_STATUS,
            "trace_id": trace_id,
            "payload": payload.model_dump(mode="json"),
        }

        # 通过 SSE Manager 发布
        from app.api.sse import sse_manager

        try:
            await sse_manager.publish(sse_event)
            logger.debug(
                f"已发布 Chat 状态事件 trace_id={trace_id} "
                f"session_id={session_id} message_id={message_id} "
                f"stage={stage.value} state={state.value} "
                f"display_text=\"{display_text}\" "
                f"sequence={payload.sequence}"
            )
        except Exception as exc:
            # 状态发布失败绝不阻断主链路，仅记录警告日志
            logger.warning(
                f"Chat 状态事件发布失败，忽略此异常 trace_id={trace_id} "
                f"session_id={session_id} message_id={message_id} "
                f"stage={stage.value} state={state.value} "
                f"sequence={payload.sequence} error={exc}"
            )
