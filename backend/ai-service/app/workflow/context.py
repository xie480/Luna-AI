"""Luna AI Chat Workflow 状态类型定义。

做什么：定义 LangGraph 节点间传递的完整状态类型 ChatWorkflowState 及其子模型。
为什么这样做：所有 LangGraph 节点共享同一个类型化状态，确保字段安全。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.mcp.skill_types import FallbackState, FinalFailState
from app.mcp.types import MCPToolResult
from app.rag.types import KnowledgeCitation, RagEvidence, RagRetrievalRoute
from app.workflow.constants import ChatPlanPreset, ChatWorkflowNodeType


# LangGraph 需要一个简单的 TypedDict 作为状态，这里使用 Pydantic BaseModel 也是可以的
# 为了保持兼容性，提供一个别名
WorkflowGraphState = dict[str, Any]


# ===========================================================================
# 子状态模型
# ===========================================================================


class ChatRuntimeState(BaseModel):
    """运行时状态（工作流级别）。"""

    trace_id: str = ""
    session_id: str = ""
    interaction_id: str = ""
    plan_preset_id: str = ChatPlanPreset.DAILY_CHAT_DEFAULT.value
    start_ms: int = Field(default=0, ge=0)
    locale: str = "zh-CN"
    user_id: str = "local_default_user"
    retry_count: int = Field(default=0, ge=0)
    chat_mode: ChatPlanPreset = ChatPlanPreset.DAILY_CHAT_DEFAULT
    current_node_type: ChatWorkflowNodeType | None = None


class ChatInputPayload(BaseModel):
    """输入载荷。"""

    raw_user_message: str = ""
    mention_luna: bool = True
    frontend_message_id: str = Field(
        default="",
        description="前端消息ID，用于前端标识消息，与 assistant_message_id 共享同一值。",
    )
    client_timestamp_ms: int = Field(default=0, ge=0, description="客户端时间戳（毫秒）。")
    locale: str = Field(default="zh-CN", description="本地化设置。")
    timezone: str = Field(default="Asia/Shanghai", description="时区设置。")
    tts_enabled: bool = True
    attachment_meta_list: list[dict[str, Any]] = Field(default_factory=list)
    extra_context: dict[str, Any] = Field(default_factory=dict)
    llm_response_mode: str = Field(
        default="streaming",
        description="LLM 回复模式：'streaming' 为流式逐句返回，'unified' 为非流式统一响应。",
    )


class ChatSessionState(BaseModel):
    """会话层面状态（含摘要与关键事实）。"""

    short_summary: str = ""
    long_summary: str = ""
    key_facts: list[str] = Field(default_factory=list)
    recent_messages: list[Any] = Field(default_factory=list)
    token_budget_total: int = Field(default=0, ge=0)
    token_budget_used: int = Field(default=0, ge=0)
    context_window_status: str = "ready"
    memory_snippets: str = ""
    rag_evidence_text: str = Field(
        default="",
        description="RAG 召回证据的拼接文本，供 MCP 前置判断节点使用。",
    )


class ChatRouteState(BaseModel):
    """输入重构与路由状态。"""

    reconstructed_text: str = ""
    disambiguated_text: str = ""
    user_intent_summary: str = ""
    search_queries: list[str] = Field(default_factory=list)
    entity_mentions: list[str] = Field(default_factory=list)
    temporal_focus: dict[str, Any] = Field(default_factory=dict)
    should_enter_long_term_memory_rag: bool = False
    should_enter_knowledge_rag: bool = False
    route_reasons: list[str] = Field(default_factory=list)
    external_search_queries: list[str] = Field(default_factory=list)
    external_entity_mentions: list[str] = Field(default_factory=list)
    external_temporal_focus: dict[str, Any] = Field(default_factory=dict)
    knowledge_route: RagRetrievalRoute = RagRetrievalRoute.HYBRID
    emotion_state: dict[str, Any] = Field(default_factory=dict)

    # --- Phase 12（v3.0）变更：MCP 判断由 MCP 前置节点处理 ---
    # MCP 前置节点完成判断后，将判定结果写入以下字段
    should_enter_skill: bool = Field(
        default=False,
        description="MCP 前置判断节点判定是否需要进入 MCP Skill 执行节点。"
                    "True 表示需要使用技能，False 表示无需。",
    )
    skill_judgment_json: dict[str, Any] | None = Field(
        default=None,
        description="MCP 前置判断节点的判定结果 JSON，"
                    "包含 need_skill(bool)、reason(str)、keywords(list[str])。"
                    "当触发退回机制时，还会包含 fallback_context 字段。",
    )
    mcp_intent: str = Field(
        default="",
        description="MCP 前置判断节点提炼的 MCP 意图文本，"
                    "用于替代原始用户输入注入到下游 Agent 的 Prompt 中。"
                    "当 should_enter_skill=False 时此字段为空字符串。",
    )


class ChatMemoryState(BaseModel):
    """长期记忆状态。"""

    entered_by_condition: bool = False
    condition_reason: str = ""
    prompt_memory_text: str = ""
    degraded: bool = False
    degraded_reason: str = ""


class ChatUserProfileState(BaseModel):
    """用户画像状态。"""

    injection_executed: bool = False
    prompt_profile_text: str = ""
    degraded: bool = False
    degraded_reason: str = ""


class ChatKnowledgeRagState(BaseModel):
    """知识库 RAG 状态。"""

    entered_by_condition: bool = False
    condition_reason: str = ""
    retrieval_route: str = ""
    evidences: list[RagEvidence] = Field(default_factory=list)
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    prompt_knowledge_text: str = ""
    degraded: bool = False
    degraded_reason: str = ""


class ChatPromptState(BaseModel):
    """Prompt 装配结果。"""

    system_prompt_text: str = ""
    prompt_variables: dict[str, str] = Field(default_factory=dict)


class ChatGenerationState(BaseModel):
    """生成结果状态。"""

    full_text: str = ""
    thought_text: str = ""
    emotion: str = ""
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    assistant_message_id: str = ""
    error: str = ""
    finish_reason: str = ""
    model_name: str = ""
    provider_name: str = ""
    stream_started_at_ms: int = Field(default=0, ge=0)
    ttft_ms: int = Field(
        default=0,
        ge=0,
        description="首 Token 到达延迟（TTFT），从请求开始到收到第一个有效生成 Token 的耗时，单位为毫秒。",
    )
    # 非流式统一响应模式新增字段
    e2e_latency_ms: int = Field(
        default=0,
        ge=0,
        description="端到端生成延迟（毫秒），从 LLM 调用开始到完整回复到达的耗时。非流式模式下替代 TTFT。",
    )
    generation_started_at_ms: int = Field(
        default=0,
        ge=0,
        description="LLM 调用开始时间戳（毫秒），用于计算 e2e_latency_ms。",
    )


class ChatObservabilityState(BaseModel):
    """可观测性状态。"""

    node_observations: list[dict[str, Any]] = Field(default_factory=list)
    emitted_event_ids: list[str] = Field(default_factory=list)


class ChatMCPToolState(BaseModel):
    """MCP 工具执行状态（含 Skill 执行状态）。
    为什么这样做：MCP Tool 和 Skill 共用 mcp_tool_state 字段，
                 避免新增字段导致其他依赖该字段的节点（如 base.py 的降级检测）大范围修改。
    """

    entered_by_condition: bool = False
    condition_reason: str = ""

    # Agent 阶段标识（兼容 Tool 和 Skill 两个阶段枚举）
    agent_phase: str = Field(
        default="idle",
        description="Agent 执行阶段标识。Tool 模式使用 ChatMCPAgentPhase 枚举值，"
                    "Skill 模式使用 SkillAgentPhase 枚举值。",
    )

    # --- Agent 1 结果 ---
    screening_result: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent 1 输出的筛选结果。Tool 模式为 ToolChainPlan，Skill 模式为 SkillChainPlan。",
    )

    # --- Agent 2 结果（Tool 旧路径） ---
    calling_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Agent 2 每轮参数提取结果数组，仅旧 Tool 路径使用。",
    )

    # --- Agent 3 结果（Tool 旧路径） ---
    alignment_result: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent 3 意图对齐结果，仅旧 Tool 路径使用。",
    )
    calibrated_output: str = Field(
        default="",
        description="Agent 3 校准后的输出文本，仅旧 Tool 路径使用。",
    )
    quality_issue: bool = Field(
        default=False,
        description="Agent 3 质量标记，仅旧 Tool 路径使用。",
    )

    # --- 工具链执行状态（Tool 旧路径） ---
    tool_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="工具链每轮执行结果累积数组。Tool 和 Skill 均写入此字段。",
    )
    chain_aborted: bool = Field(
        default=False,
        description="工具链是否因错误终止，仅旧 Tool 路径使用。",
    )
    chain_error: str = Field(
        default="",
        description="工具链终止时的错误信息，仅旧 Tool 路径使用。",
    )

    # 最后一次工具执行结果
    executed_tool_name: str = ""
    execution_id: str = ""
    output_text: str = ""
    latency_ms: int = 0

    # --- Skill 路径独有 ---
    execution_plan: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent 2 输出的执行计划。仅 Skill 路径使用，包含 state 字典和执行顺序。",
    )
    resource_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Agent 2 资源加载阶段的结果数组。仅 Skill 路径使用。",
    )
    final_fail_state: dict[str, Any] = Field(
        default_factory=dict,
        description="最终失败状态。仅 Skill 路径退回机制触发最终失败时写入。",
    )
    fallback_state: dict[str, Any] = Field(
        default_factory=dict,
        description="退回状态。仅 Skill 路径执行退回时写入，记录退回轮次和上下文。",
    )

    execution_summary: str = Field(
        default="",
        description="Skill 执行结果摘要。由 MCP Skill 执行节点在完成后调用 LLM 压缩生成，"
                    "作为 SKILL_EXECUTION_SUMMARY 变量注入到 chat/memory.j2 模板中。"
                    "内容包含本次调用的 Skill 列表、每个 Skill 执行的操作与最终执行结果。",
    )

    # --- 降级状态 ---
    degraded: bool = Field(
        default=False,
        description="MCP 工具/Skill 执行是否降级。True 表示降级跳过。",
    )
    degraded_reason: str = Field(
        default="",
        description="MCP 工具/Skill 执行降级原因。",
    )


# ===========================================================================
# 顶层工作流状态
# ===========================================================================


class ChatWorkflowState(BaseModel):
    """Chat Workflow 完整状态。"""

    schema_version: str = "chat.workflow.v1"
    input_payload: ChatInputPayload = Field(default_factory=ChatInputPayload)
    runtime: ChatRuntimeState = Field(default_factory=ChatRuntimeState)
    route_state: ChatRouteState = Field(default_factory=ChatRouteState)
    session_state: ChatSessionState = Field(default_factory=ChatSessionState)
    memory_state: ChatMemoryState = Field(default_factory=ChatMemoryState)
    profile_state: ChatUserProfileState = Field(default_factory=ChatUserProfileState)
    knowledge_state: ChatKnowledgeRagState = Field(default_factory=ChatKnowledgeRagState)
    mcp_tool_state: ChatMCPToolState = Field(
        default_factory=ChatMCPToolState,
        description="MCP 工具/Skill 执行状态。",
    )
    prompt_state: ChatPromptState = Field(default_factory=ChatPromptState)
    generation_state: ChatGenerationState = Field(default_factory=ChatGenerationState)
    observability: ChatObservabilityState = Field(default_factory=ChatObservabilityState)

    @classmethod
    def from_graph_state(cls, state: dict[str, Any]) -> ChatWorkflowState:
        """从 LangGraph 字典状态反序列化为类型化状态。"""
        if isinstance(state, cls):
            return state
        return cls(**{k: v for k, v in state.items() if k in cls.model_fields})

    def as_graph_state(self) -> dict[str, Any]:
        """序列化为 LangGraph 字典状态。"""
        return self.model_dump(mode="json")
