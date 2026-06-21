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
        """
        partitioned_outputs = state_context.get("partitioned_outputs", {})
        if not node_def.depends_on:
            # 无依赖时，使用 context 中的 input_data
            return state_context.get("input_data", "")

        parts = []
        for dep_id in node_def.depends_on:
            dep_output = partitioned_outputs.get(dep_id, {})
            # 提取各种可能的输出字段
            content = (
                dep_output.get("tool_output", "")
                or dep_output.get("resource_content", "")
                or dep_output.get("transformed_data", "")
                or dep_output.get("memory_text", "")
                or dep_output.get("knowledge_text", "")
                or str(dep_output)
            )
            if content:
                parts.append(f"[{dep_id}]: {content}")

        return "\n\n".join(parts) if parts else ""
