"""Phase 9 DAG 引擎 — Plan 重构节点。

做什么：当 State 评估不通过时，压缩当前 State 的执行结果，
        修改当前 State 和后续 State 的定义，不改变已完成的 State。
Prompt：使用 dag_plan_replan 三槽位 Prompt。
限制：整个 Plan 生命周期内最多触发 1 次重构。
"""

from __future__ import annotations

import json
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.dag.types import (
    DagEngineState,
    OverallState,
    ReplanContext,
    StateBudget,
)


class PlanReplanNode:
    """Plan 重构节点。

    做什么：当 State 评估不通过时，压缩当前 State 的执行结果，
            修改当前 State 和后续 State 的定义，不改变已完成的 State。
    为什么这样做：首次评估失败可能是因为 State 目标或标准不合理，
                  调整后续 State 的定义比盲目重试更有效。
    限制：整个 Plan 生命周期内最多触发 1 次重构。
    """

    MAX_REPLAN_COUNT = 1

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 Plan 重构节点。"""
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def execute(
        self,
        trace_id: str,
        session_id: str,
        dag_state: DagEngineState,
        replan_context: ReplanContext,
    ) -> DagEngineState:
        """执行 Plan 重构。

        做什么：调用 LLM 重构当前和后续 State 的定义。
        返回:
            DagEngineState: 更新后的 DAG 引擎状态。
        """
        # 检查重构次数限制
        if dag_state.plan_replan_count >= self.MAX_REPLAN_COUNT:
            logger.warning(
                f"[TraceID:{trace_id}] Plan 重构已达上限 ({self.MAX_REPLAN_COUNT})，"
                f"跳过重构"
            )
            dag_state.terminated = True
            dag_state.termination_reason = "Plan 重构已达上限，无法继续"
            dag_state.termination_state_id = replan_context.failed_state_id
            return dag_state

        # 发布 RUNNING 状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_PLAN_REPLAN,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_PLAN_REPLAN, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        try:
            # 渲染 Plan 重构 Prompt
            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_PLAN_REPLAN,
                variables={
                    "failed_state_id": replan_context.failed_state_id,
                    "failed_state_goal": replan_context.failed_state_goal,
                    "failed_state_result": replan_context.failed_state_result,
                    "evaluation_reason": replan_context.evaluation_reason,
                    "gap_analysis": replan_context.gap_analysis,
                    "suggestion": replan_context.suggestion,
                    "completed_states": json.dumps(
                        replan_context.completed_states, ensure_ascii=False
                    ),
                    "remaining_states": json.dumps(
                        replan_context.remaining_states, ensure_ascii=False
                    ),
                    "global_objective": json.dumps({
                        "overall_goal": replan_context.global_objective.overall_goal,
                        "success_criteria": replan_context.global_objective.success_criteria,
                    }, ensure_ascii=False),
                },
            )

            logger.info(
                f"[TraceID:{trace_id}] Plan 重构 Prompt: "
                f"{prompt_text}"
            )

            # 调用 LLM 重构 Plan
            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_replan_schema(),
            )

            # 解析重构结果
            replan_data = self._parse_replan_response(llm_response)

            # 更新 Plan 中的 State 列表
            self._apply_replan(dag_state, replan_data)

            # 递增重构计数
            dag_state.plan_replan_count += 1

            logger.info(
                f"[TraceID:{trace_id}] Plan 重构完成: "
                f"replan_count={dag_state.plan_replan_count}, "
                f"remaining_states={len(dag_state.plan.states) - dag_state.cursor}"
                f"prompt={prompt_text}"
            )

            # 发布 SUCCEEDED 状态
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_PLAN_REPLAN,
                state=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_PLAN_REPLAN, ChatStatusState.COMPLETED
                ),
                is_visible=True,
                is_terminal=True,
            )

        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] Plan 重构失败: {e}")
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_PLAN_REPLAN,
                state=ChatStatusState.ERROR,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_PLAN_REPLAN, ChatStatusState.ERROR
                ),
                is_visible=True,
                is_terminal=True,
            )
            # 重构失败时标记终止
            dag_state.terminated = True
            dag_state.termination_reason = f"Plan 重构失败: {e}"
            dag_state.termination_state_id = replan_context.failed_state_id

        return dag_state

    def _build_replan_schema(self) -> dict[str, Any]:
        """构建 Plan 重构的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "revised_states": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "order_index": {"type": "integer"},
                            "intent": {"type": "string"},
                            "goal": {"type": "string"},
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
                            "required_skill_names": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["order_index", "intent", "goal"],
                    },
                },
                "replan_reason": {"type": "string"},
            },
            "required": ["revised_states"],
        }

    def _parse_replan_response(
        self, llm_response: str | dict
    ) -> dict[str, Any]:
        """解析 Plan 重构的 LLM 输出。"""
        if isinstance(llm_response, dict):
            return llm_response
        try:
            return json.loads(llm_response)
        except json.JSONDecodeError as e:
            logger.error(f"Plan 重构 LLM 输出 JSON 解析失败: {e}")
            import re
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"revised_states": [], "replan_reason": "解析失败"}

    def _apply_replan(
        self,
        dag_state: DagEngineState,
        replan_data: dict[str, Any],
    ) -> None:
        """将重构结果应用到 Plan。

        做什么：替换 cursor 位置及之后的 State 定义，
               保留已完成的 State 不变。
        """
        from app.workflow.dag.types import CompletionCriterion

        revised_states = replan_data.get("revised_states", [])
        if not revised_states:
            return

        # 保留已完成的 State（cursor 之前的）
        completed_states = dag_state.plan.states[:dag_state.cursor]

        # 构建新的 State 列表
        new_states = []
        for state_data in revised_states:
            criteria = []
            for c in state_data.get("completion_criteria", []):
                criteria.append(CompletionCriterion(
                    field=c.get("field", ""),
                    operator=c.get("operator", ">="),
                    value=c.get("value"),
                ))

            state = OverallState(
                order_index=state_data.get("order_index", 0),
                intent=state_data.get("intent", ""),
                goal=state_data.get("goal", ""),
                completion_criteria=criteria,
                required_skill_names=state_data.get("required_skill_names", []),
                budget=StateBudget(),
            )
            new_states.append(state)

        # 更新 Plan 的 State 列表
        dag_state.plan.states = completed_states + new_states

        logger.info(
            f"Plan 重构应用完成: "
            f"completed={len(completed_states)}, "
            f"revised={len(new_states)}, "
            f"total={len(dag_state.plan.states)}"
        )
