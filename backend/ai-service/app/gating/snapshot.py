"""
Luna AI Gating 模块：工具执行快照与审批决策管理器。

快速链路说明：
    ┌─ 批准 → _execute_single_tool 轮询获取决策 → 重新执行工具 → 正常返回结果
    │
    审批决策 ─┤
    │
    └─ 拒绝 → _execute_single_tool 轮询获取决策 → 返回带拒绝信息的失败结果
              → 工具结果被标记为"用户拒绝"，后续评估节点据此寻找替代方案
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.logger import logger


# Redis 快照键前缀（按 audit_log_id 组织，保存工具调用上下文）
REDIS_GATING_SNAPSHOT_PREFIX = "gating:snapshot:"

# Redis 审批决策键前缀（供 _execute_single_tool 轮询使用）
# approve_request / reject_request 会写入，_execute_single_tool 轮询读取
REDIS_GATING_DECISION_PREFIX = "gating:decision:"

# Redis 待消费审批结果键前缀（按 session_id 组织，供下次工作流消费）
# approve_request / reject_request 写入，session_context_load_node 加载并消费
REDIS_GATING_PENDING_RESULT_PREFIX = "gating:pending_result:"

# 快照默认 TTL（秒）= 超时时间 300 秒 + 60 秒缓冲
DEFAULT_SNAPSHOT_TTL = 360

# 决策保留 TTL（秒）= 与超时一致 300 秒 + 60 秒缓冲
DEFAULT_DECISION_TTL = 360

# 待消费审批结果 TTL（秒）= 24 小时，避免长期未消费的脏数据堆积
DEFAULT_PENDING_RESULT_TTL = 86400


class GatingSnapshotManager:
    """Gating 快照与决策管理器。"""

    def __init__(self, redis_client=None) -> None:
        self._redis_client = redis_client

    async def save_tool_snapshot(
        self,
        audit_log_id: str,
        *,
        tool_name: str,
        tool_parameters: dict[str, Any],
        trace_id: str,
        task_id: str,
        risk_level: str,
        goal: str = "",
        agent_output: str = "",
        mcp_intent: str = "",
        execution_plan: dict[str, Any] | None = None,
        screening_result: dict[str, Any] | None = None,
        resource_results: list[dict[str, Any]] | None = None,
        all_tool_results: list[dict[str, Any]] | None = None,
        all_round_data: list[dict[str, Any]] | None = None,
        dag_state_snapshot: dict[str, Any] | None = None,
        prompt_snapshot: str = "",
    ) -> bool:
        if not self._redis_client:
            return False
        try:
            snapshot_key = f"{REDIS_GATING_SNAPSHOT_PREFIX}{audit_log_id}"
            now_ms = int(time.time() * 1000)
            snapshot_data = {
                "audit_log_id": audit_log_id,
                "tool_name": tool_name,
                "tool_parameters": tool_parameters,
                "trace_id": trace_id,
                "task_id": task_id,
                "risk_level": risk_level,
                "goal": goal,
                "agent_output": agent_output,
                "mcp_intent": mcp_intent,
                "execution_plan": execution_plan or {},
                "screening_result": screening_result or {},
                "resource_results": resource_results or [],
                "all_tool_results": all_tool_results or [],
                "all_round_data": all_round_data or [],
                "dag_state_snapshot": dag_state_snapshot or {},
                "prompt_snapshot": prompt_snapshot,
                "created_at": now_ms,
                "version": "1.0",
            }
            client = self._redis_client.get_client()
            await client.setex(
                snapshot_key, DEFAULT_SNAPSHOT_TTL,
                json.dumps(snapshot_data, ensure_ascii=False, default=str),
            )
            logger.info(
                f"[GatingSnapshot] 保存快照成功 audit_log_id={audit_log_id} tool={tool_name}"
            )
            return True
        except Exception as e:
            logger.warning(f"[GatingSnapshot] 保存快照失败 audit_log_id={audit_log_id} error={e}")
            return False

    async def load_tool_snapshot(self, audit_log_id: str) -> dict[str, Any] | None:
        if not self._redis_client:
            return None
        try:
            client = self._redis_client.get_client()
            raw_data = await client.get(f"{REDIS_GATING_SNAPSHOT_PREFIX}{audit_log_id}")
            if not raw_data:
                return None
            return json.loads(raw_data)
        except Exception as e:
            logger.warning(f"[GatingSnapshot] 加载快照失败 audit_log_id={audit_log_id} error={e}")
            return None

    async def delete_tool_snapshot(self, audit_log_id: str) -> bool:
        if not self._redis_client:
            return False
        try:
            client = self._redis_client.get_client()
            await client.delete(f"{REDIS_GATING_SNAPSHOT_PREFIX}{audit_log_id}")
            return True
        except Exception:
            return False

    # ============================================================
    # 审批决策持久化（供 _execute_single_tool 轮询）
    # ============================================================

    async def save_decision(
        self,
        audit_log_id: str,
        *,
        decision: str,  # "approved" | "rejected"
        user_feedback: str = "",
    ) -> bool:
        """保存审批决策。

        用户通过前端弹窗点击同意/拒绝后，GatingService 调用此方法保存决策。
        _execute_single_tool 会轮询此决策以决定下一步操作。
        """
        if not self._redis_client:
            return False
        try:
            decision_key = f"{REDIS_GATING_DECISION_PREFIX}{audit_log_id}"
            now_ms = int(time.time() * 1000)
            decision_data = {
                "decision": decision,
                "user_feedback": user_feedback,
                "created_at": now_ms,
            }
            client = self._redis_client.get_client()
            await client.setex(
                decision_key, DEFAULT_DECISION_TTL,
                json.dumps(decision_data, ensure_ascii=False),
            )
            logger.info(
                f"[GatingSnapshot] 保存决策成功 audit_log_id={audit_log_id} decision={decision}"
            )
            return True
        except Exception as e:
            logger.warning(f"[GatingSnapshot] 保存决策失败 audit_log_id={audit_log_id} error={e}")
            return False

    async def load_decision(self, audit_log_id: str) -> dict[str, Any] | None:
        """加载审批决策。_execute_single_tool 轮询时调用。"""
        if not self._redis_client:
            return None
        try:
            client = self._redis_client.get_client()
            raw_data = await client.get(f"{REDIS_GATING_DECISION_PREFIX}{audit_log_id}")
            if not raw_data:
                return None
            return json.loads(raw_data)
        except Exception as e:
            logger.warning(f"[GatingSnapshot] 加载决策失败 audit_log_id={audit_log_id} error={e}")
            return None

    async def delete_decision(self, audit_log_id: str) -> bool:
        """清除审批决策。"""
        if not self._redis_client:
            return False
        try:
            client = self._redis_client.get_client()
            await client.delete(f"{REDIS_GATING_DECISION_PREFIX}{audit_log_id}")
            return True
        except Exception:
            return False

    # ============================================================
    # 会话级待消费审批结果（供 session_context_load_node 加载）
    # ============================================================

    async def save_pending_approval_result(
        self,
        session_id: str,
        *,
        result_type: str,
        tool_name: str,
        tool_parameters: dict[str, Any],
        user_feedback: str = "",
        rejection_info: str = "",
        tool_output: str = "",
        mcp_intent: str = "",
        risk_level: str = "L2",
    ) -> bool:
        """保存会话级待消费的审批结果。

        做什么：在 approve_request 或 reject_request 完成后，
                将审批结果（含工具执行输出或拒绝信息）写入 Redis，
                按 session_id 组织，供下次工作流的 session_context_load_node 消费。
        为什么这样做：审批结果是异步发生的（用户点击弹窗），
                      需要在下次工作流执行时注入到上下文中。
        输入输出：
            - session_id: 会话 ID，作为 Redis Key 的一部分。
            - result_type: "approved" 或 "rejected"。
            - tool_name: 工具名称。
            - tool_parameters: 工具参数。
            - user_feedback: 用户反馈（拒绝时的拒绝理由）。
            - rejection_info: 拒绝信息描述。
            - tool_output: 工具执行输出（仅 approved 时有值）。
            - mcp_intent: MCP 意图描述。
            - risk_level: 风险等级。
        边界条件：
            - Redis 不可用时返回 False，不阻断主流程。
            - TTL 设为 24 小时，避免长期未消费的脏数据堆积。
        异常行为：写入失败记录 warning 并返回 False。
        """
        if not self._redis_client:
            return False
        try:
            pending_key = f"{REDIS_GATING_PENDING_RESULT_PREFIX}{session_id}"
            now_ms = int(time.time() * 1000)
            result_data = {
                "type": result_type,
                "tool_name": tool_name,
                "tool_parameters": tool_parameters,
                "user_feedback": user_feedback,
                "rejection_info": rejection_info,
                "tool_output": tool_output,
                "mcp_intent": mcp_intent,
                "risk_level": risk_level,
                "created_at": now_ms,
            }
            client = self._redis_client.get_client()
            await client.setex(
                pending_key, DEFAULT_PENDING_RESULT_TTL,
                json.dumps(result_data, ensure_ascii=False, default=str),
            )
            logger.info(
                f"[GatingSnapshot] 保存待消费审批结果成功"
                f" session_id={session_id} type={result_type} tool={tool_name}"
            )
            return True
        except Exception as e:
            logger.warning(
                f"[GatingSnapshot] 保存待消费审批结果失败"
                f" session_id={session_id} error={e}"
            )
            return False

    async def load_pending_approval_result(
        self, session_id: str
    ) -> dict[str, Any] | None:
        """加载会话级待消费的审批结果。

        做什么：在 session_context_load_node 中调用，按 session_id 加载
                上次审批的待消费结果（批准+工具输出 或 拒绝+理由）。
        输入输出：输入 session_id，输出结果字典或 None。
        边界条件：无待消费结果时返回 None。
        异常行为：加载失败记录 warning 并返回 None（降级处理）。
        """
        if not self._redis_client:
            return None
        try:
            client = self._redis_client.get_client()
            raw_data = await client.get(
                f"{REDIS_GATING_PENDING_RESULT_PREFIX}{session_id}"
            )
            if not raw_data:
                return None
            return json.loads(raw_data)
        except Exception as e:
            logger.warning(
                f"[GatingSnapshot] 加载待消费审批结果失败"
                f" session_id={session_id} error={e}"
            )
            return None

    async def clear_pending_approval_result(self, session_id: str) -> bool:
        """清除会话级待消费的审批结果。

        做什么：消费完成后调用，防止下次工作流重复消费。
        输入输出：输入 session_id，输出是否成功。
        边界条件：Key 不存在时 Redis 直接返回 0，不影响结果。
        异常行为：删除失败记录 warning 并返回 False。
        """
        if not self._redis_client:
            return False
        try:
            client = self._redis_client.get_client()
            await client.delete(
                f"{REDIS_GATING_PENDING_RESULT_PREFIX}{session_id}"
            )
            return True
        except Exception as e:
            logger.warning(
                f"[GatingSnapshot] 清除待消费审批结果失败"
                f" session_id={session_id} error={e}"
            )
            return False
