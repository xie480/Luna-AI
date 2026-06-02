"""
Luna AI Prompt 缓存管理器模块

做什么：实现基于 Redis 的 Prompt 懒加载缓存。
为什么这样做：
  - 首次访问时从 PostgreSQL 加载并缓存到 Redis
  - 后续访问直接读取 Redis 缓存
  - 使用 asyncio.Lock 防止缓存击穿
"""

import asyncio
import json
from typing import Dict, Optional

from pydantic import BaseModel

from app.infrastructure.redis import RedisClient
from app.logger import logger
from app.prompt.types import (
    PLACEHOLDER_MEMORY,
    PLACEHOLDER_RUNTIME,
    PLACEHOLDER_SYSTEM,
    SLOT_PLACEHOLDERS,
    PromptCategory,
    SlotPosition,
    render_template,
)
from app.repository.prompt_pg import PromptPGRepo

CACHE_KEY_PREFIX = "luna:prompt:"
CACHE_TTL = 3600  # 缓存过期时间（1小时）
CACHE_EMPTY_TTL = 60  # 空结果缓存过期时间（1分钟，防止缓存穿透）


class CachedPrompt(BaseModel):
    """缓存中的 Prompt 模板结构"""
    system_content: str = ""
    memory_content: str = ""
    runtime_content: str = ""


from app.utils.singleflight import SingleFlight

class CacheManager:
    """实现基于 Redis 的 Prompt 懒加载缓存"""

    def __init__(self, redis_client: Optional[RedisClient], pg_repo: PromptPGRepo):
        self.redis_client = redis_client
        self.pg_repo = pg_repo
        self._singleflight = SingleFlight()

    def _cache_key(self, category: PromptCategory) -> str:
        return f"{CACHE_KEY_PREFIX}{category.value}"

    async def get_or_load(self, category: PromptCategory) -> CachedPrompt:
        """从缓存获取，缓存未命中时从数据库加载"""
        cache_key = self._cache_key(category)

        # 1. 尝试从 Redis 读取
        if self.redis_client:
            try:
                client = self.redis_client.get_client()
                cached = await client.get(cache_key)
                if cached:
                    cp = CachedPrompt.model_validate_json(cached)
                    logger.info(f"从 Redis 缓存获取 Prompt 成功 category={category.value}")
                    return cp
            except Exception as e:
                logger.warning(f"Redis 读取 Prompt 缓存失败 category={category.value} error={e}")

        # 2. 使用 SingleFlight 防止缓存击穿
        async def _load_and_cache():
            # 从数据库加载
            cp = await self._load_from_db(category)

            # 3. 写入 Redis 缓存（异步写入，不阻塞主流程）
            if self.redis_client:
                asyncio.create_task(self._save_to_cache(cache_key, category, cp))

            return cp

        return await self._singleflight.do(cache_key, _load_and_cache)

    async def _load_from_db(self, category: PromptCategory) -> CachedPrompt:
        """从 PostgreSQL 加载指定分类的模板，按 SlotPosition 分类提取内容"""
        try:
            templates = await self.pg_repo.get_templates_by_category(category.value)
        except Exception as e:
            raise RuntimeError(f"加载分类 {category.value} 的模板失败: {e}")

        cp = CachedPrompt()

        for tmpl in templates:
            if not tmpl.active_version_id:
                continue

            try:
                version = await self.pg_repo.get_version(tmpl.active_version_id)
                if not version:
                    continue
            except Exception as e:
                logger.warning(f"获取模板版本失败，跳过 template_name={tmpl.name} error={e}")
                continue

            if tmpl.slot_position == SlotPosition.SYSTEM.value:
                cp.system_content = version.content
            elif tmpl.slot_position == SlotPosition.MEMORY.value:
                cp.memory_content = version.content
            elif tmpl.slot_position == SlotPosition.RUNTIME.value:
                cp.runtime_content = version.content
            else:
                logger.warning(f"未知的 SlotPosition 值 slot_position={tmpl.slot_position}")

        logger.info(
            f"从数据库加载 Prompt 模板成功 category={category.value} "
            f"has_system={bool(cp.system_content)} "
            f"has_memory={bool(cp.memory_content)} "
            f"has_runtime={bool(cp.runtime_content)}"
        )

        return cp

    async def _save_to_cache(self, cache_key: str, category: PromptCategory, cp: CachedPrompt) -> None:
        """异步保存到 Redis"""
        try:
            client = self.redis_client.get_client()
            data = cp.model_dump_json()
            
            ttl = CACHE_TTL
            if not cp.system_content and not cp.memory_content and not cp.runtime_content:
                ttl = CACHE_EMPTY_TTL
                
            await client.set(cache_key, data, ex=ttl)
        except Exception as e:
            logger.warning(f"写入 Prompt 缓存到 Redis 失败 category={category.value} error={e}")

    async def invalidate_cache(self, category: PromptCategory) -> None:
        """使指定分类的缓存失效"""
        if self.redis_client:
            try:
                client = self.redis_client.get_client()
                await client.delete(self._cache_key(category))
                logger.info(f"已清除 Prompt 缓存 category={category.value}")
            except Exception as e:
                raise RuntimeError(f"清除 Prompt 缓存失败: {e}")

    async def get_assembled_prompt(self, category: PromptCategory, variables: Dict[str, str]) -> str:
        """
        获取并组装完整的 Prompt 字符串
        使用固定占位符模板 {system}\n\n{memory}\n\n{runtime}
        将各 slot 的模板内容注入到对应的占位符位置
        最终将未被注入的占位符替换为空字符串
        """
        cp = await self.get_or_load(category)

        # 准备固定占位符模板
        full_text = f"{PLACEHOLDER_SYSTEM}\n\n{PLACEHOLDER_MEMORY}\n\n{PLACEHOLDER_RUNTIME}"

        # 按照标准顺序注入模板内容
        slot_contents = {
            PLACEHOLDER_SYSTEM: cp.system_content,
            PLACEHOLDER_MEMORY: cp.memory_content,
            PLACEHOLDER_RUNTIME: cp.runtime_content,
        }

        result = full_text
        for placeholder in SLOT_PLACEHOLDERS:
            content = slot_contents.get(placeholder, "")
            if content:
                # 对模板内容进行变量替换
                rendered = render_template(content, variables)
                result = result.replace(placeholder, rendered)

        return result
