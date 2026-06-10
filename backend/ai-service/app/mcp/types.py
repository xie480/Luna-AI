"""
MCP 模块统一类型定义。

做什么：定义 MCP 工具协议涉及的所有 Pydantic 结构化输出模型，包括工具注册 Schema、
        风险等级枚举、工具执行结果、三 Agent 协作的输出模型以及输入重构判定结果。
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
        ..., max_length=2048,
        description="工具功能描述，说明工具的用途和使用场景。用于 Agent 2 的参数提取上下文和语义检索。",
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
        default="", max_length=512,
        description="一句话核心用途，用于 Agent 1 Memory Prompt 轻量注入。"
                    "需要简洁概括工具能做什么。",
    )
    final_deliverable: str = Field(
        default="", max_length=512,
        description="工具调用最终交付物描述，用于 Agent 1 决策判断。"
                    "描述工具调用后返回给用户的数据格式和内容。",
    )


# ============================================================
# 工具执行结果模型
# ============================================================


class MCPToolResult(BaseModel):
    """工具执行结果。

    做什么：封装 execute_tool() 返回的完整执行结果，包含执行状态、输出、
            错误信息、耗时及审计所需字段。
    为什么这样做：统一的执行结果模型便于 Agent 3 意图对齐时解析，
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


# ============================================================
# 输入重构判定结果
# ============================================================


class MCPToolJudgment(BaseModel):
    """输入重构节点输出的工具调用判定结果。

    做什么：在输入重构节点中，LLM 以结构化输出方式判定是否需要调用工具，
            并输出用于 Tool RAG 检索的关键词。
    为什么这样做：将工具判定的逻辑嵌入输入重构流程中，不额外增加模型调用次数。
                同时为 Agent 1 提供 keyword 数组用于混合检索。
    边界条件：
        - need_tool=False 时，reason 必须给出明确原因。
        - keywords 至少包含一个关键词，建议 1~5 个。
    """
    need_tool: bool = Field(
        ..., description="是否需要调用工具。true 表示需要，false 表示无需。"
    )
    reason: str = Field(
        ..., description="具体原因说明，解释为什么判定需要或不需要工具调用。用于审计与调试。"
    )
    keywords: list[str] = Field(
        ..., description="用于 Tool RAG 检索的关键词数组。Agent 1 将以此作为混合检索的 query。"
    )


# ============================================================
# Agent 1：工具初筛 — 工具链计划
# ============================================================


class ToolChainStep(BaseModel):
    """工具链中的单个步骤。

    做什么：定义工具链中每一步的工具名称和调用目的。
    为什么这样做：Agent 1 需要明确标注每个工具的调用顺序和目的，
                 Agent 2 循环引擎按此顺序逐轮执行。
    """
    tool_name: str = Field(
        ..., description="要调用的工具名称。必须来自候选工具列表。"
    )
    purpose: str = Field(
        ..., max_length=512,
        description="调用该工具的目的。说明在此步骤中期望从该工具获得什么数据或能力。"
    )


class ToolChainPlan(BaseModel):
    """Agent 1：工具初筛结果 — 工具链计划。

    做什么：封装工具初筛 Agent 的输出，包含一个有序的工具调用链。
            每个工具按执行顺序排列，数组索引即为调用顺序。
    为什么这样做：Agent 1 评估用户需求后，输出有序工具链。
                 单个工具场景下 tool_chain 仅含一个元素；
                 多工具场景下按顺序排在 tool_chain 数组中。
    边界条件：
        - tool_chain 中的所有 tool_name 必须来自候选工具列表。
        - tool_chain 为空数组时，no_suitable_tool 必须为 true。
        - 连续性保证：Agent 2 循环引擎按 0->1->2->... 顺序执行。
        - tool_chain 最大长度限制为 10，防止工具链无限膨胀。
    """
    tool_chain: list[ToolChainStep] = Field(
        ..., min_length=0, max_length=10,
        description="有序的工具调用链。每个步骤标注了工具名称和调用目的。"
                    "数组索引即为执行顺序（0→1→2→...）。"
                    "空数组表示无需调用任何工具。",
    )
    reasoning: str = Field(
        ..., description="初筛推理过程。解释为什么选择这些工具、为什么按此顺序排列、"
                        "以及每个工具在当前步骤中解决用户需求的哪一部分。"
    )
    no_suitable_tool: bool = Field(
        default=False,
        description="标记为 true 表示候选工具池中无任何工具能匹配用户需求。"
                    "此时 tool_chain 应为空数组。",
    )


# ============================================================
# Agent 2：Tool Calling 结果（单轮输出）
# ============================================================


class ToolCallingResult(BaseModel):
    """Agent 2：Tool Calling 结果（单轮输出）。

    做什么：封装 Tool Calling Agent 的单轮输出，包含当前工具的最终参数 JSON。
    为什么这样做：每轮执行只处理工具链中的一个工具，结果由上层节点
                循环调度并注入前序结果。这种设计使单轮逻辑保持简单纯粹。
    边界条件：
        - parameters 必须严格遵循当前工具的 parameters_schema 定义。
        - call_parameters_failed=True 时上层节点终止工具链。
    """
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="调用当前工具所需的最终参数键值对，严格遵循当前工具的 parameters_schema。",
    )
    parameter_explanation: str = Field(
        default="",
        description="参数提取过程的说明，解释每个参数值是如何从用户输入、上下文或前序结果中提取的。",
    )
    call_parameters_failed: bool = Field(
        default=False,
        description="标记为 true 表示当前工具的参数提取失败，上层应终止工具链。",
    )
    failure_reason: str = Field(
        default="",
        description="参数提取失败的具体原因。call_parameters_failed=True 时必须填写。",
    )


# ============================================================
# Agent 3：意图对齐结果
# ============================================================


class IntentAlignmentResult(BaseModel):
    """Agent 3：意图对齐结果。

    做什么：封装意图对齐 Agent 的输出，包含校准后的最终文本和质量判定。
    为什么这样做：Agent 3 作为输出质量门禁，确保工具结果在注入下游 Prompt 前
                已经过意图对齐校验，避免原始数据中的噪声或不相关内容污染最终回答。
    边界条件：
        - calibrated_output 禁止包含工具返回中不存在的虚构信息。
        - quality_issue 为 true 时，下游 Context Governance 节点可据此调整权重。
        - calibrated_output 的最大长度为 4096 字符，超出部分截断。
    """
    calibrated_output: str = Field(
        ..., max_length=4096,
        description="经过校准、打磨与逻辑重组后的最终输出文本。必须基于工具返回数据，禁止编造。",
    )
    quality_issue: bool = Field(
        default=False,
        description="标记为 true 表示结果存在质量问题（如数据不完整、信息过时、无法回答用户问题）。",
    )
    quality_description: str = Field(
        default="",
        description="质量问题的具体描述。如果 quality_issue=false，此字段说明校准过程中做了哪些优化。",
    )
    data_source: str = Field(
        default="",
        description="数据来源说明，如调用的工具名称及其返回数据的简要范围。",
    )
