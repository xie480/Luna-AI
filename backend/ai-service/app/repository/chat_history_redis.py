"""
Luna AI Redis 聊天历史记录存储库

做什么：封装 Redis 短期记忆与摘要读写。
为什么这样做：用于 DAG 工作流毫秒级状态同步与 Event Bus。
输入输出：
    - ChatHistoryRedisRepo: 聊天历史记录存储库类
边界条件：
    - 序列化和反序列化 JSON
    - 使用 Pipeline 保证原子性
异常行为：
    - Redis 操作失败时抛出异常
"""

import json
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel

from app.infrastructure.redis import RedisClient

MEM_WORKING_WINDOW_SIZE = 50  # 触发压缩的阈值（以 Interaction 为单位）
MEM_COMPRESS_BATCH_SIZE = 20  # 每次压缩的 Interaction 数量


class Interaction(BaseModel):
    """
    表示单次问答记录（Redis 缓存层）
    将用户的一问与系统的一答严格绑定为一个完整的存储单元。
    如果在交互中系统未正常生成回复，Error 字段非空，AssistantContent 存储标准报错 JSON。
    """
    msgId: str
    userContent: str
    assistantContent: str
    thought: str = ""
    emotion: str = ""
    error: str = ""
    timestamp: int


class ChatSummary(BaseModel):
    """
    表示聊天摘要
    仅包含 core_summary 和 key_facts 两个核心字段，移除冗余的 short_term_memory
    """
    core_summary: str = ""
    key_facts: str = ""


class ChatHistoryRedisRepo:
    """封装 Redis 短期记忆与摘要读写"""

    def __init__(self, redis_client: RedisClient):
        self.redis_client = redis_client

    def _build_history_key(self, session_id: str) -> str:
        return f"luna:mem:chat:{session_id}:history"

    def _build_summary_key(self, session_id: str) -> str:
        return f"luna:mem:chat:{session_id}:summary"

    async def save_interaction(self, session_id: str, interaction: Interaction) -> int:
        """
        追加问答交互记录（一问一答绑定为完整单元）并返回当前长度
        """
        key = self._build_history_key(session_id)
        # exclude_defaults=False 确保空字符串也被序列化，与 Go 保持一致
        data = interaction.model_dump_json(exclude_none=True)
        
        client = self.redis_client.get_client()
        length = await client.rpush(key, data)
        return length

    async def get_context(self, session_id: str) -> Tuple[ChatSummary, List[Interaction]]:
        """
        获取当前上下文 (摘要 + 历史 Interaction 列表)
        """
        history_key = self._build_history_key(session_id)
        summary_key = self._build_summary_key(session_id)

        client = self.redis_client.get_client()
        
        # 使用 Pipeline 同时获取摘要和历史
        async with client.pipeline() as pipe:
            pipe.hgetall(summary_key)
            pipe.lrange(history_key, 0, -1)
            results = await pipe.execute()
            
        summary_map = results[0] or {}
        history_strs = results[1] or []
        
        summary = ChatSummary(
            core_summary=summary_map.get("core_summary", ""),
            key_facts=summary_map.get("key_facts", "")
        )
        
        history = []
        for s in history_strs:
            try:
                history.append(Interaction.model_validate_json(s))
            except Exception as exc:
                from app.logger import logger

                logger.warning(f"Redis 会话记录解析失败，已跳过损坏记录 session_id={session_id} error={exc}")
                continue

        return summary, history

    async def get_all_session_ids(self) -> List[str]:
        """
        获取 Redis 中所有会话的 ID 列表
        做什么：扫描 Redis 中所有 luna:mem:chat:*:history 和 summary 模式的 key，提取会话 ID
        为什么这样做：启动时兜底检测需要找出所有历史会话，有些会话可能只有 history 没有 summary
        """
        client = self.redis_client.get_client()
        session_ids = set()
        
        # 使用 SCAN 迭代器扫描 history
        async for key in client.scan_iter(match="luna:mem:chat:*:history"):
            session_id = self._extract_session_id_from_key(key)
            if session_id:
                session_ids.add(session_id)
                
        # 使用 SCAN 迭代器扫描 summary
        async for key in client.scan_iter(match="luna:mem:chat:*:summary"):
            session_id = self._extract_session_id_from_key(key)
            if session_id:
                session_ids.add(session_id)
                
        return list(session_ids)

    def _extract_session_id_from_key(self, key: str) -> str:
        """
        从 Redis key 中提取会话 ID
        输入：key 格式 "luna:mem:chat:{sessionID}:summary"
        输出：sessionID 字符串
        """
        parts = key.split(":")
        if len(parts) >= 5:
            return parts[3]
        return ""

    async def delete_session(self, session_id: str) -> None:
        """
        删除指定会话的所有 Redis 数据（history 和 summary）
        做什么：从 Redis 中物理删除历史会话的 history 列表和 summary 哈希
        为什么这样做：历史会话压缩入库后必须清理 Redis 中的原始数据
        """
        history_key = self._build_history_key(session_id)
        summary_key = self._build_summary_key(session_id)

        client = self.redis_client.get_client()
        async with client.pipeline() as pipe:
            pipe.delete(history_key)
            pipe.delete(summary_key)
            await pipe.execute()

    async def update_summary_and_trim(self, session_id: str, summary: ChatSummary, trim_count: int) -> None:
        """
        更新摘要并移除已压缩的旧 Interaction 记录
        做什么：使用 Redis Pipeline 原子化地更新摘要字段并裁剪历史记录
        为什么这样做：确保摘要更新和历史裁剪在同一事务中完成，防止数据不一致
        """
        history_key = self._build_history_key(session_id)
        summary_key = self._build_summary_key(session_id)

        client = self.redis_client.get_client()
        async with client.pipeline() as pipe:
            # 1. 仅更新 core_summary 和 key_facts 两个核心字段
            mapping = {
                "core_summary": summary.core_summary,
                "key_facts": summary.key_facts
            }
            pipe.hset(summary_key, mapping=mapping)
            
            # 2. 裁剪历史记录：保留从 trim_count 开始到末尾的元素
            pipe.ltrim(history_key, trim_count, -1)
            
            await pipe.execute()
