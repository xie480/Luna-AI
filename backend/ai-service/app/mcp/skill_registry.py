"""
MCP Skill 注册中心。

做什么：管理 MCP Skill 的注册、展开、检索功能。Skill 作为能力指针，
        包含 Tool、Resource 和 Prompt 三要素。Agent 1 在初筛阶段
        仅操作 Skill 级别的元数据，Agent 2 才展开具体内容。
为什么这样做：将 Skill 注册与三阶段 Agent 流程解耦。SkillRegistry
            作为 PG 数据的只读缓存，通过 SQLAlchemy ORM 加载数据。
边界条件：
    - 启动时从 PG 加载所有已注册 Skill。
    - 同一 skill name 不可重复注册。
    - 禁用的 Skill 不会被 Agent 1 召回。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.utils.snowflake import generate_string_id


class SkillMetadata:
    """Skill 元数据（未展开状态，供 Agent 1 使用）。

    做什么：包含 Skill 的名称、描述和核心能力说明。
            不包含 Tool/Resource/Prompt 的具体内容。
    为什么这样做：Agent 1 在初筛阶段只需要知道 Skill 的
                能力范围和适用场景，不需要加载具体工具。
    """

    def __init__(
        self,
        skill_id: str,
        name: str,
        description: str,
        enabled: bool = True,
        version: str = "1.0.0",
    ) -> None:
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.enabled = enabled
        self.version = version

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，供 Agent 1 Prompt 注入。"""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
        }


class SkillDetail:
    """Skill 完整展开信息（供 Agent 2 使用）。

    做什么：包含 Skill 的所有 Tool 简介、Resource 简介和 Prompt 模板。
            Agent 2 加载阶段使用此信息进行工具和资源的选拔规划。
    为什么这样做：将 Skill 的完整展开信息与元数据分离，避免
                Agent 1 收到过多冗余信息。
    prompts 数据结构：
        {phase: {tool_id_or_empty: {content_path, variables}}}
        其中 tool_id_or_empty 为 tool_id（工具专属 prompt）或空字符串（skill 级 prompt）。
        为什么这样做：一个 skill 下可以有多个 tool，每个 tool 可能有各自的 execution prompt，
                    通过 tool_id 区分。skill 级 prompt（screening/loading）用空字符串作为 key。
    """

    def __init__(
        self,
        skill_id: str,
        name: str,
        description: str,
        tools: list[dict[str, Any]],
        resources: list[dict[str, Any]],
        prompts: dict[str, Any],
        version: str = "1.0.0",
    ) -> None:
        self.skill_id = skill_id
        self.name = name
        self.description = description
        # tools 列表包含轻量元数据（name, description, core_purpose），不含 parameters_schema
        self.tools = tools
        # resources 列表包含资源元数据（name, resource_type, uri, description）
        self.resources = resources
        # prompts 字典包含三个阶段的提示词模板
        self.prompts = prompts
        self.version = version


class SkillRegistry:
    """MCP Skill 注册中心（单例）。"""

    _instance: SkillRegistry | None = None
    _skills: dict[str, SkillDetail] = {}

    def __new__(cls) -> SkillRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._skills = {}
        return cls._instance

    # ---- PG 加载 ----

    async def load_from_pg(self, pg_session: Any) -> None:
        """从 PostgreSQL 加载所有 Skill 到内存缓存。

        做什么：通过 SQLAlchemy ORM 查询 skills 表及关联的
                tools（mcp_tool_registrations）、resources、prompts 表。
        为什么这样做：启动时将 PG 数据加载到内存，避免运行时频繁查表。
        参数:
            pg_session: SQLAlchemy 异步会话实例。
        边界条件：PG 不可用时，缓存为空列表。
                  某个 Skill 数据不完整时，跳过该 Skill。
        """
        from sqlalchemy import select

        from app.repository.models import (
            MCPToolRegistration,
        )
        from app.repository.models import (
            Prompt as PromptModel,
        )
        from app.repository.models import (
            Resource as ResourceModel,
        )
        from app.repository.models import Skill as SkillModel

        try:
            # 查询所有启用的 Skill
            result = await pg_session.execute(
                select(SkillModel).where(SkillModel.enabled == True)  # noqa: E712
            )
            skill_rows = result.scalars().all()

            for skill_row in skill_rows:
                # 查询关联的工具（简介信息，不含 parameters_schema）
                tools_result = await pg_session.execute(
                    select(MCPToolRegistration).where(
                        MCPToolRegistration.skill_id == skill_row.id,
                        MCPToolRegistration.enabled == True,  # noqa: E712
                    )
                )
                tool_rows = tools_result.scalars().all()
                tools = [
                    {
                        "tool_id": t.id,
                        "name": t.name,
                        "description": t.description,
                        "core_purpose": t.core_purpose,
                        "final_deliverable": t.final_deliverable,
                        "risk_level": t.risk_level,
                        "category": t.category,
                        "tags": t.tags,
                    }
                    for t in tool_rows
                ]

                # 查询关联的资源
                resources_result = await pg_session.execute(
                    select(ResourceModel).where(ResourceModel.skill_id == skill_row.id)
                )
                resource_rows = resources_result.scalars().all()
                resources = [
                    {
                        "id": r.id,
                        "name": r.name,
                        "resource_type": r.resource_type,
                        "uri": r.uri,
                        "description": r.description,
                        "mime_type": r.mime_type,
                        "auto_load": r.auto_load,
                    }
                    for r in resource_rows
                ]

                # 查询关联的 Prompt
                # 注意：不使用 status 字段过滤，直接按 skill_id 查询所有 Prompt 记录。
                # 为什么这样做：skill 的 execution 阶段 prompt 是工具专属的，
                # 必须通过 skill_id（和可选的 tool_id）查找，确保工具专属 Prompt（如 search_tool_prompt.j2）能被正确加载。
                prompts_result = await pg_session.execute(
                    select(PromptModel).where(
                        PromptModel.skill_id == skill_row.id,
                    )
                )
                prompt_rows = prompts_result.scalars().all()
                # prompts_by_phase 数据结构：
                #   {phase: {tool_id_or_empty: {content_path, variables}}}
                #   tool_id_or_empty：工具专属 prompt 使用 tool_id，skill 级 prompt 使用空字符串
                prompts_by_phase: dict[str, dict[str, dict[str, str]]] = {}
                for p in prompt_rows:
                    phase = p.phase
                    tool_key = p.tool_id or ""  # 空字符串表示 skill 级 prompt（无 tool 绑定）
                    if phase not in prompts_by_phase:
                        prompts_by_phase[phase] = {}
                    prompts_by_phase[phase][tool_key] = {
                        "content_path": p.content_path,
                        "variables": p.variables,
                    }

                # 构建 SkillDetail（memory_schema 已移至 tool 级别，不再从 skill metadata 提取）
                detail = SkillDetail(
                    skill_id=skill_row.id,
                    name=skill_row.name,
                    description=skill_row.description,
                    tools=tools,
                    resources=resources,
                    prompts=prompts_by_phase,
                    version=skill_row.version,
                )
                self._skills[skill_row.id] = detail

            logger.info(f"MCP Skill 从 PG 加载完成 count={len(skill_rows)}")

        except Exception as exc:
            logger.error(f"MCP Skill 从 PG 加载失败 error={exc!s}")

    # ---- 查询 ----

    def list_skill_metadata(self) -> list[dict[str, Any]]:
        """列出所有启用的 Skill 元数据（未展开状态）。

        做什么：返回所有 Skill 的轻量元数据，供 Agent 1 初筛使用。
                不包含 Tool/Resource 的具体内容。
        返回:
            list[dict]: 每个 dict 包含 skill_id, name, description, version。
        """
        result: list[dict[str, Any]] = []
        for skill_id, detail in self._skills.items():
            result.append({
                "skill_id": skill_id,
                "name": detail.name,
                "description": detail.description,
                "version": detail.version,
            })
        return result

    def get_skill_briefs(self) -> list[dict[str, Any]]:
        """获取所有已启用 Skill 的 Brief 列表（供 DAG 引擎使用）。

        做什么：将内存缓存中的 SkillDetail 转换为 SkillBrief 兼容的字典格式，
                包含 skill_name、description、tool_names、risk_levels 和 capability_tags。
        为什么这样做：DagEngineState.skill_briefs 和 memory.j2 模板都需要此格式，
                      在 DAG 引擎启动前一次性构建，避免运行时重复遍历。
        返回:
            list[dict]: 每个 dict 包含：
                - skill_name: Skill 名称
                - description: Skill 描述
                - tool_names: 关联工具名称列表
                - risk_levels: 工具名到风险等级的映射
                - capability_tags: 能力标签列表（从所有工具的 tags 合并去重）
        边界条件：缓存为空时返回空列表，不抛异常。
        """
        result: list[dict[str, Any]] = []
        for _skill_id, detail in self._skills.items():
            # 提取工具名称列表
            tool_names: list[str] = []
            # 工具名到风险等级的映射
            risk_levels: dict[str, str] = {}
            # 能力标签合并去重
            all_tags: list[str] = []

            for tool in detail.tools:
                tool_name = tool.get("name", "")
                if tool_name:
                    tool_names.append(tool_name)
                    risk_levels[tool_name] = tool.get("risk_level", "L0")
                # 合并 tags 到能力标签列表
                tags = tool.get("tags", [])
                if isinstance(tags, list):
                    for tag in tags:
                        if tag not in all_tags:
                            all_tags.append(tag)

            result.append({
                "skill_name": detail.name,
                "description": detail.description,
                "tool_names": tool_names,
                "risk_levels": risk_levels,
                "capability_tags": all_tags,
            })
        return result

    def get_skill_detail(self, skill_id: str) -> SkillDetail | None:
        """获取指定 Skill 的完整展开信息。

        做什么：供 Agent 2 在加载阶段使用，获取 Skill 的
                tools、resources、prompts 完整信息。
        参数:
            skill_id: 技能 ID。
        返回:
            SkillDetail 或 None（不存在时）。
        """
        return self._skills.get(skill_id)

    def get_skill_id_by_name(self, name: str) -> str | None:
        """通过名称查询 Skill ID。

        做什么：供 Agent 1 输出 SkillChainPlan 后校验使用。
        参数:
            name: 技能名称。
        返回:
            str 或 None（不存在时）。
        """
        for skill_id, detail in self._skills.items():
            if detail.name == name:
                return skill_id
        return None

    # ---- 管理接口 ----

    async def create_skill(
        self,
        pg_session: Any,
        name: str,
        description: str,
        metadata: dict[str, Any] | None = None,
        version: str = "1.0.0",
    ) -> str:
        """创建新的 Skill（持久化到 PG 并同步缓存）。

        做什么：在 skills 表中插入一条记录，
                同时将 SkillDetail 缓存到内存。
        参数:
            pg_session: SQLAlchemy 异步会话实例。
            name: 技能名称（唯一）。
            description: 技能描述。
            metadata: 扩展元数据，可选。
            version: 版本号，默认 1.0.0。
        返回:
            str: 新创建的 Skill ID。
        抛出:
            ValueError: name 已存在时抛出。
        """
        from app.repository.models import Skill as SkillModel

        # 检查名称是否已存在
        if self.get_skill_id_by_name(name):
            raise ValueError(f"Skill 名称 '{name}' 已存在")

        skill_id = generate_string_id()
        new_skill = SkillModel(
            id=skill_id,
            name=name,
            description=description,
            metadata_=metadata or {},
            version=version,
            enabled=True,
        )
        pg_session.add(new_skill)
        await pg_session.flush()

        # 同步缓存（memory_schema 已移至 tool 级别，不再从 skill metadata 提取）
        self._skills[skill_id] = SkillDetail(
            skill_id=skill_id,
            name=name,
            description=description,
            tools=[],
            resources=[],
            prompts={},
            version=version,
        )

        logger.info(f"Skill 创建完成 name={name} skill_id={skill_id}")
        return skill_id

    async def delete_skill(self, pg_session: Any, skill_id: str) -> None:
        """删除指定 Skill（级联删除关联的 tools/resources/prompts）。

        做什么：删除 skills 表记录（CASCADE 级联删除关联表），
                同时清理内存缓存。
        参数:
            pg_session: SQLAlchemy 异步会话实例。
            skill_id: 要删除的技能 ID。
        抛出:
            KeyError: skill_id 不存在时抛出。
        """
        from sqlalchemy import select

        from app.repository.models import Skill as SkillModel

        if skill_id not in self._skills:
            raise KeyError(f"Skill '{skill_id}' 不存在")

        result = await pg_session.execute(
            select(SkillModel).where(SkillModel.id == skill_id)
        )
        skill_row = result.scalar_one_or_none()
        if skill_row:
            await pg_session.delete(skill_row)

        del self._skills[skill_id]
        logger.info(f"Skill 删除完成 skill_id={skill_id}")

    # ---- 资源加载 ----

    async def load_resource_file(
        self,
        resource_uri: str,
        resource_type: str = "file",
    ) -> str:
        """加载指定资源的文件内容。

        做什么：根据资源 URI 和类型读取文件内容。
        为什么这样做：ResourceTierService 和旧 DAG 引擎的 ResourceLoadingNode
                      都需要通过此方法获取资源原始内容。
        参数:
            resource_uri: 资源 URI（本地文件路径或 URL）。
            resource_type: 资源类型（file / url）。
        返回:
            文件内容字符串。
        抛出:
            FileNotFoundError: 文件不存在时。
            ValueError: 资源类型不支持时。
        边界条件：
            - 仅支持 file 类型的本地文件读取。
            - URL 类型暂不支持，抛出 ValueError。
        异常行为：
            - 文件读取失败时向上抛出，由调用方处理。
        """
        import os

        if not resource_uri:
            raise ValueError("resource_uri 不能为空")

        if resource_type != "file":
            raise ValueError(f"暂不支持的资源类型: {resource_type}")

        # 处理相对路径（相对于 ai-service 根目录）
        if not os.path.isabs(resource_uri):
            # ai-service/app/mcp/skill_registry.py -> ai-service/
            base_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            resource_uri = os.path.join(base_dir, resource_uri)

        if not os.path.exists(resource_uri):
            raise FileNotFoundError(f"资源文件不存在: {resource_uri}")

        with open(resource_uri, encoding="utf-8") as f:
            return f.read()

    async def _preprocess_resource_chunks(
        self,
        skill_id: str,
        resource_def: dict[str, Any],
        qdrant_client: Any = None,
        embedding_service: Any = None,
    ) -> None:
        """预处理资源：对大文件进行 chunk + embedding 写入向量库。

        做什么：
        1. 读取资源文件
        2. 如果 token 数 > TIER1_MAX_TOKENS，按 512 token + 64 重叠进行 chunk
        3. 对每个 chunk 生成 embedding
        4. 写入 Qdrant（collection: skill_resource_chunks）
        5. 记录 chunk_count 到资源元数据

        为什么这样做：将 IO + embedding 成本前移到注册阶段，
                      运行时只需向量检索，极大降低延迟。

        参数:
            skill_id: 技能 ID。
            resource_def: 资源定义字典（name, resource_type, uri, description）。
            qdrant_client: Qdrant 客户端包装器。
            embedding_service: Embedding 推理服务。

        边界条件：
            - Qdrant 或 Embedding 服务不可用时跳过预处理（降级为全量加载）。
            - 文件读取失败时跳过该资源。
            - 非 file 类型的资源跳过预处理。
        """
        from app.mcp.resource_tier_service import (
            QDRANT_COLLECTION_SKILL_RESOURCE_CHUNKS,
            DEFAULT_VECTOR_SIZE,
            ResourceTierService,
        )
        from app.utils.snowflake import generate_string_id

        resource_uri = resource_def.get("uri", "")
        resource_name = resource_def.get("name", "")
        resource_type = resource_def.get("resource_type", "file")
        section_title = resource_def.get("description", "")

        if resource_type != "file" or not resource_uri:
            return

        if not qdrant_client or not embedding_service:
            logger.info(
                f"资源预处理跳过（Qdrant 或 Embedding 服务不可用）: "
                f"skill_id={skill_id}, resource={resource_name}"
            )
            return

        try:
            # 读取资源文件
            content = await self.load_resource_file(resource_uri, resource_type)

            # 估算 token 数
            tier_service = ResourceTierService()
            estimated_tokens = tier_service._estimate_tokens(content)

            if estimated_tokens <= ResourceTierService.TIER1_MAX_TOKENS:
                # 小文件无需 chunk，运行时直接全量加载
                logger.info(
                    f"资源预处理跳过（小文件 {estimated_tokens} token）: "
                    f"resource={resource_name}"
                )
                return

            # chunk 切分
            chunks = self._split_text_to_chunks(
                content,
                chunk_size_chars=ResourceTierService.CHUNK_SIZE_TOKENS * 4,
                overlap_chars=ResourceTierService.CHUNK_OVERLAP_TOKENS * 4,
            )

            if not chunks:
                return

            # 确保 Qdrant 集合存在
            await qdrant_client.ensure_collection(
                QDRANT_COLLECTION_SKILL_RESOURCE_CHUNKS,
                DEFAULT_VECTOR_SIZE,
            )

            # 生成 embedding 并写入 Qdrant
            from app.infrastructure.qdrant import UpsertPoint

            points: list[Any] = []
            for i, chunk_text in enumerate(chunks):
                try:
                    vector = await embedding_service.get_embedding_vector(chunk_text)
                    point_id = generate_string_id()
                    # 将字符串 ID 转换为整数（Qdrant 要求）
                    point_id_int = int(point_id) if point_id.isdigit() else hash(point_id) % (10**15)
                    points.append(UpsertPoint(
                        id=point_id_int,
                        vector=vector,
                        payload={
                            "skill_id": skill_id,
                            "resource_name": resource_name,
                            "resource_uri": resource_uri,
                            "chunk_index": i,
                            "chunk_text": chunk_text,
                            "section_title": section_title,
                            "char_offset_start": i * (len(chunk_text) - ResourceTierService.CHUNK_OVERLAP_TOKENS * 4) if i > 0 else 0,
                            "char_offset_end": 0,
                            "token_count": tier_service._estimate_tokens(chunk_text),
                        },
                    ))
                except Exception as exc:
                    logger.warning(
                        f"Chunk embedding 生成失败: resource={resource_name}, "
                        f"chunk_index={i}, error={exc}"
                    )
                    continue

            if points:
                await qdrant_client.upsert(
                    QDRANT_COLLECTION_SKILL_RESOURCE_CHUNKS,
                    points,
                )
                logger.info(
                    f"资源预处理完成: resource={resource_name}, "
                    f"chunks={len(points)}, "
                    f"total_tokens={estimated_tokens}"
                )

        except FileNotFoundError:
            logger.warning(f"资源文件不存在，跳过预处理: uri={resource_uri}")
        except Exception as exc:
            logger.error(
                f"资源预处理异常: skill_id={skill_id}, "
                f"resource={resource_name}, error={exc}"
            )

    def _split_text_to_chunks(
        self,
        text: str,
        chunk_size_chars: int = 2048,
        overlap_chars: int = 256,
    ) -> list[str]:
        """将文本按字符数切分为 chunk。

        做什么：按固定字符数切分文本，支持重叠。
        为什么这样做：为向量检索提供 chunk 级别的索引单元。
        参数:
            text: 输入文本。
            chunk_size_chars: 每个 chunk 的字符数。
            overlap_chars: chunk 之间的重叠字符数。
        返回:
            chunk 列表。
        """
        if not text:
            return []

        chunks: list[str] = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size_chars, text_len)
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start += chunk_size_chars - overlap_chars

        return chunks

    def get_skill_resources(self, skill_name: str) -> list[dict[str, Any]]:
        """获取指定 skill 的资源列表。

        做什么：从内存缓存中查找指定 skill 的所有资源定义。
        为什么这样做：StepThinkNode 需要知道当前 skill 有哪些资源可用，
                      才能在 prompt 中引导 LLM 选择正确的 resource_name。
        参数:
            skill_name: 技能名称。
        返回:
            资源定义列表，每个 dict 包含 name, resource_type, uri, description。
        边界条件：
            - skill_name 不存在时返回空列表。
        """
        for _skill_id, detail in self._skills.items():
            if detail.name == skill_name:
                return [
                    {
                        "name": r.get("name", ""),
                        "resource_type": r.get("resource_type", "file"),
                        "uri": r.get("uri", ""),
                        "description": r.get("description", ""),
                    }
                    for r in detail.resources
                ]
        return []
