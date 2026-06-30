"""State 结果汇聚节点。

做什么：收集所有已完成 Step 的输出，构建统一的 merged_context。
为什么这样做：并行 Step 完成后，下游 Step（依赖这些已完成 Step 的步骤）
             需要访问上游 Step 的产出和信息。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.workflow.dag.types import AgentLoopState, AgentMemoryState


class StateJoinNode:
    """State 结果汇聚。

    输入：AgentLoopState 中各 Step 的 partitioned_outputs 和 step_summaries。
    输出：全局 merged_context，注入到下游 Step 的 Prompt 中。
    """

    async def join(
        self,
        agent_loop: AgentLoopState,
        completed_step_ids: set[str],
    ) -> dict[str, Any]:
        """汇聚已完成 Step 的输出。

        做什么：
        1. 遍历 completed_step_ids，从 memory.step_summaries 提取每个 Step 的摘要。
        2. 将各 Step 的输出摘要组织为结构化的 merged_context。
        3. merged_context 会作为上下文字段注入到下游 Step 的 Prompt 变量中。

        参数:
            agent_loop: Agent Loop 引擎全局状态。
            completed_step_ids: 已完成的步骤 ID 集合。

        返回:
            merged_context 字典，包含：
            - step_summaries: 所有已完成步骤的摘要文本。
            - total_completed: 已完成步骤数。
        """
        # 从 memory.step_summaries 中提取已完成 Step 的摘要
        step_summaries_text = ""
        summary_count = 0

        for step_summary in agent_loop.memory.step_summaries:
            if step_summary.get("step_id", "") in completed_step_ids:
                title = step_summary.get("title", "未知步骤")
                summary = step_summary.get("summary", "")
                if summary:
                    step_summaries_text += f"- **{title}**: {summary}\n"
                    summary_count += 1

        merged_context = {
            "step_summaries": step_summaries_text,
            "total_completed": len(completed_step_ids),
        }

        if step_summaries_text:
            logger.info(
                f"StateJoinNode: 汇聚完成, "
                f"completed_count={len(completed_step_ids)}, "
                f"summary_count={summary_count}"
            )

        return merged_context

    async def extract_ready_context(
        self,
        agent_loop: AgentLoopState,
        ready_step_id: str,
    ) -> dict[str, Any]:
        """为就绪的 Step 提取其依赖的上游上下文。

        做什么：当某个 Step 就绪时，提取其依赖的上游 Step 的输出摘要，
               作为该 Step 的输入上下文。

        参数:
            agent_loop: Agent Loop 引擎全局状态。
            ready_step_id: 即将执行的步骤 ID。

        返回:
            该 Step 的输入上下文字典，包含 dependency_summaries 等。
        """
        # 在 PlanState 中查找当前 Step 的依赖
        deps_step_ids: list[str] = []
        for step in agent_loop.plan.steps:
            if step.step_id == ready_step_id:
                deps_step_ids = step.dependencies
                break

        # 提取依赖步骤的摘要
        dependency_summaries = ""
        for dep_id in deps_step_ids:
            for step_summary in agent_loop.memory.step_summaries:
                if step_summary.get("step_id", "") == dep_id:
                    title = step_summary.get("title", "未知步骤")
                    summary = step_summary.get("summary", "")
                    if summary:
                        dependency_summaries += f"- **{title}**: {summary}\n"
                    break

        return {
            "dependency_summaries": dependency_summaries,
            "dependency_count": len(deps_step_ids),
        }
