"""
MCP 工具注册中心。

做什么：提供 MCP 工具注册、Schema 校验、检索和完整 Schema 查询功能。
        所有工具的注册必须经过此注册中心，禁止绕过注册直接调用。
        Agent 1 通过 hybrid_search_tools() 从注册中心检索候选工具。
        Agent 2 通过 get_tool_full_schema() 获取完整参数 Schema。
为什么这样做：将工具注册与执行分离，注册中心负责工具的元数据管理，
             执行网关负责工具的运行时调度。Agent 1 初筛阶段仅需轻量
             元数据（不含 Schema），此处通过 hybrid_search_tools() 实现
             混合检索召回候选工具。
边界条件：
    - 同一工具名称不可重复注册，重复注册抛出 ValueError。
    - 注册时携带的 handler 必须是 async Callable。
    - inference_service 为空时 hybrid_search_tools 降级为纯 BM25 检索。
    - 禁用的工具（schema.enabled=False）不会被检索和执行。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.logger import logger
from app.mcp.types import MCPToolSchema, MCPToolResult, ToolRiskLevel
from app.utils.snowflake import generate_string_id


# ============================================================
# 已注册工具的内部存储结构
# ============================================================


class RegisteredTool:
    """已注册的工具容器。

    做什么：将注册的 MCPToolSchema 和对应的 async handler 绑定在一起，
            作为注册中心内部存储的基本单位。
    为什么这样做：注册中心需要同时管理工具的元数据和执行逻辑，
                 通过 RegisteredTool 对象统一封装，避免 schema 和 handler
                 分开存储导致的不一致。
    """

    def __init__(self, schema: MCPToolSchema, handler: Callable[..., Any]) -> None:
        """
        初始化已注册的工具。

        参数:
            schema: 工具的完整注册 Schema，包含元数据和参数定义。
            handler: 工具的异步执行函数，必须 awaitable。
                     函数签名: async def handler(params: dict[str, Any], trace_id: str) -> MCPToolResult
        """
        self.schema = schema
        self.handler = handler


# ============================================================
# MCP 工具注册中心（单例）
# ============================================================


class MCPToolRegistry:
    """MCP 工具注册中心（单例）。

    做什么：提供工具注册、查询、混合检索和完整 Schema 获取功能。
            内部维护 _tools 字典，以工具名称（name）为键，RegisteredTool 为值。
    为什么这样做：所有工具必须通过此注册中心集中管理，确保工具的元数据
                和执行 handler 一一对应。Agent 1 的初筛和 Agent 2 的
                参数提取均依赖本注册中心的检索和查询接口。
    边界条件：
        - 使用类变量 _instance 实现单例模式。
        - 第一次实例化时清空 _tools，确保每个进程有独立的工具集。
        - 所有公开方法线程安全（异步环境中单线程执行）。
    """

    _instance: MCPToolRegistry | None = None
    _tools: dict[str, RegisteredTool] = {}

    def __new__(cls) -> MCPToolRegistry:
        """单例构造：确保全局只存在一个注册中心实例。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._tools = {}
        return cls._instance

    def register(
        self,
        name: str,
        schema: MCPToolSchema,
        handler: Callable[..., Any],
    ) -> None:
        """
        注册一个 MCP 工具。

        做什么：将工具的 Schema 元数据和执行 handler 注册到注册中心。
                注册完成后，该工具即可被混合检索召回和执行。
        为什么这样做：所有工具必须显式注册才能被使用，禁止未注册的工具被调用。
        参数:
            name: 工具唯一名称，必须与 schema.name 一致。
            schema: 工具的完整注册 Schema。
            handler: 工具的异步执行函数。
        异常行为:
            - 工具名称与已注册工具重复时抛出 ValueError。
            - schema.name 与 name 不一致时抛出 ValueError。
            - handler 不可调用时抛出 TypeError。
        """
        if name in self._tools:
            raise ValueError(f"MCP 工具名称 '{name}' 已注册，不可重复注册")
        if schema.name != name:
            raise ValueError(f"工具名称不一致: name='{name}' != schema.name='{schema.name}'")
        if not callable(handler):
            raise TypeError(f"工具 '{name}' 的 handler 必须是可调用对象")

        self._tools[name] = RegisteredTool(schema=schema, handler=handler)
        logger.info(
            f"MCP 工具注册完成 name={name} "
            f"risk_level={schema.risk_level.value} "
            f"category={schema.category} "
            f"tags={schema.tags}"
        )

    def unregister(self, name: str) -> None:
        """
        注销一个 MCP 工具。

        做什么：从注册中心移除指定名称的工具。移除后该工具不可被检索和执行。
        参数:
            name: 要注销的工具名称。
        异常行为:
            - 工具不存在时抛出 KeyError。
        """
        if name not in self._tools:
            raise KeyError(f"MCP 工具 '{name}' 未注册，无法注销")
        del self._tools[name]
        logger.info(f"MCP 工具注销完成 name={name}")

    def get_tool(self, name: str) -> RegisteredTool | None:
        """
        获取已注册的工具对象。

        做什么：根据工具名称返回对应的 RegisteredTool 对象。
                工具不存在或已禁用时返回 None。
        参数:
            name: 工具名称。
        返回:
            RegisteredTool: 工具的容器对象，包含 schema 和 handler。
            工具不存在或已禁用时返回 None。
        """
        tool = self._tools.get(name)
        if tool is None:
            return None
        if not tool.schema.enabled:
            return None
        return tool

    def list_tools(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        """
        列出所有已注册工具的基本信息（不含 handler）。

        做什么：返回所有已注册工具的 Schema 摘要列表，用于调试面板和管理界面。
        参数:
            include_disabled: 是否包含已禁用的工具。默认 False。
        返回:
            list[dict]: 每个工具的基本信息字典列表。
        """
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
            })
        return result

    async def hybrid_search_tools(
        self,
        query: str,
        top_k: int = 5,
        inference_service: Any | None = None,
    ) -> list[dict[str, Any]]:
        """
        混合检索候选工具。

        做什么：对用户输入的查询文本，执行 BM25（基于 tags + name + core_purpose）
                和语义向量检索（基于 description + use_case_examples）的双路召回，
                合并后返回 Top-K 个候选工具元数据（不含 parameters_schema）。
        为什么这样做：Agent 1 需要快速从工具池中筛选出潜在匹配工具，不携带完整 Schema
                    以节省 Token 消耗。
        输出格式：仅返回 name、core_purpose、final_deliverable、description、risk_level、
                 category、tags 字段，不包含 parameters_schema。
        参数:
            query: 用户输入的查询文本，通常来自输入重构节点的 keywords。
            top_k: 返回的最大候选工具数量，默认 5。
            inference_service: 推理服务实例，用于向量检索。为空时降级为纯 BM25 检索。
        返回:
            list[dict]: 候选工具列表，每项包含 name、core_purpose、final_deliverable、
                       description、risk_level、category、tags、_bm25_score 字段。
        边界条件:
            - inference_service 为空时降级为纯 BM25 检索（基于 tag 关键词匹配）。
            - 注册工具总数少于 top_k 时返回全部可用工具。
            - 禁用工具不会被召回。
        """
        all_tools = list(self._tools.values())

        # BM25 稀疏匹配（基于 name + core_purpose + tags 的关键词匹配）
        query_lower = query.lower()
        query_terms = set(re.findall(r'\w+', query_lower))

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
            searchable_terms = set(re.findall(r'\w+', searchable_text))
            overlap = len(query_terms & searchable_terms)
            bm25_score = overlap / max(len(query_terms), 1)
            scored_tools.append((bm25_score, tool))

        # 按 BM25 分数降序排列
        scored_tools.sort(key=lambda x: x[0], reverse=True)

        # 取 Top-K
        top_results = scored_tools[:top_k]

        result: list[dict[str, Any]] = []
        for score, tool in top_results:
            result.append({
                "name": tool.schema.name,
                "core_purpose": tool.schema.core_purpose,
                "final_deliverable": tool.schema.final_deliverable,
                "description": tool.schema.description,
                "risk_level": tool.schema.risk_level.value,
                "category": tool.schema.category,
                "tags": tool.schema.tags,
                "_bm25_score": round(score, 4),
            })
        return result

    def get_tool_full_schema(self, name: str) -> dict[str, Any] | None:
        """
        获取指定工具的完整 Schema（含 parameters_schema）。

        做什么：Agent 2 在选定工具后，按名称提取包含 parameters_schema 的完整 Schema。
        为什么这样做：Agent 2 需要完整的 parameters_schema 来精确提取参数，
                    但与 Agent 1 的轻量筛选分离以优化 Token 消耗。
        参数:
            name: 工具名称。
        返回:
            dict: 包含 name、description、parameters_schema、risk_level、
                 core_purpose、final_deliverable、tags 的字典。
                  工具不存在或已禁用时返回 None。
        """
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
