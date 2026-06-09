"""回复持久化节点。"""

from __future__ import annotations

import json
import time
from typing import Any

from app.logger import logger
from app.repository.chat_history_redis import Interaction
from app.repository.models import InteractionModel
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
        """
        处理聊天工作流状态并持久化交互数据到数据库和Redis
        
        该方法负责处理助手生成的内容，处理错误情况，并将交互数据保存到PostgreSQL和Redis中。
        
        Args:
            state (ChatWorkflowState): 当前聊天工作流的状态，包含用户输入、助手响应等信息
            
        Returns:
            ChatWorkflowState: 返回相同的状态对象，可能已更新了持久化相关的状态信息
        """
        # 提取助手生成的内容
        assistant_content = state.generation_state.full_text
        error_json = ""
        
        # 检查是否发生错误或内容为空，如果是则设置相应的错误JSON
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
        
        # 创建交互对象用于持久化
        interaction = Interaction(
            msgId=state.generation_state.assistant_message_id,
            userContent=state.input_payload.raw_user_message,
            assistantContent=assistant_content,
            thought=state.generation_state.thought_text,
            emotion=state.generation_state.emotion,
            error=error_json,
            timestamp=int(time.time()),
        )
        
        # 初始化数据库和Redis写入状态
        pg_status = CHAT_WORKFLOW_PG_WRITE_SKIPPED
        redis_status = CHAT_WORKFLOW_REDIS_WRITE_SKIPPED
        
        # 尝试将交互数据保存到PostgreSQL数据库
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
                    )
                )
                pg_status = CHAT_WORKFLOW_PG_WRITE_OK
            except Exception as exc:
                pg_status = CHAT_WORKFLOW_PG_WRITE_FAILED
                logger.error(f"Workflow 保存 Interaction 到 PG 失败 trace_id={state.runtime.trace_id} error={exc}")
        
        # 尝试将交互数据保存到Redis缓存
        if self.dependencies.redis_repo:
            try:
                await self.dependencies.redis_repo.save_interaction(state.runtime.session_id, interaction)
                redis_status = CHAT_WORKFLOW_REDIS_WRITE_OK
            except Exception as exc:
                redis_status = CHAT_WORKFLOW_REDIS_WRITE_FAILED
                logger.error(f"Workflow 保存 Interaction 到 Redis 失败 trace_id={state.runtime.trace_id} error={exc}")
        
        # 记录持久化操作的完成状态
        logger.info(
            f"回复持久化完成 trace_id={state.runtime.trace_id} interaction_id={state.runtime.interaction_id} "
            f"session_id={state.runtime.session_id} node_type={self.node_type.value} "
            f"pg_status={pg_status} redis_status={redis_status}"
        )
        return state
