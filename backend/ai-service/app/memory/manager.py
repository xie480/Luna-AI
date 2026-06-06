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
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from app.config.event_bus import Event, EventBus, EventType
from app.infrastructure.qdrant import QdrantClientWrapper
from app.logger import logger
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import PromptCategory
from app.rag.hybrid_retriever import HybridRetriever, InferenceService
from app.repository.chat_history_redis import ChatHistoryRedisRepo
from app.repository.long_term_memory_pg import LongTermMemoryPGRepo
from app.repository.long_term_memory_qdrant import LongTermMemoryQdrantRepo
from app.repository.models import LongTermMemory, MemoryStatus
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
            context_parts.append(f"[对话 {i+1}]\n")
            context_parts.append(f"用户: {h.userContent}\n")
            context_parts.append(f"Luna: {h.assistantContent}\n")
            if h.thought:
                context_parts.append(f"(内心独白: {h.thought})\n")
            if h.emotion:
                context_parts.append(f"(心情: {h.emotion})\n")
            context_parts.append("\n")
        
        messages_text = "".join(context_parts)

        # 组装长期记忆压缩提示词
        summarize_variables = {
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
            raise RuntimeError(f"调用 LongSummarize 失败 [session_id={session_id}]: {e}")

        compressed_summary = compressed_summary.strip()
        if not compressed_summary:
            raise RuntimeError(f"LongSummarize 返回空摘要 [session_id={session_id}]")

        logger.info(f"历史会话压缩完成 session_id={session_id} summary_length={len(compressed_summary)}")

        memory_id = generate_string_id()

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
        except Exception as e:
            raise RuntimeError(f"保存长期记忆到 PostgreSQL 失败 [session_id={session_id}]: {e}")

        # 6. 对压缩后的摘要进行向量化，写入 Qdrant 向量库
        if self.ltm_qdrant_repo:
            embedding_vec = None
            embed_err = None
            
            if self.inference_svc:
                try:
                    embedding_vec = await self.inference_svc.get_embedding_vector(compressed_summary)
                except Exception as e:
                    embed_err = e
            else:
                embed_err = RuntimeError("推理服务不可用")

            if embed_err or not embedding_vec:
                logger.warning(f"获取语义向量失败，使用零值向量写入 Qdrant（后续可对账补充） memory_id={memory_id} error={embed_err}")
                embedding_vec = [0.0] * 768

            try:
                await self.ltm_qdrant_repo.save_with_vector(
                    memory_id, session_id, embedding_vec, MemoryStatus.ACTIVE.value
                )
                logger.info(f"长期记忆向量写入成功 memory_id={memory_id} vector_dim={len(embedding_vec)}")
            except Exception as e:
                logger.warning(f"Qdrant 向量写入失败 memory_id={memory_id} error={e}")

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
            entity_mentions=entity_mentions,
        )

    async def retrieve_and_format_memories(
        self,
        query_text: str,
        query_vector: List[float],
        search_queries: Optional[List[str]] = None,
        reference_time: Optional[str] = None,
        entity_mentions: Optional[List[str]] = None,
    ) -> str:
        """
        检索长期记忆并格式化为 'date: ... \\n        content: ...' 文本

        做什么：委托 rag/ 模块的 HybridRetriever 完成检索和格式化。
        返回：多行文本，每行格式为 'date: YYYY-MM-DD\\ncontent: <summary>'
        """
        return await self.retriever.retrieve_and_format(
            query_text,
            query_vector,
            search_queries=search_queries,
            reference_time=reference_time,
            entity_mentions=entity_mentions,
        )
