"""
Luna AI 长期记忆管理器模块

做什么：协调长期记忆的完整生命周期：会话流转检测、历史压缩、双库提交、记忆检索。
为什么这样做：作为唯一调度权威，所有记忆写入必须经过此管理器的事务控制。
输入输出：
    - Manager: 长期记忆管理器类
边界条件：
    - 启动时兜底检测：清理 Redis 中的非当日历史会话
    - 压缩历史会话并提交到双库
    - 执行自然日会话流转
    - 检索长期记忆（带语义检索与重排）
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


class AIClient(Protocol):
    """定义 AI 客户端接口，用于与 Python AI 服务通信"""
    async def long_summarize(self, session_id: str, summarize_prompt: str) -> str:
        ...


class InferenceService(Protocol):
    """推理服务接口（用于 Embedding 和 Rerank）"""
    async def get_embedding_vector(self, text: str) -> List[float]:
        ...

    async def rerank_documents(self, query: str, documents: List[str]) -> List[Dict[str, Any]]:
        """返回包含 'index' 和 'score' 的字典列表"""
        ...


class Manager:
    """长期记忆管理器"""

    def __init__(
        self,
        redis_repo: Optional[ChatHistoryRedisRepo],
        ltm_pg_repo: Optional[LongTermMemoryPGRepo],
        ltm_qdrant_repo: Optional[LongTermMemoryQdrantRepo],
        ai_client: Optional[AIClient],
        prompt_mgr: Optional[PromptManager],
        qdrant_client: Optional[QdrantClientWrapper],
        inference_svc: Optional[InferenceService],
        retrieval_top_k: int,
    ):
        self.redis_repo = redis_repo
        self.ltm_pg_repo = ltm_pg_repo
        self.ltm_qdrant_repo = ltm_qdrant_repo
        self.ai_client = ai_client
        self.prompt_mgr = prompt_mgr
        self.qdrant_client = qdrant_client
        self.inference_svc = inference_svc
        self.retrieval_top_k = retrieval_top_k
        
        self.listeners: List[MemoryEventHandler] = []
        self._lock = asyncio.Lock()
        self.enable_sync_notify = True

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

        if not self.ai_client:
            raise RuntimeError(f"AI 客户端不可用，无法压缩历史会话 [session_id={session_id}]")

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
            compressed_summary = await self.ai_client.long_summarize(session_id, full_summarize_prompt)
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

    async def retrieve_long_term_memories(self, query_text: str, query_vector: List[float]) -> List[LongTermMemory]:
        """
        检索长期记忆（带语义检索与重排）
        做什么：根据用户意图查询文本，先通过 Embedding 转为向量进行 Qdrant 粗排检索，
                再通过 CrossEncoder 精排提升 Top-K 结果的排序质量
        """
        if not self.ltm_qdrant_repo or not self.ltm_pg_repo:
            logger.warning("长期记忆系统不可用，跳过记忆检索")
            return []

        top_k = self.retrieval_top_k
        if top_k <= 0:
            top_k = 5

        # 如果提供了 query_text，先通过 Embdedding 转为查询向量（覆盖外部传入的 query_vector）
        final_query_vector = query_vector
        if query_text and self.inference_svc:
            try:
                embedding_vec = await self.inference_svc.get_embedding_vector(query_text)
                final_query_vector = embedding_vec
            except Exception as e:
                logger.warning(f"获取查询向量的 Embedding 失败，使用外部传入向量（如有） error={e}")

        # 如果仍然没有向量，无法进行语义检索，返回空
        if not final_query_vector:
            logger.warning("查询向量为空，跳过语义检索")
            return []

        # Qdrant 粗排：检索 Top-K 的 3 倍候选数，为后续重排提供足够候选
        search_top_k = top_k * 3
        if search_top_k > 50:
            search_top_k = 50  # 限制最大候选数，防止性能问题

        try:
            results = await self.ltm_qdrant_repo.search_by_vector(final_query_vector, search_top_k)
        except Exception as e:
            logger.warning(f"Qdrant 向量检索失败，降级为空返回 error={e}")
            return []

        if not results:
            logger.info(f"Qdrant 无匹配结果 top_k={top_k}")
            return []

        memory_ids = []
        for result in results:
            mem_id = result.payload.get("memory_id")
            if mem_id:
                memory_ids.append(str(mem_id))
            else:
                # 兼容旧数据
                memory_ids.append(str(result.id))

        try:
            memories = await self.ltm_pg_repo.get_by_ids(memory_ids)
        except Exception as e:
            logger.warning(f"从 PG 拉取记忆记录失败，降级为空返回 error={e}")
            return []

        if not memories:
            return []

        # Rerank 精排：如果提供了 query_text，且推理服务支持 Rerank，对结果进行重排
        if query_text and self.inference_svc and len(memories) > 1:
            # 提取候选文档列表（使用记忆的 Summary 作为文档内容）
            documents = [mem.summary for mem in memories]

            try:
                rerank_results = await self.inference_svc.rerank_documents(query_text, documents)
                
                # 根据重排结果重新排序 memories
                reranked_memories = []
                limit = min(top_k, len(rerank_results))
                for i in range(limit):
                    idx = rerank_results[i].get("index", 0)
                    if 0 <= idx < len(memories):
                        reranked_memories.append(memories[idx])
                memories = reranked_memories
            except Exception as e:
                # Rerank 失败时降级为粗排结果，截取 top_k
                logger.warning(f"Rerank 重排失败，使用 Qdrant 粗排结果 error={e}")
                if len(memories) > top_k:
                    memories = memories[:top_k]
        elif len(memories) > top_k:
            # 没有 Rerank 时，截取前 top_k 个
            memories = memories[:top_k]

        has_rerank = bool(query_text and self.inference_svc)
        logger.info(f"长期记忆检索完成 hits={len(memories)} top_k={top_k} has_rerank={has_rerank}")
        return memories
