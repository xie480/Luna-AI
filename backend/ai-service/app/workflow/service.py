"""Phase 8.5 Chat Workflow 应用服务。"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from sqlalchemy import text

from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.memory.manager import Manager as MemoryManager
from app.prompt.manager import Manager as PromptManager
from app.rag.retrieval import RagRetrievalOrchestrator
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo
from app.types.constants import WS_MSG_TYPE_CHAT_STREAM
from app.user_profile.service import UserProfileService
from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    CHAT_STREAM_TYPE_REPLY_CHUNK,
    CHAT_WORKFLOW_CHECKPOINT_NS_SEPARATOR,
    CHAT_WORKFLOW_CHECKPOINT_TABLE,
    CHAT_WORKFLOW_DEFAULT_LOCALE,
    CHAT_WORKFLOW_DEFAULT_TIMEZONE,
    ChatMode,
    ChatPlanPreset,
    ChatWorkflowErrorCode,
    ChatWorkflowEventType,
    ChatWorkflowNodeType,
)
from app.workflow.context import (
    ChatGenerationState,
    ChatInputPayload,
    ChatRuntimeState,
    ChatWorkflowState,
)
from app.workflow.events import ChatStreamChunkPayload, ChatWorkflowEvent, ChatWorkflowEventPublisher
from app.workflow.graph_factory import ChatGraphFactory
from app.workflow.nodes.dependencies import WorkflowDependencies


class ChatWorkflowService:
    """Chat Workflow 内部应用服务。"""

    def __init__(
        self,
        *,
        redis_repo: ChatHistoryRedisRepo | None,
        pg_repo: ChatHistoryPGRepo | None,
        pg_client: PostgresClient | None,
        prompt_manager: PromptManager | None,
        memory_manager: MemoryManager | None,
        rag_orchestrator: RagRetrievalOrchestrator | None,
        user_profile_service: UserProfileService | None,
        event_publisher: ChatWorkflowEventPublisher | None = None,
        # --- Phase 12 新增：RAG 知识库 PG 仓库（InputReconstructionNode 注入 KNOWLEDGE_DOCS 用） ---
        rag_pg_repo: Any = None,
    ):
        self.pg_client = pg_client
        self.event_publisher = event_publisher or ChatWorkflowEventPublisher()
        from app.api.chat_status import ChatStatusPublisher

        chat_status_publisher = ChatStatusPublisher()
        dependencies = WorkflowDependencies(
            redis_repo=redis_repo,
            pg_repo=pg_repo,
            prompt_manager=prompt_manager,
            memory_manager=memory_manager,
            rag_orchestrator=rag_orchestrator,
            user_profile_service=user_profile_service,
            event_publisher=self.event_publisher,
            chat_status_publisher=chat_status_publisher,
            # --- Phase 12 新增：透传 RAG 知识库 PG 仓库 ---
            rag_pg_repo=rag_pg_repo,
        )
        factory = ChatGraphFactory(dependencies)
        self.daily_chat_graph = factory.build_daily_chat_graph()
        self.casual_chat_graph = factory.build_casual_chat_graph()
        self.tasks: set[asyncio.Task[Any]] = set()

    async def start_daily_chat(
        self,
        *,
        trace_id: str,
        session_id: str,
        message: str,
        frontend_message_id: str,
        tts_enabled: bool = True,
        locale: str = CHAT_WORKFLOW_DEFAULT_LOCALE,
        timezone: str = CHAT_WORKFLOW_DEFAULT_TIMEZONE,
        llm_response_mode: str = "unified",
        chat_mode: ChatMode = ChatMode.DAILY_CHAT,
    ) -> dict[str, str]:
        """
        启动聊天工作流（支持普通模式与闲聊模式）。

        参数:
            self: 类实例引用
            trace_id: 跟踪ID，用于追踪请求
            session_id: 会话ID，标识用户会话
            message: 用户发送的消息内容
            frontend_message_id: 前端消息ID，用于前端标识消息
            tts_enabled: 是否启用 TTS 语音合成
            locale: 本地化设置，默认为CHAT_WORKFLOW_DEFAULT_LOCALE
            timezone: 时区设置，默认为CHAT_WORKFLOW_DEFAULT_TIMEZONE
            llm_response_mode: LLM 响应模式，streaming（流式）或 unified（统一非流式）
            chat_mode: ChatMode 枚举值，ChatMode.DAILY_CHAT（普通模式，默认）或 ChatMode.CASUAL_CHAT（闲聊模式）

        返回:
            dict[str, str]: 包含状态信息的字典，包括'status'、'msgId'和'interaction_id'

        异常:
            ValueError: 当session_id或message为空时抛出异常
        """
        # 解析聊天模式枚举
        if chat_mode == ChatMode.CASUAL_CHAT:
            plan_preset = ChatPlanPreset.CASUAL_CHAT_DEFAULT
            disable_rerank = True
        else:
            plan_preset = ChatPlanPreset.DAILY_CHAT_DEFAULT
            disable_rerank = False

        # 清理输入参数
        cleaned_session_id = session_id.strip()
        cleaned_message = message.strip()
        if not cleaned_session_id:
            raise ValueError("sessionId 不能为空")
        if not cleaned_message:
            raise ValueError("message 不能为空")
        # 生成或使用提供的助手消息ID
        assistant_message_id = frontend_message_id.strip() or generate_string_id()
        # 生成交互ID
        interaction_id = generate_string_id()
        # 创建聊天工作流状态对象
        state = ChatWorkflowState(
            runtime=ChatRuntimeState(
                trace_id=trace_id,
                interaction_id=interaction_id,
                session_id=cleaned_session_id,
                started_at_ms=current_time_ms(),
                chat_mode=plan_preset,
                plan_preset_id=plan_preset.value,
                disable_rerank=disable_rerank,
            ),
            input_payload=ChatInputPayload(
                raw_user_message=cleaned_message,
                frontend_message_id=assistant_message_id,
                client_timestamp_ms=current_time_ms(),
                locale=locale,
                timezone=timezone,
                tts_enabled=tts_enabled,
                llm_response_mode=llm_response_mode,
            ),
            generation_state=ChatGenerationState(assistant_message_id=assistant_message_id),
        )
        # 发布聊天计划开始事件
        await self.publish_plan_event(state, ChatWorkflowEventType.EVT_CHAT_PLAN_STARTED)
        # 创建并启动异步任务执行图
        task = asyncio.create_task(self.run_graph(state))
        self.register_task(task)
        # 返回状态信息
        return {"status": "streaming", "msgId": assistant_message_id, "interaction_id": interaction_id}

    async def run_graph(self, state: ChatWorkflowState) -> None:
        """
        根据 chat_mode 选择执行对应的 LangGraph 工作流图。

        做什么：如果 chat_mode 为 CASUAL_CHAT_DEFAULT 则执行闲聊最短化链路图，
                否则执行默认的日常聊天完整链路图。
        """
        try:
            if state.runtime.chat_mode == ChatPlanPreset.CASUAL_CHAT_DEFAULT:
                logger.info(
                    f"闲聊模式图开始执行 trace_id={state.runtime.trace_id} "
                    f"session_id={state.runtime.session_id}"
                )
                graph_state = await self.casual_chat_graph.ainvoke(state.as_graph_state())
            else:
                logger.info(
                    f"日常聊天模式图开始执行 trace_id={state.runtime.trace_id} "
                    f"session_id={state.runtime.session_id}"
                )
                graph_state = await self.daily_chat_graph.ainvoke(state.as_graph_state())
            final_state = ChatWorkflowState.from_graph_state(graph_state)
            await self.write_checkpoint(final_state)
            await self.publish_plan_event(final_state, ChatWorkflowEventType.EVT_CHAT_PLAN_COMPLETED)
        except Exception as exc:
            logger.opt(exception=exc).error(
                f"Chat Workflow 图执行失败 trace_id={state.runtime.trace_id} "
                f"interaction_id={state.runtime.interaction_id} "
                f"session_id={state.runtime.session_id} "
                f"error_code={ChatWorkflowErrorCode.NODE_UNEXPECTED_FAILED.value} error={exc}"
            )
            await self.publish_error_chunk(state, str(exc))

    async def write_checkpoint(self, state: ChatWorkflowState) -> None:
        if not self.pg_client:
            logger.warning(
                f"PostgreSQL 不可用 跳过 checkpoint 写入 trace_id={state.runtime.trace_id}"
            )
            return
        chat_mode_val = state.runtime.chat_mode.value if hasattr(state.runtime.chat_mode, "value") else state.runtime.chat_mode
        preset_id_val = state.runtime.plan_preset_id.value if hasattr(state.runtime.plan_preset_id, "value") else state.runtime.plan_preset_id
        checkpoint_ns = (
            f"{chat_mode_val}"
            f"{CHAT_WORKFLOW_CHECKPOINT_NS_SEPARATOR}"
            f"{preset_id_val}"
        )
        checkpoint_sql = (
            f"INSERT INTO {CHAT_WORKFLOW_CHECKPOINT_TABLE} "
            "(checkpoint_id, thread_id, checkpoint_ns, trace_id, interaction_id, "
            "node_type, payload, created_at) "
            "VALUES (:checkpoint_id, :thread_id, :checkpoint_ns, :trace_id, "
            ":interaction_id, :node_type, CAST(:payload AS JSONB), NOW())"
        )
        
        node_type_val = ChatWorkflowNodeType.FINALIZE.value
        if state.runtime.current_node_type:
            node_type_val = state.runtime.current_node_type.value if hasattr(state.runtime.current_node_type, "value") else state.runtime.current_node_type

        async with self.pg_client.session_factory() as session:
            await session.execute(
                text(checkpoint_sql),
                {
                    "checkpoint_id": generate_string_id(),
                    "thread_id": state.runtime.session_id,
                    "checkpoint_ns": checkpoint_ns,
                    "trace_id": state.runtime.trace_id,
                    "interaction_id": state.runtime.interaction_id,
                    "node_type": node_type_val,
                    "payload": json.dumps(state.model_dump(mode="json"), ensure_ascii=False),
                },
            )
            await session.commit()

    async def publish_plan_event(
        self,
        state: ChatWorkflowState,
        event_type: ChatWorkflowEventType,
    ) -> None:
        node_type_val = state.runtime.current_node_type if not state.runtime.current_node_type else (
            state.runtime.current_node_type if hasattr(state.runtime.current_node_type, "value") else ChatWorkflowNodeType(state.runtime.current_node_type)
        )
        event = ChatWorkflowEvent(
            event_type=event_type,
            trace_id=state.runtime.trace_id,
            interaction_id=state.runtime.interaction_id,
            session_id=state.runtime.session_id,
            plan_preset_id=ChatPlanPreset.DAILY_CHAT_DEFAULT,
            node_type=node_type_val,
            timestamp_ms=current_time_ms(),
            payload={"assistant_message_id": state.generation_state.assistant_message_id},
        )
        await self.event_publisher.publish(event)
        state.observability.emitted_event_ids.append(event.event_id)

    async def publish_error_chunk(self, state: ChatWorkflowState, error: str) -> None:
        from app.api.sse import sse_manager

        node_type_val = state.runtime.current_node_type or ChatWorkflowNodeType.MAIN_CHAT_LLM
        if node_type_val and not hasattr(node_type_val, "value"):
            node_type_val = ChatWorkflowNodeType(node_type_val)

        payload = ChatStreamChunkPayload(
            type=CHAT_STREAM_TYPE_REPLY_CHUNK,
            chunk="",
            is_finished=True,
            node_id=state.generation_state.assistant_message_id,
            error=error,
            interaction_id=state.runtime.interaction_id,
            assistant_message_id=state.generation_state.assistant_message_id,
            current_node_type=node_type_val,
            is_final_chunk=True,
        )
        await sse_manager.publish(
            {
                "type": WS_MSG_TYPE_CHAT_STREAM,
                "trace_id": state.runtime.trace_id,
                "payload": payload.model_dump(mode="json"),
            }
        )

    def register_task(self, task: asyncio.Task[Any] | Any) -> None:
        if not isinstance(task, asyncio.Task):
            return
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


def current_time_ms() -> int:
    return int(time.time() * 1000)
