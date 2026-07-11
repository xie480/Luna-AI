"""回复持久化节点。"""

from __future__ import annotations

import json
import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.repository.chat_history_redis import Interaction
from app.repository.models import InteractionModel
from app.types.constants import ChatStatusStage, ChatStatusState
from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    CHAT_STREAM_EMPTY_RESPONSE_ERROR,
    CHAT_STREAM_GENERATION_ERROR,
    CHAT_WORKFLOW_PG_WRITE_FAILED,
    CHAT_WORKFLOW_PG_WRITE_OK,
    CHAT_WORKFLOW_PG_WRITE_SKIPPED,
    CHAT_WORKFLOW_REDIS_WRITE_FAILED,
    CHAT_WORKFLOW_REDIS_WRITE_OK,
    CHAT_WORKFLOW_REDIS_WRITE_SKIPPED,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies


class ResponsePersistenceNode(ChatWorkflowNode):
    """回复落盘节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.RESPONSE_PERSISTENCE,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.RESPONSE_PERSISTENCE,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.RESPONSE_PERSISTENCE, ChatStatusState.RUNNING),
        )

        assistant_content = state.generation_state.full_text
        error_json = ""

        if state.generation_state.error:
            error_json = json.dumps(
                {"error": CHAT_STREAM_GENERATION_ERROR, "details": state.generation_state.error},
                ensure_ascii=False,
            )
            if not assistant_content:
                assistant_content = error_json
        elif not assistant_content:
            error_json = json.dumps(
                {"error": CHAT_STREAM_GENERATION_ERROR, "details": CHAT_STREAM_EMPTY_RESPONSE_ERROR},
                ensure_ascii=False,
            )
            assistant_content = error_json

        long_answer_id = state.generation_state.metadata.get("long_answer_id") if state.generation_state.metadata else None

        interaction = Interaction(
            msgId=state.generation_state.assistant_message_id,
            userContent=state.input_payload.raw_user_message,
            assistantContent=assistant_content,
            thought=state.generation_state.thought_text,
            emotion=state.generation_state.emotion,
            error=error_json,
            timestamp=int(time.time()),
            hasLongAnswer=bool(long_answer_id),
            longAnswerId=long_answer_id or "",
        )

        pg_status = CHAT_WORKFLOW_PG_WRITE_SKIPPED
        redis_status = CHAT_WORKFLOW_REDIS_WRITE_SKIPPED

        if self.dependencies.pg_repo:
            try:
                await self.dependencies.pg_repo.save_interaction(
                    InteractionModel(
                        id=generate_string_id(),
                        session_id=state.runtime.session_id,
                        message_id=state.generation_state.assistant_message_id,
                        user_content=state.input_payload.raw_user_message,
                        assistant_content=assistant_content,
                        thought=state.generation_state.thought_text,
                        emotion=state.generation_state.emotion,
                        error=error_json,
                        long_answer_id=long_answer_id,
                    )
                )
                pg_status = CHAT_WORKFLOW_PG_WRITE_OK
            except Exception as exc:
                pg_status = CHAT_WORKFLOW_PG_WRITE_FAILED
                logger.error(f"Workflow 保存 Interaction 到 PG 失败 trace_id={state.runtime.trace_id} error={exc}")

        if self.dependencies.redis_repo:
            try:
                await self.dependencies.redis_repo.save_interaction(state.runtime.session_id, interaction)
                redis_status = CHAT_WORKFLOW_REDIS_WRITE_OK
            except Exception as exc:
                redis_status = CHAT_WORKFLOW_REDIS_WRITE_FAILED
                logger.error(f"Workflow 保存 Interaction 到 Redis 失败 trace_id={state.runtime.trace_id} error={exc}")

        logger.info(
            f"回复持久化完成 trace_id={state.runtime.trace_id} interaction_id={state.runtime.interaction_id} "
            f"session_id={state.runtime.session_id} node_type={self.node_type.value} "
            f"pg_status={pg_status} redis_status={redis_status}"
        )

        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.RESPONSE_PERSISTENCE,
            status=ChatStatusState.COMPLETED,
            display_text=get_chat_status_text(ChatStatusStage.RESPONSE_PERSISTENCE, ChatStatusState.COMPLETED),
            is_terminal=True,
        )

        return state

    async def _publish_chat_status(
        self,
        state: ChatWorkflowState,
        stage: ChatStatusStage,
        status: ChatStatusState,
        display_text: str,
        is_visible: bool = True,
        is_terminal: bool = False,
        error: str = "",
    ) -> None:
        publisher: ChatStatusPublisher | None = self.dependencies.chat_status_publisher
        if publisher is None:
            return
        await publisher.publish(
            trace_id=state.runtime.trace_id,
            session_id=state.runtime.session_id,
            message_id=state.generation_state.assistant_message_id,
            stage=stage,
            state=status,
            display_text=display_text,
            is_visible=is_visible,
            is_terminal=is_terminal,
            error=error,
        )
