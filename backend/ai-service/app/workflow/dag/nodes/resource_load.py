"""Agent Loop 资源加载节点 — LangGraph 节点实现。

做什么：在 StepThinkNode 和 AgentToolExecuteNode 之间插入资源加载环节，
        从 tool_calls 中提取 resource_name，调用 ResourceTierService 分级加载，
        将结果写入 ExecutionState.loaded_resources。
为什么这样做：资源加载是耗时 IO + 可选向量检索操作，独立为节点后：
    - 失败可降级，不阻塞工具执行
    - 多个 tool_call 引用同一资源时只加载一次
    - 便于未来并行加载多个资源
输入输出：
    - 输入：AgentLoopState（含 execution.last_tool_calls）
    - 输出：更新后的 AgentLoopState（execution.loaded_resources / resource_load_errors）
边界条件：
    - tool_calls 为空时直接跳过，不做任何操作
    - 单个资源加载失败记录到 resource_load_errors，不终止流程
    - 多个 tool_call 引用同一 resource_name 时只加载一次（去重）
异常行为：
    - 所有资源加载失败时流程仍然继续，由 ToolExecuteNode 决定如何处理缺失的资源上下文
"""

from __future__ import annotations

import json
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.logger import logger
from app.mcp.resource_tier_service import ResourceTierService
from app.workflow.constants import DagWorkflowEventType
from app.workflow.dag.types import AgentLoopState, ExecutionState
from app.workflow.events import ChatWorkflowEventPublisher


class ResourceLoadNode:
    """Agent Loop — 资源加载节点。

    做什么：
    1. 从 ExecutionState.last_tool_calls 中提取所有 resource_name（去重）
    2. 构建多 query 文本（step_intent + global_goal 关键词 + 上下文）
    3. 调用 ResourceTierService 分级加载
    4. 将结果写入 ExecutionState.loaded_resources
    5. 发布 EVT_DAG_RESOURCE_LOADED / EVT_DAG_RESOURCE_FAILED 事件
    6. 降级：单个资源失败记录到 resource_load_errors，不终止
    """

    def __init__(
        self,
        resource_tier_service: ResourceTierService,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ) -> None:
        """初始化资源加载节点。

        参数:
            resource_tier_service: 资源分级加载服务实例。
            chat_status_publisher: Chat 状态发布器。
            event_publisher: 工作流事件发布器，用于推送资源加载事件到前端。
        """
        self.resource_tier_service = resource_tier_service
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行资源加载。

        做什么：
        1. 从 agent_loop.execution.last_tool_calls 提取所有 resource_name
        2. 去重后逐个调用 resource_tier_service.load_resource()
        3. 将结果写入 agent_loop.execution.loaded_resources
        4. 降级策略：单个资源加载失败记录到 resource_load_errors，不终止
        5. 发布 EVT_DAG_RESOURCE_LOADED / EVT_DAG_RESOURCE_FAILED 事件

        返回:
            更新后的图状态字典。
        """
        from app.workflow.dag.agent_loop_engine import (
            _emit_dag_event,
            _extract_agent_loop_state,
            _save_agent_loop_state_to_graph,
        )

        chat_state, agent_loop = _extract_agent_loop_state(state)
        if agent_loop is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        if agent_loop.terminated:
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        tool_calls = agent_loop.execution.last_tool_calls
        if not tool_calls:
            # 无工具调用时直接跳过资源加载
            logger.info(
                f"[TraceID:{trace_id}] ResourceLoadNode: 无 tool_calls，跳过资源加载"
            )
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        # 提取所有 resource_name（去重，忽略空字符串）
        resource_names = self._extract_resource_names(tool_calls)

        if not resource_names:
            # tool_calls 中没有 resource_name，跳过
            logger.info(
                f"[TraceID:{trace_id}] ResourceLoadNode: tool_calls 中无 resource_name，跳过"
            )
            return _save_agent_loop_state_to_graph(chat_state, agent_loop)

        logger.info(
            f"[TraceID:{trace_id}] ResourceLoadNode: "
            f"发现 {len(resource_names)} 个资源需要加载: {resource_names}"
        )

        # 获取当前步骤意图（用于 Tier 3 轻精排）
        step_intent = self._get_step_intent(agent_loop)

        # 逐个加载资源（降级：单个失败不阻塞其他资源）
        loaded_resources: dict[str, str] = dict(agent_loop.execution.loaded_resources)
        resource_load_errors: dict[str, str] = dict(agent_loop.execution.resource_load_errors)

        # 获取 skill_registry 用于查找资源定义
        skill_registry = self._get_skill_registry()

        for resource_name in resource_names:
            try:
                # 从 tool_calls 中提取该资源关联的 query_text 列表
                # 为什么这样做：query_text 由 StepThinkNode 的 LLM 在思考阶段决定，
                # 确保检索意图与当前步骤紧密对齐，而非 ResourceLoadNode 自动构建。
                per_resource_queries = self._extract_query_texts_for_resource(
                    resource_name, tool_calls
                )
                # 如果 LLM 未提供 query，使用步骤意图作为兜底
                if not per_resource_queries and step_intent:
                    per_resource_queries = [step_intent]

                # 查找资源定义
                resource_def = self._find_resource_definition(
                    resource_name, tool_calls, skill_registry
                )

                # 调用 ResourceTierService 执行分级加载
                result = await self.resource_tier_service.load_resource(
                    trace_id=trace_id,
                    resource_def=resource_def,
                    query_texts=per_resource_queries,
                    step_intent=step_intent,
                )

                if result.success:
                    loaded_resources[resource_name] = result.content
                    # 清除之前的错误记录（如果有）
                    resource_load_errors.pop(resource_name, None)

                    logger.info(
                        f"[TraceID:{trace_id}] ResourceLoadNode: "
                        f"资源 {resource_name} 加载成功, "
                        f"策略={result.tier_used}, "
                        f"chunk 数={result.chunk_count}, "
                        f"内容长度={len(result.content)}"
                    )

                    # 发布 EVT_DAG_RESOURCE_LOADED 事件
                    await _emit_dag_event(
                        DagWorkflowEventType.EVT_DAG_RESOURCE_LOADED,
                        trace_id,
                        session_id,
                        {
                            "plan_id": agent_loop.goal.task_id,
                            "step_id": agent_loop.execution.current_step_id,
                            "resource_name": resource_name,
                            "tier_used": result.tier_used,
                            "chunk_count": result.chunk_count,
                            "content_length": len(result.content),
                        },
                        self.event_publisher,
                    )
                else:
                    resource_load_errors[resource_name] = result.error_message

                    logger.warning(
                        f"[TraceID:{trace_id}] ResourceLoadNode: "
                        f"资源 {resource_name} 加载失败: {result.error_message}"
                    )

                    # 发布 EVT_DAG_RESOURCE_FAILED 事件
                    await _emit_dag_event(
                        DagWorkflowEventType.EVT_DAG_RESOURCE_FAILED,
                        trace_id,
                        session_id,
                        {
                            "plan_id": agent_loop.goal.task_id,
                            "step_id": agent_loop.execution.current_step_id,
                            "resource_name": resource_name,
                            "error_message": result.error_message,
                        },
                        self.event_publisher,
                    )

            except Exception as exc:
                error_msg = f"资源加载异常: {exc}"
                resource_load_errors[resource_name] = error_msg

                logger.error(
                    f"[TraceID:{trace_id}] ResourceLoadNode: "
                    f"资源 {resource_name} 加载异常: {exc}"
                )

                # 发布 EVT_DAG_RESOURCE_FAILED 事件
                await _emit_dag_event(
                    DagWorkflowEventType.EVT_DAG_RESOURCE_FAILED,
                    trace_id,
                    session_id,
                    {
                        "plan_id": agent_loop.goal.task_id,
                        "step_id": agent_loop.execution.current_step_id,
                        "resource_name": resource_name,
                        "error_message": error_msg,
                    },
                    self.event_publisher,
                )

        # 写入加载结果
        agent_loop.execution.loaded_resources = loaded_resources
        agent_loop.execution.resource_load_errors = resource_load_errors

        logger.info(
            f"[TraceID:{trace_id}] ResourceLoadNode 完成: "
            f"成功={len(loaded_resources)}, "
            f"失败={len(resource_load_errors)}"
        )

        return _save_agent_loop_state_to_graph(chat_state, agent_loop)

    def _extract_resource_names(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[str]:
        """从 tool_calls 的 resources 数组中提取所有 resource_name（去重）。

        做什么：遍历 tool_calls 中每个条目的 resources 数组，
                收集所有非空的 resource_name。
        数据结构：每个 tool_call 的 resources 字段为数组，元素格式：
                  {"resource_name": "名称", "query_text": ["query1", "query2"]}
        参数:
            tool_calls: 工具调用列表（来自 StepThinkNode 输出）。
        返回:
            去重后的 resource_name 列表（保持首次出现顺序）。
        """
        seen: set[str] = set()
        result: list[str] = []
        for tc in tool_calls:
            resources = tc.get("resources", [])
            if not isinstance(resources, list):
                continue
            for res in resources:
                if not isinstance(res, dict):
                    continue
                resource_name = str(res.get("resource_name", "")).strip()
                if resource_name and resource_name not in seen:
                    seen.add(resource_name)
                    result.append(resource_name)
        return result

    def _extract_query_texts_for_resource(
        self, resource_name: str, tool_calls: list[dict[str, Any]]
    ) -> list[str]:
        """从 tool_calls 的 resources 数组中提取指定资源关联的 query_text 列表。

        做什么：遍历 tool_calls 中每个条目的 resources 数组，
                找到 resource_name 匹配的资源条目，提取 query_text 数组。
                多个 tool_call 引用同一资源时合并去重。
        为什么这样做：query_text 由 StepThinkNode 的 LLM 在思考阶段输出，
                      ResourceLoadNode 只负责消费，不再自行构建 query。
        参数:
            resource_name: 资源名称。
            tool_calls: 工具调用列表（来自 StepThinkNode 输出）。
        返回:
            去重后的 query 列表。
        """
        seen: set[str] = set()
        result: list[str] = []
        for tc in tool_calls:
            resources = tc.get("resources", [])
            if not isinstance(resources, list):
                continue
            for res in resources:
                if not isinstance(res, dict):
                    continue
                if res.get("resource_name") != resource_name:
                    continue
                queries = res.get("query_text", [])
                if not isinstance(queries, list):
                    continue
                for q in queries:
                    q_str = str(q).strip()
                    if q_str and q_str not in seen:
                        seen.add(q_str)
                        result.append(q_str)
        return result

    def _get_step_intent(self, agent_loop: AgentLoopState) -> str:
        """获取当前步骤意图。

        做什么：提取当前步骤的 intent 作为轻精排的参考。
        参数:
            agent_loop: Agent Loop 全局状态。
        返回:
            步骤意图字符串。
        """
        current_step = self._get_current_step(agent_loop)
        if current_step:
            return current_step.intent or ""
        return ""

    def _get_current_step(self, agent_loop: AgentLoopState) -> Any:
        """获取当前正在执行的步骤。

        参数:
            agent_loop: Agent Loop 全局状态。
        返回:
            当前步骤的 AgentStepState，或 None。
        """
        idx = agent_loop.plan.current_step_index
        if 0 <= idx < len(agent_loop.plan.steps):
            return agent_loop.plan.steps[idx]
        return None

    def _find_resource_definition(
        self,
        resource_name: str,
        tool_calls: list[dict[str, Any]],
        skill_registry: Any,
    ) -> dict[str, Any]:
        """查找资源定义。

        做什么：从 tool_calls 的 resources 数组中找到引用该资源的 skill_name，
               然后从 SkillRegistry 中查找资源的完整定义。
        参数:
            resource_name: 资源名称。
            tool_calls: 工具调用列表（resources 数组格式）。
            skill_registry: SkillRegistry 实例。
        返回:
            资源定义字典（name, resource_type, uri, description）。
        """
        # 从 tool_calls 的 resources 数组中找到引用该资源的 skill_name
        skill_name = ""
        for tc in tool_calls:
            resources = tc.get("resources", [])
            if not isinstance(resources, list):
                continue
            for res in resources:
                if isinstance(res, dict) and res.get("resource_name") == resource_name:
                    skill_name = tc.get("skill_name", "")
                    if skill_name:
                        break
            if skill_name:
                break

        # 从 SkillRegistry 查找资源定义
        if skill_registry and skill_name:
            try:
                # SkillRegistry 是单例，直接遍历 _skills 查找
                if hasattr(skill_registry, "_skills"):
                    for _sid, detail in skill_registry._skills.items():
                        if detail.name == skill_name:
                            for res in detail.resources:
                                if res.get("name") == resource_name:
                                    return {
                                        "name": resource_name,
                                        "resource_type": res.get("resource_type", "file"),
                                        "uri": res.get("uri", ""),
                                        "description": res.get("description", ""),
                                        "id": res.get("id", ""),
                                    }
            except Exception as exc:
                logger.warning(f"从 SkillRegistry 查找资源定义失败: {exc}")

        # 兜底：返回最小定义
        return {
            "name": resource_name,
            "resource_type": "file",
            "uri": "",
            "description": "",
        }

    def _get_skill_registry(self) -> Any | None:
        """获取 SkillRegistry 实例。

        做什么：从 FastAPI app.state 获取 SkillRegistry 单例。
        返回:
            SkillRegistry 实例，获取失败返回 None。
        """
        try:
            from app.mcp.skill_registry import SkillRegistry
            return SkillRegistry()
        except Exception:
            return None
