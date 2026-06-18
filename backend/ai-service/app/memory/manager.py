"""
Luna AI 长期记忆管理器模块

做什么：协调长期记忆的完整生命周期：会话流转检测、历史压缩、双库提交、记忆检索。
        记忆检索委托给 rag/ 模块中的 HybridRetriever 执行 BM25 + 向量混合检索 + Rerank 重排。
为什么这样做：作为唯一调度权威，所有记忆写入必须经过此管理器的事务控制。
             检索策略由 rag/ 模块统一负责，遵循单一职责原则。
输入输出：
    - Manager: 长期记忆管理器类
边界条件：
    - 启动时兜底检测：清理 Redis 中的非当日历史会话
    - 压缩历史会话并提交到双库
    - 执行自然日会话流转
    - 检索长期记忆（委托 rag/ 模块的 HybridRetriever）
异常行为：
    - 依赖服务不可用时记录警告并降级
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from app.config.event_bus import Event, EventBus, EventType
from app.context.compression_audit import (
    create_compression_audit_payload,
    current_timestamp_ms,
    record_compression_audit_payload,
    record_compression_span,
)
from app.context.compression_types import CompressionActionEvent
from app.infrastructure.qdrant import QdrantClientWrapper
from app.llm.context_manager import count_tokens
from app.logger import logger
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import PromptCategory
from app.rag.hybrid_retriever import HybridRetriever, InferenceService
from app.rag.chunker import parse_long_summary_to_chunks
from app.repository.chat_history_redis import ChatHistoryRedisRepo
from app.repository.long_term_memory_pg import LongTermMemoryPGRepo
from app.repository.long_term_memory_qdrant import LongTermMemoryQdrantRepo
from app.repository.models import LongTermMemory, MemoryStatus
from app.types.constants import (
    COMPRESSION_EVENT_APPLIED,
    COMPRESSION_EVENT_COMPLETED,
    COMPRESSION_EVENT_EXECUTED,
    COMPRESSION_EVENT_FAILED,
    COMPRESSION_EVENT_INPUT_MEASURED,
    COMPRESSION_EVENT_OUTPUT_MEASURED,
    COMPRESSION_EVENT_TRIGGERED,
    COMPRESSION_STATUS_FAILED,
    COMPRESSION_STATUS_SUCCESS,
    CompressionScope,
    CompressionStage,
    CompressionTriggerReason,
)
from app.utils.snowflake import generate_string_id


class MemoryEventType(str):
    """定义记忆系统事件类型"""
    EVENT_MEMORY_SYNC = "EVT_MEMORY_SYNC"


class MemoryEvent:
    """记忆系统事件"""
    def __init__(self, type_: MemoryEventType, payload: Any):
        self.type = type_
        self.payload = payload


MemoryEventHandler = Callable[[MemoryEvent], None]


class Manager:
    """长期记忆管理器"""

    def __init__(
        self,
        redis_repo: Optional[ChatHistoryRedisRepo],
        ltm_pg_repo: Optional[LongTermMemoryPGRepo],
        ltm_qdrant_repo: Optional[LongTermMemoryQdrantRepo],
        prompt_mgr: Optional[PromptManager],
        qdrant_client: Optional[QdrantClientWrapper],
        inference_svc: Optional[InferenceService],
        retrieval_top_k: int,
        rerank_top_k: int = 3,
    ):
        self.redis_repo = redis_repo
        self.ltm_pg_repo = ltm_pg_repo
        self.ltm_qdrant_repo = ltm_qdrant_repo
        self.prompt_mgr = prompt_mgr
        self.qdrant_client = qdrant_client
        self.inference_svc = inference_svc
        self.retrieval_top_k = retrieval_top_k
        self.rerank_top_k = rerank_top_k if rerank_top_k > 0 else 3

        # 延迟注入的用户画像服务
        self.user_profile_service = None

        self.listeners: List[MemoryEventHandler] = []
        self._lock = asyncio.Lock()
        self.enable_sync_notify = True

        # 混合检索器（RAG 模块）：由 rag/hybrid_retriever.py 提供
        self.retriever = HybridRetriever(
            ltm_pg_repo=ltm_pg_repo,
            ltm_qdrant_repo=ltm_qdrant_repo,
            inference_svc=inference_svc,
            retrieval_top_k=self.retrieval_top_k,
            rerank_top_k=self.rerank_top_k,
        )

    async def on_event(self, handler: MemoryEventHandler) -> None:
        """注册记忆事件监听器"""
        async with self._lock:
            self.listeners.append(handler)

    async def _emit(self, event: MemoryEvent) -> None:
        """触发记忆事件"""
        async with self._lock:
            listeners_copy = list(self.listeners)

        for handler in listeners_copy:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(None, handler, event)
            except Exception as e:
                logger.error(f"执行记忆事件监听器失败: {e}")

    async def init(self) -> None:
        """
        初始化长期记忆系统
        做什么：
         1. 确保 Qdrant 集合存在
         2. 执行启动时兜底检测：清理 Redis 中的非当日历史会话
        """
        logger.info("正在初始化长期记忆系统")

        # 1. 确保 Qdrant 集合存在（默认向量维度 768，适配 BGE-base-zh-v1.5）
        if self.qdrant_client and self.ltm_qdrant_repo:
            try:
                await self.ltm_qdrant_repo.ensure_collection(768)
            except Exception as e:
                logger.warning(f"Qdrant 集合初始化失败，将使用降级模式 error={e}")

        # 2. 执行启动时兜底检测
        try:
            await self._detect_and_cleanup_historical_sessions()
        except Exception as e:
            logger.error(f"启动时兜底检测执行失败 error={e}")
            # 不阻断启动，允许降级

        logger.info("长期记忆系统初始化完成")

    async def _detect_and_cleanup_historical_sessions(self) -> None:
        """
        启动时兜底检测
        做什么：扫描 Redis 中非今日的历史会话数据，执行压缩入库后删除 Redis 数据
        为什么这样做：桌面程序可能被随时关闭，防止历史会话数据残留导致内存泄漏或重复处理
        """
        if not self.redis_repo:
            logger.warning("Redis 不可用，跳过启动时兜底检测")
            return

        today = datetime.now().strftime("%Y%m%d")
        logger.info(f"执行启动时兜底检测 today={today}")

        try:
            session_ids = await self.redis_repo.get_all_session_ids()
        except Exception as e:
            raise RuntimeError(f"获取 Redis 中所有会话 ID 失败: {e}")

        processed_count = 0
        for session_id in session_ids:
            if session_id == today:
                continue

            logger.info(f"发现非当日历史会话，准备压缩入库 session_id={session_id}")

            try:
                await self._compress_and_commit(session_id)
            except Exception as e:
                logger.error(f"历史会话压缩入库失败，保留 Redis 数据等待下次重试 session_id={session_id} error={e}")
                continue

            try:
                await self.redis_repo.delete_session(session_id)
                logger.info(f"已从 Redis 中删除历史会话数据 session_id={session_id}")
            except Exception as e:
                logger.error(f"删除 Redis 历史会话数据失败 session_id={session_id} error={e}")

            processed_count += 1

        logger.info(f"启动时兜底检测完成 processed_count={processed_count} today={today}")

    async def _compress_and_commit(self, session_id: str) -> None:
        """
        压缩历史会话并提交到双库
        做什么：
         1. 从 Redis 提取历史会话的完整上下文（summary + history）
         2. 调用 Prompt Manager 组装长期记忆压缩提示词
         3. 调用 Python LongSummarize gRPC 进行 AI 压缩
         4. 写入 PG 长期记忆记录
         5. 同步写入 Qdrant 向量
         6. 失效 BM25 索引缓存（新记忆写完后下次检索自动重建）
        """
        trace_id = generate_string_id()
        logger.info(f"开始压缩历史会话 session_id={session_id} trace_id={trace_id}")

        if not self.redis_repo:
            raise RuntimeError("Redis 仓库不可用")

        try:
            summary, history = await self.redis_repo.get_context(session_id)
        except Exception as e:
            raise RuntimeError(f"从 Redis 获取会话上下文失败 [session_id={session_id}]: {e}")

        if not history:
            logger.info(f"会话无历史记录，跳过压缩 session_id={session_id}")
            return

        context_parts = []
        for i, h in enumerate(history):
            h_user_content = h.get("userContent", "") if isinstance(h, dict) else getattr(h, "userContent", "")
            h_assistant_content = h.get("assistantContent", "") if isinstance(h, dict) else getattr(h, "assistantContent", "")
            h_thought = h.get("thought", "") if isinstance(h, dict) else getattr(h, "thought", "")
            h_emotion = h.get("emotion", "") if isinstance(h, dict) else getattr(h, "emotion", "")
            
            context_parts.append(f"[对话 {i+1}]\n")
            context_parts.append(f"用户: {h_user_content}\n")
            context_parts.append(f"Luna: {h_assistant_content}\n")
            if h_thought:
                context_parts.append(f"(内心独白: {h_thought})\n")
            if h_emotion:
                context_parts.append(f"(心情: {h_emotion})\n")
            context_parts.append("\n")
        
        messages_text = "".join(context_parts)
        
        # 触发用户画像并行提取任务
        if getattr(self, "user_profile_service", None):
            try:
                from app.types.constants import USER_PROFILE_DEFAULT_USER_ID
                self.user_profile_service.start_extract_from_messages(
                    user_id=USER_PROFILE_DEFAULT_USER_ID,
                    session_id=session_id,
                    messages_text=messages_text,
                    trace_id=trace_id,
                )
                logger.info(f"[TraceID:{trace_id}] 已异步启动画像提取任务 session_id={session_id}")
            except Exception as e:
                logger.error(f"[TraceID:{trace_id}] 启动画像提取任务失败 session_id={session_id} error={e}")

        compression_before_text = (
            f"当前核心摘要：\n{summary.core_summary}\n\n"
            f"当前关键事实：\n{summary.key_facts}\n\n"
            f"待压缩历史会话：\n{messages_text}"
        )
        compression_raw_tokens = count_tokens(compression_before_text)
        compression_started_at = time.monotonic()
        compression_trigger_timestamp_ms = current_timestamp_ms()
        compression_events: list[CompressionActionEvent] = [
            CompressionActionEvent(
                event_type=COMPRESSION_EVENT_TRIGGERED,
                timestamp_ms=compression_trigger_timestamp_ms,
                detail="历史会话压缩已触发，准备生成长期摘要",
                payload={"session_id": session_id},
            ),
            CompressionActionEvent(
                event_type=COMPRESSION_EVENT_INPUT_MEASURED,
                timestamp_ms=current_timestamp_ms(),
                detail="已测量长期摘要压缩输入 Token",
                payload={"raw_tokens": compression_raw_tokens},
            ),
        ]
        memory_id = generate_string_id()

        # 组装长期记忆压缩提示词
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        summarize_variables = {
            "CURRENT_TIME": current_time,
            "CURRENT_CORE_SUMMARY": summary.core_summary,
            "CURRENT_KEY_FACTS": summary.key_facts,
            "MESSAGES_TEXT": messages_text,
        }

        if self.prompt_mgr:
            try:
                full_summarize_prompt = await self.prompt_mgr.assemble_prompt(
                    PromptCategory.LONG_SUMMARY, summarize_variables
                )
            except Exception as e:
                logger.error(f"组装 LongSummarize Prompt 失败 error={e}")
                raise RuntimeError(f"组装 LongSummarize Prompt 失败: {e}")
        else:
            raise RuntimeError("Prompt 管理器不可用，无法组装提示词")

        try:
            from app.api.internal_service import internal_service
            compressed_summary = await internal_service.long_summarize(session_id, full_summarize_prompt)
        except Exception as e:
            compression_events.append(
                CompressionActionEvent(
                    event_type=COMPRESSION_EVENT_FAILED,
                    timestamp_ms=current_timestamp_ms(),
                    detail="长期摘要模型调用失败",
                    payload={"error": str(e)},
                )
            )
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                memory_id=memory_id,
                stage=CompressionStage.LONG_SUMMARY,
                scope=CompressionScope.SESSION_HISTORY,
                trigger_reason=CompressionTriggerReason.HISTORY_SESSION_ROLLOVER,
                source_keys=["CURRENT_CORE_SUMMARY", "CURRENT_KEY_FACTS", "MESSAGES_TEXT"],
                before_text=compression_before_text,
                after_text=compression_before_text,
                raw_tokens=compression_raw_tokens,
                final_tokens=compression_raw_tokens,
                is_success=False,
                failure_reason=str(e),
                events=compression_events,
                timestamp_ms=compression_trigger_timestamp_ms,
            )
            duration_ms = max(1, int((time.monotonic() - compression_started_at) * 1000))
            record_compression_audit_payload(payload, status=COMPRESSION_STATUS_FAILED)
            record_compression_span(payload, duration_ms=duration_ms, status=COMPRESSION_STATUS_FAILED)
            raise RuntimeError(f"调用 LongSummarize 失败 [session_id={session_id}]: {e}")

        compressed_summary = compressed_summary.strip()
        compressed_summary_tokens = count_tokens(compressed_summary) if compressed_summary else 0
        compression_events.extend(
            [
                CompressionActionEvent(
                    event_type=COMPRESSION_EVENT_EXECUTED,
                    timestamp_ms=current_timestamp_ms(),
                    detail="长期摘要模型执行完成",
                    payload={"after_summary_tokens": compressed_summary_tokens},
                ),
                CompressionActionEvent(
                    event_type=COMPRESSION_EVENT_OUTPUT_MEASURED,
                    timestamp_ms=current_timestamp_ms(),
                    detail="已测量长期摘要压缩输出 Token",
                    payload={"after_summary_tokens": compressed_summary_tokens},
                ),
            ]
        )
        if not compressed_summary:
            compression_events.append(
                CompressionActionEvent(
                    event_type=COMPRESSION_EVENT_FAILED,
                    timestamp_ms=current_timestamp_ms(),
                    detail="长期摘要压缩结果为空，放弃提交",
                    payload={"after_summary_tokens": compressed_summary_tokens},
                )
            )
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                memory_id=memory_id,
                stage=CompressionStage.LONG_SUMMARY,
                scope=CompressionScope.SESSION_HISTORY,
                trigger_reason=CompressionTriggerReason.HISTORY_SESSION_ROLLOVER,
                source_keys=["CURRENT_CORE_SUMMARY", "CURRENT_KEY_FACTS", "MESSAGES_TEXT"],
                before_text=compression_before_text,
                after_text=compression_before_text,
                raw_tokens=compression_raw_tokens,
                after_summary_tokens=compressed_summary_tokens,
                final_tokens=compression_raw_tokens,
                is_success=False,
                failure_reason=f"LongSummarize 返回空摘要 [session_id={session_id}]",
                events=compression_events,
                timestamp_ms=compression_trigger_timestamp_ms,
            )
            duration_ms = max(1, int((time.monotonic() - compression_started_at) * 1000))
            record_compression_audit_payload(payload, status=COMPRESSION_STATUS_FAILED)
            record_compression_span(payload, duration_ms=duration_ms, status=COMPRESSION_STATUS_FAILED)
            raise RuntimeError(f"LongSummarize 返回空摘要 [session_id={session_id}]")

        logger.info(f"历史会话压缩完成 session_id={session_id} summary_length={len(compressed_summary)}")

        # 5. 保存到 PostgreSQL
        if not self.ltm_pg_repo:
            raise RuntimeError("PostgreSQL 长期记忆仓库不可用")

        memory = LongTermMemory(
            id=memory_id,
            session_id=session_id,
            summary=compressed_summary,
            status=MemoryStatus.ACTIVE.value,
        )

        try:
            await self.ltm_pg_repo.save(memory)
            compression_events.extend(
                [
                    CompressionActionEvent(
                        event_type=COMPRESSION_EVENT_APPLIED,
                        timestamp_ms=current_timestamp_ms(),
                        detail="长期摘要已写入 PostgreSQL 长期记忆主库",
                        payload={"memory_id": memory_id},
                    ),
                    CompressionActionEvent(
                        event_type=COMPRESSION_EVENT_COMPLETED,
                        timestamp_ms=current_timestamp_ms(),
                        detail="长期摘要压缩与提交流程完成",
                        payload={"memory_id": memory_id},
                    ),
                ]
            )
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                memory_id=memory_id,
                stage=CompressionStage.LONG_SUMMARY,
                scope=CompressionScope.SESSION_HISTORY,
                trigger_reason=CompressionTriggerReason.HISTORY_SESSION_ROLLOVER,
                source_keys=["CURRENT_CORE_SUMMARY", "CURRENT_KEY_FACTS", "MESSAGES_TEXT"],
                before_text=compression_before_text,
                after_text=compressed_summary,
                raw_tokens=compression_raw_tokens,
                after_summary_tokens=compressed_summary_tokens,
                final_tokens=compressed_summary_tokens,
                is_success=True,
                events=compression_events,
                timestamp_ms=compression_trigger_timestamp_ms,
            )
            duration_ms = max(1, int((time.monotonic() - compression_started_at) * 1000))
            record_compression_audit_payload(payload, status=COMPRESSION_STATUS_SUCCESS)
            record_compression_span(payload, duration_ms=duration_ms, status=COMPRESSION_STATUS_SUCCESS)
        except Exception as e:
            compression_events.append(
                CompressionActionEvent(
                    event_type=COMPRESSION_EVENT_FAILED,
                    timestamp_ms=current_timestamp_ms(),
                    detail="长期摘要写入 PostgreSQL 失败",
                    payload={"error": str(e), "memory_id": memory_id},
                )
            )
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                memory_id=memory_id,
                stage=CompressionStage.LONG_SUMMARY,
                scope=CompressionScope.SESSION_HISTORY,
                trigger_reason=CompressionTriggerReason.HISTORY_SESSION_ROLLOVER,
                source_keys=["CURRENT_CORE_SUMMARY", "CURRENT_KEY_FACTS", "MESSAGES_TEXT"],
                before_text=compression_before_text,
                after_text=compressed_summary,
                raw_tokens=compression_raw_tokens,
                after_summary_tokens=compressed_summary_tokens,
                final_tokens=compression_raw_tokens,
                is_success=False,
                failure_reason=str(e),
                events=compression_events,
                timestamp_ms=compression_trigger_timestamp_ms,
            )
            duration_ms = max(1, int((time.monotonic() - compression_started_at) * 1000))
            record_compression_audit_payload(payload, status=COMPRESSION_STATUS_FAILED)
            record_compression_span(payload, duration_ms=duration_ms, status=COMPRESSION_STATUS_FAILED)
            raise RuntimeError(f"保存长期记忆到 PostgreSQL 失败 [session_id={session_id}]: {e}")

        # 6. 对压缩后的摘要进行向量化，写入 Qdrant 向量库
        if self.ltm_qdrant_repo:
            if not self.inference_svc:
                logger.warning(f"推理服务不可用，无法进行 Qdrant 向量写入 memory_id={memory_id}")
            else:
                try:
                    repo_class_methods = type(self.ltm_qdrant_repo).__dict__
                    if "save_chunks_with_vectors" in repo_class_methods:
                        chunks = parse_long_summary_to_chunks(compressed_summary)
                        vectors = []
                        for chunk in chunks:
                            vec = await self.inference_svc.get_embedding_vector(chunk.content)
                            if not vec:
                                raise RuntimeError(f"切片 Embedding 返回空向量 chunk_type={chunk.chunk_type.value}")
                            vectors.append(vec)
                        await self.ltm_qdrant_repo.save_chunks_with_vectors(
                            memory_id, session_id, chunks, vectors, MemoryStatus.ACTIVE.value
                        )
                        logger.info(f"[TraceID:{trace_id}] 长期记忆拆分及向量写入成功 memory_id={memory_id} chunks_count={len(chunks)}")
                    elif hasattr(self.ltm_qdrant_repo, "save_with_vector"):
                        vec = await self.inference_svc.get_embedding_vector(compressed_summary)
                        await self.ltm_qdrant_repo.save_with_vector(
                            memory_id, session_id, vec, MemoryStatus.ACTIVE.value
                        )
                        logger.info(f"[TraceID:{trace_id}] 长期记忆整摘要向量写入成功 memory_id={memory_id}")
                    else:
                        raise RuntimeError("长期记忆 Qdrant 仓库缺少可用写入方法")
                except Exception as e:
                    logger.warning(f"[TraceID:{trace_id}] Qdrant 向量写入失败 memory_id={memory_id} error={e}")

        logger.info(f"长期记忆提交完成 session_id={session_id} memory_id={memory_id}")

        # 7. 触发记忆同步事件
        if self.enable_sync_notify:
            await self._emit(MemoryEvent(
                type_=MemoryEventType.EVENT_MEMORY_SYNC,
                payload={
                    "session_id": session_id,
                    "memory_id": memory_id,
                    "status": MemoryStatus.ACTIVE.value,
                }
            ))

        # 8. 注意：PG FTS 全文检索无需缓存失效，新写入的记忆立即可检索

    async def rollover_session(self, current_session_id: str) -> str:
        """
        执行自然日会话流转
        做什么：当系统时间跨过午夜（00:00）时，将当前活跃会话切换为第二天的会话，
               并触发前一天的会话压缩入库流程。
        """
        today = datetime.now().strftime("%Y%m%d")

        if current_session_id == today:
            return current_session_id

        logger.info(f"执行自然日会话流转 old_session={current_session_id} new_session={today}")

        if current_session_id:
            try:
                await self._compress_and_commit(current_session_id)
            except Exception as e:
                logger.error(f"会话流转压缩入库失败 session_id={current_session_id} error={e}")

            if self.redis_repo:
                try:
                    await self.redis_repo.delete_session(current_session_id)
                except Exception as e:
                    logger.warning(f"删除 Redis 旧会话数据失败 session_id={current_session_id} error={e}")

        return today

    async def retrieve_long_term_memories(
        self,
        query_text: str,
        query_vector: List[float],
        search_queries: Optional[List[str]] = None,
        reference_time: Optional[str] = None,
        temporal_deviation: int = 0,
        entity_mentions: Optional[List[str]] = None,
    ) -> List[LongTermMemory]:
        """
        检索长期记忆（委托 HybridRetriever）

        做什么：将检索请求透传给 rag/ 模块的 HybridRetriever，
                执行 BM25 + 向量混合检索 + Rerank 重排全流程。
        """
        return await self.retriever.retrieve(
            query_text,
            query_vector,
            search_queries=search_queries,
            reference_time=reference_time,
            temporal_deviation=temporal_deviation,
            entity_mentions=entity_mentions,
        )

    async def retrieve_and_format_memories(
        self,
        query_text: str,
        query_vector: List[float],
        search_queries: Optional[List[str]] = None,
        reference_time: Optional[str] = None,
        temporal_deviation: int = 0,
        entity_mentions: Optional[List[str]] = None,
        disable_rerank: bool = False,
    ) -> str:
        """
        检索长期记忆并格式化为 'date: ... \\n        content: ...' 文本

        做什么：委托 rag/ 模块的 HybridRetriever 完成检索和格式化。
        参数 disable_rerank: 是否强制禁用 Rerank 重排序。闲聊模式下设为 True。
        返回：多行文本，每行格式为 'date: YYYY-MM-DD\\ncontent: <summary>'
        """
        return await self.retriever.retrieve_and_format(
            query_text,
            query_vector,
            search_queries=search_queries,
            reference_time=reference_time,
            temporal_deviation=temporal_deviation,
            entity_mentions=entity_mentions,
            disable_rerank=disable_rerank,
        )
