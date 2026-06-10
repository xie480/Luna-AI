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
    - 禁用的工具不会被检索和执行。
"""

from __future__ import annotations

from typing import Any, Callable

from app.logger import logger
from app.mcp.types import MCPToolSchema, ToolRiskLevel


# ============================================================
# 已注册工具的内部存储结构
# ============================================================


class RegisteredTool:
    """已注册的工具容器。"""

    def __init__(self, schema: MCPToolSchema, handler: Callable[..., Any] | None = None) -> None:
        self.schema = schema
        self.handler = handler


# ============================================================
# MCP 工具注册中心（单例）
# ============================================================


class MCPToolRegistry:
    """MCP 工具注册中心（单例）。"""

    _instance: MCPToolRegistry | None = None
    _tools: dict[str, RegisteredTool] = {}

    def __new__(cls) -> MCPToolRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._tools = {}
        return cls._instance

    # ---- PG 持久化 ----

    async def load_from_pg(self, pg_tools: list[dict[str, Any]]) -> None:
        """从 PG 加载已注册工具到内存。"""
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
            # PG 加载的工具 handler 为空，注册后仅可检索不可执行
            self._tools[name] = RegisteredTool(schema=schema, handler=None)
            loaded_count += 1
        logger.info(f"MCP 工具 PG 加载完成 count={loaded_count}")

    async def persist_to_pg(self, pg_repo: Any) -> None:
        """将内存中所有工具持久化到 PG。"""
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
        """注册一个 MCP 工具。"""
        if name in self._tools:
            raise ValueError(f"MCP 工具名称 '{name}' 已注册，不可重复注册")
        if schema.name != name:
            raise ValueError(f"工具名称不一致: name='{name}' != schema.name='{schema.name}'")
        self._tools[name] = RegisteredTool(schema=schema, handler=handler)
        logger.info(f"MCP 工具注册完成 name={name} risk_level={schema.risk_level.value} category={schema.category}")

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
        if tool is None or not tool.schema.enabled:
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
        if tool is None or not tool.schema.enabled:
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

    # ---- 混合检索（BM25 + 向量） ----

    async def hybrid_search_tools(
        self,
        query: str,
        top_k: int = 5,
        mcp_pg_repo: Any | None = None,
    ) -> list[dict[str, Any]]:
        """
        混合检索候选工具（BM25 + 向量）。

        做什么：优先使用 PostgreSQL FTS（tsvector/ts_rank）进行 BM25 风格稀疏检索。
                如果 mcp_pg_repo 可用，则委托给 pg_repo.search_by_text()；
                否则降级为内存 BM25 检索。
        为什么这样做：与知识库 RAG 和长期记忆 RAG 的检索机制保持一致，
                    使用 PG 内建 FTS 替代内存计算 BM25，支持 GIN 索引加速。
        参数:
            query: 用户输入的查询文本。
            top_k: 返回的最大候选工具数量，默认 5。
            mcp_pg_repo: MCPToolPGRepo 实例，用于 PG FTS 检索。为空时降级到内存 BM25。
        返回:
            list[dict]: 候选工具列表。
        """
        # 优先使用 PG FTS
        if mcp_pg_repo is not None and mcp_pg_repo.is_available:
            return await mcp_pg_repo.search_by_text(query, top_k)

        # 降级到内存 BM25 检索
        return self._memory_bm25_search(query, top_k)

    def _memory_bm25_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        """
        内存 BM25 检索（PG FTS 不可用时的降级方案）。
        """
        import re

        all_tools = list(self._tools.values())
        query_lower = query.lower()
        query_terms = set(re.findall(r'[\w\u4e00-\u9fff]+', query_lower))

        scored_tools: list[tuple[float, RegisteredTool]] = []
        for tool in all_tools:
            if not tool.schema.enabled:
                continue
            searchable_text = (
                f"{tool.schema.name} {tool.schema.core_purpose} "
                f"{' '.join(tool.schema.tags)}"
            ).lower()
            searchable_terms = set(re.findall(r'[\w\u4e00-\u9fff]+', searchable_text))
            overlap = len(query_terms & searchable_terms)
            bm25_score = overlap / max(len(query_terms), 1)
            scored_tools.append((bm25_score, tool))

        scored_tools.sort(key=lambda x: x[0], reverse=True)

        result: list[dict[str, Any]] = []
        for score, tool in scored_tools[:top_k]:
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
        return result
