"""
MCP Skill 模块统一类型定义。

做什么：定义 Skill 初筛、加载、执行三阶段涉及的 Pydantic 结构化输出模型。
为什么这样做：所有 Skill 相关的数据结构独立于 workflow 状态模型，
             便于独立维护和版本化。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SkillAgentPhase(str, Enum):
    """Skill Agent 执行阶段枚举。

    做什么：标识 Skill 三阶段 Agent 的当前执行阶段，用于前端状态展示。
    """
    IDLE = "idle"
    SKILL_SCREENING = "skill_screening"
    SKILL_LOADING = "skill_loading"
    SKILL_RESOURCE_LOADING = "skill_resource_loading"  # 新增：资源加载阶段
    SKILL_EXECUTION = "skill_execution"
    SKILL_FALLBACK = "skill_fallback"
    SKILL_FINAL_FAIL = "skill_final_fail"
    COMPLETED = "completed"
    DEGRADED = "degraded"


# ============================================================
# Agent 1：Skill 初筛输出
# ============================================================


class SkillChainPlan(BaseModel):
    """Agent 1：Skill 初筛结果 — Skill 链计划。

    做什么：封装 Skill 初筛 Agent 的输出，含选中的 Skill ID。
            此时 Skill 处于未展开状态，仅作为能力指针。
    为什么这样做：Agent 1 只做 Skill 级别的选择决策，
                 不加载具体工具和资源，优化 Token 消耗。
    边界条件：
        - selected_skill_ids 必须来自候选 Skill 列表。
        - no_suitable_skill=True 时 selected_skill_ids 为空列表。
        - 支持多个 Skill 的组合（最多 3 个）。
    """
    selected_skill_ids: list[str] = Field(
        ..., min_length=0, max_length=3,
        description="选中的 Skill ID 列表（按优先级排序）。"
                    "空列表表示无需使用任何 Skill。最多支持 3 个 Skill 组合。",
    )
    reasoning: str = Field(
        ..., description="初筛推理过程。解释为什么选择这些 Skill、"
                        "以及每个 Skill 解决用户需求的哪一部分。",
    )
    no_suitable_skill: bool = Field(
        default=False,
        description="标记为 true 表示候选 Skill 中无任何技能匹配用户需求。"
                    "此时 selected_skill_ids 应为空列表。",
    )


# ============================================================
# Agent 2：Skill 加载输出 — 执行计划（v3.0：单步 state 结构）
# ============================================================
# 设计变更（v3.0）：
# - tools 从数组改为单字段 tool：一个 state 只执行一个工具，减少复杂度
# - resource 从数组改为单字段 resource：一个 state 只加载一个资源
# - 新增 goal 字段：每个 state 需要达成什么目标，用于 Agent 3 判断上下文
# - 移除 execution_order：states 字典的 key 顺序（state1 > state2）即为执行顺序
# - 移除 total_expected_steps：由业务代码通过 len(states) 统计总步数


class ExecutionState(BaseModel):
    """执行计划中的单个 State（v3.0：单工具单资源版）。

    做什么：定义执行计划中每个技能的执行步骤，一个 state 对应一步。
            每步仅执行一个工具（tool），可选关联一个资源（resource）。
    为什么这样做：v3.0 简化设计，一个 state = 一个步骤，
                业务代码通过统计 state 数量即可得到总步数。
    """
    skill: str = Field(
        ..., description="技能名称，必须来自选中的技能信息中的技能名称。"
    )
    tool: str = Field(
        default="",
        description="此步需要使用的工具名称（单工具）。"
                    "必须来自 Skill 展开后的工具列表中的 name 字段。"
                    "如果此步无需执行工具，设为空字符串。",
    )
    resource: str = Field(
        default="",
        description="此步需要加载的资源名称（单资源）。"
                    "必须来自 Skill 展开后的资源列表中的 name 字段。"
                    "如果此步无需加载资源，设为空字符串。",
    )
    goal: str = Field(
        default="",
        description="此步的执行目标。说明该步骤使用该工具/资源的目的意图，"
                    "例如「搜索用户提到的文档」、「翻译英文段落为中文」。"
                    "Agent 3 将此字段作为上下文判断能否继续执行。",
    )


class ExecutionPlan(BaseModel):
    """Agent 2：Skill 加载结果 — 执行计划（v3.0 单步 state 结构）。

    做什么：封装 Skill 加载 Agent 的输出，以 state 维度组织执行步骤。
            每个 state 对应一个执行步骤（一个工具 + 可选一个资源）。
            无 execution_order 字段，states 字典的 key 顺序即为执行顺序。
    为什么这样做：v3.0 简化设计中每个 state = 1 步，
                业务代码通过统计 state 数量得到总步数。
    边界条件：
        - states 至少有一个非空元素。
        - states 中使用的 resource/tool 名称必须来自聚合列表。
        - states 按 state1, state2, ... 顺序执行（key 的字典顺序）。
    """
    states: dict[str, ExecutionState] = Field(
        ..., description="执行状态字典。key 为 state_key（如 state1、state2），"
                        "value 包含该 state 的技能名称、工具名称、资源名称和执行目标。"
                        "系统按 key 的字典顺序（state1 < state2 < ...）驱动执行。"
                        "至少包含一个 state。",
    )
    reasoning: str = Field(
        ..., description="加载推理过程，解释为什么选择这些技能和工具、"
                        "每个 state 的资源配置和工具选择，"
                        "以及为什么按此顺序执行。",
    )


# ============================================================
# Agent 3：Skill 执行 — 单步工具执行结果
# ============================================================


class ToolExecutionResult(BaseModel):
    """单步工具执行结果。

    做什么：封装单步工具执行的完整结果。
    """
    tool_name: str = Field(..., description="执行的工具名称。")
    success: bool = Field(..., description="执行是否成功。")
    output_text: str = Field(default="", description="工具执行输出。")
    error_message: str = Field(default="", description="错误信息。success=False 时必填。")
    resource_context_injected: list[str] = Field(
        default_factory=list,
        description="注入到该工具 Prompt 的资源名称列表。",
    )
    latency_ms: int = Field(default=0, description="执行耗时（毫秒）。")


class ResourceLoadResult(BaseModel):
    """单步资源加载结果。

    做什么：封装子 Agent 资源加载的完整结果。
    """
    resource_name: str = Field(..., description="加载的资源名称。")
    success: bool = Field(..., description="加载是否成功。")
    extracted_info: str = Field(default="", description="子 Agent 提取的关键信息。")
    line_numbers: list[int] = Field(
        default_factory=list,
        description="提取信息在文件中的行号范围。用于审计回溯。",
    )
    error_message: str = Field(default="", description="加载错误信息。")
    latency_ms: int = Field(default=0, description="加载耗时（毫秒）。")


# ============================================================
# 退回与终止状态
# ============================================================


class FallbackState(BaseModel):
    """退回状态 — 子 Agent 提取与压缩的结果。

    做什么：当 Agent 3 发现当前 Skill 计划不足以完成任务时，
            子 Agent 对原执行计划各步骤的执行状态进行整合，
            生成完整的执行快照后返回此状态，退回至 Agent 1 重新筛选。
            执行快照格式（v3.0）：
            {"state1": {"skill": "search", "resource": "...", "tool": "...", "goal": "...",
                        "status": "已执行", "result": "..."},
             "state2": {"skill": "code", "resource": "...", "tool": "...", "goal": "...",
                        "status": "未执行", "result": ""}}
    """
    execution_snapshot: dict[str, dict[str, Any]] = Field(
        ..., description="原执行计划的完整快照。key 为 state_key，value 包含"
                        "skill（技能名称）、resource（资源名）、"
                        "tool（工具名）、goal（执行目标）、"
                        "status（执行状态字符串）、"
                        "result（执行结果摘要）。"
                        "此结构供退回后的 Agent 1 分析失败原因并重新筛选技能。",
    )


class FinalFailState(BaseModel):
    """最终失败状态 — 跳至主 Chat LLM。

    做什么：当达到最大执行步长或确认无法实现目标时，
            提取失败理由，直接跳至主 Chat LLM 节点说明情况。
    """
    failure_reason: str = Field(
        ..., description="失败理由说明，将作为上下文注入主 Chat LLM。"
    )
    partial_results: list[ToolExecutionResult] = Field(
        default_factory=list,
        description="已执行成功的部分工具结果，供主 LLM 参考。",
    )
    step_count_used: int = Field(
        ..., description="已使用的执行步数。",
    )
    max_steps_reached: bool = Field(
        default=False,
        description="是否达到最大执行步长。",
    )
