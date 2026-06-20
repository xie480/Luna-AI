"""Phase 9 DAG 引擎 — Step 合并器。

做什么：将 Step 内所有原子节点的分区输出合并为一个统一的输出字典。
为什么这样做：分区写入是强制策略，并行执行的节点只能写入自己的分区，
              合并器负责将分区结果汇总。
"""

from __future__ import annotations

from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState


class StepMergeNode:
    """Step 合并器。

    做什么：将 Step 内所有原子节点的分区输出合并为一个统一的输出。
    """

    def __init__(
        self,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 Step 合并器。"""
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def merge(
        self,
        trace_id: str,
        session_id: str,
        partitioned_outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """合并 Step 分区输出。

        做什么：将所有分区输出合并为一个统一字典，统计成功/失败数量。
        返回:
            dict: 包含 merged_output、succeeded_count、failed_count。
        """
        # 发布合并开始状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_STEP_MERGE,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_STEP_MERGE, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        succeeded = 0
        failed = 0
        merged: dict[str, Any] = {}

        for node_id, output in partitioned_outputs.items():
            merged[node_id] = output
            if output.get("success", True):
                succeeded += 1
            else:
                failed += 1

        logger.info(
            f"[TraceID:{trace_id}] Step 合并完成: "
            f"total={len(partitioned_outputs)}, "
            f"succeeded={succeeded}, failed={failed}"
        )

        # 发布合并完成状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_STEP_MERGE,
            state=ChatStatusState.COMPLETED,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_STEP_MERGE, ChatStatusState.COMPLETED
            ),
            is_visible=True,
            is_terminal=True,
        )

        return {
            "merged_output": merged,
            "succeeded_count": succeeded,
            "failed_count": failed,
        }
