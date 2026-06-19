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

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func, delete

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
    skills: list[dict[str, Any]]
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

            # 将注册的 Skill 更新到内存中
            from app.mcp.skill_registry import SkillRegistry
            registry = SkillRegistry()
            await registry.load_from_pg(session)

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
                skill_name = skill_config.get("name")
                if not skill_name:
                    raise ValueError("Skill 名称不能为空")

                # 检查重复
                existing_result = await session.execute(
                    select(Skill).where(
                        Skill.name == skill_name,
                    ).limit(1)
                )
                
                skill = existing_result.scalar_one_or_none()
                skill_id = skill.id if skill else generate_string_id()
                
                if skill:
                    # Update
                    skill.description = skill_config.get("description", skill.description)
                    skill.version = skill_config.get("version", skill.version)
                    skill.enabled = skill_config.get("enabled", skill.enabled)
                    if "metadata" in skill_config:
                        skill.metadata_ = skill_config["metadata"]
                else:
                    # Insert
                    skill = Skill(
                        id=skill_id,
                        name=skill_name,
                        description=skill_config.get("description", ""),
                        version=skill_config.get("version", "1.0.0"),
                        enabled=skill_config.get("enabled", True),
                        metadata_=skill_config.get("metadata", {}),
                    )
                    session.add(skill)
                
                await session.flush()

                # Process Resources
                from app.repository.models import Resource
                if "resources" in skill_config:
                    await session.execute(delete(Resource).where(Resource.skill_id == skill_id))
                    for r in skill_config["resources"]:
                        session.add(Resource(
                            id=generate_string_id(),
                            skill_id=skill_id,
                            name=r.get("name", "unknown"),
                            resource_type=r.get("resource_type", "file"),
                            uri=r.get("uri", ""),
                            description=r.get("description", ""),
                            mime_type=r.get("mime_type", ""),
                            auto_load=r.get("auto_load", False)
                        ))

                # Process Tools
                from app.repository.models import MCPToolRegistration, ToolConfig
                if "tools" in skill_config:
                    # Note: Not deleting existing tools mapped to this skill for safety,
                    # but typically tools are tightly bound to the skill.
                    for t in skill_config["tools"]:
                        tool_name = t.get("name")
                        if not tool_name: continue
                        
                        tool_res = await session.execute(
                            select(MCPToolRegistration).where(MCPToolRegistration.name == tool_name).limit(1)
                        )
                        tool_rec = tool_res.scalar_one_or_none()
                        if tool_rec:
                            tool_rec.description = t.get("description", tool_rec.description)
                            tool_rec.parameters_schema = t.get("parameters_schema", tool_rec.parameters_schema)
                            tool_rec.skill_id = skill_id
                            tool_rec.module_path = t.get("module_path", tool_rec.module_path)
                        else:
                            tool_rec = MCPToolRegistration(
                                id=generate_string_id(),
                                name=tool_name,
                                description=t.get("description", ""),
                                parameters_schema=t.get("parameters_schema", {}),
                                risk_level=t.get("risk_level", "L0"),
                                enabled=t.get("enabled", True),
                                tags=t.get("tags", []),
                                category=t.get("category", ""),
                                use_case_examples=t.get("use_case_examples", []),
                                core_purpose=t.get("core_purpose", ""),
                                final_deliverable=t.get("final_deliverable", ""),
                                source=t.get("source", "local"),
                                module_path=t.get("module_path", ""),
                                skill_id=skill_id
                            )
                            session.add(tool_rec)
                            
                        # Process Tool Config
                        if "tool_config" in t:
                            cfg_res = await session.execute(
                                select(ToolConfig).where(ToolConfig.tool_name == tool_name).limit(1)
                            )
                            cfg_rec = cfg_res.scalar_one_or_none()
                            if cfg_rec:
                                cfg_rec.config_data = t["tool_config"]
                            else:
                                session.add(ToolConfig(
                                    id=generate_string_id(),
                                    tool_name=tool_name,
                                    config_data=t["tool_config"],
                                    description=f"Auto generated config for {tool_name}"
                                ))
                                
                await session.flush() # Ensure tools are flushed before processing prompts

                # Process Prompts
                from app.repository.models import Prompt
                if "prompts" in skill_config:
                    await session.execute(delete(Prompt).where(Prompt.skill_id == skill_id))
                    for p in skill_config["prompts"]:
                        # Extract tool name from content_path, e.g., prompts/web_search_prompt.j2 -> web_search
                        content_path = p.get("content_path", "")
                        tool_id = None
                        if content_path:
                            # 尝试从 content_path 推断绑定的 tool_name
                            file_name = os.path.basename(content_path)
                            if file_name.endswith("_prompt.j2"):
                                tool_name = file_name.replace("_prompt.j2", "")
                                # 去查找对应的 tool_id
                                from app.repository.models import MCPToolRegistration
                                tool_res = await session.execute(
                                    select(MCPToolRegistration.id).where(
                                        MCPToolRegistration.name == tool_name,
                                        MCPToolRegistration.skill_id == skill_id
                                    ).limit(1)
                                )
                                tool_id = tool_res.scalar_one_or_none()
                        
                        session.add(Prompt(
                            id=generate_string_id(),
                            skill_id=skill_id,
                            tool_id=tool_id,
                            phase=p.get("phase", "execution"),
                            content_path=content_path,
                            variables=p.get("variables", []),
                            version_num=p.get("version_num", 1),
                        ))

                # Process Servers
                from app.repository.models import MCPServerRegistration
                if "servers" in skill_config:
                    for s in skill_config["servers"]:
                        server_name = s.get("name")
                        if not server_name: continue
                        
                        srv_res = await session.execute(
                            select(MCPServerRegistration).where(MCPServerRegistration.name == server_name).limit(1)
                        )
                        srv_rec = srv_res.scalar_one_or_none()
                        if srv_rec:
                            srv_rec.command = s.get("command", srv_rec.command)
                            srv_rec.args = s.get("args", srv_rec.args)
                            srv_rec.env = s.get("env", srv_rec.env)
                        else:
                            session.add(MCPServerRegistration(
                                id=generate_string_id(),
                                name=server_name,
                                command=s.get("command", ""),
                                args=s.get("args", []),
                                env=s.get("env", {}),
                                description=s.get("description", ""),
                                enabled=s.get("enabled", True),
                                metadata_=s.get("metadata", {})
                            ))

                await session.commit()
                success_count += 1

                logger.info(
                    f"批量注册 Skill 成功 "
                    f"trace_id={trace_id} name={skill_name} "
                    f"skill_id={skill_id}"
                )

                # 将注册的 Skill 更新到内存中
                from app.mcp.skill_registry import SkillRegistry
                registry = SkillRegistry()
                await registry.load_from_pg(session)

            except Exception as e:
                await session.rollback()
                failed_count += 1
                failures.append({
                    "name": skill_config.get("name", "Unknown"),
                    "error": str(e)[:200],
                })
                logger.warning(
                    f"批量注册 Skill 失败 "
                    f"trace_id={trace_id} name={skill_config.get('name')} error={e}"
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


@router.get("/api/v1/mcp/skills/{skill_id}")
async def get_skill_detail(
    skill_id: str,
    request: Request,
):
    """
    获取单个 MCP Skill 的详细信息。

    做什么：根据 skill_id 查询对应的 Skill，以及其关联的 Tools, Prompts, Resources。
    为什么这样做：前端在展开 Skill 详情时需要展示这些关联数据。
    边界条件：
        - skill_id 不存在时返回 404。
    参数:
        skill_id: 要查询的 Skill ID。
        request: FastAPI 请求对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": {...}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    from app.repository.models import MCPToolRegistration, Prompt, Resource

    try:
        async with pg_client.session_factory() as session:
            # 查 Skill
            result = await session.execute(
                select(Skill).where(Skill.id == skill_id).limit(1)
            )
            skill = result.scalar_one_or_none()
            if not skill:
                raise HTTPException(
                    status_code=404,
                    detail=f"MCP Skill '{skill_id}' 不存在",
                )

            skill_dict = await _row_to_skill_info(skill)

            # 查 Tools
            tools_result = await session.execute(
                select(MCPToolRegistration).where(MCPToolRegistration.skill_id == skill_id)
            )
            tools = []
            for t in tools_result.scalars().all():
                tools.append({
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "core_purpose": t.core_purpose,
                })
            
            # 查 Prompts
            prompts_result = await session.execute(
                select(Prompt).where(Prompt.skill_id == skill_id)
            )
            prompts = []
            for p in prompts_result.scalars().all():
                prompts.append({
                    "id": p.id,
                    "phase": p.phase,
                    "content_path": p.content_path,
                })
                
            # 查 Resources
            resources_result = await session.execute(
                select(Resource).where(Resource.skill_id == skill_id)
            )
            resources = []
            for r in resources_result.scalars().all():
                resources.append({
                    "id": r.id,
                    "name": r.name,
                    "resource_type": r.resource_type,
                    "uri": r.uri,
                })
                
            skill_dict["tools"] = tools
            skill_dict["prompts"] = prompts
            skill_dict["resources"] = resources

            logger.info(
                f"MCP Skill 详情查询完成 "
                f"trace_id={trace_id} skill_id={skill_id}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": skill_dict,
                "trace_id": trace_id,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"查询 MCP Skill 详情失败 "
            f"trace_id={trace_id} skill_id={skill_id} error={e}"
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

            # 将更新的 Skill 同步到内存中
            from app.mcp.skill_registry import SkillRegistry
            registry = SkillRegistry()
            await registry.load_from_pg(session)

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

            # 将删除操作同步到内存中
            from app.mcp.skill_registry import SkillRegistry
            registry = SkillRegistry()
            await registry.load_from_pg(session)

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
