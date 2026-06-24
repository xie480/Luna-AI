"""Phase 9 DAG 引擎 — 全局 Plan 生成节点。

做什么：接收简化输入重构的结果和 SkillBrief 列表，
        由 LLM 生成 GlobalObjective 和 PlanDefinition。
Prompt：使用 dag_plan_generation 三槽位 Prompt。
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.api.chat_status_texts import get_chat_status_text
from app.utils.snowflake import generate_string_id
from app.workflow.dag.types import (
    DagEngineState,
    GlobalObjective,
    OverallState,
    PlanDefinition,
    StateBudget,
)


class PlanGenerationNode:
    """全局 Plan 生成节点。

    做什么：接收简化输入重构的结果和 SkillBrief 列表，
            由 LLM 生成 GlobalObjective 和 PlanDefinition。
    Prompt：使用 dag_plan_generation 三槽位 Prompt。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 Plan 生成节点。

        参数:
            prompt_manager: Prompt 管理器。
            llm_client: LLM 客户端。
            chat_status_publisher: Chat 状态发布器。
        """
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def execute(
        self,
        trace_id: str,
        session_id: str,
        dag_state: DagEngineState,
    ) -> DagEngineState:
        """执行全局 Plan 生成。

        做什么：调用 LLM 生成 GlobalObjective 和 PlanDefinition。
        参数:
            trace_id: 追踪 ID。
            session_id: 会话 ID。
            dag_state: DAG 引擎全局状态。
        返回:
            DagEngineState: 更新后的 DAG 引擎状态。
        """
        started_at_ms = int(time.time() * 1000)

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

        try:
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

            # 渲染 Plan 生成 Prompt（使用标准变量名）
            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_PLAN_GENERATION,
                variables={
                    "disambiguated_text": dag_state.disambiguated_text,
                    "unresolved_pronouns": dag_state.unresolved_pronouns,
                    "skill_briefs": dag_state.skill_briefs,
                    "CORE_SUMMARY": dag_state.session_context.get("short_summary", ""),
                    "KEY_FACTS": json.dumps(
                        dag_state.session_context.get("key_facts", []),
                        ensure_ascii=False,
                    ),
                    "MEMORY_SNIPPETS": dag_state.session_context.get("memory_snippets", ""),
                    "memory_context": dag_state.memory_context,
                    "global_objective": {
                        "overall_goal": dag_state.global_objective.overall_goal,
                        "success_criteria": dag_state.global_objective.success_criteria,
                        "output_format": dag_state.global_objective.output_format,
                        "constraints": dag_state.global_objective.constraints,
                    },
                    "CURRENT_TIME": current_time,
                },
            )

            logger.info(
                f"[TraceID:{trace_id}] 全局 Plan 渲染完成: "
                f"prompt_text={prompt_text}"
            )

            # 调用 LLM 生成 Plan
            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_plan_schema(),
            )

            # 解析 LLM 输出
            plan_data = self._parse_plan_response(llm_response)

            # 构建 PlanDefinition
            plan = self._build_plan_definition(
                plan_data=plan_data,
                session_id=session_id,
                trace_id=trace_id,
                existing_global_objective=dag_state.global_objective,
            )

            # 更新 DAG 状态
            dag_state.plan = plan
            dag_state.global_objective = plan.global_objective

            elapsed_ms = int(time.time() * 1000) - started_at_ms
            logger.info(
                f"[TraceID:{trace_id}] 全局 Plan 生成完成: "
                f"states={len(plan.states)}, "
                f"planning_reason={plan_data.get('planning_reason', '')[:100]}, "
                f"elapsed_ms={elapsed_ms},"
                f"plan={plan}"
            )

            # 发布 SUCCEEDED 状态
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_PLAN_GENERATION,
                state=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_PLAN_GENERATION, ChatStatusState.COMPLETED
                ),
                is_visible=True,
                is_terminal=True,
            )

        except Exception as e:
            logger.error(
                f"[TraceID:{trace_id}] 全局 Plan 生成失败: {e}"
            )
            # 发布 FAILED 状态
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_PLAN_GENERATION,
                state=ChatStatusState.ERROR,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_PLAN_GENERATION, ChatStatusState.ERROR
                ),
                is_visible=True,
                is_terminal=True,
            )
            raise

        return dag_state

    def _build_plan_schema(self) -> dict[str, Any]:
        """构建 Plan 生成的 JSON Schema。

        做什么：定义 LLM 输出的结构化约束。
        设计原则：每个 State 强制要求填写 responsibility 字段，
                  确保按职责拆分而非按难易度拆分。
        """
        return {
            "type": "object",
            "properties": {
                "states": {
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
                                    "required": ["field", "operator", "value"],
                                },
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                            "required_skill_names": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["order_index", "responsibility", "intent", "goal"],
                    },
                },
                "planning_reason": {"type": "string"},
            },
            "required": ["states"],
        }

    def _parse_plan_response(self, llm_response: str) -> dict[str, Any]:
        """解析 LLM 的 Plan 生成输出。

        做什么：将 LLM 的 JSON 字符串输出解析为字典。
        """
        try:
            if isinstance(llm_response, dict):
                return llm_response
            return json.loads(llm_response)
        except json.JSONDecodeError as e:
            logger.error(f"Plan 生成 LLM 输出 JSON 解析失败: {e}")
            # 尝试提取 JSON 块
            import re
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError(f"Plan 生成 LLM 输出无法解析为 JSON: {llm_response[:200]}")

    def _build_plan_definition(
        self,
        plan_data: dict[str, Any],
        session_id: str,
        trace_id: str,
        existing_global_objective: GlobalObjective | None = None,
    ) -> PlanDefinition:
        """从 LLM 输出构建 PlanDefinition。

        做什么：将 LLM 输出的 JSON 结构转换为类型安全的 PlanDefinition。
        """
        # 构建 GlobalObjective
        # 优先从 LLM 输出的 global_objective 字段读取
        # 如果 LLM 输出中没有（按新 Prompt 规范），则使用已有的值
        obj_data = plan_data.get("global_objective", {})
        if obj_data and obj_data.get("overall_goal"):
            global_objective = GlobalObjective(
                overall_goal=obj_data.get("overall_goal", ""),
                success_criteria=obj_data.get("success_criteria", ""),
                output_format=obj_data.get("output_format", ""),
                constraints=obj_data.get("constraints", []),
            )
        elif existing_global_objective:
            global_objective = existing_global_objective
        else:
            global_objective = GlobalObjective(
                overall_goal="",
                success_criteria="",
            )

        # 构建 State 列表
        states = []
        for state_data in plan_data.get("states", []):
            # 构建完成标准
            criteria = []
            for c in state_data.get("completion_criteria", []):
                from app.workflow.dag.types import CompletionCriterion
                criteria.append(CompletionCriterion(
                    field=c.get("field", ""),
                    operator=c.get("operator", ">="),
                    value=c.get("value"),
                ))

            # 处理 depends_on：将 order_index 转换为 state_id
            depends_on = []
            for dep_index in state_data.get("depends_on", []):
                if isinstance(dep_index, int) and 0 <= dep_index < len(states):
                    depends_on.append(states[dep_index].state_id)

            state = OverallState(
                order_index=state_data.get("order_index", 0),
                responsibility=state_data.get("responsibility", ""),
                intent=state_data.get("intent", ""),
                goal=state_data.get("goal", ""),
                completion_criteria=criteria,
                depends_on=depends_on,
                required_skill_names=state_data.get("required_skill_names", []),
                budget=StateBudget(),
            )
            states.append(state)

        return PlanDefinition(
            session_id=session_id,
            trace_id=trace_id,
            original_intent=plan_data.get("planning_reason", ""),
            global_objective=global_objective,
            states=states,
            created_at_ms=int(time.time() * 1000),
        )
