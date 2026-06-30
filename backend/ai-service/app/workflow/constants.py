"""Phase 8.5 + Phase 9 Agent Loop workflow 常量定义。

做什么：集中定义所有 workflow 枚举、节点名、事件类型和模板变量常量。
为什么这样做：agent.md 禁止硬编码魔法字符串，所有枚举与常量集中管理。
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class ChatWorkflowSchemaVersion(str, Enum):
    """Workflow 协议版本。"""

    CHAT_WORKFLOW_V1 = "chat.workflow.v1"


class ChatMode(str, Enum):
    """当前支持的聊天模式。

    做什么：由前端模式选择 UI 提供，标识用户选择的执行路径。
    为什么这样做：不使用复杂度路由器自动判断，由用户自主选择。
    """

    DAILY_CHAT = "daily_chat"
    CASUAL_CHAT = "casual_chat"
    PLAN_STATE_NODE = "plan_state_node"     # 智能规划：Phase 9 Plan-State-Node（原 Plan + Cursor）
    AGENT_LOOP = "agent_loop"              # 智能规划：Agent Loop 架构（Goal-Stable / Plan-Mutable）


class ChatPlanPreset(str, Enum):
    """当前启用的内置预设图。"""

    DAILY_CHAT_DEFAULT = "daily_chat.default.v1"
    CASUAL_CHAT_DEFAULT = "casual_chat.default.v1"
    PLAN_STATE_NODE_DEFAULT = "plan_state_node.default.v1"
    AGENT_LOOP_DEFAULT = "agent_loop.default.v1"


class ChatWorkflowNodeType(str, Enum):
    """当前主图真实使用的节点类型。"""

    INPUT_RECONSTRUCTION = "input_reconstruction"
    SESSION_CONTEXT_LOAD = "session_context_load"
    LONG_TERM_MEMORY_RAG = "long_term_memory_rag"
    USER_PROFILE_INJECTION = "user_profile_injection"
    KNOWLEDGE_RAG = "knowledge_rag"
    CONTEXT_GOVERNANCE = "context_governance"
    PROMPT_ASSEMBLY = "prompt_assembly"
    MAIN_CHAT_LLM = "main_chat_llm"
    RESPONSE_PERSISTENCE = "response_persistence"
    FINALIZE = "finalize"
    # --- Phase 12（v3.0）新增：MCP Skill 执行节点 ---
    MCP_SKILL_EXECUTION = "mcp_skill_execution"
    # --- Phase 12（v3.0）新增：MCP 前置判断节点 ---
    MCP_INTENT_JUDGE = "mcp_intent_judge"


class ChatNodeStatus(str, Enum):
    """节点运行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEGRADED = "degraded"
    NOT_ENTERED_BY_CONDITION = "not_entered_by_condition"


class ChatConditionalRoute(str, Enum):
    """条件边结果。"""

    ENTER_LONG_TERM_MEMORY_RAG = "enter_long_term_memory_rag"
    BYPASS_LONG_TERM_MEMORY_RAG = "bypass_long_term_memory_rag"
    ENTER_KNOWLEDGE_RAG = "enter_knowledge_rag"
    BYPASS_KNOWLEDGE_RAG = "bypass_knowledge_rag"
    # --- Phase 12（v3.0）新增：Skill 路由 ---
    ENTER_MCP_SKILL = "enter_mcp_skill"
    BYPASS_MCP_SKILL = "bypass_mcp_skill"
    # --- Phase 12（v3.0）新增：MCP 前置判断路由 ---
    ENTER_MCP_SKILL_FROM_JUDGE = "enter_mcp_skill_from_judge"
    BYPASS_MCP_SKILL_FROM_JUDGE = "bypass_mcp_skill_from_judge"
    ENTER_MCP_INTENT_JUDGE = "enter_mcp_intent_judge"
    BYPASS_MCP_INTENT_JUDGE = "bypass_mcp_intent_judge"


class ChatWorkflowEventType(str, Enum):
    """当前真实发送的事件类型。"""

    EVT_CHAT_PLAN_STARTED = "EVT_CHAT_PLAN_STARTED"
    EVT_CHAT_NODE_STARTED = "EVT_CHAT_NODE_STARTED"
    EVT_CHAT_NODE_COMPLETED = "EVT_CHAT_NODE_COMPLETED"
    EVT_CHAT_NODE_FAILED = "EVT_CHAT_NODE_FAILED"
    EVT_CHAT_NODE_DEGRADED = "EVT_CHAT_NODE_DEGRADED"
    EVT_CHAT_CONDITION_EVALUATED = "EVT_CHAT_CONDITION_EVALUATED"
    EVT_CHAT_PLAN_COMPLETED = "EVT_CHAT_PLAN_COMPLETED"


class DagWorkflowEventType(str, Enum):
    """Phase 9 DAG 工作流事件类型。

    做什么：定义 DAG 引擎向前端推送的 SSE 事件类型。
    为什么这样做：前端 dagWorkflowStore 依赖这些事件驱动 DAG 面板渲染，
                   事件名必须与前端 enum.ts 中的 DAG_WORKFLOW_EVENT_TYPE 完全一致。
    输入输出：由 DagEngine.run() 中的 _emit_dag_event 发布，经 SSE 通道推送到前端。
    边界条件：新增事件类型时必须同步更新前端 enum.ts 和 sseManager.ts。
    异常行为：无。
    """
    EVT_DAG_PLAN_CREATED = "EVT_DAG_PLAN_CREATED"
    EVT_DAG_STATE_STARTED = "EVT_DAG_STATE_STARTED"
    EVT_DAG_SKILL_SCREENING = "EVT_DAG_SKILL_SCREENING"
    EVT_DAG_STEP_PLAN_GENERATED = "EVT_DAG_STEP_PLAN_GENERATED"
    EVT_DAG_NODE_STARTED = "EVT_DAG_NODE_STARTED"
    EVT_DAG_NODE_COMPLETED = "EVT_DAG_NODE_COMPLETED"
    EVT_DAG_NODE_GATING = "EVT_DAG_NODE_GATING"
    EVT_DAG_STATE_EVALUATED = "EVT_DAG_STATE_EVALUATED"
    EVT_DAG_PLAN_REPLANNED = "EVT_DAG_PLAN_REPLANNED"
    EVT_DAG_PLAN_COMPLETED = "EVT_DAG_PLAN_COMPLETED"
    EVT_DAG_PLAN_TERMINATED = "EVT_DAG_PLAN_TERMINATED"
    EVT_DAG_BUDGET_EXHAUSTED = "EVT_DAG_BUDGET_EXHAUSTED"
    # --- Agent Loop 新增事件 ---
    EVT_DAG_GOAL_LOCKED = "EVT_DAG_GOAL_LOCKED"
    EVT_DAG_STEP_THINKING = "EVT_DAG_STEP_THINKING"
    EVT_DAG_RESOURCE_LOADED = "EVT_DAG_RESOURCE_LOADED"
    EVT_DAG_RESOURCE_FAILED = "EVT_DAG_RESOURCE_FAILED"
    EVT_DAG_STEP_OBSERVED = "EVT_DAG_STEP_OBSERVED"
    EVT_DAG_STEP_EVALUATED = "EVT_DAG_STEP_EVALUATED"
    EVT_DAG_STEP_REPAIRED = "EVT_DAG_STEP_REPAIRED"
    EVT_DAG_FINAL_VERIFIED = "EVT_DAG_FINAL_VERIFIED"
    # === Level 1 新增：State 并行事件 ===
    EVT_DAG_PARALLEL_STEPS_DISPATCHED = "EVT_DAG_PARALLEL_STEPS_DISPATCHED"
    EVT_DAG_STEP_COMPLETED = "EVT_DAG_STEP_COMPLETED"
    EVT_DAG_STEP_FAILED = "EVT_DAG_STEP_FAILED"
    EVT_DAG_STATE_JOIN_READY = "EVT_DAG_STATE_JOIN_READY"
    # === Level 3 新增：Tool 并行事件 ===
    EVT_DAG_TOOLS_PARALLEL_DISPATCHED = "EVT_DAG_TOOLS_PARALLEL_DISPATCHED"
    EVT_DAG_TOOL_BATCH_COMPLETED = "EVT_DAG_TOOL_BATCH_COMPLETED"


class AgentLoopSubGraphNodeName(str, Enum):
    """Agent Loop 子图外层节点名。

    做什么：定义 build_agent_loop_subgraph() 工厂函数生成的外层子图内部 4 个节点名。
    为什么这样做：将原 Plan + Cursor 外层图（Planner/Executor/Router/Summary）重构为
                  Agent Loop 外层图（GoalLock/GlobalPlanner/StepLoop/FinalVerify）。
    """

    GOAL_LOCK = "agent_goal_lock"
    GLOBAL_PLANNER = "agent_global_planner"
    STEP_LOOP = "agent_step_loop"
    FINAL_VERIFY = "agent_final_verify"


class AgentStepLoopSubGraphNodeName(str, Enum):
    """Agent Step Loop 子图内部节点名。

    做什么：定义 Step Loop 内层子图的 9 个节点名。
    为什么这样做：对应 agent loop.md 的 StepLoop = Think → ResourceLoad → Execute → Observe → Evaluate → (Pass/Repair/Replan/FastPass)。
    """

    STEP_ROUTER = "agent_step_router"
    STEP_THINK = "agent_step_think"
    RESOURCE_LOAD = "agent_resource_load"
    TOOL_EXECUTE = "agent_tool_execute"
    OBSERVE = "agent_observe"
    STEP_EVALUATE = "agent_step_evaluate"
    STEP_REPAIR = "agent_step_repair"
    REPLAN = "agent_replan"
    FAST_PASS = "agent_fast_pass"


class AgentStepRoute(str, Enum):
    """Step 路由结果枚举（并行版扩展）。

    做什么：标识 StepLoop 中 step_router 的路由决策。
    """

    STEP_THINK = "step_think"       # 还有未执行步骤，继续思考
    FINAL_VERIFY = "final_verify"   # 全部完成或终止，进入最终验收
    # === 新增并行路由 ===
    STEP_PARALLEL_DISPATCH = "step_parallel_dispatch"  # 有就绪步骤，进入并行调度
    WAIT_FOR_COMPLETION = "wait_for_completion"        # 等待正在运行的步骤完成


class StepEvaluationRoute(str, Enum):
    """Step 评估路由结果枚举。

    做什么：标识 step_evaluate 节点后的路由决策。
    为什么这样做：支持四种评估结论的路由分发，
                  其中 partial 表示步骤部分完成，需进入修复循环补齐缺口。
    """

    PASS = "pass"                   # 步骤通过，回到 step_router 推进下一步
    PARTIAL = "partial"             # 部分完成，进入 step_repair 补齐缺口后重试
    FAIL = "fail"                   # 步骤失败，尝试 step_repair
    NEEDS_REPLAN = "needs_replan"   # 需要重规划，触发 replan


class ChatWorkflowErrorCode(str, Enum):
    """当前真实使用的错误码。"""

    PROMPT_ASSEMBLY_FAILED = "CHAT_WORKFLOW_PROMPT_ASSEMBLY_FAILED"
    MAIN_LLM_FAILED = "CHAT_WORKFLOW_MAIN_LLM_FAILED"
    NODE_UNEXPECTED_FAILED = "CHAT_WORKFLOW_NODE_UNEXPECTED_FAILED"


class ChatWorkflowGraphNodeName(str, Enum):
    """LangGraph 内部节点名。"""

    INPUT_RECONSTRUCTION = "input_reconstruction"
    SESSION_CONTEXT_LOAD = "session_context_load"
    LONG_TERM_MEMORY_RAG = "long_term_memory_rag"
    LONG_TERM_MEMORY_BYPASS = "long_term_memory_bypass"
    USER_PROFILE_INJECTION = "user_profile_injection"
    KNOWLEDGE_RAG = "knowledge_rag"
    KNOWLEDGE_RAG_BYPASS = "knowledge_rag_bypass"
    CONTEXT_GOVERNANCE = "context_governance"
    PROMPT_ASSEMBLY = "prompt_assembly"
    MAIN_CHAT_LLM = "main_chat_llm"
    RESPONSE_PERSISTENCE = "response_persistence"
    FINALIZE = "finalize"
    # --- Phase 12（v3.0）新增：Skill 节点 ---
    MCP_SKILL_EXECUTION = "mcp_skill_execution"
    MCP_SKILL_BYPASS = "mcp_skill_bypass"
    # --- Phase 12（v3.0）新增：MCP 前置判断节点 ---
    MCP_INTENT_JUDGE = "mcp_intent_judge"
    MCP_INTENT_BYPASS = "mcp_intent_bypass"
    # --- Phase 9 新增：DAG 引擎节点（原 Plan + Cursor）---
    DAG_ENGINE = "dag_engine"
    # --- Agent Loop 新增：Agent Loop DAG 引擎节点 ---
    DAG_ENGINE_AGENT_LOOP = "dag_engine_agent_loop"
    # --- Phase 9 新增：简化输入重构节点 ---
    INPUT_RECONSTRUCTION_SIMPLIFIED = "input_reconstruction_simplified"


class DagSubGraphNodeName(str, Enum):
    """Phase 9 重构：Plan + Cursor 子图内部节点名。

    做什么：定义 build_plan_cursor_subgraph() 工厂函数生成的子图内部 4 个节点名。
    为什么这样做：将原 DagEngine.run() 中的 Python while 循环逻辑拆分为
                  4 个独立 LangGraph 节点，每个节点名必须是唯一常量，
                  避免硬编码魔法字符串。
    """

    DAG_PLANNER = "dag_planner"
    DAG_STATE_EXECUTOR = "dag_state_executor"
    DAG_CURSOR_ROUTER = "dag_cursor_router"
    DAG_PLAN_SUMMARIZER = "dag_plan_summarizer"


class DagExecutorSubGraphNodeName(str, Enum):
    """Phase 9 重构：State Executor 子图内部节点名。

    做什么：定义 build_state_executor_subgraph() 工厂函数生成的子图内部 4 个节点名。
    为什么这样做：将原 DagStateExecutorNode 中的单体逻辑拆分为
                  Skill 初筛 → Step Plan → Step 执行（循环）→ State 评估 的独立节点。
    """

    SKILL_SCREENING = "executor_skill_screening"
    STEP_PLAN = "executor_step_plan"
    STEP_EXECUTOR = "executor_step_executor"
    STATE_EVALUATOR = "executor_state_evaluator"


class DagStepCursorRoute(str, Enum):
    """Step Cursor 路由结果枚举。

    做什么：标识 Step 执行循环中路由函数的决策结果。
    为什么这样做：step_executor_node 执行完当前 step 后，
                  由路由函数判断是否还有剩余 step。
    """

    NEXT_STEP = "next_step"         # step_cursor < len(steps)，继续下一个 Step
    ALL_DONE = "all_done"           # 所有 Step 执行完毕，进入 State 评估


class DagEvalRoute(str, Enum):
    """State 评估路由结果枚举。

    做什么：标识 State 评估后路由函数的决策结果。
    为什么这样做：state_evaluator_node 评估完成后，
                  由路由函数决定是重走 skill 筛选还是结束子图。
    """

    SATISFIED = "eval_satisfied"    # 评估通过，子图结束
    RETRY = "eval_retry"            # 评估不通过且未达上限，回退到 skill_screening 重走
    TERMINATED = "eval_terminated"  # 评估不通过且已达上限，子图结束（终止）


CHAT_WORKFLOW_CHECKPOINT_TABLE: Final[str] = "langgraph_chat_checkpoints"
CHAT_WORKFLOW_CHECKPOINT_NS_SEPARATOR: Final[str] = ":"
CHAT_WORKFLOW_DEFAULT_LOCALE: Final[str] = "zh-CN"
CHAT_WORKFLOW_DEFAULT_TIMEZONE: Final[str] = "Asia/Shanghai"
CHAT_WORKFLOW_DEFAULT_USER_ID: Final[str] = "local_default_user"
CHAT_WORKFLOW_CONTEXT_WINDOW_READY: Final[str] = "ready"
CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED: Final[str] = "degraded"
CHAT_WORKFLOW_EMPTY_PROFILE_REASON: Final[str] = "用户画像为空"
CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON: Final[str] = "未触发长期记忆检索"
CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON: Final[str] = "未触发知识库检索"
CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON: Final[str] = "输入重构降级"

class ChatMCPAgentPhase(str, Enum):
    """MCP Agent 执行阶段枚举。

    做什么：标识 MCPSkillExecutionNode 中三 Agent 协作的当前执行阶段。
    为什么这样做：使用枚举替代硬编码的字符串常量，避免拼写错误和散落。
    """
    IDLE = "idle"
    SKILL_SCREENING = "skill_screening"
    SKILL_LOADING = "skill_loading"
    SKILL_EXECUTION = "skill_execution"
    SKILL_FALLBACK = "skill_fallback"
    SKILL_FINAL_FAIL = "skill_final_fail"

# Phase 12（v3.0）新增：Skill 常量
CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON: Final[str] = "未触发 MCP Skill 调用"
CHAT_WORKFLOW_SKILL_DEGRADED_REASON: Final[str] = "MCP Skill 执行降级"
CHAT_WORKFLOW_SKILL_NO_SKILL_REASON: Final[str] = "MCP Agent 判定无需调用技能"

# Phase 12 新增：MCP 工具输出变量名，用于下游 Prompt 装配时引用。
PROMPT_VARIABLE_MCP_TOOL_OUTPUT: Final[str] = "MCP_TOOL_OUTPUT"

# Phase 12（v3.1）新增：Skill 执行结果摘要变量名，用于向 chat/memory.j2 注入 LLM 压缩后的技能执行摘要。
PROMPT_VARIABLE_SKILL_EXECUTION_SUMMARY: Final[str] = "SKILL_EXECUTION_SUMMARY"

# Phase 13 新增：Gating 审批结果注入变量
# 当用户拒绝了 L2/L3 工具调用时，此变量包含拒绝信息和工具调用上下文，
# 注入到 chat/memory.j2 供主 Chat LLM 生成合适的回复。
PROMPT_VARIABLE_GATING_REJECTION_INFO: Final[str] = "GATING_REJECTION_INFO"

# Phase 13 新增：Gating 审批通过后的工具执行结果
# 当用户批准了 L2/L3 工具调用且工具执行完毕后，此变量包含执行结果，
# 注入到 chat/memory.j2 供主 Chat LLM 知道工具已执行完成。
PROMPT_VARIABLE_GATING_APPROVAL_RESULT: Final[str] = "GATING_APPROVAL_RESULT"

PROMPT_VARIABLE_CURRENT_TIME: Final[str] = "CURRENT_TIME"
PROMPT_VARIABLE_CURRENT_MESSAGE: Final[str] = "CURRENT_MESSAGE"
PROMPT_VARIABLE_CORE_SUMMARY: Final[str] = "CORE_SUMMARY"
PROMPT_VARIABLE_KEY_FACTS: Final[str] = "KEY_FACTS"
PROMPT_VARIABLE_MEMORY_SNIPPETS: Final[str] = "MEMORY_SNIPPETS"
PROMPT_VARIABLE_KNOWLEDGE_DOCS: Final[str] = "KNOWLEDGE_DOCS"
PROMPT_VARIABLE_LONG_TERM_MEMORY: Final[str] = "LONG_TERM_MEMORY"
PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE: Final[str] = "EXTERNAL_KNOWLEDGE"
PROMPT_VARIABLE_USER_PROFILE: Final[str] = "USER_PROFILE"
PROMPT_VARIABLE_EMOTION_PRIMARY: Final[str] = "EMOTION_PRIMARY"
PROMPT_VARIABLE_EMOTION_INTENSITY: Final[str] = "EMOTION_INTENSITY"
PROMPT_VARIABLE_EMOTION_VALENCE: Final[str] = "EMOTION_VALENCE"
PROMPT_VARIABLE_EMOTION_AROUSAL: Final[str] = "EMOTION_AROUSAL"
PROMPT_VARIABLE_EMOTION_TRIGGER: Final[str] = "EMOTION_TRIGGER"
# 重试错误信息变量：当 LLM 输出不符合 JSON 格式时，将解析错误信息注入此变量，
# 在 runtime.j2 中渲染为修正指令，指导模型在重试时修正输出格式。
PROMPT_VARIABLE_RETRY_ERROR_INFO: Final[str] = "RETRY_ERROR_INFO"
# TTS 语音语言选项：zh（中文）/ ja（日语），用于 runtime.j2 模板判断是否需要输出 replay_translation。
PROMPT_VARIABLE_TTS_LANGUAGE: Final[str] = "TTS_LANGUAGE"

# Phase 9 新增：DAG 智能规划执行结果模板变量，
# 当 plan_state_node 路径执行完毕后，将 DAG 汇总结果（含成功汇总与失败原因）注入此变量，
# 供 chat/memory.j2 渲染为主 Chat LLM 可感知的上下文。
PROMPT_VARIABLE_DAG_PLAN_RESULT: Final[str] = "DAG_PLAN_RESULT"

CHAT_STREAM_TYPE_REPLY_CHUNK: Final[str] = "reply_chunk"
CHAT_STREAM_TYPE_THOUGHT_CONTENT: Final[str] = "thought_content"
CHAT_STREAM_TYPE_EMOTION_UPDATE: Final[str] = "emotion_update"
# 非流式统一响应事件类型
CHAT_STREAM_TYPE_UNIFIED_RESPONSE: Final[str] = "unified_response"
CHAT_STREAM_GENERATION_ERROR: Final[str] = "generation_failed"
CHAT_STREAM_EMPTY_RESPONSE_ERROR: Final[str] = "Assistant returned empty content"

CHAT_WORKFLOW_REDIS_WRITE_OK: Final[str] = "redis_write_ok"
CHAT_WORKFLOW_REDIS_WRITE_SKIPPED: Final[str] = "redis_write_skipped"
CHAT_WORKFLOW_REDIS_WRITE_FAILED: Final[str] = "redis_write_failed"
CHAT_WORKFLOW_PG_WRITE_OK: Final[str] = "pg_write_ok"
CHAT_WORKFLOW_PG_WRITE_SKIPPED: Final[str] = "pg_write_skipped"
CHAT_WORKFLOW_PG_WRITE_FAILED: Final[str] = "pg_write_failed"
