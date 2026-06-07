"""
Luna 用户画像服务层。

做什么：编排用户画像 CRUD、缓存失效、压缩摘要重建和会话压缩触发的异步提取任务。
为什么这样做：Python 后端是用户画像提取、冲突处理和 Prompt 注入的唯一控制面。
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from app.logger import logger
from app.repository.models import UserProfileItem
from app.repository.user_profile_pg import UserProfilePGRepository
from app.types.constants import USER_PROFILE_DEFAULT_USER_ID, UserProfileCacheStatus, UserProfileCategory
from app.user_profile.cache import UserProfileCache
from app.user_profile.conflict_resolver import normalize_profile_content
from app.user_profile.extractor import UserProfileExtractor
from app.user_profile.schemas import (
    ProfileMutationPlan,
    UserProfileCacheRebuildResponse,
    UserProfileCacheStatusResponse,
    UserProfileExtractionTaskResponse,
    UserProfileItemDTO,
    UserProfileListResponse,
    UserProfileMutationRequest,
    category_label,
    datetime_to_text,
)
from app.user_profile.summarizer import UserProfileSummarizer
from app.utils.snowflake import generate_string_id


class UserProfileService:
    """用户画像服务。"""

    def __init__(
        self,
        repo: UserProfilePGRepository,
        cache: UserProfileCache | None,
        extractor: UserProfileExtractor,
        summarizer: UserProfileSummarizer,
    ):
        self.repo = repo
        self.cache = cache
        self.extractor = extractor
        self.summarizer = summarizer
        self._tracked_tasks: set[asyncio.Task[Any]] = set()

    async def list_items(
        self,
        *,
        user_id: str = USER_PROFILE_DEFAULT_USER_ID,
        category: str | None = None,
        include_inactive: bool = False,
    ) -> UserProfileListResponse:
        """获取用户画像列表并按类别分组。"""
        items = await self.repo.list_items(user_id=user_id, category=category, include_inactive=include_inactive)
        dtos = [self.to_dto(item) for item in items]
        grouped: dict[str, list[UserProfileItemDTO]] = defaultdict(list)
        for dto in dtos:
            grouped[dto.category.value].append(dto)
        cache_status = await self._cache_status_value(user_id)
        return UserProfileListResponse(
            items=dtos,
            grouped=dict(grouped),
            total=len(dtos),
            cache_status=cache_status,
        )

    async def list_by_category(self, *, user_id: str, category: UserProfileCategory) -> UserProfileListResponse:
        """按类别获取用户画像。"""
        return await self.list_items(user_id=user_id, category=category.value, include_inactive=False)

    async def create_manual(
        self,
        *,
        user_id: str,
        request: UserProfileMutationRequest,
        trace_id: str,
        idempotency_key: str | None,
    ) -> UserProfileItemDTO:
        """手动新增用户画像。"""
        existing = await self.repo.list_active_by_user(user_id)
        normalized = normalize_profile_content(request.content)
        for item in existing:
            if item.category == request.category.value and item.normalized_content == normalized:
                if self.cache:
                    await self.cache.invalidate(user_id, trace_id)
                return self.to_dto(item)
        item = await self.repo.create_manual(
            user_id=user_id,
            category=request.category,
            custom_category_name=request.custom_category_name,
            content=request.content,
            normalized_content=normalized,
            trace_id=trace_id,
            idempotency_key=idempotency_key or request.idempotency_key,
        )
        if self.cache:
            await self.cache.invalidate(user_id, trace_id)
        return self.to_dto(item)

    async def update_manual(
        self,
        *,
        user_id: str,
        item_id: str,
        request: UserProfileMutationRequest,
        trace_id: str,
    ) -> UserProfileItemDTO | None:
        """手动编辑用户画像。"""
        item = await self.repo.update_manual(
            user_id=user_id,
            item_id=item_id,
            category=request.category,
            custom_category_name=request.custom_category_name,
            content=request.content,
            normalized_content=normalize_profile_content(request.content),
            trace_id=trace_id,
        )
        if item and self.cache:
            await self.cache.invalidate(user_id, trace_id)
        return self.to_dto(item) if item else None

    async def delete_manual(self, *, user_id: str, item_id: str, trace_id: str) -> dict[str, Any] | None:
        """手动软删除用户画像。"""
        item, already_deleted = await self.repo.soft_delete(user_id, item_id, trace_id)
        if item and self.cache:
            await self.cache.invalidate(user_id, trace_id)
        if not item:
            return None
        return {"id": item.id, "already_deleted": already_deleted}

    async def get_cache_status(
        self,
        user_id: str = USER_PROFILE_DEFAULT_USER_ID,
    ) -> UserProfileCacheStatusResponse:
        """查询用户画像压缩缓存状态。"""
        if not self.cache:
            return UserProfileCacheStatusResponse(status=UserProfileCacheStatus.MISSING)
        return await self.cache.get_status(user_id)

    async def get_prompt_summary(self, user_id: str = USER_PROFILE_DEFAULT_USER_ID) -> str:
        """读取聊天 Prompt 可注入的用户画像摘要。"""
        if not self.cache:
            return ""
        summary = await self.cache.get_summary(user_id)
        if not summary:
            self.start_rebuild_summary(user_id=user_id, trace_id=generate_string_id())
        return summary

    def start_rebuild_summary(self, *, user_id: str, trace_id: str) -> UserProfileCacheRebuildResponse:
        """启动用户画像摘要缓存重建任务。"""
        task_id = generate_string_id()
        task = asyncio.create_task(
            self._rebuild_summary_task(user_id=user_id, trace_id=trace_id, task_id=task_id)
        )
        self._track_task(task)
        return UserProfileCacheRebuildResponse(
            task_id=task_id,
            status=UserProfileCacheStatus.REBUILDING,
        )

    def start_extract_from_messages(
        self,
        *,
        user_id: str,
        session_id: str,
        messages_text: str,
        trace_id: str,
    ) -> UserProfileExtractionTaskResponse:
        """启动从会话压缩片段提取用户画像的后台任务。"""
        task_id = generate_string_id()
        task = asyncio.create_task(
            self._extract_task(
                user_id=user_id,
                session_id=session_id,
                messages_text=messages_text,
                trace_id=trace_id,
                task_id=task_id,
            )
        )
        self._track_task(task)
        return UserProfileExtractionTaskResponse(
            task_id=task_id,
            status=UserProfileCacheStatus.REBUILDING,
        )

    async def extract_from_messages(
        self,
        *,
        user_id: str,
        session_id: str,
        messages_text: str,
        trace_id: str,
    ) -> int:
        """同步执行画像提取，供测试和内部任务复用。"""
        if self.cache:
            await self.cache.invalidate(user_id, trace_id)
        existing = await self.repo.list_active_by_user(user_id)
        plan = await self.extract_mutation_plan(
            session_id=session_id,
            messages_text=messages_text,
            existing_items=existing,
            trace_id=trace_id,
        )
        mutation_count = await self.repo.apply_mutation_plan(
            user_id=user_id,
            session_id=session_id,
            source_ref_id=session_id,
            plan=plan,
            trace_id=trace_id,
        )
        await self.rebuild_summary(user_id=user_id, trace_id=trace_id)
        return mutation_count

    async def extract_mutation_plan(
        self,
        *,
        session_id: str,
        messages_text: str,
        existing_items: list[UserProfileItem],
        trace_id: str,
    ) -> ProfileMutationPlan:
        """执行模型提取并返回可直接提交的变更计划。"""
        return await self.extractor.extract(
            session_id=session_id,
            messages_text=messages_text,
            existing_items=existing_items,
            trace_id=trace_id,
        )

    async def rebuild_summary(self, *, user_id: str, trace_id: str) -> str:
        """重建 Redis 中的用户画像压缩摘要。"""
        items = await self.repo.list_active_by_user(user_id)
        summary = await self.summarizer.summarize(items, trace_id)
        if self.cache:
            await self.cache.save_summary(user_id, summary, len(items))
        return summary

    async def _extract_task(
        self,
        *,
        user_id: str,
        session_id: str,
        messages_text: str,
        trace_id: str,
        task_id: str,
    ) -> None:
        """
        后台执行画像提取任务。

        该方法在后台异步执行用户画像提取任务，通过分析用户的消息文本提取相关信息，
        并更新到用户画像中。该任务使用分布式锁防止并发冲突，并记录任务状态。

        Args:
            user_id: 用户唯一标识符
            session_id: 会话唯一标识符，用于标识消息来源
            messages_text: 需要分析的消息文本内容
            trace_id: 跟踪ID，用于追踪整个操作链路
            task_id: 当前任务的唯一标识符

        Returns:
            None: 此方法没有返回值，所有结果通过缓存或日志输出
        """
        # 记录任务开始时间，用于计算延迟
        start_time = time.monotonic()
        # 设置锁的所有者为当前任务ID
        lock_owner = task_id
        try:
            # 检查是否有可用的缓存实例
            if self.cache:
                # 更新任务状态为重建中
                await self.cache.save_task_status(
                    user_id,
                    task_id,
                    UserProfileCacheStatus.REBUILDING,
                    {"session_id": session_id},
                )
                # 使当前用户的缓存失效，确保后续请求获取最新数据
                await self.cache.invalidate(user_id, trace_id)
                # 尝试获取用户级别的分布式锁，防止并发冲突
                acquired = await self.cache.acquire_lock(user_id, lock_owner)
                # 如果未能获得锁，则标记任务失败并退出
                if not acquired:
                    await self.cache.save_task_status(
                        user_id,
                        task_id,
                        UserProfileCacheStatus.FAILED,
                        {"error": "用户画像任务锁已被占用"},
                    )
                    return
            # 执行画像提取，设置超时时间为90秒
            mutation_count = await asyncio.wait_for(
                self.extract_from_messages(
                    user_id=user_id,
                    session_id=session_id,
                    messages_text=messages_text,
                    trace_id=trace_id,
                ),
                timeout=90.0,
            )
            # 提取成功后，更新任务状态为有效
            if self.cache:
                await self.cache.save_task_status(
                    user_id,
                    task_id,
                    UserProfileCacheStatus.VALID,
                    {"mutation_count": mutation_count},
                )
            # 计算并记录任务执行延迟
            latency_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                f"用户画像提取任务完成 trace_id={trace_id} task_id={task_id} "
                f"session_id={session_id} user_id={user_id} latency_ms={latency_ms} mutation_count={mutation_count}"
            )
        # 处理任务被取消的情况
        except asyncio.CancelledError:
            logger.warning(
                f"用户画像提取任务被取消 trace_id={trace_id} task_id={task_id} "
                f"session_id={session_id} user_id={user_id}"
            )
            raise
        # 处理其他异常情况
        except Exception as exc:
            # 在缓存中标记任务失败状态
            if self.cache:
                await self.cache.mark_failed(user_id, str(exc))
                await self.cache.save_task_status(
                    user_id,
                    task_id,
                    UserProfileCacheStatus.FAILED,
                    {"error": str(exc)},
                )
            logger.error(
                f"用户画像提取任务失败 trace_id={trace_id} task_id={task_id} "
                f"session_id={session_id} user_id={user_id} error={exc}"
            )
        # 无论任务成功、失败还是被取消，都要释放锁
        finally:
            if self.cache:
                await self.cache.release_lock(user_id, lock_owner)

    async def _rebuild_summary_task(
        self,
        *,
        user_id: str,
        trace_id: str,
        task_id: str,
    ) -> None:
        """后台执行摘要缓存重建任务。"""
        try:
            if self.cache:
                await self.cache.mark_rebuilding(user_id, task_id)
                acquired = await self.cache.acquire_lock(user_id, task_id)
                if not acquired:
                    await self.cache.mark_failed(user_id, "用户画像缓存重建锁已被占用")
                    return
            await asyncio.wait_for(
                self.rebuild_summary(user_id=user_id, trace_id=trace_id),
                timeout=45.0,
            )
        except asyncio.CancelledError:
            logger.warning(
                f"用户画像摘要重建任务被取消 trace_id={trace_id} task_id={task_id} user_id={user_id}"
            )
            raise
        except Exception as exc:
            if self.cache:
                await self.cache.mark_failed(user_id, str(exc))
            logger.error(
                f"用户画像摘要重建失败 trace_id={trace_id} task_id={task_id} user_id={user_id} error={exc}"
            )
        finally:
            if self.cache:
                await self.cache.release_lock(user_id, task_id)

    def _track_task(self, task: asyncio.Task[Any]) -> None:
        """跟踪后台任务并在结束后释放引用。"""
        self._tracked_tasks.add(task)
        task.add_done_callback(self._tracked_tasks.discard)

    async def _cache_status_value(self, user_id: str) -> UserProfileCacheStatus:
        """读取缓存状态枚举。"""
        status = await self.get_cache_status(user_id)
        return status.status

    def to_dto(self, item: UserProfileItem) -> UserProfileItemDTO:
        """将 ORM 用户画像转换为 DTO。"""
        return UserProfileItemDTO(
            id=item.id,
            category=UserProfileCategory(item.category),
            category_label=category_label(item.category, item.custom_category_name),
            custom_category_name=item.custom_category_name,
            content=item.content,
            source_type=item.source_type,
            confidence=float(item.confidence),
            status=item.status,
            source_excerpt=item.source_excerpt,
            created_at=datetime_to_text(item.created_at),
            updated_at=datetime_to_text(item.updated_at),
            last_confirmed_at=datetime_to_text(item.last_confirmed_at),
        )
