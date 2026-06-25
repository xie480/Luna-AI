"""Agent Loop 架构 LangGraph 实现 — 智能规划模式重构。

做什么：将原 Plan + Cursor 双层子图重构为 agent loop.md 定义的
        「Goal-Stable / Plan-Mutable」6 层 Agent Loop 架构。
        包含 9 个节点实现 + 1 个子图工厂函数。
为什么这样做：当前实现缺少目标锁定、步进思考、观察层、Step 级评估和三级容错，
              与 agent loop.md 的设计差距较大，需要全面重构。

核心公式：
    Agent Loop = GoalLock(1次) + GlobalPlan(可版本化) + StepLoop(步进) + FinalVerify(1次)
    StepLoop = Think → Execute → Observe → Evaluate → (Pass/Repair/Replan)

拓扑：
    外层: goal_lock → global_planner → step_loop_subgraph → final_verify → END
    内层: step_router → step_think → tool_execute → observe → step_evaluate
           ├─ pass → step_router
           ├─ fail → step_repair → step_think
           └─ needs_replan → replan → step_router
"""

from __future__ import annotations

import json
import time
from typing import Any

from langgraph.graph import END, StateGraph

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    AgentLoopSubGraphNodeName,
    AgentStepLoopSubGraphNodeName,
    AgentStepRoute,
    DagWorkflowEventType,
    StepEvaluationRoute,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.dag.types import (
    AgentBudgetState,
    AgentLoopState,
    AgentMemoryState,
    AgentStepState,
    DagEngineState,
    DagNodeStatus,
    ExecutionState,
    GoalState,
    PlanState,
    ReplanRecord,
    StepEvaluationResult,
    StepEvaluationVerdict,
    StepStatusEnum,
)
from app.workflow.events import ChatWorkflowEventPublisher


# ===========================================================================
# 模块级工具函数
# ===========================================================================


async def _emit_dag_event(
    event_type: DagWorkflowEventType,
    trace_id: str,
    session_id: str,
    payload: dict[str, Any],
    event_publisher: ChatWorkflowEventPublisher | None,
) -> None:
    """发布 DAG 工作流事件到前端。

    做什么：将 Agent Loop 生命周期事件通过 SSE 通道推送给前端 dagWorkflowStore。
    参数:
        event_type: DAG 事件类型枚举。
        trace_id: 当前请求的追踪 ID。
        session_id: 会话 ID。
        payload: 事件载荷字典。
        event_publisher: 事件发布器实例。
    边界条件：event_publisher 为空时静默跳过。
    """
    if not event_publisher:
        return
    try:
        from app.api.sse import sse_manager
        await sse_manager.publish({
            "type": event_type.value,
            "trace_id": trace_id,
            "payload": payload,
        })
    except Exception as exc:
        logger.warning(f"Agent Loop 事件发布失败: type={event_type.value}, error={exc}")


def _extract_agent_loop_state(state: dict[str, Any]) -> tuple[ChatWorkflowState, AgentLoopState | None]:
    """从图状态中提取 ChatWorkflowState 和 AgentLoopState。

    做什么：反序列化 ChatWorkflowState，再从 dag_engine_state 中提取 AgentLoopState。
    返回: (chat_state, agent_loop_state_or_none)
    """
    chat_state = ChatWorkflowState.from_graph_state(state)
    dag_engine_data = chat_state.dag_state.dag_engine_state
    if not dag_engine_data:
        return chat_state, None
    try:
        agent_loop = AgentLoopState(**dag_engine_data)
    except Exception:
        # 兼容旧 DagEngineState 数据，回退为新建
        agent_loop = AgentLoopState()
    return chat_state, agent_loop


def _save_agent_loop_state_to_graph(
    chat_state: ChatWorkflowState,
    agent_loop: AgentLoopState,
) -> dict[str, Any]:
    """将 AgentLoopState 写回 ChatWorkflowState 并返回图状态。

    做什么：序列化 AgentLoopState 到 dag_engine_state 字段。
    """
    chat_state.dag_state.dag_engine_state = agent_loop.model_dump(mode="json")
    return chat_state.as_graph_state()


# ===========================================================================
# 节点 1: GoalLockNode — 目标锁定
# ===========================================================================


class GoalLockNode:
    """Agent Loop — 目标锁定节点。

    做什么：从用户输入和上下文中提取全局目标，生成验收标准、
            非目标声明、约束条件，将 GoalState.locked 设为 True。
    为什么这样做：agent loop.md 要求 GoalState 只写一次，锁定后不允许
                  replan 改写，防止目标漂移。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        """初始化目标锁定节点。

        参数:
            prompt_manager: Prompt 管理器。
            llm_client: LLM 客户端。
            chat_status_publisher: Chat 状态发布器。
            event_publisher: 工作流事件发布器。
        """
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行目标锁定。

        做什么：
        1. 从图状态提取上下文信息
        2. 调用 LLM 提取全局目标、验收标准、非目标声明
        3. 将 GoalState.locked 设为 True
        4. 发布 EVT_DAG_GOAL_LOCKED 事件
        5. 返回更新后的图状态
        """
        chat_state = ChatWorkflowState.from_graph_state(state)
        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        # 构建 AgentLoopState（首次进入时从 ChatWorkflowState 初始化）
        agent_loop = self._build_agent_loop_state(chat_state)

        # 发布 RUNNING 状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_PLAN_GENERATION,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_PLAN_GENERATION, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        agent_loop.workflow_state["dag_engine_started_at_ms"] = int(time.time() * 1000)

        try:
            # 渲染目标锁定 Prompt
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_GOAL_LOCK,
                variables={
                    "disambiguated_text": agent_loop.disambiguated_text,
                    "unresolved_pronouns": agent_loop.unresolved_pronouns,
                    "skill_briefs": agent_loop.skill_briefs,
                    "CORE_SUMMARY": agent_loop.session_context.get("short_summary", ""),
                    "KEY_FACTS": json.dumps(
                        agent_loop.session_context.get("key_facts", []),
                        ensure_ascii=False,
                    ),
                    "MEMORY_SNIPPETS": agent_loop.session_context.get("memory_snippets", ""),
                    "memory_context": agent_loop.memory_context,
                    "CURRENT_TIME": current_time,
                },
            )

            logger.info(f"[Agent Loop] 锁定目标 Prompt: {prompt_text}")

            # 调用 LLM 提取目标
            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_goal_schema(),
            )

            logger.info(f"[Agent Loop] 锁定目标 LLM 响应: {llm_response}")

            goal_data = self._parse_goal_response(llm_response)

            # 写入 GoalState 并锁定
            now_ms = int(time.time() * 1000)
            agent_loop.goal = GoalState(
                task_id=generate_string_id(),
                global_goal=goal_data.get("global_goal", ""),
                goal_definition=goal_data.get("goal_definition", ""),
                acceptance_criteria=goal_data.get("acceptance_criteria", []),
                non_goals=goal_data.get("non_goals", []),
                constraints=goal_data.get("constraints", []),
                locked=True,
                locked_at_ms=now_ms,
            )

            # 发布目标锁定事件
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_GOAL_LOCKED,
                trace_id, session_id,
                {
                    "task_id": agent_loop.goal.task_id,
                    "global_goal": agent_loop.goal.global_goal,
                    "acceptance_criteria": agent_loop.goal.acceptance_criteria,
                    "non_goals": agent_loop.goal.non_goals,
                    "constraints": agent_loop.goal.constraints,
                },
                self.event_publisher,
            )

            logger.info(
                f"[TraceID:{trace_id}] GoalLockNode 完成: "
                f"global_goal={agent_loop.goal.global_goal[:100]}, "
                f"criteria_count={len(agent_loop.goal.acceptance_criteria)}"
            )

        except Exception as exc:
            logger.error(f"[TraceID:{trace_id}] GoalLockNode 异常: {exc}")
            agent_loop.terminated = True
            agent_loop.termination_reason = f"目标锁定失败: {exc}"

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)

    def _build_agent_loop_state(self, chat_state: ChatWorkflowState) -> AgentLoopState:
        """从 ChatWorkflowState 构建 AgentLoopState。

        做什么：提取上下文信息，初始化 AgentLoopState 的运行时字段。
        """
        from app.mcp.skill_registry import SkillRegistry
        skill_briefs = SkillRegistry().get_skill_briefs()

        return AgentLoopState(
            disambiguated_text=chat_state.dag_state.disambiguated_text
                or chat_state.input_payload.raw_user_message,
            unresolved_pronouns=chat_state.dag_state.unresolved_pronouns,
            skill_briefs=skill_briefs,
            session_context={
                "memory_snippets": chat_state.session_state.memory_snippets,
                "key_facts": chat_state.session_state.key_facts,
                "short_summary": chat_state.session_state.short_summary,
                "recent_messages": chat_state.session_state.recent_messages,
            },
            user_profile={
                "prompt_profile_text": chat_state.profile_state.prompt_profile_text,
            },
            memory_context=chat_state.memory_state.prompt_memory_text,
            workflow_state=chat_state.model_dump(mode="json"),
        )

    def _build_goal_schema(self) -> dict[str, Any]:
        """构建目标锁定的 JSON Schema。

        做什么：定义 LLM 输出的结构化约束。
        """
        return {
            "type": "object",
            "properties": {
                "global_goal": {
                    "type": "string",
                    "description": "全局总目标描述，一句话概括用户最终要什么。",
                },
                "goal_definition": {
                    "type": "string",
                    "description": "目标的详细描述，补充全局目标中无法容纳的细节。",
                },
                "acceptance_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "验收标准列表，可量化的完成条件。",
                },
                "non_goals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "非目标声明，防止目标漂移。",
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "约束条件列表。",
                },
            },
            "required": ["global_goal", "acceptance_criteria"],
        }

    def _parse_goal_response(self, response: str) -> dict[str, Any]:
        """解析 LLM 目标锁定输出。

        做什么：从 LLM 原始响应中提取结构化目标数据。
        """
        try:
            if isinstance(response, dict):
                return response
            text = str(response).strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"目标锁定 LLM 输出解析失败: {exc}")
            return {"global_goal": str(response), "acceptance_criteria": []}


# ===========================================================================
# 节点 2: GlobalPlannerNode — 全局计划生成
# ===========================================================================


class GlobalPlannerNode:
    """Agent Loop — 全局计划生成节点。

    做什么：读取已锁定的 GoalState（不可修改），生成中粒度的全局步骤序列（3~12 步）。
    为什么这样做：agent loop.md 要求目标锁定后独立生成计划，
                  计划可变但目标不可变。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行全局计划生成。

        做什么：
        1. 读取已锁定的 GoalState
        2. 调用 LLM 生成步骤序列
        3. 写入 PlanState
        4. 发布 EVT_DAG_PLAN_CREATED 事件
        """
        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        # 安全守卫：目标未锁定时跳过
        if not agent_loop.goal.locked:
            logger.warning(
                f"[TraceID:{trace_id}] GlobalPlannerNode: 目标未锁定，跳过"
            )
            agent_loop.terminated = True
            agent_loop.termination_reason = "目标未锁定，无法生成计划"
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        try:
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_GLOBAL_PLANNER,
                variables={
                    "global_goal": agent_loop.goal.global_goal,
                    "goal_definition": agent_loop.goal.goal_definition,
                    "acceptance_criteria": json.dumps(
                        agent_loop.goal.acceptance_criteria, ensure_ascii=False
                    ),
                    "non_goals": json.dumps(
                        agent_loop.goal.non_goals, ensure_ascii=False
                    ),
                    "constraints": json.dumps(
                        agent_loop.goal.constraints, ensure_ascii=False
                    ),
                    "disambiguated_text": agent_loop.disambiguated_text,
                    "skill_briefs": agent_loop.skill_briefs,
                    "CORE_SUMMARY": agent_loop.session_context.get("short_summary", ""),
                    "KEY_FACTS": json.dumps(
                        agent_loop.session_context.get("key_facts", []),
                        ensure_ascii=False,
                    ),
                    "MEMORY_SNIPPETS": agent_loop.session_context.get("memory_snippets", ""),
                    "memory_context": agent_loop.memory_context,
                    "CURRENT_TIME": current_time,
                },
            )

            logger.info(
                f"[TraceID:{trace_id}] GlobalPlannerNode: 开始生成全局计划, prompt_text: {prompt_text}"
            )

            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_plan_schema(),
            )

            logger.info(
                f"[TraceID:{trace_id}] GlobalPlannerNode: LLM 输出: {llm_response}"
            )

            plan_data = self._parse_plan_response(llm_response)

            # 构建 PlanState
            steps = []
            for i, step_data in enumerate(plan_data.get("steps", [])):
                from app.workflow.dag.types import CompletionCriterion
                criteria = []
                for c in step_data.get("completion_criteria", []):
                    criteria.append(CompletionCriterion(
                        field=c.get("field", ""),
                        operator=c.get("operator", "not_empty"),
                        value=c.get("value", True),
                    ))
                steps.append(AgentStepState(
                    step_id=generate_string_id(),
                    title=step_data.get("title", f"步骤 {i + 1}"),
                    intent=step_data.get("intent", ""),
                    dependencies=step_data.get("dependencies", []),
                    expected_output=step_data.get("expected_output", ""),
                    completion_criteria=criteria,
                    status=StepStatusEnum.PENDING,
                    risk_notes=step_data.get("risk_notes", ""),
                    rollback_hint=step_data.get("rollback_hint", ""),
                    pre_allocated_skills=step_data.get("pre_allocated_skills", []),
                ))

            agent_loop.plan = PlanState(
                plan_version=1,
                steps=steps,
                current_step_index=0,
                replan_history=[],
            )

            # 发布计划创建事件
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_PLAN_CREATED,
                trace_id, session_id,
                {
                    "plan_id": agent_loop.goal.task_id,
                    "session_id": session_id,
                    "global_objective": {
                        "overall_goal": agent_loop.goal.global_goal,
                        "success_criteria": "; ".join(agent_loop.goal.acceptance_criteria),
                    },
                    "states": [
                        {
                            "state_id": s.step_id,
                            "order_index": i,
                            "responsibility": s.title,
                            "intent": s.intent,
                            "goal": s.expected_output,
                            "completion_criteria": [c.model_dump() for c in s.completion_criteria],
                            "depends_on": s.dependencies,
                            "required_skill_names": [],
                        }
                        for i, s in enumerate(steps)
                    ],
                    "planning_reason": plan_data.get("planning_reason", ""),
                    "budget_consumed": {"tool_calls": 0},
                    "budget_limit": {"max_total_tool_calls": agent_loop.budget.max_tool_calls},
                },
                self.event_publisher,
            )

            logger.info(
                f"[TraceID:{trace_id}] GlobalPlannerNode 完成: "
                f"steps={len(steps)}, "
                f"planning_reason={plan_data.get('planning_reason', '')[:100]}"
            )

        except Exception as exc:
            logger.error(f"[TraceID:{trace_id}] GlobalPlannerNode 异常: {exc}")
            agent_loop.terminated = True
            agent_loop.termination_reason = f"全局计划生成失败: {exc}"

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)

    def _build_plan_schema(self) -> dict[str, Any]:
        """构建全局计划生成的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "check": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "intent": {"type": "string"},
                            "expected_output": {"type": "string"},
                            "completion_criteria": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "field": {"type": "string"},
                                        "operator": {"type": "string"},
                                        "value": {},
                                    },
                                },
                            },
                            "dependencies": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "risk_notes": {"type": "string"},
                            "rollback_hint": {"type": "string"},
                            "pre_allocated_skills": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["title", "intent", "expected_output"],
                    },
                },
                "planning_reason": {"type": "string"},
            },
            "required": ["steps"],
        }

    def _parse_plan_response(self, response: str) -> dict[str, Any]:
        """解析 LLM 全局计划输出。"""
        try:
            if isinstance(response, dict):
                return response
            text = str(response).strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"全局计划 LLM 输出解析失败: {exc}")
            return {"steps": [], "planning_reason": str(response)}


# ===========================================================================
# 节点 3: StepRouterNode — 步骤路由（条件边）
# ===========================================================================


class StepRouterNode:
    """Agent Loop — 步骤路由节点。

    做什么：读取 PlanState.current_step_index，判断是否有未执行的步骤，
            路由到 step_think（继续）或 final_verify（全部完成）。
    为什么这样做：LangGraph 条件边需要一个源节点作为路由起点。
    """

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口（无操作，仅作为条件边源节点和 checkpoint 点）。"""
        return {}


def route_by_step(state: dict[str, Any]) -> str:
    """Step Loop 路由函数。

    做什么：判断是否有未执行的步骤，返回路由结果。
    路由逻辑：
        - 已终止 → final_verify
        - 预算耗尽 → final_verify
        - 还有未执行步骤 → step_think
        - 全部完成 → final_verify
    """
    chat_state, agent_loop = _extract_agent_loop_state(state)
    if agent_loop is None:
        return AgentStepRoute.FINAL_VERIFY.value

    # 终止条件
    if agent_loop.terminated:
        return AgentStepRoute.FINAL_VERIFY.value

    # 预算检查
    if agent_loop.budget.is_exhausted():
        agent_loop.terminated = True
        agent_loop.termination_reason = "预算耗尽"
        # 写回状态
        chat_state.dag_state.dag_engine_state = agent_loop.model_dump(mode="json")
        return AgentStepRoute.FINAL_VERIFY.value

    # 还有未执行步骤
    if agent_loop.plan.current_step_index < len(agent_loop.plan.steps):
        return AgentStepRoute.STEP_THINK.value

    # 全部完成
    return AgentStepRoute.FINAL_VERIFY.value


# ===========================================================================
# 节点 4: StepThinkNode — 步骤思考
# ===========================================================================


class StepThinkNode:
    """Agent Loop — 步骤思考节点。

    做什么：对当前步骤做局部思考（不重新定义全局目标），
            决定该步的最佳执行路径、确定需要哪些工具。
    为什么这样做：agent loop.md 要求每步先思考再执行。
    输出写入 ExecutionState.last_thought。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行步骤思考。

        做什么：
        1. 读取当前步骤定义
        2. 调用 LLM 进行局部思考
        3. 将思考结果写入 ExecutionState.last_thought
        4. 将规划的工具调用写入 ExecutionState.last_tool_calls
        5. 发布 EVT_DAG_STEP_THINKING 事件
        """
        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        if agent_loop.terminated:
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        # 安全守卫
        if agent_loop.plan.current_step_index >= len(agent_loop.plan.steps):
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        current_step = agent_loop.plan.steps[agent_loop.plan.current_step_index]
        current_step.status = StepStatusEnum.RUNNING
        agent_loop.execution.current_step_id = current_step.step_id

        try:
            # 构建上一步观察上下文（重试场景）
            retry_context = ""
            if agent_loop.execution.last_observation:
                retry_context = (
                    f"\n\n[上一次观察结果]\n{agent_loop.execution.last_observation}\n"
                    f"[上一次错误]\n{agent_loop.execution.last_error}\n"
                    f"[重试次数] {agent_loop.execution.retry_count}"
                )

            # 构建已完成步骤摘要
            completed_steps_text = ""
            if agent_loop.memory.step_summaries:
                summaries = [
                    f"- {s.get('title', '')}: {s.get('summary', '')}"
                    for s in agent_loop.memory.step_summaries
                ]
                completed_steps_text = "\n".join(summaries)

            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_STEP_THINK,
                variables={
                    "global_goal": agent_loop.goal.global_goal,
                    "acceptance_criteria": json.dumps(
                        agent_loop.goal.acceptance_criteria, ensure_ascii=False
                    ),
                    "non_goals": json.dumps(
                        agent_loop.goal.non_goals, ensure_ascii=False
                    ),
                    "step_title": current_step.title,
                    "step_intent": current_step.intent,
                    "step_expected_output": current_step.expected_output,
                    "step_completion_criteria": json.dumps(
                        [c.model_dump() for c in current_step.completion_criteria],
                        ensure_ascii=False,
                    ),
                    "step_risk_notes": current_step.risk_notes,
                    "step_rollback_hint": current_step.rollback_hint,
                    "retry_context": retry_context,
                    "completed_steps": completed_steps_text,
                    "disambiguated_text": agent_loop.disambiguated_text,
                    "memory_context": agent_loop.memory_context,
                },
            )

            logger.info(f"[DAG_STEP_THINK] DAG思考节点： {prompt_text}")

            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_think_schema(),
            )

            logger.info(f"[TraceID:{trace_id}] LLM 输出： {llm_response}")

            think_data = self._parse_think_response(llm_response)

            agent_loop.execution.last_thought = think_data.get("thought", "")
            agent_loop.execution.last_tool_calls = think_data.get("tool_calls", [])
            agent_loop.execution.last_error = ""

            # 发布思考事件
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_STEP_THINKING,
                trace_id, session_id,
                {
                    "plan_id": agent_loop.goal.task_id,
                    "step_id": current_step.step_id,
                    "step_index": agent_loop.plan.current_step_index,
                    "thought": agent_loop.execution.last_thought[:200],
                    "tool_calls_count": len(agent_loop.execution.last_tool_calls),
                },
                self.event_publisher,
            )

            logger.info(
                f"[TraceID:{trace_id}] StepThinkNode 完成: "
                f"step_id={current_step.step_id}, "
                f"tool_calls={len(agent_loop.execution.last_tool_calls)}"
            )

        except Exception as exc:
            logger.error(f"[TraceID:{trace_id}] StepThinkNode 异常: {exc}")
            agent_loop.execution.last_error = str(exc)
            agent_loop.execution.last_thought = f"思考异常: {exc}"

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)

    def _build_think_schema(self) -> dict[str, Any]:
        """构建步骤思考的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "thought": {
                    "type": "string",
                    "description": "对当前步骤的局部思考过程。",
                },
                "tool_calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string"},
                            "tool_name": {"type": "string"},
                            "parameters": {"type": "object"},
                            "purpose": {"type": "string"},
                        },
                        "required": ["tool_name"],
                    },
                    "description": "规划的工具调用列表。",
                },
            },
            "required": ["thought"],
        }

    def _parse_think_response(self, response: str) -> dict[str, Any]:
        """解析 LLM 步骤思考输出。"""
        try:
            if isinstance(response, dict):
                return response
            text = str(response).strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"thought": str(response), "tool_calls": []}


# ===========================================================================
# 节点 5: ToolExecuteNode — 工具执行
# ===========================================================================


class AgentToolExecuteNode:
    """Agent Loop — 工具执行节点。

    做什么：读取 ExecutionState.last_tool_calls，
            调用 MCP 工具执行网关，将结果写入 ExecutionState.partitioned_outputs。
    为什么这样做：对应 agent loop.md 的 Tool Calling 阶段。
    注意：复用现有 StepExecutor 和 ToolExecuteNode 的底层能力。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        mcp_tool_registry: Any,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
        gating_service: Any = None,
        snapshot_manager: Any = None,
    ):
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.mcp_tool_registry = mcp_tool_registry
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher
        self._gating_service = gating_service
        self._snapshot_manager = snapshot_manager

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行工具调用。

        做什么：
        1. 读取 ExecutionState.last_tool_calls
        2. 逐个调用 MCP 工具
        3. 将结果写入 ExecutionState.partitioned_outputs
        4. 更新 BudgetState.tool_calls_used
        """
        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        if agent_loop.terminated:
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        tool_calls = agent_loop.execution.last_tool_calls
        if not tool_calls:
            # 无工具调用（纯思考步骤），直接通过
            logger.info(
                f"[TraceID:{trace_id}] ToolExecuteNode: 无工具调用，跳过"
            )
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        # 恢复 gating 依赖
        gating_svc = self._gating_service
        snap_mgr = self._snapshot_manager
        if not gating_svc:
            try:
                from app.main import app as _fastapi_app
                gating_svc = getattr(_fastapi_app.state, "gating_service", None)
                if not snap_mgr:
                    redis_client = getattr(_fastapi_app.state, "redis_client", None)
                    if redis_client:
                        from app.gating.snapshot import GatingSnapshotManager
                        snap_mgr = GatingSnapshotManager(redis_client)
            except Exception:
                pass

        partitioned_outputs: dict[str, dict[str, Any]] = {}

        for tc in tool_calls:
            tool_name = tc.get("tool_name", "")
            skill_name = tc.get("skill_name", "")
            parameters = tc.get("parameters", {})
            tc_id = generate_string_id()

            # 检查预算
            if agent_loop.budget.tool_calls_used >= agent_loop.budget.max_tool_calls:
                logger.warning(
                    f"[TraceID:{trace_id}] ToolExecuteNode: 预算耗尽，跳过工具 {tool_name}"
                )
                partitioned_outputs[tc_id] = {
                    "success": False,
                    "error_message": "工具调用预算耗尽",
                    "tool_name": tool_name,
                }
                continue

            # 发布 NODE_STARTED 事件
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_NODE_STARTED,
                trace_id, session_id,
                {
                    "plan_id": agent_loop.goal.task_id,
                    "step_id": agent_loop.execution.current_step_id,
                    "node_id": tc_id,
                    "node_type": "tool_execute",
                    "tool_name": tool_name,
                },
                self.event_publisher,
            )

            try:
                # 调用 MCP 工具执行
                from app.workflow.dag.nodes.tool_execute import ToolExecuteNode as BaseToolExecutor
                from app.workflow.dag.types import AtomicNodeDefinition, DagNodeType

                tool_executor = BaseToolExecutor(
                    prompt_manager=self.prompt_manager,
                    llm_client=self.llm_client,
                    mcp_tool_registry=self.mcp_tool_registry,
                    chat_status_publisher=self.chat_status_publisher,
                )

                logger.info(
                    f"[TraceID:{trace_id}] ToolExecuteNode: 调用工具 {tool_name}"
                )

                # 构造 AtomicNodeDefinition 适配 execute 方法签名
                node_def = AtomicNodeDefinition(
                    node_id=tc_id,
                    node_type=DagNodeType.TOOL_EXECUTE,
                    tool_name=tool_name,
                    skill_name=skill_name,
                    parameter_hint=json.dumps(parameters, ensure_ascii=False)
                        if parameters else "",
                    gating_required=False,
                )

                result = await tool_executor.execute(
                    trace_id=trace_id,
                    node_def=node_def,
                    state_context={
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "gating_service": gating_svc,
                        "snapshot_manager": snap_mgr,
                        "skill_registry": self.mcp_tool_registry,
                    },
                )

                logger.info(
                    f"[TraceID:{trace_id}] ToolExecuteNode: 工具 {tool_name} "
                    f"执行完毕，结果：{result}"
                )

                partitioned_outputs[tc_id] = result
                agent_loop.budget.tool_calls_used += 1

                # 发布 NODE_COMPLETED 事件
                await _emit_dag_event(
                    DagWorkflowEventType.EVT_DAG_NODE_COMPLETED,
                    trace_id, session_id,
                    {
                        "plan_id": agent_loop.goal.task_id,
                        "step_id": agent_loop.execution.current_step_id,
                        "node_id": tc_id,
                        "node_type": "tool_execute",
                        "success": result.get("success", False),
                        "outputs": {
                            k: v for k, v in result.items()
                            if k not in ("success", "error_message")
                        },
                        "error_message": result.get("error_message", "")
                            if not result.get("success", True) else None,
                    },
                    self.event_publisher,
                )

            except Exception as exc:
                logger.error(
                    f"[TraceID:{trace_id}] ToolExecuteNode 异常: "
                    f"tool={tool_name}, error={exc}"
                )
                partitioned_outputs[tc_id] = {
                    "success": False,
                    "error_message": str(exc),
                    "tool_name": tool_name,
                }

        agent_loop.execution.partitioned_outputs = partitioned_outputs

        # 检查是否有工具返回了 gating_pending
        gating_pending = [
            nid for nid, out in partitioned_outputs.items()
            if out.get("gating_pending", False)
        ]
        if gating_pending:
            agent_loop.gating_suspended = True
            agent_loop.gating_pending_node_ids = gating_pending

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)


# ===========================================================================
# 节点 6: ObserveNode — 观察层
# ===========================================================================


class ObserveNode:
    """Agent Loop — 观察节点。

    做什么：将工具原始返回转换为结构化观察。
            判断：是否成功、带来了什么新信息、是否接近完成标准。
    为什么这样做：agent loop.md 要求工具返回 → 结构化 Observation。
    实现方式：轻量规则校验优先，LLM 校验降级。
    """

    def __init__(
        self,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        """初始化观察节点。

        参数:
            event_publisher: 工作流事件发布器，用于推送观察事件到前端。
        """
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 生成结构化观察。

        做什么：
        1. 读取 ExecutionState.partitioned_outputs
        2. 规则校验（关键字段非空、成功标志为 True）
        3. 生成结构化观察文本
        4. 写入 ExecutionState.last_observation
        5. 发布 EVT_DAG_STEP_OBSERVED 事件
        """
        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        if agent_loop.terminated:
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        try:
            outputs = agent_loop.execution.partitioned_outputs

            if not outputs:
                # 无工具输出（纯思考步骤）：将思考内容作为步骤产出
                # 为什么这样做：纯思考步骤（如问候回应、推理总结）的思考内容本身就是
                #               步骤的输出，不应仅声明"无工具输出"而丢失实际产出。
                #               观察层应如实反映步骤产出，使评估层能正确判断完成度。
                thought_content = agent_loop.execution.last_thought or ""
                agent_loop.execution.last_observation = (
                    f"本步骤为纯思考步骤（无工具调用）。思考过程即为本步骤的产出。\n\n"
                    f"## 思考内容\n{thought_content}"
                )
            else:
                # 规则校验：收集成功和失败的工具
                successes = []
                failures = []
                for nid, out in outputs.items():
                    if isinstance(out, dict):
                        if out.get("success", True):
                            successes.append({
                                "node_id": nid,
                                "tool_name": out.get("tool_name", "unknown"),
                                "output_preview": str(out.get("tool_output", ""))[:500],
                            })
                        else:
                            failures.append({
                                "node_id": nid,
                                "tool_name": out.get("tool_name", "unknown"),
                                "error": out.get("error_message", "未知错误"),
                            })

                # 构建结构化观察
                observation_parts = []
                if successes:
                    observation_parts.append(
                        f"成功执行 {len(successes)} 个工具:"
                    )
                    for s in successes:
                        observation_parts.append(
                            f"  - [{s['tool_name']}] 输出: {s['output_preview']}"
                        )
                if failures:
                    observation_parts.append(
                        f"失败 {len(failures)} 个工具:"
                    )
                    for f in failures:
                        observation_parts.append(
                            f"  - [{f['tool_name']}] 错误: {f['error']}"
                        )

                agent_loop.execution.last_observation = "\n".join(observation_parts)

            # 发布观察事件
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_STEP_OBSERVED,
                trace_id, session_id,
                {
                    "plan_id": agent_loop.goal.task_id,
                    "step_id": agent_loop.execution.current_step_id,
                    "observation_preview": agent_loop.execution.last_observation[:300],
                },
                self.event_publisher,
            )

            logger.info(
                f"[TraceID:{trace_id}] ObserveNode 完成: "
                f"step_id={agent_loop.execution.current_step_id}, "
                f"observation_len={len(agent_loop.execution.last_observation)}"
            )

        except Exception as exc:
            logger.error(f"[TraceID:{trace_id}] ObserveNode 异常: {exc}")
            agent_loop.execution.last_observation = f"观察生成异常: {exc}"

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)


# ===========================================================================
# 节点 7: StepEvaluateNode — 步骤评估
# ===========================================================================


class AgentStepEvaluateNode:
    """Agent Loop — 步骤评估节点。

    做什么：判断当前步骤是否完成，输出四种结论之一：
            pass / fail / partial / needs_replan。
    为什么这样做：agent loop.md 要求 Step 级评估（每步完成后），
                  而非 State 级评估（所有 Step 完成后）。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行步骤评估。

        做什么：
        1. 读取 ExecutionState.last_observation
        2. 读取当前步骤的 completion_criteria
        3. 调用 LLM 做深度评估
        4. 写入 ExecutionState.evaluation_result
        5. 发布 EVT_DAG_STEP_EVALUATED 事件
        """
        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        if agent_loop.terminated:
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        idx = agent_loop.plan.current_step_index
        if idx >= len(agent_loop.plan.steps):
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        current_step = agent_loop.plan.steps[idx]

        try:
            # 机械层预检：检查工具是否全部失败
            outputs = agent_loop.execution.partitioned_outputs
            all_failed = False
            if outputs:
                all_failed = all(
                    not out.get("success", True)
                    for out in outputs.values()
                    if isinstance(out, dict)
                )

            if all_failed:
                # 全部失败，直接判定 fail
                eval_result = StepEvaluationResult(
                    verdict=StepEvaluationVerdict.FAIL,
                    evaluation_reason="所有工具调用均失败",
                    gap_analysis="无法获取任何有效输出",
                    suggestion="检查工具参数或网络连接",
                )
            else:

                # 调用 LLM 做深度评估
                prompt_text = await self.prompt_manager.render(
                    category=PromptCategory.DAG_STEP_EVALUATE,
                    variables={
                        "step_title": current_step.title,
                        "step_intent": current_step.intent,
                        "step_expected_output": current_step.expected_output,
                        "step_completion_criteria": json.dumps(
                            [c.model_dump() for c in current_step.completion_criteria],
                            ensure_ascii=False,
                        ),
                        "observation": agent_loop.execution.last_observation,
                        "retry_count": agent_loop.execution.retry_count,
                        "repair_count": agent_loop.execution.repair_count,
                    },
                )

                logger.info(
                    f"[TraceID:{trace_id}] EvaluateNode 输入: "
                    f"step_id={agent_loop.execution.current_step_id}, "
                    f"prompt={prompt_text}"
                )

                llm_response = await self.llm_client.invoke_structured(
                    trace_id=trace_id,
                    prompt=prompt_text,
                    schema=self._build_evaluate_schema(),
                )

                logger.info(
                    f"[TraceID:{trace_id}] EvaluateNode 输出: "
                    f"step_id={agent_loop.execution.current_step_id}, "
                    f"llm_response={llm_response}"
                )

                eval_data = self._parse_evaluate_response(llm_response)

                verdict_str = eval_data.get("verdict", "pass")
                try:
                    verdict = StepEvaluationVerdict(verdict_str)
                except ValueError:
                    verdict = StepEvaluationVerdict.PASS

                eval_result = StepEvaluationResult(
                    verdict=verdict,
                    evaluation_reason=eval_data.get("evaluation_reason", ""),
                    gap_analysis=eval_data.get("gap_analysis", ""),
                    suggestion=eval_data.get("suggestion", ""),
                    criteria_checklist=eval_data.get("criteria_checklist", []),
                )

            # 重试阈值判断：fail 次数过多则升级为 needs_replan
            if eval_result.verdict == StepEvaluationVerdict.FAIL:
                if agent_loop.execution.retry_count >= agent_loop.budget.max_step_retries:
                    eval_result.verdict = StepEvaluationVerdict.NEEDS_REPLAN
                    eval_result.evaluation_reason += (
                        f"（重试次数 {agent_loop.execution.retry_count} "
                        f"已达到上限 {agent_loop.budget.max_step_retries}，"
                        f"升级为 needs_replan）"
                    )

            agent_loop.execution.evaluation_result = eval_result

            # 发布评估事件
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_STEP_EVALUATED,
                trace_id, session_id,
                {
                    "plan_id": agent_loop.goal.task_id,
                    "step_id": current_step.step_id,
                    "step_index": idx,
                    "verdict": eval_result.verdict.value,
                    "evaluation_reason": eval_result.evaluation_reason,
                    "gap_analysis": eval_result.gap_analysis,
                    "suggestion": eval_result.suggestion,
                },
                self.event_publisher,
            )

            logger.info(
                f"[TraceID:{trace_id}] StepEvaluateNode 完成: "
                f"step_id={current_step.step_id}, "
                f"verdict={eval_result.verdict.value}"
            )

        except Exception as exc:
            logger.error(f"[TraceID:{trace_id}] StepEvaluateNode 异常: {exc}")
            # 评估异常时默认通过，避免阻塞流程
            agent_loop.execution.evaluation_result = StepEvaluationResult(
                verdict=StepEvaluationVerdict.PASS,
                evaluation_reason=f"评估异常，自动通过: {exc}",
            )

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)

    def _build_evaluate_schema(self) -> dict[str, Any]:
        """构建步骤评估的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["pass", "fail", "partial", "needs_replan"],
                    "description": "评估结论。",
                },
                "evaluation_reason": {"type": "string"},
                "gap_analysis": {"type": "string"},
                "suggestion": {"type": "string"},
                "criteria_checklist": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion": {"type": "string"},
                            "met": {"type": "boolean"},
                            "evidence": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["verdict", "evaluation_reason"],
        }

    def _parse_evaluate_response(self, response: str) -> dict[str, Any]:
        """解析 LLM 步骤评估输出。"""
        try:
            if isinstance(response, dict):
                return response
            text = str(response).strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"verdict": "pass", "evaluation_reason": str(response)}


# ===========================================================================
# 节点 8: StepRepairNode — 局部修复
# ===========================================================================


class StepRepairNode:
    """Agent Loop — 局部修复节点。

    做什么：当 StepEvaluateNode 返回 fail 时，执行局部修复。
            修复策略：修正参数 / 换工具 / 补上下文 / 重试同一步。
    为什么这样做：agent loop.md 要求三级容错中的第一级 Repair。
    """

    def __init__(
        self,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        """初始化局部修复节点。

        做什么：注入事件发布器，用于发布修复相关事件。
        为什么这样做：与其他 Agent Loop 节点保持一致的依赖注入模式。
        """
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行局部修复。

        做什么：
        1. 读取上一次观察和评估结果
        2. 生成修复上下文
        3. 递增 retry_count
        4. 发布 EVT_DAG_STEP_REPAIRED 事件
        5. 清空上一次的观察和工具调用（准备重新思考）
        """
        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        try:
            eval_result = agent_loop.execution.evaluation_result

            # 构建修复上下文
            repair_context = (
                f"[上一次评估结论] {eval_result.verdict.value if eval_result else 'unknown'}\n"
                f"[评估原因] {eval_result.evaluation_reason if eval_result else ''}\n"
                f"[差距分析] {eval_result.gap_analysis if eval_result else ''}\n"
                f"[改进建议] {eval_result.suggestion if eval_result else ''}\n"
                f"[上一次观察] {agent_loop.execution.last_observation[:500]}"
            )

            # 递增重试计数
            agent_loop.execution.retry_count += 1
            agent_loop.execution.repair_count += 1
            agent_loop.budget.step_retries_used += 1

            # 将修复上下文注入到思考上下文中（通过 last_observation 传递）
            agent_loop.execution.last_observation = repair_context
            agent_loop.execution.last_error = ""
            # 清空上一次的工具调用（修复后需要重新规划）
            agent_loop.execution.last_tool_calls = []

            # 发布修复事件
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_STEP_REPAIRED,
                trace_id, session_id,
                {
                    "plan_id": agent_loop.goal.task_id,
                    "step_id": agent_loop.execution.current_step_id,
                    "retry_count": agent_loop.execution.retry_count,
                    "repair_count": agent_loop.execution.repair_count,
                },
                self.event_publisher,
            )

            logger.info(
                f"[TraceID:{trace_id}] StepRepairNode 完成: "
                f"step_id={agent_loop.execution.current_step_id}, "
                f"retry_count={agent_loop.execution.retry_count}"
            )

        except Exception as exc:
            logger.error(f"[TraceID:{trace_id}] StepRepairNode 异常: {exc}")

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)


# ===========================================================================
# 节点 9: ReplanNode — 步骤重规划
# ===========================================================================


class AgentReplanNode:
    """Agent Loop — 步骤重规划节点。

    做什么：只修改 PlanState.steps，绝不修改 GoalState。
            生成新的 PlanState 版本（plan_version += 1）。
    为什么这样做：agent loop.md 要求 replan 只改步骤不改目标，
                  防止目标漂移。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行步骤重规划。

        做什么：
        1. 检查 replan 预算
        2. 保存原始 GoalState 用于校验
        3. 调用 LLM 重构步骤计划
        4. 校验目标未被修改
        5. 递增 plan_version
        6. 发布 EVT_DAG_PLAN_REPLANNED 事件
        """
        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        # 检查 replan 预算
        if agent_loop.budget.replan_count >= agent_loop.budget.max_replan_count:
            logger.warning(
                f"[TraceID:{trace_id}] ReplanNode: "
                f"replan 已达上限 ({agent_loop.budget.max_replan_count})，终止"
            )
            agent_loop.terminated = True
            agent_loop.termination_reason = "重规划次数已达上限"
            agent_loop.termination_step_id = agent_loop.execution.current_step_id
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        # 保存原始目标用于校验
        original_goal = agent_loop.goal.global_goal
        original_criteria = list(agent_loop.goal.acceptance_criteria)

        try:
            # 构建已完成和待规划步骤信息
            completed_steps = []
            for s in agent_loop.plan.steps[:agent_loop.plan.current_step_index]:
                completed_steps.append({
                    "step_id": s.step_id,
                    "title": s.title,
                    "intent": s.intent,
                    "status": s.status.value,
                })

            remaining_steps = []
            for s in agent_loop.plan.steps[agent_loop.plan.current_step_index + 1:]:
                remaining_steps.append({
                    "step_id": s.step_id,
                    "title": s.title,
                    "intent": s.intent,
                    "expected_output": s.expected_output,
                })

            eval_result = agent_loop.execution.evaluation_result

            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_PLAN_REPLAN,
                variables={
                    "failed_state_id": agent_loop.execution.current_step_id,
                    "failed_state_responsibility": (
                        agent_loop.plan.steps[agent_loop.plan.current_step_index].title
                        if agent_loop.plan.current_step_index < len(agent_loop.plan.steps)
                        else ""
                    ),
                    "failed_state_intent": (
                        agent_loop.plan.steps[agent_loop.plan.current_step_index].intent
                        if agent_loop.plan.current_step_index < len(agent_loop.plan.steps)
                        else ""
                    ),
                    "failed_state_goal": (
                        agent_loop.plan.steps[agent_loop.plan.current_step_index].expected_output
                        if agent_loop.plan.current_step_index < len(agent_loop.plan.steps)
                        else ""
                    ),
                    "failed_state_result": agent_loop.execution.last_observation[:1000],
                    "evaluation_reason": eval_result.evaluation_reason if eval_result else "",
                    "gap_analysis": eval_result.gap_analysis if eval_result else "",
                    "suggestion": eval_result.suggestion if eval_result else "",
                    "completed_states": json.dumps(completed_steps, ensure_ascii=False),
                    "remaining_states": json.dumps(remaining_steps, ensure_ascii=False),
                    "global_objective": json.dumps({
                        "overall_goal": agent_loop.goal.global_goal,
                        "success_criteria": "; ".join(agent_loop.goal.acceptance_criteria),
                    }, ensure_ascii=False),
                    "non_goals": json.dumps(agent_loop.goal.non_goals, ensure_ascii=False),
                },
            )

            logger.info(
                f"[TraceID:{trace_id}] ReplanNode: "
                f"开始重规划步骤，当前步骤索引：{agent_loop.plan.current_step_index}"
                f"prompt_text={prompt_text}"
            )

            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_replan_schema(),
            )

            logger.info(
                f"[TraceID:{trace_id}] ReplanNode: "
                f"LLM 响应：{llm_response}"
            )

            replan_data = self._parse_replan_response(llm_response)

            # 构建新的步骤列表
            new_steps = []
            for i, step_data in enumerate(replan_data.get("revised_states", [])):
                from app.workflow.dag.types import CompletionCriterion
                criteria = []
                for c in step_data.get("completion_criteria", []):
                    criteria.append(CompletionCriterion(
                        field=c.get("field", ""),
                        operator=c.get("operator", "not_empty"),
                        value=c.get("value", True),
                    ))
                new_steps.append(AgentStepState(
                    step_id=generate_string_id(),
                    title=step_data.get("title", f"步骤 {i + 1}"),
                    intent=step_data.get("intent", ""),
                    dependencies=step_data.get("dependencies", []),
                    expected_output=step_data.get("expected_output", ""),
                    completion_criteria=criteria,
                    status=StepStatusEnum.PENDING,
                    risk_notes=step_data.get("risk_notes", ""),
                    rollback_hint=step_data.get("rollback_hint", ""),
                    pre_allocated_skills=step_data.get("pre_allocated_skills", []),
                ))

            # 校验：目标不可变
            assert agent_loop.goal.global_goal == original_goal, (
                "ReplanNode 非法修改了 global_goal"
            )
            assert agent_loop.goal.acceptance_criteria == original_criteria, (
                "ReplanNode 非法修改了 acceptance_criteria"
            )

            # 记录 replan 历史
            old_version = agent_loop.plan.plan_version
            replan_record = ReplanRecord(
                from_version=old_version,
                to_version=old_version + 1,
                reason=replan_data.get("replan_reason", ""),
                failed_step_id=agent_loop.execution.current_step_id,
                changed_step_ids=[s.step_id for s in new_steps],
                timestamp_ms=int(time.time() * 1000),
            )

            # 更新 PlanState
            agent_loop.plan.plan_version = old_version + 1
            agent_loop.plan.steps = new_steps
            agent_loop.plan.current_step_index = 0
            agent_loop.plan.replan_history.append(replan_record)

            # 递增 replan 计数
            agent_loop.budget.replan_count += 1

            # 重置执行状态
            agent_loop.execution = ExecutionState()

            # 记录失败模式到记忆
            agent_loop.memory.failure_patterns.append(
                f"[v{old_version}] {eval_result.evaluation_reason if eval_result else '未知原因'}"
            )

            # 发布 replan 事件
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_PLAN_REPLANNED,
                trace_id, session_id,
                {
                    "plan_id": agent_loop.goal.task_id,
                    "replan_reason": replan_data.get("replan_reason", ""),
                    "plan_version": agent_loop.plan.plan_version,
                    "modified_states": [
                        {
                            "state_id": s.step_id,
                            "order_index": i,
                            "responsibility": s.title,
                            "intent": s.intent,
                            "goal": s.expected_output,
                        }
                        for i, s in enumerate(new_steps)
                    ],
                },
                self.event_publisher,
            )

            logger.info(
                f"[TraceID:{trace_id}] ReplanNode 完成: "
                f"plan_version={agent_loop.plan.plan_version}, "
                f"new_steps={len(new_steps)}, "
                f"replan_count={agent_loop.budget.replan_count}"
            )

        except AssertionError as ae:
            raise ae
        except Exception as exc:
            logger.error(f"[TraceID:{trace_id}] ReplanNode 异常: {exc}")
            agent_loop.terminated = True
            agent_loop.termination_reason = f"重规划失败: {exc}"
            agent_loop.termination_step_id = agent_loop.execution.current_step_id

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)

    def _build_replan_schema(self) -> dict[str, Any]:
        """构建重规划的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "check": {"type": "string"},
                "revised_states": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "intent": {"type": "string"},
                            "expected_output": {"type": "string"},
                            "completion_criteria": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "field": {"type": "string"},
                                        "operator": {"type": "string"},
                                        "value": {},
                                    },
                                },
                            },
                            "dependencies": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "risk_notes": {"type": "string"},
                            "rollback_hint": {"type": "string"},
                            "pre_allocated_skills": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["title", "intent", "expected_output"],
                    },
                },
                "replan_reason": {"type": "string"},
            },
            "required": ["revised_states", "replan_reason"],
        }

    def _parse_replan_response(self, response: str) -> dict[str, Any]:
        """解析 LLM 重规划输出。"""
        try:
            if isinstance(response, dict):
                return response
            text = str(response).strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"重规划 LLM 输出解析失败: {exc}")
            return {"revised_states": [], "replan_reason": str(response)}


# ===========================================================================
# 节点 10: FinalVerifyNode — 最终验收
# ===========================================================================


class AgentFinalVerifyNode:
    """Agent Loop — 最终验收节点。

    做什么：所有步骤完成后，对照全局目标做最终验收。
            逐条检查 GoalState.acceptance_criteria，生成最终报告。
    为什么这样做：agent loop.md 要求 FinalVerifyNode 对照全局目标验收，
                  而不只是汇总结果。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行最终验收。

        做什么：
        1. 收集所有 Step 结果
        2. 调用 LLM 对照验收标准做最终验证
        3. 生成最终报告
        4. 发布 EVT_DAG_FINAL_VERIFIED / EVT_DAG_PLAN_COMPLETED 事件
        5. 将结果写回 ChatWorkflowState
        """
        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            logger.warning("FinalVerifyNode: agent_loop_state 为空")
            chat_state.dag_state.is_dag_active = True
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id
        started_at_ms = agent_loop.workflow_state.get("dag_engine_started_at_ms", 0)

        try:
            # 收集步骤结果摘要
            step_results = []
            for i, step in enumerate(agent_loop.plan.steps):
                summary = ""
                for ss in agent_loop.memory.step_summaries:
                    if ss.get("step_id") == step.step_id:
                        summary = ss.get("summary", "")
                        break
                step_results.append({
                    "step_id": step.step_id,
                    "title": step.title,
                    "intent": step.intent,
                    "status": step.status.value,
                    "summary": summary,
                })

            # 调用 LLM 做最终验收
            verification = {"status": "completed", "report": ""}

            try:
                from datetime import datetime
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

                prompt_text = await self.prompt_manager.render(
                    category=PromptCategory.DAG_FINAL_VERIFY,
                    variables={
                        "global_goal": agent_loop.goal.global_goal,
                        "goal_definition": agent_loop.goal.goal_definition,
                        "acceptance_criteria": json.dumps(
                            agent_loop.goal.acceptance_criteria, ensure_ascii=False
                        ),
                        "non_goals": json.dumps(
                            agent_loop.goal.non_goals, ensure_ascii=False
                        ),
                        "step_results": json.dumps(step_results, ensure_ascii=False),
                        "plan_version": agent_loop.plan.plan_version,
                        "replan_count": agent_loop.budget.replan_count,
                        "tool_calls_used": agent_loop.budget.tool_calls_used,
                        "terminated": agent_loop.terminated,
                        "termination_reason": agent_loop.termination_reason,
                        "CURRENT_TIME": current_time,
                    },
                )

                logger.info(f"[TraceID:{trace_id}] FinalVerifyNode LLM 调用: {prompt_text}")

                llm_response = await self.llm_client.invoke_structured(
                    trace_id=trace_id,
                    prompt=prompt_text,
                    schema=self._build_verify_schema(),
                )

                logger.info(f"[TraceID:{trace_id}] FinalVerifyNode LLM 输出: {llm_response}")

                verify_data = self._parse_verify_response(llm_response)

                verification = {
                    "status": verify_data.get("status", "completed"),
                    "report": verify_data.get("report", ""),
                    "criteria_verification": verify_data.get("criteria_verification", []),
                    "all_criteria_met": verify_data.get("all_criteria_met", True),
                }

            except Exception as exc:
                logger.error(f"[TraceID:{trace_id}] FinalVerifyNode LLM 调用异常: {exc}")
                verification = {
                    "status": "completed_with_gaps",
                    "report": f"验收过程异常: {exc}",
                    "all_criteria_met": False,
                }

            agent_loop.final_verification = verification

            # 构建 Plan 汇总结果（兼容前端 EVT_DAG_PLAN_COMPLETED）
            elapsed_ms = int(time.time() * 1000) - started_at_ms if started_at_ms else 0

            succeeded = sum(
                1 for s in agent_loop.plan.steps if s.status == StepStatusEnum.PASSED
            )
            failed = sum(
                1 for s in agent_loop.plan.steps if s.status == StepStatusEnum.FAILED
            )

            plan_summary = {
                "plan_id": agent_loop.goal.task_id,
                "total_states": len(agent_loop.plan.steps),
                "succeeded_states": succeeded,
                "failed_states": failed,
                "overall_result": verification.get("report", ""),
                "execution_highlights": [],
                "execution_issues": [],
                "elapsed_ms": elapsed_ms,
                "plan_version": agent_loop.plan.plan_version,
            }
            agent_loop.plan_summary = plan_summary

            # 发布最终验收事件
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_FINAL_VERIFIED,
                trace_id, session_id,
                {
                    "plan_id": agent_loop.goal.task_id,
                    "verification_status": verification.get("status", ""),
                    "all_criteria_met": verification.get("all_criteria_met", True),
                    "report_preview": verification.get("report", "")[:300],
                },
                self.event_publisher,
            )

            # 发布 Plan 完成/终止事件
            if agent_loop.terminated:
                await _emit_dag_event(
                    DagWorkflowEventType.EVT_DAG_PLAN_TERMINATED,
                    trace_id, session_id,
                    {
                        "plan_id": agent_loop.goal.task_id,
                        "termination_reason": agent_loop.termination_reason,
                        "termination_step_id": agent_loop.termination_step_id,
                        "partial_results": verification.get("report", ""),
                    },
                    self.event_publisher,
                )
            else:
                await _emit_dag_event(
                    DagWorkflowEventType.EVT_DAG_PLAN_COMPLETED,
                    trace_id, session_id,
                    plan_summary,
                    self.event_publisher,
                )

            logger.info(
                f"[TraceID:{trace_id}] FinalVerifyNode 完成: "
                f"status={verification.get('status', '')}, "
                f"all_criteria_met={verification.get('all_criteria_met', True)}, "
                f"elapsed_ms={elapsed_ms}"
            )

        except Exception as exc:
            logger.error(f"[TraceID:{trace_id}] FinalVerifyNode 异常: {exc}")
            agent_loop.terminated = True
            agent_loop.termination_reason = f"最终验收异常: {exc}"

        # 发布引擎入口完成状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_ENGINE_ENTRY,
            state=ChatStatusState.COMPLETED,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_ENGINE_ENTRY, ChatStatusState.COMPLETED
            ),
            is_visible=True,
            is_terminal=True,
        )

        # 将结果写回 ChatWorkflowState
        chat_state.dag_state.is_dag_active = True
        chat_state.dag_state.dag_engine_state = agent_loop.model_dump(mode="json")
        chat_state.dag_state.disambiguated_text = agent_loop.disambiguated_text
        chat_state.dag_state.unresolved_pronouns = agent_loop.unresolved_pronouns

        summary = agent_loop.plan_summary
        if summary:
            chat_state.dag_state.plan_summary_text = summary.get("overall_result", "")

        if agent_loop.terminated:
            chat_state.dag_state.terminated = True
            chat_state.dag_state.termination_reason = agent_loop.termination_reason
            # 收集已完成步骤的部分结果
            partial_parts = []
            for step in agent_loop.plan.steps:
                if step.status == StepStatusEnum.PASSED:
                    partial_parts.append(f"- {step.title}: {step.expected_output}")
            chat_state.dag_state.partial_results = "\n".join(partial_parts)

        if summary and summary.get("overall_result"):
            chat_state.mcp_tool_state.execution_summary = summary.get("overall_result", "")

        return chat_state.as_graph_state()

    def _build_verify_schema(self) -> dict[str, Any]:
        """构建最终验收的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["completed", "completed_with_gaps", "failed"],
                },
                "report": {
                    "type": "string",
                    "description": "最终验收报告，面向用户的总结文本。",
                },
                "all_criteria_met": {"type": "boolean"},
                "criteria_verification": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion": {"type": "string"},
                            "met": {"type": "boolean"},
                            "evidence": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["status", "report"],
        }

    def _parse_verify_response(self, response: str) -> dict[str, Any]:
        """解析 LLM 最终验收输出。"""
        try:
            if isinstance(response, dict):
                return response
            text = str(response).strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"status": "completed", "report": str(response), "all_criteria_met": True}


# ===========================================================================
# 节点 9: FastPassNode — 纯思考步骤快速通过
# ===========================================================================


class FastPassNode:
    """Agent Loop — 纯思考步骤快速通过节点。

    做什么：当 StepThinkNode 返回空 tool_calls 时，跳过 Execute/Observe/Evaluate，
            直接将 thought 内容作为步骤产出，标记为 PASSED 并推进到下一步。
    为什么这样做：纯思考步骤（如问候回应、推理总结）的思考内容本身就是步骤输出，
                  无需经过工具执行和评估验证，避免浪费 3 次 LLM 调用（Observe 无 LLM
                  但 StepEvaluate 需要 LLM）和 token。
                  思考结果通过 step_summaries 流入 FinalVerifyNode 的汇总管道，
                  最终注入 MainChatLlmNode 生成面向用户的回复。
    输入输出：
        - 输入：AgentLoopState（含 execution.last_thought）
        - 输出：更新后的 AgentLoopState（step 标记 PASSED，index 推进，execution 重置）
    边界条件：
        - agent_loop 为空时静默返回。
        - 无当前步骤时静默返回。
    """

    def __init__(
        self,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        """初始化纯思考步骤快速通过节点。

        参数:
            event_publisher: 工作流事件发布器，用于推送步骤完成事件到前端。
        """
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行纯思考步骤快速通过。

        做什么：
        1. 读取当前步骤和 thought 内容
        2. 将 thought 作为步骤摘要写入 memory.step_summaries
        3. 标记当前步骤为 PASSED
        4. 推进 current_step_index
        5. 重置执行状态（准备下一步）
        6. 发布 EVT_DAG_STEP_EVALUATED 事件（verdict=pass，由快速通道）
        """
        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        if agent_loop.terminated:
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        idx = agent_loop.plan.current_step_index
        if idx >= len(agent_loop.plan.steps):
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        current_step = agent_loop.plan.steps[idx]
        thought_content = agent_loop.execution.last_thought or ""

        try:
            # 将 thought 作为步骤摘要写入记忆（与 route_by_step_evaluation 的 pass 路径一致）
            agent_loop.memory.step_summaries.append({
                "step_id": current_step.step_id,
                "title": current_step.title,
                "summary": thought_content[:500],
            })

            # 标记步骤完成
            current_step.status = StepStatusEnum.PASSED

            # 推进到下一步
            agent_loop.plan.current_step_index += 1

            # 重置执行状态（准备下一步，与 route_by_step_evaluation 的 pass 路径一致）
            agent_loop.execution = ExecutionState()

            # 发布评估事件（verdict=pass，标记为快速通道）
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_STEP_EVALUATED,
                trace_id, session_id,
                {
                    "plan_id": agent_loop.goal.task_id,
                    "step_id": current_step.step_id,
                    "step_index": idx,
                    "verdict": "pass",
                    "evaluation_reason": "纯思考步骤快速通过：无工具调用，thought 即为产出",
                    "fast_pass": True,
                },
                self.event_publisher,
            )

            logger.info(
                f"[TraceID:{trace_id}] FastPassNode 完成: "
                f"step_id={current_step.step_id}, "
                f"thought_len={len(thought_content)}"
            )

        except Exception as exc:
            logger.error(f"[TraceID:{trace_id}] FastPassNode 异常: {exc}")
            # 异常时仍标记通过，避免阻塞流程
            current_step.status = StepStatusEnum.PASSED
            agent_loop.plan.current_step_index += 1
            agent_loop.execution = ExecutionState()

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)


# ===========================================================================
# Step Router 路由函数（评估结果路由 + 思考后路由）
# ===========================================================================


def route_by_step_evaluation(state: dict[str, Any]) -> str:
    """Step 评估路由函数。

    做什么：根据 StepEvaluateNode 的评估结果路由到不同处理节点。
    路由逻辑：
        - pass → step_router（推进到下一步）
        - fail → step_repair（尝试修复）
        - needs_replan → replan（重规划）
    """
    _, agent_loop = _extract_agent_loop_state(state)
    if agent_loop is None:
        return StepEvaluationRoute.PASS.value

    eval_result = agent_loop.execution.evaluation_result
    if eval_result is None:
        return StepEvaluationRoute.PASS.value

    verdict = eval_result.verdict

    if verdict == StepEvaluationVerdict.PASS or verdict == StepEvaluationVerdict.PARTIAL:
        # 通过或部分通过：标记步骤完成，推进到下一步
        idx = agent_loop.plan.current_step_index
        if idx < len(agent_loop.plan.steps):
            agent_loop.plan.steps[idx].status = StepStatusEnum.PASSED
            # 记录步骤摘要到记忆
            agent_loop.memory.step_summaries.append({
                "step_id": agent_loop.plan.steps[idx].step_id,
                "title": agent_loop.plan.steps[idx].title,
                "summary": agent_loop.execution.last_observation[:500],
            })
        agent_loop.plan.current_step_index += 1
        # 重置执行状态（准备下一步）
        agent_loop.execution = ExecutionState()
        return StepEvaluationRoute.PASS.value

    if verdict == StepEvaluationVerdict.FAIL:
        return StepEvaluationRoute.FAIL.value

    if verdict == StepEvaluationVerdict.NEEDS_REPLAN:
        return StepEvaluationRoute.NEEDS_REPLAN.value

    return StepEvaluationRoute.PASS.value


# ===========================================================================
# Step 思考后路由函数
# ===========================================================================

# 思考后路由结果常量（与 AgentStepLoopSubGraphNodeName 值对齐）
_AFTER_THINK_TOOL_EXECUTE = "tool_execute"
_AFTER_THINK_FAST_PASS = "fast_pass"


def route_after_think(state: dict[str, Any]) -> str:
    """步骤思考后路由函数。

    做什么：根据 StepThinkNode 的 tool_calls 输出决定执行路径。
    路由逻辑：
        - tool_calls 非空 → tool_execute（正常工具执行路径）
        - tool_calls 为空 → fast_pass（纯思考步骤快速通过，跳过 Execute/Observe/Evaluate）
    为什么这样做：纯思考步骤（如问候回应、推理总结）的思考内容本身就是步骤输出，
                  无需经过工具执行和三步评估循环，节省 LLM 调用和 token 消耗。
    """
    _, agent_loop = _extract_agent_loop_state(state)
    if agent_loop is None:
        return _AFTER_THINK_TOOL_EXECUTE

    # tool_calls 非空 → 走正常工具执行路径
    if agent_loop.execution.last_tool_calls:
        return _AFTER_THINK_TOOL_EXECUTE

    # tool_calls 为空 → 纯思考步骤，走快速通过路径
    return _AFTER_THINK_FAST_PASS


# ===========================================================================
# Step Loop 子图工厂
# ===========================================================================


def build_step_loop_subgraph(
    step_think: StepThinkNode,
    tool_execute: AgentToolExecuteNode,
    observe: ObserveNode,
    step_evaluate: AgentStepEvaluateNode,
    step_repair: StepRepairNode,
    replan: AgentReplanNode,
    fast_pass: FastPassNode,
    event_publisher: ChatWorkflowEventPublisher | None = None,
) -> Any:
    """构建 Step Loop 内层子图。

    做什么：创建 8 节点 LangGraph 子图，实现步进执行循环。
    拓扑：
        step_router → step_think →（条件路由）
            ├─ tool_calls 非空 → tool_execute → observe → step_evaluate
            │       ├─ pass → step_router（循环）
            │       ├─ fail → step_repair → step_think（重试）
            │       └─ needs_replan → replan → step_router（重规划后循环）
            └─ tool_calls 为空 → fast_pass → step_router（快速通过循环）
    返回:
        CompiledGraph: 编译后的子图。
    """
    graph = StateGraph(ChatWorkflowState)

    # 创建无操作路由节点
    step_router = StepRouterNode()

    # 注册节点（8 个节点，含 fast_pass）
    graph.add_node(AgentStepLoopSubGraphNodeName.STEP_ROUTER.value, step_router)
    graph.add_node(AgentStepLoopSubGraphNodeName.STEP_THINK.value, step_think)
    graph.add_node(AgentStepLoopSubGraphNodeName.TOOL_EXECUTE.value, tool_execute)
    graph.add_node(AgentStepLoopSubGraphNodeName.OBSERVE.value, observe)
    graph.add_node(AgentStepLoopSubGraphNodeName.STEP_EVALUATE.value, step_evaluate)
    graph.add_node(AgentStepLoopSubGraphNodeName.STEP_REPAIR.value, step_repair)
    graph.add_node(AgentStepLoopSubGraphNodeName.REPLAN.value, replan)
    graph.add_node(AgentStepLoopSubGraphNodeName.FAST_PASS.value, fast_pass)

    # 入口 → step_router
    graph.set_entry_point(AgentStepLoopSubGraphNodeName.STEP_ROUTER.value)

    # step_router → step_think（继续）或 END（全部完成）
    graph.add_conditional_edges(
        AgentStepLoopSubGraphNodeName.STEP_ROUTER.value,
        route_by_step,
        {
            AgentStepRoute.STEP_THINK.value:
                AgentStepLoopSubGraphNodeName.STEP_THINK.value,
            AgentStepRoute.FINAL_VERIFY.value:
                END,
        },
    )

    # step_think → 条件路由：有工具调用走 tool_execute，无工具调用走 fast_pass
    graph.add_conditional_edges(
        AgentStepLoopSubGraphNodeName.STEP_THINK.value,
        route_after_think,
        {
            _AFTER_THINK_TOOL_EXECUTE:
                AgentStepLoopSubGraphNodeName.TOOL_EXECUTE.value,
            _AFTER_THINK_FAST_PASS:
                AgentStepLoopSubGraphNodeName.FAST_PASS.value,
        },
    )

    # tool_execute → observe → step_evaluate（工具执行完整路径）
    graph.add_edge(
        AgentStepLoopSubGraphNodeName.TOOL_EXECUTE.value,
        AgentStepLoopSubGraphNodeName.OBSERVE.value,
    )
    graph.add_edge(
        AgentStepLoopSubGraphNodeName.OBSERVE.value,
        AgentStepLoopSubGraphNodeName.STEP_EVALUATE.value,
    )

    # step_evaluate → 路由
    graph.add_conditional_edges(
        AgentStepLoopSubGraphNodeName.STEP_EVALUATE.value,
        route_by_step_evaluation,
        {
            StepEvaluationRoute.PASS.value:
                AgentStepLoopSubGraphNodeName.STEP_ROUTER.value,
            StepEvaluationRoute.FAIL.value:
                AgentStepLoopSubGraphNodeName.STEP_REPAIR.value,
            StepEvaluationRoute.NEEDS_REPLAN.value:
                AgentStepLoopSubGraphNodeName.REPLAN.value,
        },
    )

    # step_repair → step_think（修复后重新思考）
    graph.add_edge(
        AgentStepLoopSubGraphNodeName.STEP_REPAIR.value,
        AgentStepLoopSubGraphNodeName.STEP_THINK.value,
    )

    # replan → step_router（重规划后回到路由）
    graph.add_edge(
        AgentStepLoopSubGraphNodeName.REPLAN.value,
        AgentStepLoopSubGraphNodeName.STEP_ROUTER.value,
    )

    # fast_pass → step_router（纯思考步骤快速通过后回到路由推进下一步）
    graph.add_edge(
        AgentStepLoopSubGraphNodeName.FAST_PASS.value,
        AgentStepLoopSubGraphNodeName.STEP_ROUTER.value,
    )

    return graph.compile()


# ===========================================================================
# Agent Loop 外层子图工厂
# ===========================================================================


def build_agent_loop_subgraph(
    goal_lock: GoalLockNode,
    global_planner: GlobalPlannerNode,
    step_think: StepThinkNode,
    tool_execute: AgentToolExecuteNode,
    observe: ObserveNode,
    step_evaluate: AgentStepEvaluateNode,
    step_repair: StepRepairNode,
    replan: AgentReplanNode,
    final_verify: AgentFinalVerifyNode,
    chat_status_publisher: ChatStatusPublisher,
    event_publisher: ChatWorkflowEventPublisher | None = None,
) -> Any:
    """构建 Agent Loop 子图。

    做什么：创建 6 层 Agent Loop 的 LangGraph 子图。
    拓扑：
        goal_lock → global_planner → step_loop_subgraph → final_verify → END
    其中 step_loop_subgraph 内部：
        step_router → step_think →（条件路由）
            ├─ tool_calls 非空 → tool_execute → observe → step_evaluate
            │       ├─ pass → step_router（循环）
            │       ├─ fail → step_repair → step_think（重试）
            │       └─ needs_replan → replan → step_router（重规划后循环）
            └─ tool_calls 为空 → fast_pass → step_router（快速通过循环）
    返回:
        CompiledGraph: 编译后的子图，可被 DagEngineNode 作为 ainvoke 调用。
    """
    # 创建纯思考步骤快速通过节点
    fast_pass = FastPassNode(event_publisher=event_publisher)

    # === 构建 Step Loop 内层子图 ===
    step_loop_subgraph = build_step_loop_subgraph(
        step_think=step_think,
        tool_execute=tool_execute,
        observe=observe,
        step_evaluate=step_evaluate,
        step_repair=step_repair,
        replan=replan,
        fast_pass=fast_pass,
        event_publisher=event_publisher,
    )

    # === 构建 Agent Loop 外层子图 ===
    agent_loop_graph = StateGraph(ChatWorkflowState)

    agent_loop_graph.add_node(AgentLoopSubGraphNodeName.GOAL_LOCK.value, goal_lock)
    agent_loop_graph.add_node(AgentLoopSubGraphNodeName.GLOBAL_PLANNER.value, global_planner)
    agent_loop_graph.add_node(AgentLoopSubGraphNodeName.STEP_LOOP.value, step_loop_subgraph)
    agent_loop_graph.add_node(AgentLoopSubGraphNodeName.FINAL_VERIFY.value, final_verify)

    agent_loop_graph.set_entry_point(AgentLoopSubGraphNodeName.GOAL_LOCK.value)
    agent_loop_graph.add_edge(
        AgentLoopSubGraphNodeName.GOAL_LOCK.value,
        AgentLoopSubGraphNodeName.GLOBAL_PLANNER.value,
    )
    agent_loop_graph.add_edge(
        AgentLoopSubGraphNodeName.GLOBAL_PLANNER.value,
        AgentLoopSubGraphNodeName.STEP_LOOP.value,
    )
    agent_loop_graph.add_edge(
        AgentLoopSubGraphNodeName.STEP_LOOP.value,
        AgentLoopSubGraphNodeName.FINAL_VERIFY.value,
    )
    agent_loop_graph.add_edge(
        AgentLoopSubGraphNodeName.FINAL_VERIFY.value,
        END,
    )

    return agent_loop_graph.compile()
