"""Phase 9 DAG 引擎 — State 评估节点。

做什么：在 State 内所有 Step 执行完毕后，
        评估该 State 的执行结果是否满足 goal 和 completion_criteria。
Prompt：使用 dag_state_evaluation 三槽位 Prompt。
"""

from __future__ import annotations

import json
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.dag.types import StateEvaluationResult


class StateEvaluationNode:
    """State 评估节点。

    做什么：在 State 内所有 Step 执行完毕后，
            评估该 State 的执行结果是否满足 goal 和 completion_criteria。
    评估依据：
        - 该 State 内所有 Node 的 merged_output
        - State 的 goal 和 completion_criteria
        - 各 Node 的成功/失败状态
    输出：StateEvaluationResult
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 State 评估节点。"""
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def execute(
        self,
        trace_id: str,
        session_id: str,
        state_goal: str,
        state_intent: str,
        completion_criteria: list[dict[str, Any]],
        merged_output: dict[str, Any],
        nodes_succeeded: int,
        nodes_failed: int,
    ) -> StateEvaluationResult:
        """执行 State 评估。

        做什么：调用 LLM 评估 State 执行结果是否满足目标。
        返回:
            StateEvaluationResult: 评估结果。
        """
        # 发布 RUNNING 状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_STATE_EVALUATION,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_STATE_EVALUATION, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        try:
            # 格式化合并输出
            formatted_output = self._format_merged_output(merged_output)

            # 渲染评估 Prompt
            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_STATE_EVALUATION,
                variables={
                    "state_goal": state_goal,
                    "state_intent": state_intent,
                    "completion_criteria": json.dumps(
                        completion_criteria, ensure_ascii=False
                    ),
                    "merged_output": formatted_output,
                    "nodes_succeeded": nodes_succeeded,
                    "nodes_failed": nodes_failed,
                },
            )

            logger.info(
                f"[TraceID:{trace_id}] 评估 Prompt: "
                f"{prompt_text}"
            )

            # 调用 LLM 做评估
            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_evaluation_schema(),
            )

            # 解析评估结果
            eval_data = self._parse_evaluation_response(llm_response)
            result = StateEvaluationResult(
                state_satisfied=eval_data.get("state_satisfied", False),
                evaluation_reason=eval_data.get("evaluation_reason", ""),
                gap_analysis=eval_data.get("gap_analysis", ""),
                suggestion=eval_data.get("suggestion", ""),
                criteria_checklist=eval_data.get("criteria_checklist", []),
            )

            logger.info(
                f"[TraceID:{trace_id}] State 评估完成: "
                f"satisfied={result.state_satisfied}, "
                f"reason={result.evaluation_reason}"
                f"output={formatted_output}"
            )

            # 发布评估结果状态
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_STATE_EVALUATION,
                state=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_STATE_EVALUATION,
                    ChatStatusState.COMPLETED,
                ),
                is_visible=True,
                is_terminal=True,
            )

            return result

        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] State 评估失败: {e}")
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_STATE_EVALUATION,
                state=ChatStatusState.ERROR,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_STATE_EVALUATION,
                    ChatStatusState.ERROR,
                ),
                is_visible=True,
                is_terminal=True,
            )
            # 评估失败时默认通过，避免阻塞流程
            return StateEvaluationResult(
                state_satisfied=True,
                evaluation_reason=f"评估异常，自动通过: {e}",
            )

    def _build_evaluation_schema(self) -> dict[str, Any]:
        """构建评估的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "state_satisfied": {"type": "boolean"},
                "evaluation_reason": {"type": "string"},
                "gap_analysis": {"type": "string"},
                "suggestion": {"type": "string"},
                "criteria_checklist": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "expected": {"type": "string"},
                            "actual": {"type": "string"},
                            "met": {"type": "boolean"},
                        },
                    },
                },
            },
            "required": ["state_satisfied"],
        }

    def _parse_evaluation_response(
        self, llm_response: str | dict
    ) -> dict[str, Any]:
        """解析评估的 LLM 输出。"""
        if isinstance(llm_response, dict):
            return llm_response
        try:
            return json.loads(llm_response)
        except json.JSONDecodeError as e:
            logger.error(f"State 评估 LLM 输出 JSON 解析失败: {e}")
            import re
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"state_satisfied": False, "evaluation_reason": "解析失败"}

    def _format_merged_output(self, merged_output: dict[str, Any]) -> str:
        """格式化 State 的合并输出为可读文本。"""
        if not merged_output:
            return "（无输出）"

        parts = []
        for node_id, output in merged_output.items():
            if isinstance(output, dict):
                success = output.get("success", True)
                status = "成功" if success else "失败"
                content = (
                    output.get("tool_output", "")
                    or output.get("resource_content", "")
                    or output.get("transformed_data", "")
                    or output.get("memory_text", "")
                    or output.get("knowledge_text", "")
                    or ""
                )
                if content:
                    if len(content) > 800:
                        content = content[:800] + "……"
                    parts.append(f"[{node_id}] {status}: {content}")
                else:
                    error = output.get("error_message", "")
                    parts.append(f"[{node_id}] {status}: {error}")
            else:
                parts.append(f"[{node_id}]: {str(output)[:300]}")

        return "\n".join(parts) if parts else "（无输出）"
