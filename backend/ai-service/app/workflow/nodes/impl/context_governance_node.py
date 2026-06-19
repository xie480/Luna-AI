"""上下文治理节点。

Phase 13 增强：在注入模板变量时，检查 mcp_tool_state 中是否有 Gating 审批结果
（gating_rejected 或 execution_summary），并将其注入到 prompt_state 中，
供 chat/memory.j2 模板渲染时使用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.context.compression_governor import MemorySlotCompressionGovernor
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.constants import (
    PROMPT_VARIABLE_CORE_SUMMARY,
    PROMPT_VARIABLE_CURRENT_MESSAGE,
    PROMPT_VARIABLE_CURRENT_TIME,
    PROMPT_VARIABLE_EMOTION_AROUSAL,
    PROMPT_VARIABLE_EMOTION_INTENSITY,
    PROMPT_VARIABLE_EMOTION_PRIMARY,
    PROMPT_VARIABLE_EMOTION_TRIGGER,
    PROMPT_VARIABLE_EMOTION_VALENCE,
    PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE,
    PROMPT_VARIABLE_GATING_APPROVAL_RESULT,
    PROMPT_VARIABLE_GATING_REJECTION_INFO,
    PROMPT_VARIABLE_KEY_FACTS,
    PROMPT_VARIABLE_RETRY_ERROR_INFO,
    PROMPT_VARIABLE_LONG_TERM_MEMORY,
    PROMPT_VARIABLE_MEMORY_SNIPPETS,
    PROMPT_VARIABLE_SKILL_EXECUTION_SUMMARY,
    PROMPT_VARIABLE_TTS_LANGUAGE,
    PROMPT_VARIABLE_USER_PROFILE,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies


class ContextGovernanceNode(ChatWorkflowNode):
    """上下文治理节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.CONTEXT_GOVERNANCE,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.CONTEXT_GOVERNANCE,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.CONTEXT_GOVERNANCE, ChatStatusState.RUNNING),
        )

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        emotion_state = state.route_state.emotion_state

        # ============================================================
        # Phase 13：构造 Gating 审批结果注入变量
        # 做什么：检查 mcp_tool_state 是否有待处理的 Gating 审批结果。
        #         如果用户拒绝了工具调用，将拒绝信息和工具上下文格式化为
        #         GATING_REJECTION_INFO 变量。
        #         如果用户批准了工具调用且已有执行结果，将结果格式化为
        #         GATING_APPROVAL_RESULT 变量。
        # 为什么这样做：主 Chat LLM 需要知道用户拒绝了什么工具以及原因，
        #              才能生成合适的回复（如解释为什么需要该工具）。
        # ============================================================
        gating_rejection_info = ""
        gating_approval_result = ""

        if state.mcp_tool_state.gating_rejected:
            # 用户拒绝工具调用，构造拒绝信息
            tool_name = state.mcp_tool_state.gating_tool_name
            user_feedback = state.mcp_tool_state.gating_user_feedback
            risk_level = state.mcp_tool_state.gating_risk_level
            tool_params = state.mcp_tool_state.gating_tool_parameters
            mcp_intent = state.mcp_tool_state.gating_mcp_intent
            rejected_info = state.mcp_tool_state.gating_rejected_tool_info

            if rejected_info:
                gating_rejection_info = rejected_info
            else:
                # 兜底：手动构造拒绝信息
                parts = [
                    f"## 用户拒绝的工具调用",
                    f"工具名称：{tool_name}",
                    f"风险等级：{risk_level}",
                ]
                if mcp_intent:
                    parts.append(f"原始意图：{mcp_intent}")
                if user_feedback:
                    parts.append(f"用户反馈：{user_feedback}")
                if tool_params:
                    import json
                    parts.append(
                        f"工具参数：\n```json\n"
                        f"{json.dumps(tool_params, ensure_ascii=False, indent=2)}\n"
                        f"```\n"
                    )
                gating_rejection_info = "\n".join(parts)

            logger.info(
                f"[ContextGovernance] 注入 Gating 拒绝信息"
                f" trace_id={state.runtime.trace_id}"
                f" tool={tool_name}"
            )

        elif state.mcp_tool_state.execution_summary:
            # 有 Skill 执行摘要（可能来自 Gating 批准后的工具执行）
            # 复用 execution_summary 字段，这里已经包含了工具执行结果
            summary = state.mcp_tool_state.execution_summary.strip()
            if summary and ("已执行的工具" in summary or "执行结果" in summary):
                gating_approval_result = summary

                logger.info(
                    f"[ContextGovernance] 注入 Gating 批准结果"
                    f" trace_id={state.runtime.trace_id}"
                )

        variables = {
            PROMPT_VARIABLE_CURRENT_TIME: current_time,
            PROMPT_VARIABLE_CURRENT_MESSAGE: state.input_payload.raw_user_message,
            PROMPT_VARIABLE_CORE_SUMMARY: state.session_state.short_summary,
            PROMPT_VARIABLE_KEY_FACTS: "\n".join(state.session_state.key_facts),
            PROMPT_VARIABLE_MEMORY_SNIPPETS: state.session_state.memory_snippets,
            PROMPT_VARIABLE_LONG_TERM_MEMORY: state.memory_state.prompt_memory_text,
            PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE: state.knowledge_state.prompt_knowledge_text,
            PROMPT_VARIABLE_USER_PROFILE: state.profile_state.prompt_profile_text,
            PROMPT_VARIABLE_SKILL_EXECUTION_SUMMARY: state.mcp_tool_state.execution_summary,
            PROMPT_VARIABLE_EMOTION_PRIMARY: str(emotion_state.get("primary_emotion", "")),
            PROMPT_VARIABLE_EMOTION_INTENSITY: f"{float(emotion_state.get('intensity', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_VALENCE: f"{float(emotion_state.get('valence', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_AROUSAL: f"{float(emotion_state.get('arousal', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_TRIGGER: str(emotion_state.get("emotion_trigger", "")),
            # Phase 13：Gating 审批结果注入
            PROMPT_VARIABLE_GATING_REJECTION_INFO: gating_rejection_info,
            PROMPT_VARIABLE_GATING_APPROVAL_RESULT: gating_approval_result,
            # TTS 语音语言选项
            PROMPT_VARIABLE_TTS_LANGUAGE: state.input_payload.tts_language,
            # JSON 格式重试错误信息：首次调用为空，重试时由 MainChatLlmNode 设置
            PROMPT_VARIABLE_RETRY_ERROR_INFO: state.prompt_state.retry_error_info,
        }

        try:
            result = await MemorySlotCompressionGovernor().govern(
                trace_id=state.runtime.trace_id,
                session_id=state.runtime.session_id,
                message_id=state.input_payload.frontend_message_id,
                prompt_variables=variables,
            )
            state.prompt_state.prompt_variables = result.updated_variables

            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.CONTEXT_GOVERNANCE,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.CONTEXT_GOVERNANCE, ChatStatusState.COMPLETED),
                is_terminal=True,
            )

        except Exception as exc:
            logger.warning(
                f"上下文治理降级使用原始变量 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
            state.prompt_state.prompt_variables = variables
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.CONTEXT_GOVERNANCE,
                status=ChatStatusState.ERROR,
                display_text="",
                is_visible=False,
                is_terminal=True,
                error=str(exc),
            )
        return state

    async def _publish_chat_status(
        self,
        state: ChatWorkflowState,
        stage: ChatStatusStage,
        status: ChatStatusState,
        display_text: str,
        is_visible: bool = True,
        is_terminal: bool = False,
        error: str = "",
    ) -> None:
        publisher: ChatStatusPublisher | None = self.dependencies.chat_status_publisher
        if publisher is None:
            return
        await publisher.publish(
            trace_id=state.runtime.trace_id,
            session_id=state.runtime.session_id,
            message_id=state.generation_state.assistant_message_id,
            stage=stage,
            state=status,
            display_text=display_text,
            is_visible=is_visible,
            is_terminal=is_terminal,
            error=error,
        )
