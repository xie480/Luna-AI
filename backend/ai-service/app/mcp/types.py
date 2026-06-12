"""
MCP 模块统一类型定义。

做什么：定义 MCP 工具协议涉及的所有 Pydantic 结构化输出模型，包括工具注册 Schema、
        风险等级枚举、工具执行结果。
        所有类型集中在此模块管理，避免与 workflow/context.py 耦合。
为什么这样做：严格遵循 agent.md 6.1 第2条"所有枚举与常量集中管理"的规范。
             MCP 相关的数据结构独立于 workflow 状态模型，便于独立维护和版本化。
边界条件：
    - ToolRiskLevel 的枚举值对应 Phase 13 中的 L0~L3 分级策略。
    - 所有模型使用 Pydantic v2 的 BaseModel，保证在 LLM 结构化输出中的兼容性。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# 风险等级枚举
# ============================================================


class ToolRiskLevel(str, Enum):
    """工具风险等级枚举。

    做什么：定义工具调用的风险等级分级，用于执行网关的权限控制。
            共分 L0~L3 四个等级，等级越高管控越严格。
    为什么这样做：Phase 13 权限治理需要按风险等级对工具进行分级管控。
                 本阶段（Phase 12）仅接入 L0 级低危工具。
    边界条件：
        - L0：低危，直接放行（如时间查询、天气查询）。
        - L1：中危，自动放行但记录审计（如只读文件读取）。
        - L2：高危，需要用户确认（如文件修改、网络请求）。
        - L3：极危，必须用户显式授权（如系统命令执行、数据删除）。
    """
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


# ============================================================
# 工具注册相关模型
# ============================================================


class MCPToolSchema(BaseModel):
    """单个工具的完整注册 Schema。

    做什么：定义向 MCPToolRegistry 注册工具时所需的全部元数据字段。
            包含工具名称、描述、参数 Schema、风险等级以及用于 Agent 1
            混合检索的增强标签和分类信息。
    为什么这样做：Agent 1 工具初筛阶段需要检索能力，tags、category、
                 use_case_examples、core_purpose 和 final_deliverable 字段
                 专为混合检索而设计。
    边界条件：
        - tool_id 由注册中心在注册时自动生成，调用方无需传入。
        - parameters_schema 必须符合 OpenAPI 3.0 Schema Object 规范。
        - enabled 为 False 的工具不会被混合检索召回。
    """
    name: str = Field(
        ..., min_length=1, max_length=128,
        description="工具唯一名称，用于在注册中心和路由中标识此工具。必须唯一。",
    )
    description: str = Field(
        ..., description="工具功能描述，说明工具的用途和使用场景。用于 Agent 2 的参数提取上下文和语义检索。",
    )
    parameters_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="工具的 JSON Schema 参数定义。必须符合 OpenAPI 3.0 Schema Object 规范。"
                    "用于 Agent 2 的精确参数提取和执行网关的参数校验。",
    )
    risk_level: ToolRiskLevel = Field(
        default=ToolRiskLevel.L0,
        description="工具风险等级。Phase 12 仅接入 L0 级低危工具，L1~L3 留待 Phase 13 治理。",
    )
    enabled: bool = Field(
        default=True,
        description="工具是否启用。False 表示工具已废弃或禁用，不会被检索和执行。",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="工具标签，用于 BM25/向量检索匹配。包含工具功能相关的关键词。",
    )
    category: str = Field(
        default="",
        description="工具分类：utility / data_access / system / communication。用于检索筛选。",
    )
    use_case_examples: list[str] = Field(
        default_factory=list,
        description="典型使用场景示例，用于语义检索匹配。例如：['现在几点', '今天几号', '目前时间']。",
    )
    core_purpose: str = Field(
        default="",
        description="一句话核心用途，用于 Agent 1 Memory Prompt 轻量注入。"
                    "需要简洁概括工具能做什么。",
    )
    final_deliverable: str = Field(
        default="",
        description="工具调用最终交付物描述，用于 Agent 1 决策判断。"
                    "描述工具调用后返回给用户的数据格式和内容。",
    )
    source: str = Field(
        default="local",
        description="工具来源：local（代码注册）/ remote（市场接入）。"
                    "local 工具不可通过 API 注册或注销。",
    )
    endpoint_url: str = Field(
        default="",
        description="远程 MCP 的 Endpoint URL。仅 source=remote 时有效，"
                    "local 工具此字段为空。",
    )
    remote_instance_id: str = Field(
        default="",
        description="关联的远程实例 ID（关联 mcp_remote_instances.id）。"
                    "仅 source=remote 时有效。",
    )
    auth_type: str = Field(
        default="none",
        description="鉴权类型：none / bearer / api_key / basic。"
                    "仅 source=remote 时有效。",
    )


# ============================================================
# 工具执行结果模型
# ============================================================


class MCPToolResult(BaseModel):
    """工具执行结果。

    做什么：封装 execute_tool() 返回的完整执行结果，包含执行状态、输出、
            错误信息、耗时及审计所需字段。
    为什么这样做：统一的执行结果模型便于下游 Skill 执行节点解析，
                 同时也为审计回放提供结构化数据。
    边界条件：
        - success=False 时，error_message 必须非空。
        - output_text 最大长度为 4096 字符，超出截断并标记 [truncated]。
        - execution_id 由 Gateway 在执行时生成，用于审计回放。
    """
    success: bool = Field(
        ..., description="工具执行是否成功。true 表示正常返回，false 表示发生错误。"
    )
    output_text: str = Field(
        default="", max_length=4096,
        description="工具返回的输出文本。超出 4096 字符的部分截断并追加 [truncated] 标记。",
    )
    error_message: str = Field(
        default="",
        description="工具执行的错误信息。success=False 时此字段必填。",
    )
    execution_id: str = Field(
        default="",
        description="工具执行记录的唯一 ID，使用雪花算法生成。用于审计回放。",
    )
    latency_ms: int = Field(
        default=0, ge=0,
        description="工具执行耗时，单位毫秒。",
    )
    risk_level: str = Field(
        default="L0",
        description="本次执行的工具风险等级。",
    )
