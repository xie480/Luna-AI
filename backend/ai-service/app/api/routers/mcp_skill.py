"""
MCP Skill 管理 API 路由。

做什么：提供供前端调用的 MCP Skill 注册、更新、删除和列表查询接口。
        Skill 是 MCP 能力的顶层抽象，一个 Skill 包含一组 Tool、Resource 和 Prompt，
        系统通过三阶段 Agent 流水线执行 Skill。
为什么这样做：前后端分离，为前端提供标准化的 Skill 管理入口。
边界条件：
    - 所有 API 返回完整的 trace_id 用于全链路追踪。
    - 数据库连接不可用时返回 HTTP 503。
    - 传参错误时返回 HTTP 422 详细描述。
    - name 字段唯一，重复注册返回 409 冲突。
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func

from app.logger import logger
from app.infrastructure.postgres import PostgresClient
from app.repository.models import Skill
from app.utils.snowflake import generate_string_id


router = APIRouter(tags=["MCP Skill"])


# ============================================================================
# Pydantic 请求/响应模型
# ============================================================================


class SkillConfig(BaseModel):
    """注册 MCP Skill 的请求体。"""
    name: str
    """Skill 唯一名称（在 skills 表中作为 name 字段）。"""
    description: str = ""
    """Skill 功能描述。"""
    version: str = "1.0.0"
    """Skill 版本号。"""
    enabled: bool = True
    """是否启用。"""


class BatchSkillRegisterRequest(BaseModel):
    """批量注册 MCP Skill 的请求体。"""
    skills: list[SkillConfig]
    """待注册的技能列表。"""


class UpdateSkillRequest(BaseModel):
    """更新 MCP Skill 配置的请求体。"""
    name: str | None = None
    description: str | None = None
    version: str | None = None
    enabled: bool | None = None


# ============================================================================
# 辅助函数
# ============================================================================


async def _get_pg_client(request: Request) -> PostgresClient:
    """
    从 app.state 获取 PostgreSQL 客户端。

    做什么：从请求的 app.state 中提取 pg_client 实例。
    为什么这样做：pg_client 在 lifespan 中初始化并注入到 app.state，路由从中获取。
    边界条件：pg_client 不可用时抛 503 并附带中文描述。
    异常行为：pg_client 为 None 时立即抛出 HTTPException(503)。
    """
    pg_client: PostgresClient | None = request.app.state.pg_client
    if not pg_client:
        raise HTTPException(status_code=503, detail="数据库连接不可用，请检查服务状态")
    return pg_client


async def _row_to_skill_info(row: Skill) -> dict[str, Any]:
    """
    将 Skill ORM 行对象转为技能信息字典。

    做什么：从 ORM 行对象中提取字段，序列化为前端期望的字典格式。
    为什么这样做：ORM 行对象不能直接序列化为 JSON，需要手动转换。
    参数:
        row: Skill ORM 行对象。
    返回:
        dict: 包含 id、name、description、version、enabled、
              metadata、created_at、updated_at 的字典。
    """
    if row is None:
        return {}

    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "version": row.version or "1.0.0",
        "enabled": row.enabled,
        "metadata": row.metadata_ or {},
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


# ============================================================================
# API 端点
# ============================================================================


@router.post("/api/v1/mcp/skills/register")
async def register_skill(
    body: SkillConfig,
    request: Request,
):
    """
    注册单个 MCP Skill。

    做什么：
        1. 检查 name 是否已存在，重复则返回 409。
        2. 在 skills 表中创建一条记录。
        3. 记录操作日志。
    为什么这样做：用户在前端填写 Skill 配置后提交注册。
    边界条件：
        - name 重复时返回 409 冲突。
        - 数据库连接不可用时返回 503。
    参数:
        body: Skill 配置（name、description、version、enabled）。
        request: FastAPI 请求对象，用于获取 pg_client 和 trace_id。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"skill_id": "...", "success": true}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session_factory() as session:
        try:
            # Step 1: 检查 name 是否已存在
            existing_result = await session.execute(
                select(Skill).where(
                    Skill.name == body.name,
                ).limit(1)
            )
            if existing_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail=f"MCP Skill '{body.name}' 已经注册，请勿重复操作",
                )

            # Step 2: 创建新记录
            skill_id = generate_string_id()
            new_skill = Skill(
                id=skill_id,
                name=body.name,
                description=body.description,
                version=body.version,
                enabled=body.enabled,
            )
            session.add(new_skill)
            await session.commit()

            logger.info(
                f"MCP Skill 注册完成 "
                f"trace_id={trace_id} skill_id={skill_id} name={body.name}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "skill_id": skill_id,
                    "success": True,
                },
                "trace_id": trace_id,
            }

        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.error(
                f"MCP Skill 注册失败 "
                f"trace_id={trace_id} name={body.name} error={e}"
            )
            raise HTTPException(status_code=500, detail=f"注册失败: {e!s}")


@router.post("/api/v1/mcp/skills/batch-register")
async def batch_register_skills(
    body: BatchSkillRegisterRequest,
    request: Request,
):
    """
    批量注册 MCP Skill。

    做什么：遍历 skills 列表，对每个 Skill 依次执行注册逻辑。
            部分成功时仍返回成功计数和失败详情，不整体回滚。
    为什么这样做：用户可能一次导入多个 Skill 配置，批量操作更高效。
    边界条件：
        - 列表中某个 Skill 注册失败不影响其他 Skill 的注册。
        - 重复名称的 Skill 被计入 failures 而非成功。
        - 空列表返回 success_count=0, failed_count=0。
    参数:
        body: 包含 skills 列表的请求体。
        request: FastAPI 请求对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"success_count": N, "failed_count": M, "failures": [...]}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    success_count = 0
    failed_count = 0
    failures: list[dict[str, str]] = []

    for skill_config in body.skills:
        async with pg_client.session_factory() as session:
            try:
                # 检查重复
                existing_result = await session.execute(
                    select(Skill).where(
                        Skill.name == skill_config.name,
                    ).limit(1)
                )
                if existing_result.scalar_one_or_none():
                    failed_count += 1
                    failures.append({
                        "name": skill_config.name,
                        "error": "该 Skill 已经注册",
                    })
                    continue

                # 创建新记录
                skill_id = generate_string_id()
                new_skill = Skill(
                    id=skill_id,
                    name=skill_config.name,
                    description=skill_config.description,
                    version=skill_config.version,
                    enabled=skill_config.enabled,
                )
                session.add(new_skill)
                await session.commit()
                success_count += 1

                logger.info(
                    f"批量注册 Skill 成功 "
                    f"trace_id={trace_id} name={skill_config.name} "
                    f"skill_id={skill_id}"
                )

            except Exception as e:
                await session.rollback()
                failed_count += 1
                failures.append({
                    "name": skill_config.name,
                    "error": str(e)[:200],
                })
                logger.warning(
                    f"批量注册 Skill 失败 "
                    f"trace_id={trace_id} name={skill_config.name} error={e}"
                )

    logger.info(
        f"批量注册 Skill 完成 "
        f"trace_id={trace_id} success={success_count} failed={failed_count}"
    )

    return {
        "code": 0,
        "msg": "success",
        "data": {
            "success_count": success_count,
            "failed_count": failed_count,
            "failures": failures,
        },
        "trace_id": trace_id,
    }


@router.get("/api/v1/mcp/skills")
async def list_skills(request: Request):
    """
    获取已注册的 MCP Skill 列表。

    做什么：从 skills 表查询所有记录，按创建时间倒序返回列表。
    为什么这样做：前端 MCP 面板需要展示已注册的 Skill 列表。
    边界条件：
        - 没有注册记录时返回空列表而非错误。
        - 数据库连接不可用时返回 503。
    参数:
        request: FastAPI 请求对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": [SkillInfo, ...], "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            result = await session.execute(
                select(Skill)
                .order_by(Skill.created_at.desc())
            )
            rows = result.scalars().all()

            items = []
            for row in rows:
                item = await _row_to_skill_info(row)
                items.append(item)

            logger.info(
                f"MCP Skill 列表查询完成 "
                f"trace_id={trace_id} count={len(items)}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": items,
                "trace_id": trace_id,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"查询 MCP Skill 列表失败 "
            f"trace_id={trace_id} error={e}"
        )
        raise HTTPException(status_code=500, detail=f"查询失败: {e!s}")


@router.patch("/api/v1/mcp/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    body: UpdateSkillRequest,
    request: Request,
):
    """
    更新 MCP Skill 的配置。

    做什么：根据 skill_id 查找对应的记录，更新传入的非空字段。
            只更新传入的非空（非 None）字段，未传的字段保持不变。
    为什么这样做：用户可以在前端修改已注册 Skill 的配置。
    边界条件：
        - skill_id 不存在时返回 404。
        - 如果同时更新 name 且新名称已存在，返回 409 冲突。
    参数:
        skill_id: 要更新的 Skill ID。
        body: 更新请求体，包含需要更新的字段。
        request: FastAPI 请求对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"success": true}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session_factory() as session:
        try:
            # Step 1: 查找现有记录
            result = await session.execute(
                select(Skill).where(
                    Skill.id == skill_id,
                ).limit(1)
            )
            skill = result.scalar_one_or_none()

            if not skill:
                raise HTTPException(
                    status_code=404,
                    detail=f"MCP Skill '{skill_id}' 不存在",
                )

            # Step 2: 如果更新 name，检查新名称是否与其他记录冲突
            if body.name is not None and body.name != skill.name:
                conflict_result = await session.execute(
                    select(Skill).where(
                        Skill.name == body.name,
                        Skill.id != skill_id,
                    ).limit(1)
                )
                if conflict_result.scalar_one_or_none():
                    raise HTTPException(
                        status_code=409,
                        detail=f"名称 '{body.name}' 已被其他 Skill 使用",
                    )
                skill.name = body.name

            # Step 3: 更新各字段
            if body.description is not None:
                skill.description = body.description
            if body.version is not None:
                skill.version = body.version
            if body.enabled is not None:
                skill.enabled = body.enabled

            # Step 4: 提交更新
            skill.updated_at = func.now()
            await session.commit()

            logger.info(
                f"MCP Skill 更新完成 "
                f"trace_id={trace_id} skill_id={skill_id}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {"success": True},
                "trace_id": trace_id,
            }

        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.error(
                f"更新 MCP Skill 失败 "
                f"trace_id={trace_id} skill_id={skill_id} error={e}"
            )
            raise HTTPException(status_code=500, detail=f"更新失败: {e!s}")


@router.delete("/api/v1/mcp/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    request: Request,
):
    """
    删除 MCP Skill。

    做什么：根据 skill_id 查找对应的记录，从数据库中永久删除。
    为什么这样做：用户在前端点击删除按钮后移除不再使用的 Skill。
    边界条件：
        - skill_id 不存在时返回 404。
        - 删除操作不可逆，操作前应有前端确认。
    参数:
        skill_id: 要删除的 Skill ID。
        request: FastAPI 请求对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"success": true}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session_factory() as session:
        try:
            # Step 1: 查找记录
            result = await session.execute(
                select(Skill).where(
                    Skill.id == skill_id,
                ).limit(1)
            )
            skill = result.scalar_one_or_none()

            if not skill:
                raise HTTPException(
                    status_code=404,
                    detail=f"MCP Skill '{skill_id}' 不存在",
                )

            skill_name = skill.name

            # Step 2: 删除记录
            await session.delete(skill)
            await session.commit()

            logger.info(
                f"MCP Skill 删除完成 "
                f"trace_id={trace_id} skill_id={skill_id} name={skill_name}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {"success": True},
                "trace_id": trace_id,
            }

        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.error(
                f"删除 MCP Skill 失败 "
                f"trace_id={trace_id} skill_id={skill_id} error={e}"
            )
            raise HTTPException(status_code=500, detail=f"删除失败: {e!s}")
