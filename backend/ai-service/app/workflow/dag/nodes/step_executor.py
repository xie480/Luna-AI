"""Phase 9 DAG 引擎 — Step 执行器。

做什么：接收 StepDefinition，将其中的原子节点按拓扑分层并行执行，
        结果写入 partitioned_outputs。
为什么用 asyncio.gather 而非 LangGraph 子图：
        State 内部的 Step 通常只有 2-5 个节点，
        asyncio.gather 足够且更简单。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import format_step_progress, get_chat_status_text
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.dag.nodes.data_transform import DataTransformNode
from app.workflow.dag.nodes.resource_loading import ResourceLoadingNode
from app.workflow.dag.nodes.tool_execute import ToolExecuteNode
from app.workflow.dag.types import (
    AtomicNodeDefinition,
    DagNodeType,
    StepDefinition,
)


class StepRetryPolicy:
    """Step 级重试策略。

    做什么：当 Step 内某个节点执行失败时，带错误信息重试。
    为什么这样做：执行层面的临时故障（参数格式错误、工具超时等）
                  应该在 Step 级别快速重试，而非上升到 State 评估层。
    """

    MAX_RETRIES = 2  # 最多重试 2 次（含首次共 3 次尝试）

    def __init__(self, step_executor: "StepExecutor"):
        """初始化重试策略。"""
        self.step_executor = step_executor

    async def execute_with_retry(
        self,
        trace_id: str,
        step_def: StepDefinition,
        state_context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """带重试的 Step 执行。

        返回:
            (partitioned_outputs, error_messages)
            - 成功时 error_messages 为空列表
            - 重试耗尽时 error_messages 包含所有尝试的错误信息
        """
        errors = []
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                outputs = await self.step_executor.execute(
                    trace_id, step_def, state_context
                )
                # 检查是否有节点失败
                failed_nodes = [
                    nid for nid, out in outputs.items()
                    if not out.get("success", True)
                ]
                if not failed_nodes:
                    return outputs, []

                # 收集错误信息用于下次重试
                error_msg = "; ".join(
                    outputs[nid].get("error_message", "未知错误")
                    for nid in failed_nodes
                )
                errors.append(f"[attempt={attempt + 1}] {error_msg}")

                # 将错误注入到下一次执行的上下文中
                state_context["_step_retry_context"] = errors[-1]

            except Exception as e:
                errors.append(f"[attempt={attempt + 1}] 异常: {e}")

        # 重试耗尽
        logger.error(
            f"[TraceID:{trace_id}] Step {step_def.step_id} "
            f"重试 {self.MAX_RETRIES} 次后仍然失败: {errors}"
        )
        return {}, errors


class StepExecutor:
    """Step 执行器。

    做什么：接收 StepDefinition，将其中的原子节点并行执行，
            结果写入 partitioned_outputs。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        mcp_tool_registry: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 Step 执行器。

        参数:
            prompt_manager: Prompt 管理器。
            llm_client: LLM 客户端。
            mcp_tool_registry: MCP 工具注册中心。
            chat_status_publisher: Chat 状态发布器。
        """
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()
        # 初始化五种原子节点执行器
        self.resource_loading = ResourceLoadingNode()
        self.tool_execute = ToolExecuteNode(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
            mcp_tool_registry=mcp_tool_registry,
            chat_status_publisher=chat_status_publisher,
        )
        self.data_transform = DataTransformNode(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
        )

    async def execute(
        self,
        trace_id: str,
        step_def: StepDefinition,
        state_context: dict[str, Any],
    ) -> dict[str, Any]:
        """并行执行 Step 内所有原子节点，返回分区输出。

        做什么：按 depends_on 拓扑排序，分层并行执行。
        返回:
            dict: partitioned_outputs — node_id -> 执行结果。
        """
        # 发布 Step 执行开始状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=state_context.get("session_id", ""),
            message_id="",
            stage=ChatStatusStage.DAG_STEP_EXECUTION,
            state=ChatStatusState.RUNNING,
            display_text=format_step_progress(
                step_def.step_index + 1,
                state_context.get("steps_total", 1),
                step_def.description,
            ),
            is_visible=True,
            is_terminal=False,
        )

        # 按 depends_on 拓扑排序，分层并行
        layers = self._topological_sort(step_def.nodes)
        partitioned_outputs: dict[str, dict[str, Any]] = {}

        for layer in layers:
            # 同一层的节点并行执行
            tasks = [
                self._execute_node(trace_id, node, state_context, partitioned_outputs)
                for node in layer
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for node, result in zip(layer, results):
                if isinstance(result, Exception):
                    partitioned_outputs[node.node_id] = {
                        "success": False,
                        "error_message": str(result),
                    }
                else:
                    partitioned_outputs[node.node_id] = result

        # 发布 Step 执行完成状态
        succeeded = sum(
            1 for out in partitioned_outputs.values() if out.get("success", True)
        )
        failed = len(partitioned_outputs) - succeeded

        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=state_context.get("session_id", ""),
            message_id="",
            stage=ChatStatusStage.DAG_STEP_EXECUTION,
            state=(
                ChatStatusState.COMPLETED if failed == 0
                else ChatStatusState.ERROR
            ),
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_STEP_EXECUTION,
                ChatStatusState.COMPLETED if failed == 0
                else ChatStatusState.ERROR,
            ),
            is_visible=True,
            is_terminal=True,
        )

        return partitioned_outputs

    async def _execute_node(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
        partitioned_outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """执行单个原子节点。

        做什么：根据节点类型分发到对应的执行器。
        """
        # 更新 state_context 中的分区输出，供依赖节点读取
        state_context["partitioned_outputs"] = partitioned_outputs

        if node_def.node_type == DagNodeType.RESOURCE_LOADING:
            return await self.resource_loading.execute(
                trace_id, node_def, state_context
            )
        elif node_def.node_type == DagNodeType.TOOL_EXECUTE:
            return await self.tool_execute.execute(
                trace_id, node_def, state_context
            )
        elif node_def.node_type == DagNodeType.DATA_TRANSFORM:
            return await self.data_transform.execute(
                trace_id, node_def, state_context
            )
        elif node_def.node_type == DagNodeType.LONG_TERM_MEMORY:
            return await self._execute_long_term_memory(
                trace_id, node_def, state_context
            )
        elif node_def.node_type == DagNodeType.KNOWLEDGE_RAG:
            return await self._execute_knowledge_rag(
                trace_id, node_def, state_context
            )
        else:
            return {
                "success": False,
                "error_message": f"未知的节点类型: {node_def.node_type}",
            }

    async def _execute_long_term_memory(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行长期记忆检索节点。

        做什么：复用现有的记忆管理器做长期记忆检索。
        """
        try:
            memory_manager = state_context.get("memory_manager")
            if not memory_manager:
                return {
                    "success": False,
                    "memory_text": "",
                    "error_message": "memory_manager 未注入到 state_context 中",
                }

            # 执行长期记忆检索：委托 HybridRetriever 混合检索 + Rerank 全流程
            query_text = node_def.query_text
            memory_text = await memory_manager.retrieve_and_format_memories(
                query_text=query_text,
                query_vector=[],
            )

            return {
                "success": True,
                "memory_text": memory_text,
                "error_message": "",
            }
        except Exception as e:
            logger.error(
                f"[TraceID:{trace_id}] 长期记忆检索失败: "
                f"node_id={node_def.node_id}, error={e}"
            )
            return {
                "success": False,
                "memory_text": "",
                "error_message": str(e),
            }

    async def _execute_knowledge_rag(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行知识库 RAG 检索节点。

        做什么：复用现有的 RAG 检索编排器做知识库检索。
        """
        try:
            rag_orchestrator = state_context.get("rag_orchestrator")
            if not rag_orchestrator:
                return {
                    "success": False,
                    "knowledge_text": "",
                    "citations": [],
                    "error_message": "rag_orchestrator 未注入到 state_context 中",
                }

            # 执行 RAG 检索
            query_text = node_def.query_text
            rag_result = await rag_orchestrator.retrieve(
                query=query_text,
                session_id=state_context.get("session_id", ""),
            )

            knowledge_text = ""
            citations = []
            if hasattr(rag_result, "evidence_text"):
                knowledge_text = rag_result.evidence_text
            if hasattr(rag_result, "citations"):
                citations = [
                    c.model_dump() if hasattr(c, "model_dump") else c
                    for c in rag_result.citations
                ]

            return {
                "success": True,
                "knowledge_text": knowledge_text,
                "citations": citations,
                "error_message": "",
            }
        except Exception as e:
            logger.error(
                f"[TraceID:{trace_id}] 知识库 RAG 检索失败: "
                f"node_id={node_def.node_id}, error={e}"
            )
            return {
                "success": False,
                "knowledge_text": "",
                "citations": [],
                "error_message": str(e),
            }

    def _topological_sort(
        self, nodes: list[AtomicNodeDefinition]
    ) -> list[list[AtomicNodeDefinition]]:
        """拓扑排序：将节点按依赖关系分层。

        做什么：同一层的节点可以并行执行，不同层的节点有先后依赖。
        返回:
            list[list[AtomicNodeDefinition]]: 分层后的节点列表。
        """
        node_map = {n.node_id: n for n in nodes}
        in_degree: dict[str, int] = {n.node_id: 0 for n in nodes}

        # 计算入度
        for node in nodes:
            for dep_id in node.depends_on:
                if dep_id in in_degree:
                    in_degree[node.node_id] += 1

        layers = []
        remaining = set(n.node_id for n in nodes)

        while remaining:
            # 找出当前入度为 0 的节点
            current_layer = [
                node_map[nid] for nid in remaining
                if in_degree[nid] == 0
            ]
            if not current_layer:
                # 存在循环依赖，将剩余节点全部放入最后一层
                logger.warning(
                    f"Step 拓扑排序检测到循环依赖，"
                    f"剩余节点: {remaining}"
                )
                layers.append([node_map[nid] for nid in remaining])
                break

            layers.append(current_layer)

            # 更新入度
            for node in current_layer:
                remaining.discard(node.node_id)
                for other_node in nodes:
                    if node.node_id in other_node.depends_on:
                        in_degree[other_node.node_id] -= 1

        return layers
