"""Phase 9 DAG 引擎 — Skill 初筛节点。

做什么：根据当前 State 的 goal 和 completion_criteria，
        从 SkillRegistry 中筛选出相关的 Skill 列表。
Prompt：使用 dag_skill_screening 三槽位 Prompt。
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.dag.types import DagEngineState, SkillBrief


class SkillScreeningNode:
    """Skill 初筛节点。

    做什么：根据当前 State 的 goal 和 completion_criteria，
            从 SkillRegistry 中筛选出相关的 Skill 列表。
    为什么不放在 Plan 生成阶段：Plan 生成时已注入 Skill 列表，
                                 但 State 执行时需要更精确的筛选。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 Skill 初筛节点。"""
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def execute(
        self,
        trace_id: str,
        session_id: str,
        dag_state: DagEngineState,
        state_goal: str,
        state_intent: str,
        completion_criteria: list[dict[str, Any]],
        state_responsibility: str = "",
    ) -> list[dict[str, Any]]:
        """执行 Skill 初筛。

        做什么：根据 State 的 goal 筛选相关 Skill。
        返回:
            list[dict]: 筛选后的 SkillBrief 序列化列表。
        """
        # 发布 RUNNING 状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_SKILL_SCREENING,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_SKILL_SCREENING, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        try:
            # 如果没有可用 Skill，直接返回空列表
            if not dag_state.skill_briefs:
                logger.info(
                    f"[TraceID:{trace_id}] Skill 初筛: 无可用 Skill，跳过筛选"
                )
                await self._publish_completed(trace_id, session_id)
                return []

            # 渲染 Skill 初筛 Prompt
            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_SKILL_SCREENING,
                variables={
                    "state_responsibility": state_responsibility,
                    "state_goal": state_goal,
                    "state_intent": state_intent,
                    "completion_criteria": json.dumps(
                        completion_criteria, ensure_ascii=False
                    ),
                    "skill_briefs": dag_state.skill_briefs,
                },
            )

            logger.info(
                f"[TraceID:{trace_id}] Skill 初筛 Prompt: {prompt_text}"
            )

            # 调用 LLM 做筛选
            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_screening_schema(),
            )

            # 解析筛选结果
            screening_result = self._parse_screening_response(llm_response)
            selected_skills = screening_result.get("selected_skills", [])

            logger.info(
                f"[TraceID:{trace_id}] Skill 初筛完成: "
                f"selected={len(selected_skills)}, "
                f"total={len(dag_state.skill_briefs)}"
                f"llm_response={llm_response}"
            )

            # 发布 SUCCEEDED 状态
            await self._publish_completed(trace_id, session_id)

            return selected_skills

        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] Skill 初筛失败: {e}")
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_SKILL_SCREENING,
                state=ChatStatusState.ERROR,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_SKILL_SCREENING, ChatStatusState.ERROR
                ),
                is_visible=True,
                is_terminal=True,
            )
            # 筛选失败时返回所有 Skill 作为降级策略
            return dag_state.skill_briefs

    async def _publish_completed(self, trace_id: str, session_id: str) -> None:
        """发布筛选完成状态。"""
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_SKILL_SCREENING,
            state=ChatStatusState.COMPLETED,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_SKILL_SCREENING, ChatStatusState.COMPLETED
            ),
            is_visible=True,
            is_terminal=True,
        )

    def _build_screening_schema(self) -> dict[str, Any]:
        """构建 Skill 初筛的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "selected_skills": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string"},
                            "relevance_reason": {"type": "string"},
                        },
                        "required": ["skill_name"],
                    },
                },
                "screening_reason": {"type": "string"},
            },
            "required": ["selected_skills"],
        }

    def _parse_screening_response(self, llm_response: str | dict) -> dict[str, Any]:
        """解析 Skill 初筛的 LLM 输出。"""
        try:
            if isinstance(llm_response, dict):
                return llm_response
            return json.loads(llm_response)
        except json.JSONDecodeError as e:
            logger.error(f"Skill 初筛 LLM 输出 JSON 解析失败: {e}")
            import re
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"selected_skills": [], "screening_reason": "解析失败"}
