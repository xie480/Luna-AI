"""并行工具执行器。

做什么：接收 StepThinkNode 输出的多个 tool_calls，通过 asyncio.gather 并行执行。
为什么这样做：这是 Agent Loop 提速最明显的一部分，
             多个独立工具调用可以同时执行，大幅降低延迟。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.logger import logger
from app.utils.snowflake import generate_string_id
from app.workflow.dag.worker_pool import ToolWorkerPool


class ParallelToolExecutor:
    """并行工具执行器。

    核心逻辑：
        1. 接收 tool_calls 列表
        2. 检查每个 tool_call 的依赖关系（tool_graph）
        3. 无依赖的 tool 通过 asyncio.gather 并行执行
        4. 有依赖的 tool 等待前置 tool 完成后执行
        5. 通过 Semaphore 控制最大并发数（Worker Pool）
    """

    def __init__(
        self,
        max_concurrency: int = 10,
        tool_executor: Any = None,
        worker_pool: ToolWorkerPool | None = None,
    ):
        """初始化。

        参数:
            max_concurrency: 最大并发数，防止资源耗尽。
            tool_executor: 底层工具执行器（复用 ToolExecuteNode）。
            worker_pool: 工具执行工作池（含分层限流）。
                         None 时使用默认单层 Semaphore。
        """
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._tool_executor = tool_executor
        self._worker_pool = worker_pool

    async def execute_batch(
        self,
        tool_calls: list[dict[str, Any]],
        state_context: dict[str, Any],
        trace_id: str,
    ) -> dict[str, dict[str, Any]]:
        """并行执行一批工具调用。

        做什么：
        1. 检查 tool_calls 中是否有 depends_on 声明，构建 DAG 依赖图
        2. 无依赖的 tool 先并行执行第一批
        3. 有依赖的 tool 等待前置完成后执行后续批次
        4. 通过 Semaphore 控制并发
        5. 收集所有结果

        参数:
            tool_calls: StepThinkNode 输出的工具调用列表。
            state_context: 执行上下文。
            trace_id: 追踪 ID。

        返回:
            {tc_id: result} 映射
        """
        if not tool_calls:
            return {}

        logger.info(
            f"[TraceID:{trace_id}] ParallelToolExecutor: "
            f"开始并行执行 {len(tool_calls)} 个工具调用"
        )

        # 构建 tool_calls 的 ID 映射
        tc_list: list[dict[str, Any]] = []
        for tc in tool_calls:
            tc_data = dict(tc)
            if "call_id" not in tc_data:
                tc_data["call_id"] = generate_string_id()
            tc_list.append(tc_data)

        # 按依赖关系分层
        layers = self._build_tool_layers(tc_list)

        # 逐层执行
        all_results: dict[str, dict[str, Any]] = {}
        for layer_idx, layer in enumerate(layers):
            logger.info(
                f"[TraceID:{trace_id}] ParallelToolExecutor: "
                f"执行第 {layer_idx + 1}/{len(layers)} 层, 共 {len(layer)} 个工具"
            )

            layer_results = await self._execute_layer(
                layer=layer,
                state_context=state_context,
                trace_id=trace_id,
            )
            all_results.update(layer_results)

        logger.info(
            f"[TraceID:{trace_id}] ParallelToolExecutor: "
            f"全部执行完成, 共 {len(all_results)} 个结果"
        )

        return all_results

    def _build_tool_layers(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        """将 tool_calls 按依赖关系分层。

        做什么：构建 tool_call_id → tool_call 的映射，
               通过拓扑排序将工具划分为多个执行层。
        同层工具无依赖关系，可并行执行。

        参数:
            tool_calls: 工具调用列表（含 call_id 和 depends_on）。

        返回:
            分层后的工具列表，每个元素是一层可并行执行的工具。
        """
        # 构建映射
        tc_map: dict[str, dict[str, Any]] = {
            tc.get("call_id", ""): tc for tc in tool_calls
        }

        # 计算每个工具的入度（前置依赖数）
        in_degree: dict[str, int] = {}
        for tc in tool_calls:
            cid = tc.get("call_id", "")
            deps = tc.get("depends_on", []) or []
            in_degree[cid] = len(deps)

        # 分层
        layers: list[list[dict[str, Any]]] = []
        remaining = set(tc_map.keys())

        while remaining:
            # 找出当前入度为 0 的节点
            current_layer_ids = [
                cid for cid in remaining if in_degree.get(cid, 0) == 0
            ]

            if not current_layer_ids:
                # 检测到循环依赖，将剩余工具全部放入最后一层
                logger.warning(
                    f"ParallelToolExecutor: 检测到循环依赖或无效依赖, "
                    f"剩余 {len(remaining)} 个工具强制放入最后一层"
                )
                current_layer_ids = list(remaining)

            current_layer = [tc_map[cid] for cid in current_layer_ids]
            layers.append(current_layer)

            # 从 remaining 移除已处理的节点
            for cid in current_layer_ids:
                remaining.discard(cid)
                # 减少下游节点的入度
                for tc in tool_calls:
                    deps = tc.get("depends_on", []) or []
                    if cid in deps:
                        tc_id = tc.get("call_id", "")
                        if tc_id in in_degree:
                            in_degree[tc_id] = max(0, in_degree[tc_id] - 1)

        return layers

    async def _execute_layer(
        self,
        layer: list[dict[str, Any]],
        state_context: dict[str, Any],
        trace_id: str,
    ) -> dict[str, dict[str, Any]]:
        """并行执行一层工具。

        参数:
            layer: 同一层的工具调用列表（无依赖关系，可并行）。
            state_context: 执行上下文。
            trace_id: 追踪 ID。

        返回:
            {call_id: result} 映射。
        """
        tasks = [
            self._execute_single(
                tc=tc,
                state_context=state_context,
                trace_id=trace_id,
            )
            for tc in layer
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: dict[str, dict[str, Any]] = {}
        for tc, result in zip(layer, results):
            call_id = tc.get("call_id", "")
            if isinstance(result, Exception):
                logger.error(
                    f"[TraceID:{trace_id}] ParallelToolExecutor: "
                    f"工具 {tc.get('tool_name', '')} 执行异常: {result}"
                )
                output[call_id] = {
                    "success": False,
                    "error_message": str(result),
                    "tool_name": tc.get("tool_name", ""),
                }
            elif isinstance(result, dict):
                output[call_id] = result
            else:
                output[call_id] = {
                    "success": True,
                    "tool_output": str(result),
                    "tool_name": tc.get("tool_name", ""),
                }

        return output

    async def _execute_single(
        self,
        tc: dict[str, Any],
        state_context: dict[str, Any],
        trace_id: str,
    ) -> tuple[str, dict[str, Any]]:
        """执行单个工具调用（带 Semaphore 控制）。

        做什么：
        1. async with self._semaphore（或 worker_pool.acquire）
        2. 调用 tool_executor.execute_tool()
        3. 返回 (call_id, result)

        参数:
            tc: 单个工具调用定义。
            state_context: 执行上下文。
            trace_id: 追踪 ID。

        返回:
            (call_id, result) 元组。
        """
        call_id = tc.get("call_id", generate_string_id())
        tool_name = tc.get("tool_name", "")
        parameters = tc.get("parameters", {})

        try:
            # 通过 WorkerPool 或 Semaphore 控制并发
            if self._worker_pool:
                await self._worker_pool.acquire(tool_name)
            else:
                await self._semaphore.acquire()

            try:
                if self._tool_executor:
                    result = await self._tool_executor.execute_tool(
                        tool_name=tool_name,
                        parameters=parameters,
                        state_context=state_context,
                        trace_id=trace_id,
                    )
                else:
                    # 没有 tool_executor 时返回占位结果
                    result = {
                        "success": True,
                        "tool_output": f"[模拟] 工具 {tool_name} 执行完成",
                        "tool_name": tool_name,
                    }
                return call_id, result
            finally:
                if self._worker_pool:
                    await self._worker_pool.release(tool_name)
                else:
                    self._semaphore.release()

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] ParallelToolExecutor: "
                f"执行工具 {tool_name} 失败: {exc}"
            )
            return call_id, {
                "success": False,
                "error_message": str(exc),
                "tool_name": tool_name,
            }
