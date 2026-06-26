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
                    "failed_state_responsibility": replan_context.failed_state_responsibility,
                    "failed_state_intent": replan_context.failed_state_intent,
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

            # 重试机制：Pydantic 参数校验失败时最多重试 2 次（共 3 次尝试）
            from pydantic import ValidationError

            max_retries = 3
            replan_data: dict[str, Any] = {}

            for attempt in range(max_retries):
                try:
                    # 调用 LLM 重构 Plan
                    llm_response = await self.llm_client.invoke_structured(
                        trace_id=trace_id,
                        prompt=prompt_text,
                        schema=self._build_replan_schema(),
                    )

                    # 解析重构结果
                    replan_data = self._parse_replan_response(llm_response)

                    # 更新 Plan 中的 State 列表（可能抛出 ValidationError）
                    self._apply_replan(dag_state, replan_data)
                    break  # 成功应用，退出重试循环

                except ValidationError as ve:
                    logger.warning(
                        f"[TraceID:{trace_id}] Plan 重构参数校验失败 "
                        f"(attempt {attempt+1}/{max_retries}): {ve}"
                    )
                    if attempt < max_retries - 1:
                        # 追加错误反馈到 prompt，引导 LLM 修正输出格式
                        prompt_text += (
                            f"\n\n## 前一次输出校验失败，请修正\n"
                            f"错误信息: {ve}\n"
                            f"请确保 selected_skills 中每个元素都是包含 "
                            f"skill_name 和 relevance_reason 的字典对象，"
                            f"不要使用纯字符串。"
                        )
                        continue
                    raise  # 最后一次重试也失败，向上抛出

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
        """构建 Plan 重构的 JSON Schema。

        做什么：定义重构 LLM 输出的结构化约束，与 Prompt 模板（system.j2 + runtime.j2）
                的输出要求完全对齐。
        为什么这样做：Prompt 中要求 LLM 输出 check 字段用于 CoT 推演校验，
                       且 replan_reason 为必填项，Schema 必须反映这一点。
        设计原则：每个 State 强制要求填写 responsibility 字段，
                  确保重构后的 Plan 仍然按职责拆分。
        """
        return {
            "type": "object",
            "properties": {
                "check": {
                    "type": "string",
                    "description": (
                        "生成前推演校验结果，按 [失败根因][调整合理性][技能选择] "
                        "三个维度逐一校验并记录。"
                    ),
                },
                "revised_states": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "order_index": {"type": "integer"},
                            "responsibility": {
                                "type": "string",
                                "description": (
                                    "该 State 承担的唯一职责类型，如：信息收集、"
                                    "数据分析、内容生成、知识检索、格式转换、"
                                    "验证校对、总结归纳、方案设计、代码实现、测试验证。"
                                    "每个 State 只能有一种职责。"
                                ),
                            },
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
                            "selected_skills": {
                                "type": "array",
                                "description": (
                                    "预分配的技能筛选结果。对于需要外部工具的 State，"
                                    "列出筛选出的技能及选择理由；纯推理/写作类 State 留空。"
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "skill_name": {
                                            "type": "string",
                                            "description": "技能名称，必须与可用能力列表中的名称完全一致。",
                                        },
                                        "relevance_reason": {
                                            "type": "string",
                                            "description": "选择该技能的原因。",
                                        },
                                    },
                                    "required": ["skill_name"],
                                },
                            },
                        },
                        "required": ["order_index", "responsibility", "intent", "goal"],
                    },
                },
                "replan_reason": {"type": "string"},
            },
            "required": ["check", "revised_states", "replan_reason"],
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

            # 提取预分配的 Skill 筛选结果
            # 做什么：从重构 LLM 输出中读取 selected_skills，存入 pre_allocated_skills。
            # 为什么这样做：与 Plan 生成保持一致，重构后的 State 也使用预分配
            #               跳过独立的 SkillScreening LLM 调用。
            pre_allocated_skills = state_data.get("selected_skills", [])

            state = OverallState(
                order_index=state_data.get("order_index", 0),
                responsibility=state_data.get("responsibility", ""),
                intent=state_data.get("intent", ""),
                goal=state_data.get("goal", ""),
                completion_criteria=criteria,
                required_skill_names=state_data.get("required_skill_names", []),
                pre_allocated_skills=pre_allocated_skills,
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
