"""并行执行检查点管理器。

做什么：在并行执行的关键节点保存检查点，支持从断点恢复。
为什么这样做：串行模式下恢复简单（从 current_step_index 处继续），
             但并行模式下需要更复杂的恢复策略。
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.logger import logger
from app.workflow.dag.ready_queue import ReadyQueue
from app.workflow.dag.types import (
    AgentLoopState,
    StepStatusEnum,
)


class ParallelCheckpointManager:
    """并行检查点管理器。

    检查点保存时机：
        1. 每个 Step 开始执行时
        2. 每个 Step 完成时
        3. 每个 Tool 调用完成时

    恢复逻辑：
        1. 加载最新检查点
        2. 识别 RUNNING 状态的 Step（未完成就崩溃的）
        3. 将 RUNNING 重置为 PENDING（允许重试）
        4. 重新计算 ReadyQueue，从断点继续
    """

    def __init__(
        self,
        redis_client: Any = None,
        checkpoint_ttl: int = 86400,  # 24 小时
    ):
        """初始化。

        参数:
            redis_client: Redis 客户端实例。None 时只记录日志，不做持久化。
            checkpoint_ttl: 检查点过期时间（秒）。
        """
        self._redis = redis_client
        self._checkpoint_ttl = checkpoint_ttl

    async def save_checkpoint(
        self,
        agent_loop: AgentLoopState,
        trigger: str,
    ) -> None:
        """保存检查点到 Redis。

        做什么：将 AgentLoopState 的关键字段序列化后保存到 Redis，
               覆盖旧的检查点（只保留最新）。
        为什么这样做：并行执行中 crash，重启时加载最新的 checkpoint。

        参数:
            agent_loop: Agent Loop 引擎全局状态。
            trigger: 保存触发原因，如 "step_completed"、"step_started" 等。
        """
        if not self._redis:
            return

        task_id = agent_loop.goal.task_id
        if not task_id:
            return

        # 构建检查点数据（只保存关键字段，减少序列化开销）
        checkpoint_data = {
            "task_id": task_id,
            "plan_version": agent_loop.plan.plan_version,
            "completed_step_ids": list(agent_loop.plan.completed_step_ids),
            "running_step_ids": list(agent_loop.plan.running_step_ids),
            "failed_step_ids": list(agent_loop.plan.failed_step_ids),
            "current_step_index": agent_loop.plan.current_step_index,
            "terminated": agent_loop.terminated,
            "termination_reason": agent_loop.termination_reason,
            "tool_calls_used": agent_loop.budget.tool_calls_used,
            "trigger": trigger,
            "saved_at_ms": int(time.time() * 1000),
            # 保存步骤状态摘要
            "step_statuses": {
                step.step_id: step.status.value
                for step in agent_loop.plan.steps
            },
        }

        redis_key = f"checkpoint:parallel:{task_id}"
        try:
            await self._redis.setex(
                redis_key,
                self._checkpoint_ttl,
                json.dumps(checkpoint_data, ensure_ascii=False),
            )
            logger.info(
                f"ParallelCheckpointManager: 保存检查点成功 "
                f"task={task_id}, trigger={trigger}"
            )
        except Exception as exc:
            logger.warning(
                f"ParallelCheckpointManager: 保存检查点失败 "
                f"task={task_id}, error={exc}"
            )

    async def restore_checkpoint(
        self,
        task_id: str,
    ) -> AgentLoopState | None:
        """从检查点恢复 AgentLoopState。

        恢复逻辑：
            1. 从 Redis 加载最新检查点
            2. 将所有 RUNNING 状态的 Step 重置为 PENDING
            3. 保留 PASSED 和 FAILED 的状态
            4. 重新计算 ReadyQueue

        参数:
            task_id: 任务 ID。

        返回:
            恢复后的 AgentLoopState 关键字段的 dict，或 None（无检查点）。
        """
        if not self._redis:
            return None

        redis_key = f"checkpoint:parallel:{task_id}"
        try:
            raw = await self._redis.get(redis_key)
            if not raw:
                return None

            data = json.loads(raw)

            # 重置 RUNNING 状态为 PENDING
            step_statuses: dict[str, str] = data.get("step_statuses", {})
            recovered_statuses: dict[str, str] = {}
            for step_id, status in step_statuses.items():
                if status == StepStatusEnum.RUNNING.value:
                    recovered_statuses[step_id] = StepStatusEnum.PENDING.value
                else:
                    recovered_statuses[step_id] = status

            logger.info(
                f"ParallelCheckpointManager: 从检查点恢复成功 "
                f"task={task_id}, version={data.get('plan_version')}, "
                f"trigger={data.get('trigger')}"
            )

            return {
                "plan_version": data.get("plan_version", 1),
                "previous_completed_ids": set(data.get("completed_step_ids", [])),
                "previous_running_ids": set(data.get("running_step_ids", [])),
                "previous_failed_ids": set(data.get("failed_step_ids", [])),
                "current_step_index": data.get("current_step_index", 0),
                "terminated": data.get("terminated", False),
                "tool_calls_used": data.get("tool_calls_used", 0),
                "recovered_statuses": recovered_statuses,
            }

        except Exception as exc:
            logger.warning(
                f"ParallelCheckpointManager: 恢复检查点失败 "
                f"task={task_id}, error={exc}"
            )
            return None

    async def delete_checkpoint(self, task_id: str) -> None:
        """删除检查点。

        做什么：任务正常完成时清理检查点。

        参数:
            task_id: 任务 ID。
        """
        if not self._redis:
            return

        redis_key = f"checkpoint:parallel:{task_id}"
        try:
            await self._redis.delete(redis_key)
            logger.info(
                f"ParallelCheckpointManager: 删除检查点 task={task_id}"
            )
        except Exception:
            pass
