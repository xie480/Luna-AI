"""Phase 9 Plan-State-Node 工作流内核 — DAG 数据结构定义。

做什么：定义 DAG 引擎运行时所需的所有数据类型，包括 Plan 定义、State 运行时、
        原子节点定义、全局目标、预算等。
为什么这样做：所有 DAG 相关实体集中管理，遵循 agent.md 禁止魔法字符串的规定。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.utils.snowflake import generate_string_id


# ===========================================================================
# DAG 节点类型枚举
# ===========================================================================


class DagNodeType(str, Enum):
    """DAG 原子节点类型枚举。

    做什么：定义 State 内部 Step 中可使用的 5 种原子节点类型。
    为什么这样做：固定类型比 JIT 动态生成更容易实现、调试和理解。
    """

    RESOURCE_LOADING = "resource_loading"       # 资源加载节点
    TOOL_EXECUTE = "tool_execute"               # MCP 工具执行节点
    DATA_TRANSFORM = "data_transform"           # 数据转换节点（纯 LLM 推理）
    LONG_TERM_MEMORY = "long_term_memory"       # 长期记忆检索节点
    KNOWLEDGE_RAG = "knowledge_rag"             # 知识库 RAG 检索节点


class DagNodeStatus(str, Enum):
    """DAG 节点状态枚举。

    做什么：标识 DAG 引擎中每个节点/State 的运行状态。
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    PENDING_USER_APPROVAL = "PENDING_USER_APPROVAL"


class DagCursorRoute(str, Enum):
    """Cursor 路由结果枚举。

    做什么：标识 Plan + Cursor 循环中路由函数的决策结果。
    """

    CONTINUE = "continue"         # cursor < len(states)，继续下一个 State
    COMPLETE = "complete"         # 全部完成，退出引擎
    TERMINATE = "terminate"       # 终止（评估失败或预算耗尽）


# ===========================================================================
# 全局目标
# ===========================================================================


class GlobalObjective(BaseModel):
    """全局总目标 — 用户对最终结果的期望。

    做什么：描述整个 Plan 的最终交付物要求。
    为什么这样做：Plan 生成 Agent 需要知道"终点在哪里"才能合理拆分 State。
    """

    overall_goal: str = Field(
        ...,
        description="全局总目标描述。例如：'写一份关于XX公司的2023-2024年财务分析报告'。",
    )
    success_criteria: str = Field(
        ...,
        description="实现标准/验收标准。例如：'报告需包含营收趋势、利润率分析、同比环比数据'。",
    )
    output_format: str = Field(
        default="",
        description="期望的输出格式。例如：'Markdown 格式，分章节'。",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="约束条件列表。例如：['数据来源需标注', '中文撰写']。",
    )


# ===========================================================================
# Skill 元数据
# ===========================================================================


class SkillBrief(BaseModel):
    """Skill 简介 — 注入到 Plan 生成 Prompt 中。

    做什么：提供 Skill 的元数据摘要，不包含内部实现细节。
    为什么这样做：让 Plan 生成 Agent 知道有哪些能力可用，
                  从而生成基于实际能力的 State 序列。
    """

    skill_name: str
    description: str
    tool_names: list[str] = Field(default_factory=list)
    risk_levels: dict[str, str] = Field(
        default_factory=dict,
        description="工具名到风险等级的映射，如 {'web_search': 'L0'}。",
    )
    capability_tags: list[str] = Field(
        default_factory=list,
        description="能力标签列表，如 ['search', 'file_io', 'web']。",
    )


# ===========================================================================
# 预算守门
# ===========================================================================


class StateBudget(BaseModel):
    """State 级别预算守门。

    做什么：约束单个 State 的最大工具调用次数。
    """

    max_tool_calls: int = Field(default=10, ge=1)


class GlobalBudget(BaseModel):
    """Plan 级别全局预算守门。

    做什么：约束整个 Plan 的最大工具调用总次数。
    """

    max_total_tool_calls: int = Field(default=50, ge=1)


# ===========================================================================
# 完成标准
# ===========================================================================


class CompletionCriterion(BaseModel):
    """完成标准定义。

    做什么：描述 State 的可量化验收条件。
    """

    field: str
    operator: str = Field(
        description="比较运算符：>=, ==, contains, not_empty, len_gt。",
    )
    value: Any


# ===========================================================================
# Plan 与 State 定义
# ===========================================================================


class OverallState(BaseModel):
    """宏观状态定义。

    做什么：描述 Plan 中单个 State 的职责、目标、完成标准和依赖关系。
    设计原则：每个 State 只承担单一职责，按职责类型（而非难易度）进行划分。
    """

    state_id: str = Field(default_factory=generate_string_id)
    order_index: int
    responsibility: str = Field(
        default="",
        description="该 State 承担的唯一职责类型。"
                    "如：信息收集、数据分析、内容生成、知识检索、格式转换、"
                    "验证校对、总结归纳、方案设计、代码实现、测试验证。"
                    "每个 State 只能有一种职责，禁止将多种职责混在一个 State 中。",
    )
    intent: str
    goal: str
    completion_criteria: list[CompletionCriterion] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    pre_allocated_skills: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Plan 阶段预分配的 Skill 筛选结果列表。"
                    "每个元素包含 skill_name 和 relevance_reason。"
                    "当此列表非空时，Executor 子图中的 SkillScreening 节点"
                    "将跳过 LLM 调用，直接使用预分配结果，以减少 token 消耗。"
                    "由 Plan 生成 Agent 在生成 Plan 时同步输出。",
    )

    @field_validator("pre_allocated_skills", mode="before")
    @classmethod
    def _coerce_pre_allocated_skills(cls, v: Any) -> list[dict[str, Any]]:
        """防御性校验：LLM 可能返回纯字符串名称（如 'web_search'）而非字典格式，
           需要自动规整为标准字典格式（{"skill_name": "web_search", "relevance_reason": ""}）。
        """
        if not isinstance(v, list):
            return []
        coerced: list[dict[str, Any]] = []
        for item in v:
            if isinstance(item, dict):
                coerced.append(item)
            elif isinstance(item, str):
                # LLM 返回了纯字符串，包装为标准格式
                coerced.append({"skill_name": item, "relevance_reason": ""})
            else:
                # 兜底：跳过无法识别的类型
                continue
        return coerced

    budget: StateBudget = Field(default_factory=StateBudget)


class PlanDefinition(BaseModel):
    """顶级 Plan 容器。

    做什么：承载整个 Plan 的元信息、State 列表和预算。
    """

    plan_id: str = Field(default_factory=generate_string_id)
    session_id: str = ""
    trace_id: str = ""
    original_intent: str = ""
    global_objective: GlobalObjective = Field(
        default_factory=lambda: GlobalObjective(
            overall_goal="",
            success_criteria="",
        ),
    )
    states: list[OverallState] = Field(default_factory=list)
    global_budget: GlobalBudget = Field(default_factory=GlobalBudget)
    created_at_ms: int = 0


# ===========================================================================
# Step 与原子节点定义
# ===========================================================================


class AtomicNodeDefinition(BaseModel):
    """原子节点定义。

    做什么：描述 State 内部 Step 中一个可执行的原子操作。
    """

    node_id: str = Field(default_factory=generate_string_id)
    node_type: DagNodeType
    skill_name: str | None = Field(
        default=None,
        description="tool_execute / resource_loading 时非空。",
    )
    tool_name: str | None = Field(
        default=None,
        description="tool_execute 时非空。",
    )
    resource_name: str | None = Field(
        default=None,
        description="resource_loading 时非空。",
    )
    parameter_hint: str = Field(
        default="",
        description="tool_execute 时的参数提取提示。",
    )
    transform_instruction: str = Field(
        default="",
        description="data_transform 时的转换指令。",
    )
    query_text: str = Field(
        default="",
        description="long_term_memory / knowledge_rag 时的查询文本。",
    )
    depends_on: list[str] = Field(default_factory=list)
    gating_required: bool = False


class StepDefinition(BaseModel):
    """Step 定义 — State 内部的一个执行步骤。

    做什么：描述 State 内部一组可以并行执行的原子节点。
    """

    step_id: str = Field(default_factory=generate_string_id)
    step_index: int
    nodes: list[AtomicNodeDefinition] = Field(default_factory=list)
    description: str = ""

    # === 新增：依赖声明 ===
    depends_on: list[str] = Field(
        default_factory=list,
        description="依赖的前置 Step ID 列表。"
                    "为空时表示可与同级 Step 并行执行。",
    )
    execution_mode: str = Field(
        default="parallel",
        description="节点内原子节点的执行模式：parallel（gather）/ sequential（逐个）。",
    )

# ===========================================================================
# State 运行时状态
# ===========================================================================


class StateRuntimeState(BaseModel):
    """State 运行时状态。

    做什么：承载单个 State 在执行过程中的全部运行时数据。
    """

    state_id: str
    status: DagNodeStatus = DagNodeStatus.PENDING
    responsibility: str = Field(
        default="",
        description="该 State 承担的唯一职责类型。",
    )
    intent: str = ""
    goal: str = ""

    # Skill 初筛结果
    selected_skills: list[dict[str, Any]] = Field(default_factory=list)

    # Step Plan
    step_plan: list[dict[str, Any]] = Field(default_factory=list)

    # 分区写入模式
    partitioned_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # State 汇总输出
    merged_output: dict[str, Any] = Field(default_factory=dict)

    # 执行统计
    steps_completed: int = 0
    steps_total: int = 0
    nodes_succeeded: int = 0
    nodes_failed: int = 0

    # 评估结果
    evaluation_result: dict[str, Any] | None = None

    # 预算
    budget_remaining: StateBudget = Field(default_factory=StateBudget)
    budget_exhausted: bool = False

    # 错误信息
    error_messages: list[str] = Field(default_factory=list)


# ===========================================================================
# 工具执行结果
# ===========================================================================


class ToolExecuteResult(BaseModel):
    """MCP 工具执行结果。

    做什么：承载单个 MCP 工具调用的执行结果。
    """

    node_id: str = ""
    skill_name: str = ""
    tool_name: str = ""
    success: bool = False
    tool_output: str = ""
    error_message: str = ""
    tool_parameters: dict[str, Any] = Field(default_factory=dict)
    gating_rejected: bool = False
    user_feedback: str = ""
    latency_ms: int = 0


# ===========================================================================
# State 评估结果
# ===========================================================================


class StateEvaluationResult(BaseModel):
    """State 评估结果。

    做什么：承载 State 评估节点的输出。
    """

    state_satisfied: bool = Field(
        ...,
        description="State 的执行内容是否满足 goal 和 completion_criteria。",
    )
    evaluation_reason: str = Field(
        default="",
        description="评估判断的详细理由。",
    )
    gap_analysis: str = Field(
        default="",
        description="当前结果与目标之间的差距分析。satisfied=True 时为空。",
    )
    suggestion: str = Field(
        default="",
        description="改进建议，供 Plan 重构时参考。satisfied=True 时为空。",
    )
    criteria_checklist: list[dict[str, Any]] = Field(
        default_factory=list,
        description="逐条 completion_criteria 的验证结果。",
    )
    check: str = Field(
        default="",
        description="系统校验推演过程，包含标准对齐、证据充分性、改进建议等维度的自检结果。",
    )


# ===========================================================================
# Plan 汇总结果
# ===========================================================================


class StateSummary(BaseModel):
    """单个 State 的执行摘要。

    做什么：封装单个 State 的执行结果摘要。
    """

    state_id: str = ""
    responsibility: str = Field(
        default="",
        description="该 State 承担的职责类型。",
    )
    intent: str = ""
    goal: str = ""
    status: DagNodeStatus = DagNodeStatus.SUCCEEDED
    result_summary: str = ""
    key_facts: list[str] = Field(default_factory=list)


class PlanSummaryResult(BaseModel):
    """Plan 汇总结果。

    做什么：承载整个 Plan 的执行结果汇总。
    """

    plan_id: str = ""
    total_states: int = 0
    succeeded_states: int = 0
    degraded_states: int = 0
    failed_states: int = 0
    state_summaries: list[StateSummary] = Field(default_factory=list)
    overall_result: str = ""
    execution_highlights: list[str] = Field(default_factory=list)
    execution_issues: list[str] = Field(default_factory=list)


# ===========================================================================
# 终止上下文
# ===========================================================================


class TerminationContext(BaseModel):
    """终止上下文 — 注入到主 Chat LLM 的 Prompt 中。

    做什么：封装终止原因和已执行的部分结果。
    为什么这样做：即使 Plan 执行失败，用户也需要得到有意义的响应，
                  而不是沉默或错误码。
    """

    terminated: bool = False
    reason: str = ""
    partial_results: str = ""
    suggestion: str = ""


# ===========================================================================
# Plan 重构上下文
# ===========================================================================


class ReplanContext(BaseModel):
    """Plan 重构上下文。

    做什么：承载 Plan 重构节点所需的全部上下文。
    设计原则：包含失败 State 的完整职责信息，
              确保重构时能准确理解原始职责定位。
    """

    failed_state_id: str = ""
    failed_state_responsibility: str = Field(
        default="",
        description="失败 State 的职责类型。",
    )
    failed_state_intent: str = Field(
        default="",
        description="失败 State 的意图描述。",
    )
    failed_state_goal: str = ""
    failed_state_result: str = ""
    evaluation_reason: str = ""
    gap_analysis: str = ""
    suggestion: str = ""
    completed_states: list[dict[str, Any]] = Field(default_factory=list)
    remaining_states: list[dict[str, Any]] = Field(default_factory=list)
    global_objective: GlobalObjective = Field(
        default_factory=lambda: GlobalObjective(
            overall_goal="",
            success_criteria="",
        ),
    )


# ===========================================================================
# 简化输入重构结果
# ===========================================================================


class UnresolvedPronoun(BaseModel):
    """未解析代词。

    做什么：记录在当前短期会话上下文中无法找到明确指代目标的代词。
    """

    original: str = Field(..., description="原始代词文本。")
    reason: str = Field(..., description="无法消歧的原因，例如：短期上下文缺失。")


class SimplifiedReconstruction(BaseModel):
    """Plan-State-Node 路径的简化输入重构结果。

    做什么：只做代词消歧和未解析代词标记，不做路由决策。
    为什么这样做：路由决策权交给全局 Plan 生成节点，
                  输入重构只负责清洗文本。
    """

    disambiguated_text: str = Field(
        ...,
        description="消歧后的完整文本。"
                    "如果能在短期记忆中找到指代对象，会将其替换；"
                    "如果找不到，会用 [未知实体] 等占位符标记。",
    )
    unresolved_pronouns: list[UnresolvedPronoun] = Field(
        default_factory=list,
        description="在当前短期会话上下文中无法找到明确指代目标的代词列表。",
    )
    emotion_state: dict[str, Any] = Field(
        default_factory=dict,
        description="用户情绪状态，保留给下游 ESM 使用。",
    )


# ===========================================================================
# DAG 引擎全局状态（LangGraph State）
# ===========================================================================


class DagEngineState(BaseModel):
    """DAG 引擎全局状态 — Plan + Cursor 模式的核心。

    做什么：承载 Plan + Cursor 的全部运行时数据。
    为什么这样做：LangGraph State 是图节点间传递数据的唯一通道，
                  Plan 和 Cursor 都放在 State 中，LangGraph 自动处理
                  Checkpoint 持久化。
    """

    # === Plan + Cursor 核心 ===
    plan: PlanDefinition = Field(default_factory=PlanDefinition)
    cursor: int = Field(default=0, ge=0, description="当前执行到第几个 State。")
    terminated: bool = False

    # === 全局目标 ===
    global_objective: GlobalObjective = Field(
        default_factory=lambda: GlobalObjective(
            overall_goal="",
            success_criteria="",
        ),
    )

    # === Skill 元数据 ===
    skill_briefs: list[dict[str, Any]] = Field(default_factory=list)

    # === 输入上下文 ===
    disambiguated_text: str = ""
    unresolved_pronouns: list[dict[str, Any]] = Field(default_factory=list)
    session_context: dict[str, Any] = Field(default_factory=dict)
    user_profile: dict[str, Any] = Field(default_factory=dict)
    memory_context: str = ""

    # === 运行时状态 ===
    state_runtimes: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="state_id -> StateRuntimeState 序列化。",
    )
    global_merged_context: dict[str, Any] = Field(
        default_factory=dict,
        description="所有已完成 State 的汇总上下文。",
    )
    budget_consumed: dict[str, int] = Field(
        default_factory=lambda: {"tool_calls": 0},
        description="预算消耗统计。",
    )

    # === 终止信息 ===
    termination_reason: str = ""
    termination_state_id: str = ""

    # === Plan 重构计数 ===
    plan_replan_count: int = Field(
        default=0,
        description="整个 Plan 生命周期内的重构次数，最多允许 1 次。",
    )

    # === Plan 汇总结果 ===
    plan_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="PlanResultSummaryResult 序列化。",
    )

    # === Executor 子图运行时状态 ===
    # 做什么：存储 Executor 子图（skill_screening → step_plan → step_executor → state_evaluator）
    #         的中间运行时数据，供子图内 4 个节点跨调用共享。
    # 为什么这样做：LangGraph 子图的每个节点调用是独立的，需要通过 State 传递中间数据。
    executor_runtime: dict[str, Any] = Field(
        default_factory=dict,
        description="DagExecutorRuntimeState 的序列化结果。"
                    "由 Executor 子图内部节点读写，外层图不直接访问。",
    )

    # === 原始工作流状态引用 ===
    # 做什么：DAG 引擎需要访问原始 ChatWorkflowState 中的字段
    #         （trace_id、session_id 等），通过序列化字典传递。
    workflow_state: dict[str, Any] = Field(
        default_factory=dict,
        description="原始 ChatWorkflowState 的序列化副本。"
                    "包含 runtime、input_payload、session_state 等。",
    )

    # === Phase 13: Gating 审批挂起状态 ===
    # 做什么：当 L2/L3 工具触发 Gating 审批时，标记子图为挂起状态。
    #         gating_suspended=True 时，子图暂停执行，等待用户审批结果。
    # 为什么这样做：审批挂起不是错误，是一种正常的业务状态。
    #              需要在 DagEngineState 中显式记录，以便路由和恢复逻辑正确处理。
    gating_suspended: bool = Field(
        default=False,
        description="Phase 13：当前 DAG 是否处于 Gating 审批挂起状态。"
                    "True 时表示有 L2/L3 工具正在等待用户审批。",
    )
    gating_pending_node_ids: list[str] = Field(
        default_factory=list,
        description="Phase 13：处于 Gating 审批挂起状态的节点 ID 列表。",
    )

    class Config:
        """允许任意类型嵌套。"""
        arbitrary_types_allowed = True


# ===========================================================================
# Executor 节点输出（Phase 9 重构新增）
# ===========================================================================


class DagExecutorOutput(BaseModel):
    """Executor 节点输出 — 写入 DagEngineState。

    做什么：承载单次 State 执行的产出，供 Router 和下一轮 Executor 使用。
    为什么这样做：在 Plan + Cursor 子图中，Executor 节点每次只执行一个 State，
                  需要一个中间类型来跟踪本次执行的状态和 cursor 推进情况。
    """

    state_id: str = Field(
        default="",
        description="本次执行的 State ID。",
    )
    status: DagNodeStatus = Field(
        default=DagNodeStatus.PENDING,
        description="本次 State 执行的最终状态。",
    )
    state_runtime: dict[str, Any] = Field(
        default_factory=dict,
        description="本次 State 的 StateRuntimeState 序列化结果。",
    )
    cursor_advanced: bool = Field(
        default=False,
        description="cursor 是否已推进（评估通过时为 True）。",
    )


# ===========================================================================
# Executor 子图运行时状态（Phase 9 子图拆解新增）
# ===========================================================================


class DagExecutorRuntimeState(BaseModel):
    """Executor 子图运行时状态 — 在子图节点间传递中间数据。

    做什么：承载 Executor 子图内部 4 个节点（SkillScreening / StepPlan /
           StepExecutor / StateEvaluator）之间传递的运行时数据。
    为什么这样做：将原 DagStateExecutorNode.__call__() 中的局部变量
                  提升为可序列化的 Pydantic Model，使 LangGraph 子图的
                  每个节点都能读取和更新这些状态，天然享受 Checkpoint 持久化。
    存储位置：序列化后存储在 DagEngineState.dag_engine_state["_executor_runtime"] 中。
    """

    # === 当前 State 信息 ===
    current_state_id: str = Field(
        default="",
        description="当前正在执行的 State ID。",
    )
    current_state_goal: str = Field(
        default="",
        description="当前 State 的目标描述。",
    )
    current_state_intent: str = Field(
        default="",
        description="当前 State 的意图描述。",
    )
    current_state_order_index: int = Field(
        default=0,
        description="当前 State 在 Plan 中的顺序索引。",
    )
    completion_criteria: list[dict[str, Any]] = Field(
        default_factory=list,
        description="当前 State 的完成标准列表（序列化后的 CompletionCriterion）。",
    )

    # === State 运行时 ===
    state_runtime: dict[str, Any] = Field(
        default_factory=dict,
        description="StateRuntimeState 的序列化结果。",
    )

    # === 预算 ===
    budget_global_consumed: int = Field(
        default=0,
        description="全局预算已消耗的工具调用次数。",
    )

    # === Skill 初筛结果 ===
    selected_skills: list[dict[str, Any]] = Field(
        default_factory=list,
        description="SkillScreeningNode 输出的筛选结果。",
    )

    # === Step Plan ===
    steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="StepPlanNode 输出的 StepDefinition 序列化列表。",
    )
    step_cursor: int = Field(
        default=0,
        ge=0,
        description="当前执行到第几个 Step。",
    )

    # === Step 执行结果 ===
    all_partitioned_outputs: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="所有已执行 Step 的分区输出汇总。",
    )
    node_def_map: dict[str, Any] = Field(
        default_factory=dict,
        description="node_id → AtomicNodeDefinition 序列化映射。",
    )

    # === State 上下文（可序列化子集） ===
    state_context: dict[str, Any] = Field(
        default_factory=dict,
        description="供原子节点使用的 state_context（已过滤不可序列化对象）。",
    )

    # === 初始化标记 ===
    initialized: bool = Field(
        default=False,
        description="子图是否已完成初始化（SkillScreeningNode 首次调用时设为 True）。",
    )


# ===========================================================================
# Agent Loop 状态模型（agent-loop-langgraph-design.md Phase A）
# ===========================================================================


class StepEvaluationVerdict(str, Enum):
    """Step 评估结论 — 对应 agent loop.md 的四种结果。

    做什么：标识 StepEvaluateNode 对单步执行结果的评估结论。
    为什么这样做：agent loop.md 要求每步完成后评估，支持 pass/fail/partial/needs_replan。
    """

    PASS = "pass"               # 步骤完成，进入下一步
    FAIL = "fail"               # 步骤失败，尝试 Repair
    PARTIAL = "partial"         # 部分完成，可继续或 Repair
    NEEDS_REPLAN = "needs_replan"  # 路径不对，触发 Replan


class StepStatusEnum(str, Enum):
    """Step 状态枚举 — StepState 的生命周期状态。

    做什么：标识 PlanState 中每个步骤的执行状态。
    """

    PENDING = "pending"         # 等待执行
    RUNNING = "running"         # 正在执行
    PASSED = "passed"           # 已通过评估
    FAILED = "failed"           # 执行失败
    SKIPPED = "skipped"         # 被跳过（replan 后不再需要）


class ReplanRecord(BaseModel):
    """Replan 历史记录 — 每次 replan 追加一条。

    做什么：记录 replan 的版本、原因和受影响步骤，便于回溯。
    """

    from_version: int = Field(default=1, description="replan 前的版本号。")
    to_version: int = Field(default=2, description="replan 后的版本号。")
    reason: str = Field(default="", description="replan 原因。")
    failed_step_id: str = Field(default="", description="触发 replan 的失败步骤 ID。")
    changed_step_ids: list[str] = Field(
        default_factory=list,
        description="replan 中被修改、新增或删除的步骤 ID 列表。",
    )
    timestamp_ms: int = Field(default=0, description="replan 发生的时间戳（毫秒）。")


class GoalState(BaseModel):
    """全局目标锁定态 — 写入后不可变。

    做什么：存储任务的全局目标、验收标准、非目标声明和约束。
    为什么这样做：agent loop.md 要求 GoalState 只写一次，锁定后不允许
                  replan 改写，防止目标漂移。
    不变量：locked=True 后，任何节点都不允许修改 global_goal / acceptance_criteria / non_goals。
    """

    task_id: str = Field(default_factory=generate_string_id)
    global_goal: str = Field(default="", description="全局总目标描述，锁定后不可变。")
    goal_definition: str = Field(default="", description="目标详细描述。")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="验收标准列表，锁定后不可变。",
    )
    non_goals: list[str] = Field(
        default_factory=list,
        description="非目标声明，防止目标漂移。例如：'不涉及竞品分析'。",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="约束条件列表。例如：['数据来源需标注', '中文撰写']。",
    )
    locked: bool = Field(
        default=False,
        description="目标是否已锁定。GoalLockNode 执行完毕后设为 True。",
    )
    locked_at_ms: int = Field(default=0, description="锁定时间戳（毫秒）。")


class AgentStepState(BaseModel):
    """单步定义 — PlanState 中的一个步骤。

    做什么：描述一个可执行步骤的元信息和运行时状态。
    为什么这样做：对应 agent loop.md 的 StepState，粒度比 OverallState 更精细。
    """

    step_id: str = Field(default_factory=generate_string_id)
    title: str = Field(default="", description="步骤标题，简要描述该步做什么。")
    intent: str = Field(default="", description="步骤意图。")
    dependencies: list[str] = Field(
        default_factory=list,
        description="依赖的前置步骤 ID 列表。",
    )

    @field_validator("dependencies", mode="before")
    @classmethod
    def _coerce_dependencies(cls, v: list) -> list[str]:
        """防御性校验：LLM 可能返回整数索引而非字符串 ID，需强制转为 str。"""
        return [str(item) for item in v]

    expected_output: str = Field(
        default="",
        description="预期输出描述，用于 StepEvaluateNode 判断是否完成。",
    )
    completion_criteria: list[CompletionCriterion] = Field(
        default_factory=list,
        description="可量化的完成标准。",
    )
    status: StepStatusEnum = Field(
        default=StepStatusEnum.PENDING,
        description="步骤状态：pending / running / passed / failed / skipped。",
    )
    risk_notes: str = Field(default="", description="风险点说明。")
    rollback_hint: str = Field(default="", description="可能的回退点说明。")
    pre_allocated_skills: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Plan 阶段预分配的 Skill 筛选结果列表。",
    )

    @field_validator("pre_allocated_skills", mode="before")
    @classmethod
    def _coerce_pre_allocated_skills(cls, v: Any) -> list[dict[str, Any]]:
        """防御性校验：LLM 可能返回纯字符串名称（如 'web_search'）而非字典格式，
           需要自动规整为标准字典格式（{"skill_name": "web_search", "relevance_reason": ""}）。
        """
        if not isinstance(v, list):
            return []
        coerced: list[dict[str, Any]] = []
        for item in v:
            if isinstance(item, dict):
                coerced.append(item)
            elif isinstance(item, str):
                # LLM 返回了纯字符串，包装为标准格式
                coerced.append({"skill_name": item, "relevance_reason": ""})
            else:
                # 兜底：跳过无法识别的类型
                continue
        return coerced

    # === 新增：并行执行元数据 ===
    execution_mode: str = Field(
        default="sequential",
        description="执行模式：sequential（串行）/ parallel（可并行）。",
    )
    started_at_ms: int = Field(
        default=0,
        description="步骤开始执行的时间戳（毫秒）。",
    )
    completed_at_ms: int = Field(
        default=0,
        description="步骤完成的时间戳（毫秒）。",
    )
    result_summary: str = Field(
        default="",
        description="步骤执行结果摘要，供下游步骤和 FinalVerify 使用。",
    )

class PlanState(BaseModel):
    """全局步骤计划 — 可变，版本化。

    做什么：存储当前全局步骤序列，每次 replan 产生新版本。
    为什么这样做：agent loop.md 要求 PlanState 是可变的，
                   每次 replan 都保留版本便于回溯。
    """

    plan_version: int = Field(default=1, ge=1, description="计划版本号，replan 时递增。")
    steps: list[AgentStepState] = Field(
        default_factory=list,
        description="全局步骤列表，中粒度（3~12 步）。",
    )
    # current_step_index 保留用于向后兼容，但不再作为主调度依据
    current_step_index: int = Field(default=0, ge=0, description="当前执行到第几步。")

    # === 新增：并行调度状态 ===
    completed_step_ids: set[str] = Field(
        default_factory=set,
        description="已完成的步骤 ID 集合。",
    )
    running_step_ids: set[str] = Field(
        default_factory=set,
        description="正在执行的步骤 ID 集合（可能有多个同时运行）。",
    )
    failed_step_ids: set[str] = Field(
        default_factory=set,
        description="失败的步骤 ID 集合。",
    )
    replan_history: list[ReplanRecord] = Field(
        default_factory=list,
        description="replan 历史记录，每次 replan 追加一条。",
    )


class StepEvaluationResult(BaseModel):
    """Step 评估结果 — StepEvaluateNode 的输出。

    做什么：承载 Step 级评估的结构化结果。
    """

    verdict: StepEvaluationVerdict = Field(
        default=StepEvaluationVerdict.PASS,
        description="评估结论：pass / fail / partial / needs_replan。",
    )
    evaluation_reason: str = Field(default="", description="评估判断的理由。")
    gap_analysis: str = Field(
        default="",
        description="当前结果与预期之间的差距分析。verdict=pass 时为空。",
    )
    suggestion: str = Field(
        default="",
        description="改进建议，供 StepRepairNode 和 ReplanNode 使用。",
    )
    criteria_checklist: list[dict[str, Any]] = Field(
        default_factory=list,
        description="逐条 completion_criteria 的验证结果。",
    )


class ExecutionState(BaseModel):
    """执行实时快照 — 正在发生什么。

    做什么：存储当前步骤的执行过程中的实时信息。
    为什么这样做：agent loop.md 要求 ExecutionState 是"正在发生什么"的快照。
    """

    current_step_id: str = Field(default="", description="当前正在执行的步骤 ID。")
    last_thought: str = Field(default="", description="StepThinkNode 输出的局部思考。")
    last_tool_calls: list[dict[str, Any]] = Field(
        default_factory=list,
        description="最近一次工具调用记录。",
    )
    last_observation: str = Field(
        default="",
        description="ObserveNode 输出的结构化观察。",
    )
    last_error: str = Field(default="", description="最近一次错误信息。")
    retry_count: int = Field(default=0, ge=0, description="当前步骤的重试次数（仅 fail 触发）。")
    repair_count: int = Field(default=0, ge=0, description="当前步骤的修复次数（仅 fail 触发）。")
    loop_count: int = Field(default=0, ge=0, description="当前步骤的 loop 次数（partial 触发，正常多轮执行不计入重试）。")
    evaluation_result: StepEvaluationResult | None = Field(
        default=None,
        description="最近一次 Step 评估结果。",
    )
    partitioned_outputs: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="当前步骤的分区输出。",
    )
    # === 新增：资源加载结果 ===
    loaded_resources: dict[str, str] = Field(
        default_factory=dict,
        description="已加载的资源内容。key 为 resource_name，value 为加载的内容（全量文本或检索结果）。",
    )
    resource_load_errors: dict[str, str] = Field(
        default_factory=dict,
        description="资源加载失败记录。key 为 resource_name，value 为错误信息。",
    )


class AgentBudgetState(BaseModel):
    """预算集中管理态。

    做什么：集中管理所有预算维度，禁止散落在各节点中。
    为什么这样做：agent loop.md 要求预算状态不能散落在各节点里。
    """

    token_used: int = Field(default=0, ge=0, description="已消耗 Token 数。")
    tool_calls_used: int = Field(default=0, ge=0, description="已消耗工具调用次数。")
    step_retries_used: int = Field(default=0, ge=0, description="已消耗步骤重试次数。")
    replan_count: int = Field(default=0, ge=0, description="已触发 replan 次数。")
    time_used_ms: int = Field(default=0, ge=0, description="已消耗执行时间（毫秒）。")

    # 上限配置
    max_tool_calls: int = Field(default=50, ge=1, description="最大工具调用次数。")
    max_step_retries: int = Field(default=3, ge=1, description="单步最大重试次数（仅 fail 触发）。")
    max_step_loops: int = Field(default=5, ge=1, description="单步最大 loop 次数（partial 触发，正常多轮执行上限）。")
    max_replan_count: int = Field(default=2, ge=0, description="最大 replan 次数。")
    max_time_ms: int = Field(default=300000, ge=1, description="最大执行时间（毫秒）。")

    def is_exhausted(self) -> bool:
        """判断预算是否已耗尽。

        做什么：检查任意维度是否超出上限。
        返回: True 表示预算已耗尽。
        """
        return (
            self.tool_calls_used >= self.max_tool_calls
            or self.replan_count >= self.max_replan_count
            or self.time_used_ms >= self.max_time_ms
        )


class AgentMemoryState(BaseModel):
    """Agent 记忆态 — 稳定信息。

    做什么：存储 Agent Loop 中可复用的稳定信息，不存临时噪音。
    为什么这样做：对应 agent loop.md 的 MemoryState。
    """

    reusable_patterns: list[str] = Field(
        default_factory=list,
        description="可复用的执行模式。",
    )
    failure_patterns: list[str] = Field(
        default_factory=list,
        description="失败模式，供 Repair/Replan 参考。",
    )
    step_summaries: list[dict[str, Any]] = Field(
        default_factory=list,
        description="已完成步骤的摘要列表，供后续步骤参考。",
    )


class AgentLoopState(BaseModel):
    """Agent Loop 引擎全局状态 — 替代 DagEngineState。

    做什么：承载 Agent Loop 的全部运行时数据。
    设计原则：严格对应 agent loop.md 的 5 核心状态对象。
    """

    # === 1. GoalState（只写一次）===
    goal: GoalState = Field(default_factory=lambda: GoalState(global_goal=""))

    # === 2. PlanState（可变，版本化）===
    plan: PlanState = Field(default_factory=PlanState)

    # === 3. ExecutionState（实时快照）===
    execution: ExecutionState = Field(default_factory=ExecutionState)

    # === 4. BudgetState（集中管理）===
    budget: AgentBudgetState = Field(default_factory=AgentBudgetState)

    # === 5. MemoryState（稳定信息）===
    memory: AgentMemoryState = Field(default_factory=AgentMemoryState)

    # === 运行时上下文（从 ChatWorkflowState 注入）===
    disambiguated_text: str = ""
    unresolved_pronouns: list[dict[str, Any]] = Field(default_factory=list)
    session_context: dict[str, Any] = Field(default_factory=dict)
    user_profile: dict[str, Any] = Field(default_factory=dict)
    memory_context: str = ""
    skill_briefs: list[dict[str, Any]] = Field(default_factory=list)

    # === 终止信息 ===
    terminated: bool = False
    termination_reason: str = ""
    termination_step_id: str = ""

    # === 最终验收结果 ===
    final_verification: dict[str, Any] = Field(
        default_factory=dict,
        description="FinalVerifyNode 输出的验收结果。",
    )
    plan_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="PlanResultSummaryNode 输出的汇总结果。",
    )

    # === Gating 审批挂起（Phase 13 保留）===
    gating_suspended: bool = False
    gating_pending_node_ids: list[str] = Field(default_factory=list)

    # === 原始工作流状态引用 ===
    workflow_state: dict[str, Any] = Field(default_factory=dict)
