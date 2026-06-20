"""Phase 9 DAG 引擎 — 结果压缩节点。

做什么：将 State 的完整执行结果压缩为精简摘要，
        保留关键事实、错误信息、已获取的资源摘要。
为什么这样做：避免 Token 膨胀，让 Plan 重构 Agent 聚焦于关键信息。
"""

from __future__ import annotations

import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.dag.types import StateEvaluationResult, StateRuntimeState


class StateResultCompressor:
    """State 结果压缩节点。

    做什么：将 State 的完整执行结果压缩为精简摘要。
    为什么这样做：Plan 重构时需要参考当前 State 的执行结果，
                  但完整结果可能包含大量冗余数据，需要压缩。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化压缩节点。

        参数:
            prompt_manager: Prompt 管理器，用于渲染压缩 Prompt。
            llm_client: LLM 客户端，用于调用模型做压缩。
            chat_status_publisher: Chat 状态发布器。
        """
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def compress(
        self,
        trace_id: str,
        session_id: str,
        state_runtime: dict[str, Any],
        evaluation_result: dict[str, Any],
    ) -> str:
        """压缩 State 执行结果。

        做什么：将 State 的完整执行结果压缩为精简摘要。
        参数:
            trace_id: 追踪 ID。
            session_id: 会话 ID。
            state_runtime: StateRuntimeState 序列化字典。
            evaluation_result: StateEvaluationResult 序列化字典。
        返回:
            str: 压缩后的结果摘要文本。
        """
        # 发布 RUNNING 状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_RESULT_COMPRESSION,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_RESULT_COMPRESSION, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        try:
            # 构建压缩 Prompt 变量
            variables = {
                "state_goal": state_runtime.get("goal", ""),
                "merged_output": self._format_merged_output(
                    state_runtime.get("merged_output", {})
                ),
                "error_messages": self._format_error_messages(
                    state_runtime.get("error_messages", [])
                ),
                "evaluation_reason": evaluation_result.get("evaluation_reason", ""),
                "gap_analysis": evaluation_result.get("gap_analysis", ""),
                "nodes_succeeded": state_runtime.get("nodes_succeeded", 0),
                "nodes_failed": state_runtime.get("nodes_failed", 0),
            }

            # 渲染压缩 Prompt
            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_RESULT_COMPRESSION,
                variables=variables,
            )

            # 调用 LLM 做压缩
            result = await self.llm_client.invoke(
                trace_id=trace_id,
                prompt=prompt_text,
            )

            logger.info(
                f"[TraceID:{trace_id}] State 结果压缩完成: "
                f"state_goal={state_runtime.get('goal', '')[:50]}"
            )

            # 发布 SUCCEEDED 状态
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_RESULT_COMPRESSION,
                state=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_RESULT_COMPRESSION,
                    ChatStatusState.COMPLETED,
                ),
                is_visible=True,
                is_terminal=True,
            )

            return result

        except Exception as e:
            logger.error(
                f"[TraceID:{trace_id}] State 结果压缩失败: {e}"
            )
            # 压缩失败时返回基础摘要
            fallback = self._build_fallback_summary(state_runtime, evaluation_result)

            # 发布 SUCCEEDED 状态（降级兜底不视为失败）
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_RESULT_COMPRESSION,
                state=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_RESULT_COMPRESSION,
                    ChatStatusState.COMPLETED,
                ),
                is_visible=True,
                is_terminal=True,
            )

            return fallback

    def _format_merged_output(self, merged_output: dict[str, Any]) -> str:
        """格式化 State 的合并输出为可读文本。"""
        if not merged_output:
            return "（无输出）"

        parts = []
        for node_id, output in merged_output.items():
            if isinstance(output, dict):
                success = output.get("success", True)
                status = "成功" if success else "失败"
                # 提取关键输出字段
                content = (
                    output.get("tool_output", "")
                    or output.get("resource_content", "")
                    or output.get("transformed_data", "")
                    or output.get("memory_text", "")
                    or output.get("knowledge_text", "")
                    or ""
                )
                if content:
                    # 截断过长内容
                    if len(content) > 500:
                        content = content[:500] + "……"
                    parts.append(f"[{node_id}] {status}: {content}")
                else:
                    error = output.get("error_message", "")
                    parts.append(f"[{node_id}] {status}: {error}")
            else:
                parts.append(f"[{node_id}]: {str(output)[:200]}")

        return "\n".join(parts) if parts else "（无输出）"

    def _format_error_messages(self, error_messages: list[str]) -> str:
        """格式化错误消息列表。"""
        if not error_messages:
            return "（无错误）"
        return "\n".join(f"- {msg}" for msg in error_messages)

    def _build_fallback_summary(
        self,
        state_runtime: dict[str, Any],
        evaluation_result: dict[str, Any],
    ) -> str:
        """构建兜底摘要（LLM 调用失败时使用）。"""
        goal = state_runtime.get("goal", "未知目标")
        succeeded = state_runtime.get("nodes_succeeded", 0)
        failed = state_runtime.get("nodes_failed", 0)
        reason = evaluation_result.get("evaluation_reason", "未知原因")
        gap = evaluation_result.get("gap_analysis", "")

        summary = (
            f"State 目标：{goal}\n"
            f"执行结果：{succeeded} 个节点成功，{failed} 个节点失败\n"
            f"评估不通过原因：{reason}\n"
        )
        if gap:
            summary += f"差距分析：{gap}\n"

        return summary
