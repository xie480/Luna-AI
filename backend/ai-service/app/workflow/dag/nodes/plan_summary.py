"""Phase 9 DAG 引擎 — Plan 结果汇总节点。

做什么：当所有 State 执行完毕后，收集每个 State 的执行结果，
        汇总为 Plan 级别的执行摘要。
Prompt：使用 dag_plan_summary 三槽位 Prompt。
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
    DagNodeStatus,
    PlanSummaryResult,
    StateSummary,
)


class PlanResultSummaryNode:
    """Plan 结果汇总节点。

    做什么：当所有 State 执行完毕后，收集每个 State 的执行结果，
            汇总为 Plan 级别的执行摘要。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 Plan 结果汇总节点。"""
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def execute(
        self,
        trace_id: str,
        session_id: str,
        dag_state: DagEngineState,
    ) -> PlanSummaryResult:
        """执行 Plan 结果汇总。

        做什么：收集所有 State 的执行结果，生成汇总摘要。
        返回:
            PlanSummaryResult: Plan 汇总结果。
        """
        # 发布 RUNNING 状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_PLAN_SUMMARY,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_PLAN_SUMMARY, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        try:
            # 收集各 State 的摘要
            state_summaries = []
            succeeded = 0
            degraded = 0
            failed = 0

            for state_def in dag_state.plan.states:
                runtime_data = dag_state.state_runtimes.get(
                    state_def.state_id, {}
                )
                status_str = runtime_data.get("status", "SUCCEEDED")
                try:
                    status = DagNodeStatus(status_str)
                except ValueError:
                    status = DagNodeStatus.SUCCEEDED

                if status == DagNodeStatus.SUCCEEDED:
                    succeeded += 1
                elif status == DagNodeStatus.DEGRADED:
                    degraded += 1
                else:
                    failed += 1

                # 生成 State 结果摘要文本
                merged_output = runtime_data.get("merged_output", {})
                result_summary = self._build_state_result_summary(
                    merged_output, runtime_data.get("error_messages", [])
                )

                summary = StateSummary(
                    state_id=state_def.state_id,
                    intent=state_def.intent,
                    goal=state_def.goal,
                    status=status,
                    result_summary=result_summary,
                )
                state_summaries.append(summary)

            # 调用 LLM 生成整体汇总文本
            overall_result = await self._generate_overall_summary(
                trace_id, dag_state, state_summaries
            )

            # 构建汇总结果
            result = PlanSummaryResult(
                plan_id=dag_state.plan.plan_id,
                total_states=len(dag_state.plan.states),
                succeeded_states=succeeded,
                degraded_states=degraded,
                failed_states=failed,
                state_summaries=state_summaries,
                overall_result=overall_result,
                execution_highlights=self._extract_highlights(state_summaries),
                execution_issues=self._extract_issues(state_summaries),
            )

            logger.info(
                f"[TraceID:{trace_id}] Plan 结果汇总完成: "
                f"total={result.total_states}, "
                f"succeeded={result.succeeded_states}, "
                f"degraded={result.degraded_states}, "
                f"failed={result.failed_states}"
            )

            # 发布 SUCCEEDED 状态
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_PLAN_SUMMARY,
                state=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_PLAN_SUMMARY, ChatStatusState.COMPLETED
                ),
                is_visible=True,
                is_terminal=True,
            )

            return result

        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] Plan 结果汇总失败: {e}")
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_PLAN_SUMMARY,
                state=ChatStatusState.ERROR,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_PLAN_SUMMARY, ChatStatusState.ERROR
                ),
                is_visible=True,
                is_terminal=True,
            )
            raise

    async def _generate_overall_summary(
        self,
        trace_id: str,
        dag_state: DagEngineState,
        state_summaries: list[StateSummary],
    ) -> str:
        """调用 LLM 生成整体汇总文本。"""
        try:
            summaries_text = []
            for s in state_summaries:
                summaries_text.append(
                    f"- [{s.status.value}] {s.intent}: {s.goal}\n"
                    f"  结果: {s.result_summary[:200]}"
                )

            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_PLAN_SUMMARY,
                variables={
                    "global_objective": json.dumps({
                        "overall_goal": dag_state.global_objective.overall_goal,
                        "success_criteria": dag_state.global_objective.success_criteria,
                    }, ensure_ascii=False),
                    "state_summaries": "\n".join(summaries_text),
                    "total_states": len(state_summaries),
                    "terminated": dag_state.terminated,
                    "termination_reason": dag_state.termination_reason,
                },
            )

            result = await self.llm_client.invoke(
                trace_id=trace_id,
                prompt=prompt_text,
            )
            return result

        except Exception as e:
            logger.warning(f"[TraceID:{trace_id}] LLM 汇总生成失败，使用兜底: {e}")
            return self._build_fallback_summary(dag_state, state_summaries)

    def _build_state_result_summary(
        self,
        merged_output: dict[str, Any],
        error_messages: list[str],
    ) -> str:
        """构建单个 State 的结果摘要。"""
        if not merged_output:
            if error_messages:
                return f"执行失败: {'; '.join(error_messages[:3])}"
            return "（无输出）"

        parts = []
        for node_id, output in merged_output.items():
            if isinstance(output, dict):
                success = output.get("success", True)
                content = (
                    output.get("tool_output", "")
                    or output.get("resource_content", "")
                    or output.get("transformed_data", "")
                    or ""
                )
                if content:
                    if len(content) > 200:
                        content = content[:200] + "……"
                    parts.append(content)

        return "; ".join(parts[:5]) if parts else "（无有效输出）"

    def _build_fallback_summary(
        self,
        dag_state: DagEngineState,
        state_summaries: list[StateSummary],
    ) -> str:
        """构建兜底汇总文本。"""
        goal = dag_state.global_objective.overall_goal
        succeeded = sum(
            1 for s in state_summaries if s.status == DagNodeStatus.SUCCEEDED
        )
        total = len(state_summaries)

        return (
            f"任务目标：{goal}\n"
            f"执行结果：{succeeded}/{total} 个阶段成功完成。\n"
        )

    def _extract_highlights(
        self, state_summaries: list[StateSummary]
    ) -> list[str]:
        """提取执行亮点。"""
        highlights = []
        for s in state_summaries:
            if s.status == DagNodeStatus.SUCCEEDED and s.result_summary:
                highlights.append(f"{s.intent}: {s.result_summary[:100]}")
        return highlights[:5]

    def _extract_issues(
        self, state_summaries: list[StateSummary]
    ) -> list[str]:
        """提取执行问题。"""
        issues = []
        for s in state_summaries:
            if s.status in (DagNodeStatus.FAILED, DagNodeStatus.DEGRADED):
                issues.append(f"{s.intent}: {s.result_summary[:100]}")
        return issues
