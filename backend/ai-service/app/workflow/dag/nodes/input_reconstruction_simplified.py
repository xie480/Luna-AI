"""Phase 9 DAG 引擎 — 简化输入重构节点。

做什么：Plan-State-Node 路径的代词消歧。
        只做代词消歧和未解析代词标记，不做路由决策。
Prompt：使用 input_reconstruction_simplified 三槽位 Prompt。
"""

from __future__ import annotations

import json
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.dag.types import SimplifiedReconstruction, UnresolvedPronoun


class SimplifiedInputReconstructionNode:
    """简化输入重构节点。

    做什么：只做代词消歧和未解析代词标记，不做路由决策。
    为什么这样做：路由决策权交给全局 Plan 生成节点，
                  输入重构只负责清洗文本。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化简化输入重构节点。"""
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def execute(
        self,
        trace_id: str,
        session_id: str,
        raw_user_message: str,
        session_context: dict[str, Any],
    ) -> SimplifiedReconstruction:
        """执行简化输入重构。

        做什么：调用 LLM 对用户输入进行代词消歧。
        返回:
            SimplifiedReconstruction: 消歧结果。
        """
        # 发布 RUNNING 状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.INPUT_RECONSTRUCTION,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        try:
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

            # 渲染简化输入重构 Prompt（使用标准变量名）
            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.INPUT_RECONSTRUCTION_SIMPLIFIED,
                variables={
                    "CURRENT_MESSAGE": raw_user_message,
                    "CORE_SUMMARY": session_context.get("short_summary", ""),
                    "KEY_FACTS": json.dumps(
                        session_context.get("key_facts", []),
                        ensure_ascii=False,
                    ),
                    "MEMORY_SNIPPETS": session_context.get("memory_snippets", ""),
                    "CURRENT_TIME": current_time,
                },
            )

            logger.info(f"[TraceID:{trace_id}] 渲染简化输入重构 Prompt: {prompt_text}")

            # 调用 LLM 做代词消歧
            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_reconstruction_schema(),
            )

            # 解析结果
            result_data = self._parse_response(llm_response)

            # 构建 SimplifiedReconstruction
            unresolved = []
            for p in result_data.get("unresolved_pronouns", []):
                unresolved.append(UnresolvedPronoun(
                    original=p.get("original", ""),
                    reason=p.get("reason", ""),
                ))

            result = SimplifiedReconstruction(
                disambiguated_text=result_data.get(
                    "disambiguated_text", raw_user_message
                ),
                unresolved_pronouns=unresolved,
                emotion_state=result_data.get("emotion_state", {}),
            )

            logger.info(
                f"[TraceID:{trace_id}] 简化输入重构完成: "
                f"disambiguated_len={len(result.disambiguated_text)}, "
                f"unresolved_count={len(result.unresolved_pronouns)},"
                f"prompt_text={prompt_text}"
            )

            # 发布 SUCCEEDED 状态
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.INPUT_RECONSTRUCTION,
                state=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.INPUT_RECONSTRUCTION,
                    ChatStatusState.COMPLETED,
                ),
                is_visible=True,
                is_terminal=True,
            )

            return result

        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] 简化输入重构失败: {e}")
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.INPUT_RECONSTRUCTION,
                state=ChatStatusState.ERROR,
                display_text=get_chat_status_text(
                    ChatStatusStage.INPUT_RECONSTRUCTION,
                    ChatStatusState.ERROR,
                ),
                is_visible=True,
                is_terminal=True,
            )
            # 向上抛出异常，终止 DAG 流程
            # 为什么这样做：输入重构是 DAG 引擎的前置关键步骤，失败后继续执行
            #               会导致后续节点（如 Plan 生成）基于未处理的原始文本产生错误结果。
            #               因此必须在第一个节点失败时立即终止整个流程。
            raise

    def _build_reconstruction_schema(self) -> dict[str, Any]:
        """构建简化输入重构的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "disambiguated_text": {"type": "string"},
                "unresolved_pronouns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "original": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["original", "reason"],
                    },
                },
            },
            "required": ["disambiguated_text"],
        }

    def _parse_response(
        self, llm_response: str | dict
    ) -> dict[str, Any]:
        """解析 LLM 输出。"""
        if isinstance(llm_response, dict):
            return llm_response
        try:
            return json.loads(llm_response)
        except json.JSONDecodeError as e:
            logger.error(f"简化输入重构 LLM 输出 JSON 解析失败: {e}")
            import re
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"disambiguated_text": llm_response}
