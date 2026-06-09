"""
Phase 8.5 Chat Workflow 应用服务。

做什么：封装 API 层到 LangGraph daily_chat.default.v1 预设图的调用入口。
为什么这样做：API 层只负责请求校验与立即响应，ChatWorkflowService 负责创建强类型初始状态、调用图、转发事件、归一化异常与写入 checkpoint。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from sqlalchemy import text

from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo
from app.memory.manager import Manager as MemoryManager
from app.prompt.manager import Manager as PromptManager
from app.rag.retrieval import RagRetrievalOrchestrator
from app.user_profile.service import UserProfileService
from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    CHAT_STREAM_TYPE_REPLY_CHUNK,
    CHAT_WORKFLOW_CHECKPOINT_NS_SEPARATOR,
    CHAT_WORKFLOW_CHECKPOINT_TABLE,
    CHAT_WORKFLOW_DEFAULT_LOCALE,
    CHAT_WORKFLOW_DEFAULT_TIMEZONE,
    ChatPlanPreset,
    ChatWorkflowErrorCode,
    ChatWorkflowEventType,
    ChatWorkflowNodeType,
)
from app.workflow.context import (
    ChatGenerationState,
    ChatInputPayload,
    ChatRuntimeContext,
    ChatWorkflowState,
)
from app.workflow.events import ChatWorkflowEvent, ChatWorkflowEventPublisher
from app.workflow.graph_factory import ChatGraphFactory
from app.workflow.nodes.adapters import WorkflowDependencies


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
    ):
        """
        初始化 Chat Workflow 服务。

        做什么：保存依赖并预编译 daily_chat.default.v1 图。
        为什么这样做：图结构固定，可在服务启动阶段构建，避免每次请求重复注册节点。
        输入输出：输入 FastAPI lifespan 注入的仓库、管理器、编排器；输出服务实例。
        边界条件：部分依赖为空时节点按降级策略执行；Prompt/LLM 等主链路关键依赖失败会进入错误恢复。
        异常行为：初始化图失败会向启动流程抛出异常，避免服务假成功。
        """
        self.pg_client = pg_client
        self.event_publisher = event_publisher or ChatWorkflowEventPublisher()
        dependencies = WorkflowDependencies(
            redis_repo=redis_repo,
            pg_repo=pg_repo,
            prompt_manager=prompt_manager,
            memory_manager=memory_manager,
            rag_orchestrator=rag_orchestrator,
            user_profile_service=user_profile_service,
            event_publisher=self.event_publisher,
        )
        self.graph = ChatGraphFactory(dependencies).build_daily_chat_graph()
        self._tracked_tasks: set[asyncio.Task[Any]] = set()

    async def start_daily_chat(
        self,
        *,
        trace_id: str,
        session_id: str,
        message: str,
        frontend_message_id: str,
        locale: str = CHAT_WORKFLOW_DEFAULT_LOCALE,
        timezone: str = CHAT_WORKFLOW_DEFAULT_TIMEZONE,
    ) -> dict[str, str]:
        """
        启动 daily_chat.default.v1 图执行并立即返回。

        做什么：校验输入、创建初始状态、创建后台任务运行 LangGraph。
        为什么这样做：保持现有 /api/chat 立即返回、SSE 流式推送的接口体验。
        输入输出：输入聊天请求关键字段，输出兼容旧前端的 status/msgId。
        边界条件：session_id/message 为空直接抛 ValueError，不进入图。
        异常行为：后台任务异常会发送最终错误流并写日志，不让 HTTP 请求挂起。
        """
        # 清理输入参数
        cleaned_session_id = session_id.strip()
        cleaned_message = message.strip()
        
        # 校验必要参数
        if not cleaned_session_id:
            raise ValueError("sessionId 不能为空")
        if not cleaned_message:
            raise ValueError("message 不能为空")
            
        # 生成或使用提供的消息ID和交互ID
        assistant_message_id = frontend_message_id.strip() or generate_string_id()
        interaction_id = generate_string_id()
        now_ms = _now_ms()
        
        # 创建聊天工作流状态对象
        state = ChatWorkflowState(
            runtime=ChatRuntimeContext(
                trace_id=trace_id,
                interaction_id=interaction_id,
                session_id=cleaned_session_id,
                started_at_ms=now_ms,
            ),
            input_payload=ChatInputPayload(
                raw_user_message=cleaned_message,
                frontend_message_id=assistant_message_id,
                client_timestamp_ms=now_ms,
                locale=locale,
                timezone=timezone,
            ),
            generation_state=ChatGenerationState(assistant_message_id=assistant_message_id),
        )
        
        # 发布聊天计划开始事件
        await self._publish_plan_event(state, ChatWorkflowEventType.EVT_CHAT_PLAN_STARTED)
        
        # 创建并启动后台任务运行图
        task = asyncio.create_task(self._run_graph_task(state))
        self._track_task(task)
        
        # 返回状态信息给前端
        return {"status": "streaming", "msgId": assistant_message_id, "interaction_id": interaction_id}

    async def _run_graph_task(self, state: ChatWorkflowState) -> None:
        """
        后台执行 LangGraph 图。

        做什么：调用预编译图、持久化 checkpoint、发送完成事件。
        为什么这样做：隔离 HTTP 请求生命周期与 LLM 流式生成生命周期。
        边界条件：主链路异常时发送兼容 CHAT_STREAM 的最终错误块。
        异常行为：异常被记录并转为 SSE 错误事件，不向事件循环泄漏未处理异常。
        """
        try:
            # 执行LangGraph图并获取最终状态
            final_graph_state = await self.graph.ainvoke(state.as_graph_state())
            # 将图状态转换回工作流状态
            final_state = ChatWorkflowState.from_graph_state(final_graph_state)
            # 持久化检查点数据
            await self._write_checkpoint(final_state)
            # 发布聊天计划完成事件
            await self._publish_plan_event(final_state, ChatWorkflowEventType.EVT_CHAT_PLAN_COMPLETED)
        except Exception as exc:
            # 记录图执行失败的错误日志
            logger.opt(exception=exc).error(
                f"Chat Workflow 图执行失败 trace_id={state.runtime.trace_id} "
                f"interaction_id={state.runtime.interaction_id} session_id={state.runtime.session_id} "
                f"error_code={ChatWorkflowErrorCode.NODE_UNEXPECTED_FAILED.value} error={exc}"
            )
            # 发布终端错误事件
            await self._publish_terminal_error(state, str(exc))

    async def _write_checkpoint(self, state: ChatWorkflowState) -> None:
        """
        写入 Phase 8.5 独立 checkpoint 表。

        做什么：按 session_id 作为 thread_id，chat_mode + plan_preset_id 作为 checkpoint_ns 保存最终状态快照。
        为什么这样做：满足 checkpoint 与业务表物理隔离要求，并为 Phase 9 回放和恢复保留元数据。
        边界条件：pg_client 不可用时只记录 warning，不阻断主回复。
        异常行为：写入失败记录明确错误码，不伪造成功。
        """
        if not self.pg_client:
            logger.warning(
                f"PostgreSQL 不可用，跳过 Chat Workflow checkpoint 写入 trace_id={state.runtime.trace_id}"
            )
            return
        checkpoint_ns = (
            f"{state.runtime.chat_mode.value}{CHAT_WORKFLOW_CHECKPOINT_NS_SEPARATOR}"
            f"{state.runtime.plan_preset_id.value}"
        )
        checkpoint_id = generate_string_id()
        async with self.pg_client.session_factory() as session:
            await session.execute(
                text(
                    f"INSERT INTO {CHAT_WORKFLOW_CHECKPOINT_TABLE} "
                    "(checkpoint_id, thread_id, checkpoint_ns, trace_id, interaction_id, node_type, payload, created_at) "
                    "VALUES (:checkpoint_id, :thread_id, :checkpoint_ns, :trace_id, :interaction_id, :node_type, CAST(:payload AS JSONB), NOW())"
                ),
                {
                    "checkpoint_id": checkpoint_id,
                    "thread_id": state.runtime.session_id,
                    "checkpoint_ns": checkpoint_ns,
                    "trace_id": state.runtime.trace_id,
                    "interaction_id": state.runtime.interaction_id,
                    "node_type": (state.runtime.current_node_type or ChatWorkflowNodeType.FINALIZE).value,
                    "payload": json.dumps(state.model_dump(mode="json"), ensure_ascii=False),
                },
            )
            await session.commit()
        logger.info(
            f"Chat Workflow checkpoint 写入完成 trace_id={state.runtime.trace_id} "
            f"interaction_id={state.runtime.interaction_id} session_id={state.runtime.session_id} "
            f"checkpoint_id={checkpoint_id}"
        )

    async def _publish_plan_event(self, state: ChatWorkflowState, event_type: ChatWorkflowEventType) -> None:
        """发布计划开始或完成事件。"""
        event = ChatWorkflowEvent(
            event_type=event_type,
            trace_id=state.runtime.trace_id,
            interaction_id=state.runtime.interaction_id,
            session_id=state.runtime.session_id,
            plan_preset_id=ChatPlanPreset.DAILY_CHAT_DEFAULT,
            node_type=state.runtime.current_node_type,
            timestamp_ms=_now_ms(),
            payload={
                "node_observation_count": len(state.observability.node_observations),
                "assistant_message_id": state.generation_state.assistant_message_id,
            },
        )
        try:
            await self.event_publisher.publish(event)
            state.observability.emitted_event_ids.append(event.event_id)
        except Exception as exc:
            logger.warning(f"Chat Workflow 计划事件发布失败 trace_id={state.runtime.trace_id} error={exc}")

    async def _publish_terminal_error(self, state: ChatWorkflowState, error: str) -> None:
        """发送兼容旧前端的最终错误流。"""
        from app.api.sse import sse_manager
        from app.types.constants import WS_MSG_TYPE_CHAT_STREAM
        from app.workflow.events import ChatStreamChunkPayload

        payload = ChatStreamChunkPayload(
            type=CHAT_STREAM_TYPE_REPLY_CHUNK,
            chunk="",
            is_finished=True,
            node_id=state.generation_state.assistant_message_id,
            error=error,
            interaction_id=state.runtime.interaction_id,
            assistant_message_id=state.generation_state.assistant_message_id,
            current_node_type=state.runtime.current_node_type or ChatWorkflowNodeType.ERROR_RECOVERY,
            is_final_chunk=True,
        )
        await sse_manager.publish(
            {
                "type": WS_MSG_TYPE_CHAT_STREAM,
                "trace_id": state.runtime.trace_id,
                "payload": payload.model_dump(mode="json"),
            }
        )

    def _track_task(self, task: asyncio.Task[Any]) -> None:
        """跟踪后台任务并在结束后回收引用。"""
        self._tracked_tasks.add(task)
        task.add_done_callback(self._tracked_tasks.discard)


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)
