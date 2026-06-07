"""
Luna 用户画像 Redis 缓存模块。

做什么：封装用户画像压缩摘要、缓存状态、脏标记、任务状态和锁的 Redis 读写。
为什么这样做：聊天链路只能读取 Redis 压缩画像，不能每轮扫描 PostgreSQL。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.infrastructure.redis import RedisClient
from app.logger import logger
from app.types.constants import USER_PROFILE_DEFAULT_USER_ID, UserProfileCacheStatus
from app.user_profile.schemas import UserProfileCacheStatusResponse

TASK_TTL_SECONDS = 86400
LOCK_TTL_SECONDS = 120
CACHE_VERSION = "v1"


class UserProfileCache:
    """
    用户画像 Redis 缓存。

    做什么：读写压缩画像 summary、summary_meta、dirty、lock 和 task key。
    为什么这样做：缓存 key 规则集中在一个类中，避免各模块硬编码 Redis key。
    输入输出：输入 user_id/task_id/status 等业务值，输出文本或状态 DTO。
    边界条件：Redis 不可用时调用方不创建本类；dirty 存在时 summary 不视为可用。
    异常行为：Redis 异常向上抛出，由服务层记录并决定是否降级。
    """

    def __init__(self, redis_client: RedisClient):
        self.redis_client = redis_client

    def summary_key(self, user_id: str = USER_PROFILE_DEFAULT_USER_ID) -> str:
        """构造用户画像摘要 key。"""
        return f"luna:user_profile:{user_id}:summary:{CACHE_VERSION}"

    def summary_meta_key(self, user_id: str = USER_PROFILE_DEFAULT_USER_ID) -> str:
        """构造用户画像摘要元信息 key。"""
        return f"luna:user_profile:{user_id}:summary_meta:{CACHE_VERSION}"

    def dirty_key(self, user_id: str = USER_PROFILE_DEFAULT_USER_ID) -> str:
        """构造用户画像脏标记 key。"""
        return f"luna:user_profile:{user_id}:dirty:{CACHE_VERSION}"

    def lock_key(self, user_id: str = USER_PROFILE_DEFAULT_USER_ID) -> str:
        """构造用户画像任务锁 key。"""
        return f"luna:user_profile:{user_id}:lock:{CACHE_VERSION}"

    def task_key(self, user_id: str, task_id: str) -> str:
        """构造用户画像任务状态 key。"""
        return f"luna:user_profile:{user_id}:task:{task_id}:{CACHE_VERSION}"

    async def get_summary(self, user_id: str = USER_PROFILE_DEFAULT_USER_ID) -> str:
        """读取可用于聊天注入的压缩画像；dirty 存在时返回空字符串。"""
        client = self.redis_client.get_client()
        dirty = await client.get(self.dirty_key(user_id))
        if dirty:
            return ""
        summary = await client.get(self.summary_key(user_id))
        return str(summary or "")

    async def invalidate(self, user_id: str, reason: str) -> None:
        """删除摘要并写入 dirty 标记。"""
        client = self.redis_client.get_client()
        async with client.pipeline() as pipe:
            pipe.delete(self.summary_key(user_id))
            pipe.set(self.dirty_key(user_id), reason)
            pipe.hset(self.summary_meta_key(user_id), mapping={
                "status": UserProfileCacheStatus.DIRTY.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "last_error": "",
            })
            await pipe.execute()
        logger.info(f"用户画像缓存已失效 user_id={user_id} reason={reason}")

    async def save_summary(self, user_id: str, summary: str, source_item_count: int) -> None:
        """保存压缩画像并清理 dirty 标记。"""
        client = self.redis_client.get_client()
        now = datetime.now(timezone.utc).isoformat()
        async with client.pipeline() as pipe:
            pipe.set(self.summary_key(user_id), summary)
            pipe.delete(self.dirty_key(user_id))
            pipe.hset(self.summary_meta_key(user_id), mapping={
                "status": UserProfileCacheStatus.VALID.value,
                "version": CACHE_VERSION,
                "updated_at": now,
                "source_item_count": str(source_item_count),
                "summary_length": str(len(summary)),
                "last_error": "",
            })
            await pipe.execute()
        logger.info(f"用户画像压缩缓存已写入 user_id={user_id} source_item_count={source_item_count} summary_length={len(summary)}")

    async def mark_rebuilding(self, user_id: str, task_id: str) -> None:
        """标记缓存正在重建。"""
        client = self.redis_client.get_client()
        await client.hset(self.summary_meta_key(user_id), mapping={
            "status": UserProfileCacheStatus.REBUILDING.value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "last_error": "",
        })

    async def mark_failed(self, user_id: str, error: str) -> None:
        """标记缓存重建失败。"""
        client = self.redis_client.get_client()
        await client.hset(self.summary_meta_key(user_id), mapping={
            "status": UserProfileCacheStatus.FAILED.value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_error": error[:500],
        })

    async def get_status(self, user_id: str = USER_PROFILE_DEFAULT_USER_ID) -> UserProfileCacheStatusResponse:
        """获取用户画像缓存状态。"""
        client = self.redis_client.get_client()
        meta = await client.hgetall(self.summary_meta_key(user_id)) or {}
        dirty = await client.get(self.dirty_key(user_id))
        summary = await client.get(self.summary_key(user_id))
        if dirty:
            status = UserProfileCacheStatus.DIRTY
        elif meta.get("status"):
            status = UserProfileCacheStatus(meta.get("status"))
        elif summary:
            status = UserProfileCacheStatus.VALID
        else:
            status = UserProfileCacheStatus.MISSING
        return UserProfileCacheStatusResponse(
            status=status,
            updated_at=meta.get("updated_at"),
            source_item_count=int(meta.get("source_item_count") or 0),
            summary_length=int(meta.get("summary_length") or len(summary or "")),
            last_error=meta.get("last_error") or "",
        )

    async def acquire_lock(self, user_id: str, owner: str) -> bool:
        """获取用户画像任务锁。"""
        client = self.redis_client.get_client()
        result = await client.set(self.lock_key(user_id), owner, nx=True, ex=LOCK_TTL_SECONDS)
        return bool(result)

    async def release_lock(self, user_id: str, owner: str) -> None:
        """释放属于当前 owner 的用户画像任务锁。"""
        client = self.redis_client.get_client()
        key = self.lock_key(user_id)
        current = await client.get(key)
        if current == owner:
            await client.delete(key)

    async def save_task_status(self, user_id: str, task_id: str, status: UserProfileCacheStatus, payload: dict[str, Any] | None = None) -> None:
        """保存后台任务状态。"""
        client = self.redis_client.get_client()
        mapping = {
            "status": status.value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if payload:
            mapping.update({key: str(value) for key, value in payload.items()})
        await client.hset(self.task_key(user_id, task_id), mapping=mapping)
        await client.expire(self.task_key(user_id, task_id), TASK_TTL_SECONDS)
