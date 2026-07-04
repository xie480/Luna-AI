import json
import logging
from typing import Optional, Dict, Any

from app.infrastructure.redis import RedisClient

logger = logging.getLogger(__name__)

class LongAnswerSummaryCache:
    """
    长回答小总结 Redis 缓存服务
    
    做什么：在长回答生成结束后，将小总结存入 Redis 中，供上下文压缩时读取。
    为什么这样做：长期记忆和长回答正文不进入日常对话的短期上下文，但压缩任务时
                模型需要知道之前的多轮中“Luna 发过什么样的报告”，小总结作为轻量级
                的代理，被合并到压缩上下文中。
    """
    _redis_client: Optional[RedisClient] = None

    @classmethod
    def set_client(cls, client: RedisClient):
        """设置全局 RedisClient"""
        cls._redis_client = client

    """
    长回答小总结 Redis 缓存服务
    
    做什么：在长回答生成结束后，将小总结存入 Redis 中，供上下文压缩时读取。
    为什么这样做：长期记忆和长回答正文不进入日常对话的短期上下文，但压缩任务时
                模型需要知道之前的多轮中“Luna 发过什么样的报告”，小总结作为轻量级
                的代理，被合并到压缩上下文中。
    """
    
    @staticmethod
    def _build_key(session_id: str, message_id: str) -> str:
        return f"luna:long_answer:{session_id}:{message_id}:summary"
        
    @staticmethod
    def _build_index_key(session_id: str) -> str:
        return f"luna:long_answer:{session_id}:summary_index"

    @classmethod
    async def set_summary(
        cls,
        session_id: str,
        message_id: str,
        long_answer_id: str,
        summary: str,
        title: str = "",
        status: str = "COMPLETED"
    ) -> bool:
        """
        保存长回答的小总结到 Redis，并添加到会话索引。
        """
        key = cls._build_key(session_id, message_id)
        index_key = cls._build_index_key(session_id)
        
        if not cls._redis_client:
            logger.warning("RedisClient not set, skip caching long answer summary.")
            return False

        try:
            mapping = {
                "long_answer_id": long_answer_id,
                "interaction_message_id": message_id,
                "session_id": session_id,
                "summary": summary,
                "title": title,
                "status": status,
            }
            
            # 使用 pipelined 保证原子性
            async with cls._redis_client.client.pipeline() as pipe:
                pipe.hset(key, mapping=mapping)
                # TTL 暂时不设，等待压缩系统或清理任务统一清理
                pipe.rpush(index_key, message_id)
                await pipe.execute()
                
            return True
        except Exception as e:
            logger.error(f"Failed to save long answer summary to redis: session_id={session_id}, msg_id={message_id}, error={e}")
            return False

    @classmethod
    async def get_summary(cls, session_id: str, message_id: str) -> Optional[Dict[str, str]]:
        """
        获取指定消息的长回答小总结。
        """
        if not cls._redis_client:
            return None

        key = cls._build_key(session_id, message_id)
        try:
            data = await cls._redis_client.client.hgetall(key)
            if not data:
                return None
            
            # decode values
            decoded = {k.decode("utf-8") if isinstance(k, bytes) else k: 
                       v.decode("utf-8") if isinstance(v, bytes) else v 
                       for k, v in data.items()}
            return decoded
        except Exception as e:
            logger.error(f"Failed to get long answer summary from redis: session_id={session_id}, msg_id={message_id}, error={e}")
            return None

    @classmethod
    async def remove_summary(cls, session_id: str, message_id: str) -> bool:
        """
        删除指定的长回答小总结缓存。
        通常在完成压缩或者会话清理时调用。
        """
        key = cls._build_key(session_id, message_id)
        index_key = cls._build_index_key(session_id)
        
        if not cls._redis_client:
            return False

        try:
            async with cls._redis_client.client.pipeline() as pipe:
                pipe.delete(key)
                pipe.lrem(index_key, 0, message_id)
                await pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Failed to remove long answer summary from redis: session_id={session_id}, msg_id={message_id}, error={e}")
            return False
