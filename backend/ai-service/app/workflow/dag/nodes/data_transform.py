"""Phase 9 DAG 引擎 — 数据转换节点。

做什么：对前序节点的输出做纯 LLM 推理的数据转换。
        例如：从搜索结果中提取表格数据、将 JSON 转为 Markdown、
        对多个数据源做对比分析。
Prompt：使用 dag_data_transform 三槽位 Prompt。
"""

from __future__ import annotations

import json
from typing import Any

from app.logger import logger
from app.prompt.types import PromptCategory
from app.workflow.dag.types import AtomicNodeDefinition


class DataTransformNode:
    """数据转换节点。

    做什么：对前序节点的输出做纯 LLM 推理的数据转换。
    为什么需要：有些数据转换不是工具调用也不是 RAG，
               而是纯 LLM 推理的数据处理，需要独立的节点类型。
    """

    def __init__(self, prompt_manager: Any, llm_client: Any):
        """初始化数据转换节点。"""
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client

    async def execute(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行数据转换。

        做什么：收集依赖节点的输出，调用 LLM 做数据转换。
        返回:
            dict: 包含 success、transformed_data、error_message。
        """
        try:
            # 收集依赖节点的输出作为输入
            input_data = self._gather_dependency_outputs(
                node_def, state_context
            )

            # 渲染数据转换 Prompt
            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_DATA_TRANSFORM,
                variables={
                    "input_data": input_data,
                    "transform_instruction": node_def.transform_instruction,
                    "node_id": node_def.node_id,
                },
            )

            logger.info(
                f"[TraceID:{trace_id}] 数据转换开始: "
                f"node_id={node_def.node_id}, "
                f"input_len={len(input_data)}, "
                f"prompt={prompt_text}"
            )

            # 调用 LLM 做数据转换
            result = await self.llm_client.invoke(
                trace_id=trace_id,
                prompt=prompt_text,
            )

            logger.info(
                f"[TraceID:{trace_id}] 数据转换完成: "
                f"node_id={node_def.node_id}, "
                f"output={result}"
            )

            return {
                "success": True,
                "transformed_data": result,
                "error_message": "",
            }

        except Exception as e:
            logger.error(
                f"[TraceID:{trace_id}] 数据转换失败: "
                f"node_id={node_def.node_id}, error={e}"
            )
            return {
                "success": False,
                "transformed_data": "",
                "error_message": str(e),
            }

    def _gather_dependency_outputs(
        self,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
    ) -> str:
        """收集依赖节点的输出。

        做什么：从 partitioned_outputs 中提取依赖节点的输出，
               拼接为文本供 LLM 使用。
        跨 Step 依赖处理：
               depends_on 只能引用同 Step 内的节点（node_id 按 Step 独立生成）。
               当 depends_on 为空时，说明 LLM 无法在 Step Plan 中指定跨 Step 依赖，
               此时需要从 partitioned_outputs 中自动收集前序 Step 的所有可用输出。
        """
        partitioned_outputs = state_context.get("partitioned_outputs", {})

        # 情况 1：depends_on 非空 — 精确查找同 Step 内的依赖节点输出
        if node_def.depends_on:
            parts = []
            for dep_id in node_def.depends_on:
                dep_output = partitioned_outputs.get(dep_id, {})
                content = self._extract_output_content(dep_output)
                if content:
                    parts.append(f"[{dep_id}]: {content}")
            if parts:
                return "\n\n".join(parts)

        # 情况 2：depends_on 为空 — 回退策略
        # 优先使用 state_context 中显式注入的 input_data
        input_data = state_context.get("input_data", "")
        if input_data:
            return input_data

        # 最后尝试从 partitioned_outputs 中自动收集所有可用输出
        # 为什么这样做：跨 Step 依赖无法通过 depends_on 表达，
        #               但前序 Step 的输出已通过 StepExecutor 的
        #               partitioned_outputs 继承机制注入到 state_context 中。
        if partitioned_outputs:
            parts = []
            for node_id, dep_output in partitioned_outputs.items():
                content = self._extract_output_content(dep_output)
                if content:
                    parts.append(f"[{node_id}]: {content}")
            if parts:
                return "\n\n".join(parts)

        return ""

    @staticmethod
    def _extract_output_content(dep_output: dict[str, Any]) -> str:
        """从节点输出字典中提取文本内容。

        做什么：按优先级尝试提取各种可能的输出字段。
        为什么这样做：不同类型的节点（tool_execute、long_term_memory、
                      knowledge_rag、data_transform）使用不同的输出字段名。
        """
        return (
            dep_output.get("tool_output", "")
            or dep_output.get("resource_content", "")
            or dep_output.get("transformed_data", "")
            or dep_output.get("memory_text", "")
            or dep_output.get("knowledge_text", "")
            or ""
        )
