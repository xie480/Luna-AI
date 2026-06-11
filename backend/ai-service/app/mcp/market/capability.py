"""
MCP 能力分析引擎。

做什么：解析远程 MCP Server 暴露的工具（Tool）、资源（Resource）和
        Prompt 列表，将其原始字段（name、description、parameters_schema）
        直接映射到 MCPToolSchema 的对应字段中。
        不进行 LLM 标签提取或 AI 总结——远程 Server 自带的描述就是
        最好的检索素材，直接用于 Agent 1 的混合检索。
为什么这样做：
    1. 成本考量：远程 MCP 生态中有数千甚至上万个 Server，每个 Server
       包含多个 tool，使用 LLM 为每个 tool 提取标签的成本不可接受。
    2. 数据原真性：远程 Server 的 tool 所带的 description 由工具开发者
       编写，是对工具能力最准确的描述。任何 AI 总结都可能引入偏差。
    3. 检索充分性：Agent 1 的 hybrid_search_tools() 同时对 name 和
       description 做 PG FTS 和向量检索，原始 description 已经包含了
       所有需要的关键词和语义信息。额外生成标签不会显著提升召回率。
    4. 实时性：远程 MCP 的描述可能会更新，依赖 LLM 预提取的标签会过期。
       直接基于原始字段做实时检索始终是最新的。
边界条件：部分 Server 可能不暴露能力清单，此时标记为 unknown。
"""

import re
from typing import Any
from app.mcp.types import MCPToolSchema, ToolRiskLevel


class CapabilityAnalyzer:
    """MCP 能力分析引擎。"""
    
    @staticmethod
    def build_tool_schema_from_remote(
        tool_def: dict[str, Any],
        server_category: str = "",
        endpoint_url: str = "",
    ) -> MCPToolSchema:
        """
        将远程 MCP 原始工具定义直接映射到 MCPToolSchema。
        
        做什么：零开销地映射远程 MCP 的原始 tool 定义到本地注册 Schema。
                不调用 LLM，不做 AI 总结，完全基于原始字段。
        为什么这样做：远程 Server 自带的 description 由工具作者编写，
                    已经足够用于混合检索。额外生成标签是过度工程。
        """
        name = tool_def.get("name", "")
        description = tool_def.get("description", "")
        
        # tags：仅从 name 做 camelCase/snake_case 分词提取（零成本）
        tags = set()
        if name:
            name_parts = re.sub(r'([A-Z])', r' \1', name).strip().lower().split()
            tags.update(name_parts)
            # 添加 snake_case 分词
            if '_' in name:
                tags.update(name.split('_'))
            # 添加 kebab-case 分词
            if '-' in name:
                tags.update(name.split('-'))
                
        # 清理空标签
        tags = {t for t in tags if t and len(t) > 1}
        
        return MCPToolSchema(
            name=name,
            description=description,
            parameters_schema=tool_def.get("inputSchema", {}),
            source="remote",
            endpoint_url=endpoint_url,
            tags=list(tags),
            core_purpose=description or name,
            final_deliverable=description,
            category=server_category,
            risk_level=ToolRiskLevel.L0,
            enabled=True,
        )

    @staticmethod
    def extract_capabilities(schema_response: dict[str, Any]) -> dict[str, Any]:
        """
        从远程 MCP Server 的 schema 响应中提取能力结构。
        
        schema_response 预期格式（类似 JSON-RPC 响应）:
        {
            "tools": [{"name": "...", "description": "...", "inputSchema": {...}}],
            "resources": [...],
            "prompts": [...]
        }
        """
        tools = schema_response.get("tools", [])
        resources = schema_response.get("resources", [])
        prompts = schema_response.get("prompts", [])
        
        return {
            "tools": tools,
            "resources": resources,
            "prompts": prompts,
            "tool_count": len(tools),
            "resource_count": len(resources),
            "prompt_count": len(prompts)
        }
