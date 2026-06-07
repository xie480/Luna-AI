"""
Luna 用户画像 PostgreSQL 仓库。

做什么：封装 user_profile_items、user_profile_item_versions、user_profile_conflicts 的事务读写。
为什么这样做：PostgreSQL 是用户画像唯一事实来源，所有画像写入、版本记录和冲突记录必须集中在仓库层。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.repository.models import UserProfileConflict, UserProfileItem, UserProfileItemVersion
from app.types.constants import (
    USER_PROFILE_DEFAULT_USER_ID,
    UserProfileSourceRefType,
    UserProfileSourceType,
    UserProfileStatus,
)
from app.user_profile.schemas import ProfileMutationPlan
from app.utils.snowflake import generate_string_id


class UserProfilePGRepository:
    """
    用户画像 PostgreSQL 仓库。

    做什么：提供用户画像主表、版本表和冲突表的 CRUD 与事务提交能力。
    为什么这样做：服务层只负责编排，数据库一致性由仓库层集中保证。
    输入输出：输入 user_id、画像模型或变更计划，输出 ORM 模型列表或单条模型。
    边界条件：所有查询都按 user_id 隔离；删除为软删除；编辑必须写版本。
    异常行为：数据库异常直接向上抛出，由 API 或任务层记录中文日志并返回明确错误。
    """

    def __init__(self, pg_client: PostgresClient):
        self.pg_client = pg_client

    async def list_active_by_user(self, user_id: str = USER_PROFILE_DEFAULT_USER_ID) -> list[UserProfileItem]:
        """全量读取指定用户所有 active 用户画像。"""
        async with self.pg_client.session_factory() as session:
            stmt = (
                select(UserProfileItem)
                .where(UserProfileItem.user_id == user_id)
                .where(UserProfileItem.status == UserProfileStatus.ACTIVE.value)
                .order_by(UserProfileItem.category.asc(), UserProfileItem.updated_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_by_category(
        self,
        user_id: str,
        category: str,
        include_inactive: bool = False,
    ) -> list[UserProfileItem]:
        """按类别读取指定用户画像。"""
        async with self.pg_client.session_factory() as session:
            stmt = select(UserProfileItem).where(UserProfileItem.user_id == user_id).where(UserProfileItem.category == category)
            if not include_inactive:
                stmt = stmt.where(UserProfileItem.status == UserProfileStatus.ACTIVE.value)
            stmt = stmt.order_by(UserProfileItem.updated_at.desc())
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_items(
        self,
        user_id: str,
        category: str | None = None,
        include_inactive: bool = False,
    ) -> list[UserProfileItem]:
        """读取用户画像列表，可按类别过滤。"""
        async with self.pg_client.session_factory() as session:
            stmt = select(UserProfileItem).where(UserProfileItem.user_id == user_id)
            if category:
                stmt = stmt.where(UserProfileItem.category == category)
            if not include_inactive:
                stmt = stmt.where(UserProfileItem.status == UserProfileStatus.ACTIVE.value)
            stmt = stmt.order_by(UserProfileItem.category.asc(), UserProfileItem.updated_at.desc())
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_by_id(self, user_id: str, item_id: str) -> UserProfileItem | None:
        """按 ID 读取指定用户画像，确保用户隔离。"""
        async with self.pg_client.session_factory() as session:
            result = await session.execute(
                select(UserProfileItem).where(UserProfileItem.id == item_id).where(UserProfileItem.user_id == user_id)
            )
            return result.scalars().first()

    async def create_manual(
        self,
        *,
        user_id: str,
        category: str,
        custom_category_name: str | None,
        content: str,
        normalized_content: str,
        trace_id: str,
        idempotency_key: str | None,
    ) -> UserProfileItem:
        """手动创建用户画像并写入初始版本。"""
        now = datetime.now(timezone.utc)
        item = UserProfileItem(
            id=generate_string_id(),
            user_id=user_id,
            category=category,
            custom_category_name=custom_category_name,
            content=content,
            normalized_content=normalized_content,
            source_type=UserProfileSourceType.MANUAL.value,
            source_ref_type=UserProfileSourceRefType.MANUAL_INPUT.value,
            source_ref_id=None,
            source_excerpt=None,
            confidence=1.0,
            status=UserProfileStatus.ACTIVE.value,
            last_confirmed_at=now,
            metadata_payload={"idempotency_key": idempotency_key} if idempotency_key else {},
            created_at=now,
            updated_at=now,
        )
        async with self.pg_client.session_factory() as session:
            async with session.begin():
                session.add(item)
                await session.flush()
                await self._write_version(
                    session=session,
                    item=item,
                    change_reason="手动新增用户画像",
                    operator_type=UserProfileSourceType.MANUAL.value,
                    trace_id=trace_id,
                )
        logger.info(f"用户画像手动新增成功 trace_id={trace_id} user_id={user_id} item_id={item.id}")
        return item

    async def update_manual(
        self,
        *,
        user_id: str,
        item_id: str,
        category: str,
        custom_category_name: str | None,
        content: str,
        normalized_content: str,
        trace_id: str,
    ) -> UserProfileItem | None:
        """手动编辑用户画像并写入版本。"""
        now = datetime.now(timezone.utc)
        async with self.pg_client.session_factory() as session:
            async with session.begin():
                item = await self._get_for_update(session, user_id, item_id)
                if item is None:
                    return None
                if item.status != UserProfileStatus.ACTIVE.value:
                    return item
                if item.category == category and item.content == content and item.custom_category_name == custom_category_name:
                    return item
                await self._write_version(
                    session=session,
                    item=item,
                    change_reason="手动编辑前快照",
                    operator_type=UserProfileSourceType.MANUAL.value,
                    trace_id=trace_id,
                )
                item.category = category
                item.custom_category_name = custom_category_name
                item.content = content
                item.normalized_content = normalized_content
                item.source_type = UserProfileSourceType.MANUAL.value
                item.last_confirmed_at = now
                item.updated_at = now
                session.add(item)
        logger.info(f"用户画像手动编辑成功 trace_id={trace_id} user_id={user_id} item_id={item_id}")
        return await self.get_by_id(user_id, item_id)

    async def soft_delete(self, user_id: str, item_id: str, trace_id: str) -> tuple[UserProfileItem | None, bool]:
        """软删除指定画像，重复删除保持幂等。"""
        now = datetime.now(timezone.utc)
        async with self.pg_client.session_factory() as session:
            async with session.begin():
                item = await self._get_for_update(session, user_id, item_id)
                if item is None:
                    return None, False
                if item.status == UserProfileStatus.DELETED.value:
                    return item, True
                await self._write_version(
                    session=session,
                    item=item,
                    change_reason="手动删除前快照",
                    operator_type=UserProfileSourceType.MANUAL.value,
                    trace_id=trace_id,
                )
                item.status = UserProfileStatus.DELETED.value
                item.deleted_at = now
                item.updated_at = now
                session.add(item)
        logger.info(f"用户画像软删除成功 trace_id={trace_id} user_id={user_id} item_id={item_id}")
        return await self.get_by_id(user_id, item_id), False

    async def apply_mutation_plan(
        self,
        *,
        user_id: str,
        session_id: str,
        source_ref_id: str,
        plan: ProfileMutationPlan,
        trace_id: str,
    ) -> int:
        """
        在单个事务中应用模型提取后的用户画像变更计划。

        参数:
            user_id (str): 用户ID，用于数据隔离
            session_id (str): 会话ID，用于记录确认来源
            source_ref_id (str): 来源引用ID，标识画像数据来源
            plan (ProfileMutationPlan): 用户画像变更计划，包含多个变更操作
            trace_id (str): 跟踪ID，用于链路追踪和日志关联

        返回值:
            int: 实际应用的变更数量
        """
        mutation_count = 0
        now = datetime.now(timezone.utc)
        async with self.pg_client.session_factory() as session:
            async with session.begin():
                # 遍历变更计划中的所有变更操作
                for mutation in plan.mutations:
                    candidate = mutation.candidate
                    if mutation.action == "reject":
                        # 拒绝操作，跳过此次变更
                        continue
                    if mutation.action == "confirm_existing" and mutation.target_item_id:
                        # 确认现有画像项目，更新确认时间和元数据
                        item = await self._get_for_update(session, user_id, mutation.target_item_id)
                        if item and item.status == UserProfileStatus.ACTIVE.value:
                            item.last_confirmed_at = now
                            item.updated_at = now
                            metadata = dict(item.metadata_payload or {})
                            metadata.setdefault("confirm_sources", []).append({"session_id": session_id, "trace_id": trace_id})
                            item.metadata_payload = metadata
                            session.add(item)
                            mutation_count += 1
                        continue
                    if mutation.action == "add":
                        # 新增画像项目，并记录版本信息
                        item = self._build_model_item(user_id, source_ref_id, candidate, mutation.reason, trace_id, now)
                        session.add(item)
                        await session.flush()
                        await self._write_version(session, item, "模型提取新增用户画像", UserProfileSourceType.MODEL_EXTRACTED.value, trace_id)
                        mutation_count += 1
                        continue
                    if mutation.action == "supersede" and mutation.target_item_id:
                        # 替换现有画像项目，处理语义冲突
                        old_item = await self._get_for_update(session, user_id, mutation.target_item_id)
                        if old_item is None or old_item.status != UserProfileStatus.ACTIVE.value:
                            continue
                        new_item = self._build_model_item(user_id, source_ref_id, candidate, mutation.reason, trace_id, now)
                        conflict_group_id = old_item.conflict_group_id or generate_string_id()
                        new_item.conflict_group_id = conflict_group_id
                        old_item.conflict_group_id = conflict_group_id
                        session.add(new_item)
                        await session.flush()
                        await self._write_version(session, old_item, "模型提取冲突覆盖前快照", UserProfileSourceType.MODEL_EXTRACTED.value, trace_id)
                        old_item.status = UserProfileStatus.SUPERSEDED.value
                        old_item.superseded_by_id = new_item.id
                        old_item.updated_at = now
                        session.add(old_item)
                        # 记录冲突信息到冲突表
                        session.add(UserProfileConflict(
                            id=generate_string_id(),
                            user_id=user_id,
                            old_item_id=old_item.id,
                            new_item_id=new_item.id,
                            conflict_type="semantic_conflict",
                            resolution="supersede",
                            reason=mutation.reason,
                            trace_id=trace_id,
                            created_at=now,
                        ))
                        await self._write_version(session, new_item, "模型提取冲突覆盖新增画像", UserProfileSourceType.MODEL_EXTRACTED.value, trace_id)
                        mutation_count += 1
        logger.info(f"用户画像变更计划提交完成 trace_id={trace_id} user_id={user_id} mutation_count={mutation_count}")
        return mutation_count

    async def create_indexes(self) -> None:
        """创建用户画像生产索引，幂等执行。"""
        statements = [
            "CREATE INDEX IF NOT EXISTS idx_user_profile_user_category_status ON user_profile_items(user_id, category, status)",
            "CREATE INDEX IF NOT EXISTS idx_user_profile_user_updated ON user_profile_items(user_id, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_user_profile_normalized ON user_profile_items(user_id, category, normalized_content)",
            "CREATE INDEX IF NOT EXISTS idx_user_profile_conflict_group ON user_profile_items(user_id, conflict_group_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_profile_versions_item ON user_profile_item_versions(profile_item_id, version_num DESC)",
        ]
        from sqlalchemy import text

        async with self.pg_client.session_factory() as session:
            for statement in statements:
                await session.execute(text(statement))
            await session.commit()
        logger.info("用户画像 PostgreSQL 索引创建或确认完成")

    async def _get_for_update(self, session: AsyncSession, user_id: str, item_id: str) -> UserProfileItem | None:
        """在事务内按用户隔离读取画像并加行锁。"""
        result = await session.execute(
            select(UserProfileItem)
            .where(UserProfileItem.id == item_id)
            .where(UserProfileItem.user_id == user_id)
            .with_for_update()
        )
        return result.scalars().first()

    async def _write_version(
        self,
        session: AsyncSession,
        item: UserProfileItem,
        change_reason: str,
        operator_type: str,
        trace_id: str,
    ) -> None:
        """在当前事务中写入画像快照版本。"""
        next_version = await self._next_version_num(session, item.id)
        session.add(UserProfileItemVersion(
            id=generate_string_id(),
            profile_item_id=item.id,
            user_id=item.user_id,
            version_num=next_version,
            snapshot=self._snapshot(item),
            change_reason=change_reason,
            operator_type=operator_type,
            trace_id=trace_id,
        ))

    async def _next_version_num(self, session: AsyncSession, item_id: str) -> int:
        """计算画像下一版本号。"""
        result = await session.execute(
            select(func.max(UserProfileItemVersion.version_num)).where(UserProfileItemVersion.profile_item_id == item_id)
        )
        current = result.scalar()
        return int(current or 0) + 1

    def _snapshot(self, item: UserProfileItem) -> dict[str, Any]:
        """生成画像版本快照。"""
        return {
            "id": item.id,
            "user_id": item.user_id,
            "category": item.category,
            "custom_category_name": item.custom_category_name,
            "content": item.content,
            "normalized_content": item.normalized_content,
            "source_type": item.source_type,
            "source_ref_type": item.source_ref_type,
            "source_ref_id": item.source_ref_id,
            "source_excerpt": item.source_excerpt,
            "confidence": float(item.confidence),
            "status": item.status,
            "last_confirmed_at": item.last_confirmed_at.isoformat() if item.last_confirmed_at else None,
            "superseded_by_id": item.superseded_by_id,
            "conflict_group_id": item.conflict_group_id,
            "metadata": item.metadata_payload or {},
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
        }

    def _build_model_item(
        self,
        user_id: str,
        source_ref_id: str,
        candidate: Any,
        reason: str,
        trace_id: str,
        now: datetime,
    ) -> UserProfileItem:
        """根据模型候选构造画像 ORM。"""
        from app.user_profile.conflict_resolver import normalize_profile_content

        return UserProfileItem(
            id=generate_string_id(),
            user_id=user_id,
            category=candidate.category.value,
            custom_category_name=candidate.custom_category_name,
            content=candidate.content,
            normalized_content=normalize_profile_content(candidate.content),
            source_type=UserProfileSourceType.MODEL_EXTRACTED.value,
            source_ref_type=UserProfileSourceRefType.SESSION_COMPRESSION.value,
            source_ref_id=source_ref_id,
            source_excerpt=candidate.evidence,
            confidence=candidate.confidence,
            status=UserProfileStatus.ACTIVE.value,
            last_confirmed_at=now,
            metadata_payload={
                "reasoning": candidate.reasoning,
                "source_risk_flags": candidate.source_risk_flags,
                "mutation_reason": reason,
                "trace_id": trace_id,
            },
            created_at=now,
            updated_at=now,
        )
