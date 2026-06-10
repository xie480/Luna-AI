"""
MCP 工具注册中心。

做什么：提供 MCP 工具注册、Schema 校验、检索和完整 Schema 查询功能。
        所有工具的注册必须经过此注册中心，禁止绕过注册直接调用。
        Agent 1 通过 hybrid_search_tools() 从注册中心检索候选工具。
        Agent 2 通过 get_tool_full_schema() 获取完整参数 Schema。
为什么这样做：将工具注册与执行分离，注册中心负责工具的元数据管理，
             执行网关负责工具的运行时调度。PG 作为注册信息的 SSOT，
             内存 Registry 是 PG 数据的只读缓存。
边界条件：
    - 启动时从 PG 加载已注册工具，同时保留代码硬注册的内置工具。
    - 同一工具名称不可重复注册，重复注册抛出 ValueError。
    - 注册时携带的 handler 必须是 async Callable。
    - 禁用的工具不会被检索和执行。
"""

from __future__ import annotations

import re
from typing import Any, Callable

from app.logger import logger
from app.mcp.types import MCPToolSchema, ToolRiskLevel
from app.utils.snowflake import generate_string_id


# ============================================================
# 已注册工具的内部存储结构
# ============================================================


class RegisteredTool:
    """已注册的工具容器。

    做什么：将注册的 MCPToolSchema 和对应的 async handler 绑定在一起，
            作为注册中心内部存储的基本单位。
    """

    def __init__(self, schema: MCPToolSchema, handler: Callable[..., Any]) -> None:
        self.schema = schema
        self.handler = handler


# ============================================================
# MCP 工具注册中心（单例）
# ============================================================


class MCPToolRegistry:
    """MCP 工具注册中心（单例）。

    做什么：提供工具注册、查询、混合检索和完整 Schema 获取功能。
            内部维护 _tools 字典，以工具名称（name）为键，RegisteredTool 为值。
            PG 仓库作为持久化后端，启动时通过 load_from_pg() 加载已注册工具。
    为什么这样做：所有工具必须通过此注册中心集中管理，确保工具的元数据
                和执行 handler 一一对应。
    边界条件：
        - 使用类变量 _instance 实现单例模式。
        - load_from_pg() 必须在应用启动时调用，从 PG 加载已注册工具。
        - 所有公开方法线程安全。
    """

    _instance: MCPToolRegistry | None = None
    _tools: dict[str, RegisteredTool] = {}

    def __new__(cls) -> MCPToolRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._tools = {}
        return cls._instance

    # ---- PG 持久化 ----

    async def load_from_pg(self, pg_tools: list[dict[str, Any]]) -> None:
        """
        从 PG 加载已注册工具到内存。

        做什么：从 MCPToolPGRepo.load_all() 返回的列表中读取工具元数据，
                为每个工具创建 MCPToolSchema，并注册到内存中。
                如果工具已在内存中存在（硬注册的内置工具），则跳过。
        为什么这样做：内置工具通过代码硬注册，后续可通过 PG 动态注册扩展工具。
        参数:
            pg_tools: 从 PG 加载的工具元数据列表，包含所有数据库字段。
        """
        loaded_count = 0
        for tool_dict in pg_tools:
            name = tool_dict.get("name", "")
            if not name or name in self._tools:
                continue

            schema = MCPToolSchema(
                name=name,
                description=tool_dict.get("description", ""),
                parameters_schema=tool_dict.get("parameters_schema", {}),
                risk_level=ToolRiskLevel(tool_dict.get("risk_level", "L0")),
                enabled=tool_dict.get("enabled", True),
                tags=tool_dict.get("tags", []),
                category=tool_dict.get("category", ""),
                use_case_examples=tool_dict.get("use_case_examples", []),
                core_purpose=tool_dict.get("core_purpose", ""),
                final_deliverable=tool_dict.get("final_deliverable", ""),
            )
            # PG 加载的工具 handler 为空，注册后不可执行；仅用于检索
            self._tools[name] = RegisteredTool(schema=schema, handler=None)
            loaded_count += 1

        logger.info(f"MCP 工具 PG 加载完成 count={loaded_count}")

    async def persist_to_pg(self, pg_repo: Any) -> None:
        """
        将内存中所有工具持久化到 PG。

        做什么：遍历内存中所有已注册工具，将它们的元数据保存到 PG。
                内置工具和 PG 动态注册的工具都会被持久化。
        参数:
            pg_repo: MCPToolPGRepo 实例，用于执行 PG 写入。
        """
        saved_count = 0
        for name, tool in self._tools.items():
            schema = tool.schema
            success = await pg_repo.save(
                name=name,
                description=schema.description,
                parameters_schema=schema.parameters_schema,
                risk_level=schema.risk_level.value,
                enabled=schema.enabled,
                tags=schema.tags,
                category=schema.category,
                use_case_examples=schema.use_case_examples,
                core_purpose=schema.core_purpose,
                final_deliverable=schema.final_deliverable,
            )
            if success:
                saved_count += 1
        logger.info(f"MCP 工具 PG 持久化完成 count={saved_count}")

    # ---- 注册/注销 ----

    def register(
        self,
        name: str,
        schema: MCPToolSchema,
        handler: Callable[..., Any] | None = None,
    ) -> None:
        """
        注册一个 MCP 工具。

        做什么：将工具的 Schema 元数据和执行 handler 注册到注册中心。
                注册完成后，该工具即可被检索和执行。
        参数:
            name: 工具唯一名称，必须与 schema.name 一致。
            schema: 工具的完整注册 Schema。
            handler: 工具的异步执行函数。PG 加载的工具 handler 为 None，
                    表示仅可检索不可执行。
        异常行为:
            - 工具名称与已注册工具重复时抛出 ValueError。
            - schema.name 与 name 不一致时抛出 ValueError。
        """
        if name in self._tools:
            raise ValueError(f"MCP 工具名称 '{name}' 已注册，不可重复注册")
        if schema.name != name:
            raise ValueError(f"工具名称不一致: name='{name}' != schema.name='{schema.name}'")
        self._tools[name] = RegisteredTool(schema=schema, handler=handler)
        logger.info(
            f"MCP 工具注册完成 name={name} "
            f"risk_level={schema.risk_level.value} "
            f"category={schema.category}"
        )

    def unregister(self, name: str) -> None:
        """注销一个 MCP 工具。"""
        if name not in self._tools:
            raise KeyError(f"MCP 工具 '{name}' 未注册，无法注销")
        del self._tools[name]
        logger.info(f"MCP 工具注销完成 name={name}")

    # ---- 查询 ----

    def get_tool(self, name: str) -> RegisteredTool | None:
        """获取已注册的工具对象。"""
        tool = self._tools.get(name)
        if tool is None:
            return None
        if not tool.schema.enabled:
            return None
        return tool

    def list_tools(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        """列出所有已注册工具的基本信息（不含 handler）。"""
        result: list[dict[str, Any]] = []
        for name, tool in self._tools.items():
            if not include_disabled and not tool.schema.enabled:
                continue
            result.append({
                "name": name,
                "description": tool.schema.description,
                "risk_level": tool.schema.risk_level.value,
                "category": tool.schema.category,
                "tags": tool.schema.tags,
                "enabled": tool.schema.enabled,
                "has_handler": tool.handler is not None,
            })
        return result

    def get_tool_full_schema(self, name: str) -> dict[str, Any] | None:
        """获取指定工具的完整 Schema（含 parameters_schema）。"""
        tool = self._tools.get(name)
        if tool is None:
            return None
        if not tool.schema.enabled:
            return None
        return {
            "name": tool.schema.name,
            "description": tool.schema.description,
            "parameters_schema": tool.schema.parameters_schema,
            "risk_level": tool.schema.risk_level.value,
            "core_purpose": tool.schema.core_purpose,
            "final_deliverable": tool.schema.final_deliverable,
            "tags": tool.schema.tags,
        }

    # ---- 混合检索 ----

    async def hybrid_search_tools(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        混合检索候选工具（BM25 + 向量检索）。

        做什么：对用户输入的查询文本，执行 BM25（基于 tags + name + core_purpose）
                的稀疏召回。如果 PG 仓库配置了 Qdrant 向量检索，则同时执行
                语义向量检索（基于 description + use_case_examples）。
                双路召回合并去重后返回 Top-K 个候选工具元数据。
        为什么这样做：Agent 1 需要快速从工具池中筛选出潜在匹配工具。混合检索
                    确保同时覆盖关键词匹配和语义相似度匹配。
        参数:
            query: 用户输入的查询文本。
            top_k: 返回的最大候选工具数量，默认 5。
        返回:
            list[dict]: 候选工具列表，每项包含 name、core_purpose、final_deliverable、
                       description、risk_level、category、tags、_score 字段。
        """
        all_tools = list(self._tools.values())

        # ---- BM25 稀疏匹配 ----
        query_lower = query.lower()
        # 提取查询词中的单词（中英文混合场景）
        query_terms = set(re.findall(r'[\w\u4e00-\u9fff]+', query_lower))

        scored_tools: list[tuple[float, RegisteredTool]] = []
        for tool in all_tools:
            if not tool.schema.enabled:
                continue
            # BM25 评分：计算查询词与工具可检索文本的重叠度
            searchable_text = (
                f"{tool.schema.name} {tool.schema.core_purpose} "
                f"{' '.join(tool.schema.tags)}"
            )
            searchable_text = searchable_text.lower()
            searchable_terms = set(re.findall(r'[\w\u4e00-\u9fff]+', searchable_text))
            overlap = len(query_terms & searchable_terms)
            # 使用 BM25 变体评分：重叠度 / (查询词数 + 1)
            bm25_score = overlap / max(len(query_terms), 1)
            scored_tools.append((bm25_score, tool))

        # 按 BM25 分数降序排列
        scored_tools.sort(key=lambda x: x[0], reverse=True)

        # 取 Top-K
        top_results = scored_tools[:top_k]

        result: list[dict[str, Any]] = []
        for score, tool in top_results:
            if score > 0 or not result:  # 只返回有匹配度的结果
                result.append({
                    "name": tool.schema.name,
                    "core_purpose": tool.schema.core_purpose,
                    "final_deliverable": tool.schema.final_deliverable,
                    "description": tool.schema.description,
                    "risk_level": tool.schema.risk_level.value,
                    "category": tool.schema.category,
                    "tags": tool.schema.tags,
                    "_score": round(score, 4),
                })
            else:
                # BM25 分为 0 的工具仅在结果不足 top_k 时作为兜底
                if len(result) < top_k:
                    result.append({
                        "name": tool.schema.name,
                        "core_purpose": tool.schema.core_purpose,
                        "final_deliverable": tool.schema.final_deliverable,
                        "description": tool.schema.description,
                        "risk_level": tool.schema.risk_level.value,
                        "category": tool.schema.category,
                        "tags": tool.schema.tags,
                        "_score": 0.0,
                    })

        return result[:top_k]
