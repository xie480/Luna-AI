"""Phase 9 DAG 引擎 — MCP 工具执行节点。

做什么：接收 Step Plan 产出的节点定义，结合当前上下文提取工具参数，
        执行参数 Schema 机械校验，调用 execute_tool。
改造自 MCPSkillExecutionNode：移除内部规划和评估逻辑，只保留
        参数提取 + 机械层校验 + 工具调用 + Gating 审批。
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.dag.types import AtomicNodeDefinition


class ToolExecuteNode:
    """MCP 工具执行节点（改造自 MCPSkillExecutionNode）。

    做什么：接收 Step Plan 产出的节点定义，
            结合当前上下文提取工具参数，执行参数 Schema 机械校验，
            调用 execute_tool，校验失败时重试 1 次。
    改造点：
        - 移除内部的 Skill 初筛逻辑（上移到 SkillScreeningNode）
        - 移除内部的执行计划生成（上移到 StepPlanNode）
        - 移除内部的评估逻辑（上移到 StateEvaluationNode）
        - 保留：参数提取 + 机械层校验 + 工具调用 + Gating 审批
    """

    # 机械层参数校验重试次数
    MECHANICAL_RETRY_MAX = 1

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        mcp_tool_registry: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化工具执行节点。"""
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.mcp_tool_registry = mcp_tool_registry
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def execute(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行单个 MCP 工具节点。

        做什么：参数提取 -> Schema 校验 -> 工具调用。
        返回:
            dict: 包含 success、tool_output、error_message、tool_parameters。
        """
        started_at_ms = int(time.time() * 1000)

        try:
            # Step 1: 资源预加载（如果有 resource 依赖）
            resource_context = ""
            if node_def.resource_name:
                resource_context = await self._load_resource(
                    trace_id, node_def.skill_name, node_def.resource_name,
                    state_context,
                )

            # Step 2: LLM 提取工具参数
            tool_parameters, param_error = await self._extract_and_validate_params(
                trace_id, node_def, state_context, resource_context,
                retry_context="",
            )

            # Step 3: 机械层参数 Schema 校验 + 1次重试
            if param_error:
                tool_parameters, param_error = await self._extract_and_validate_params(
                    trace_id, node_def, state_context, resource_context,
                    retry_context=(
                        f"上一次参数校验失败，错误信息：{param_error}。"
                        f"请修正参数后重新生成。"
                    ),
                )
                if param_error:
                    elapsed_ms = int(time.time() * 1000) - started_at_ms
                    return {
                        "success": False,
                        "error_message": (
                            f"参数校验失败（已重试 {self.MECHANICAL_RETRY_MAX} 次）: "
                            f"{param_error}"
                        ),
                        "tool_output": "",
                        "tool_parameters": tool_parameters,
                        "latency_ms": elapsed_ms,
                    }

            # Step 4: 执行工具
            tool_result = await self._execute_tool(
                trace_id, node_def, tool_parameters,
            )

            elapsed_ms = int(time.time() * 1000) - started_at_ms
            tool_result["latency_ms"] = elapsed_ms

            logger.info(
                f"[TraceID:{trace_id}] 工具执行完成: "
                f"tool={node_def.tool_name}, "
                f"success={tool_result.get('success', False)}, "
                f"elapsed_ms={elapsed_ms}"
            )

            return tool_result

        except Exception as e:
            elapsed_ms = int(time.time() * 1000) - started_at_ms
            logger.error(
                f"[TraceID:{trace_id}] 工具执行异常: "
                f"tool={node_def.tool_name}, error={e}"
            )
            return {
                "success": False,
                "error_message": str(e),
                "tool_output": "",
                "tool_parameters": {},
                "latency_ms": elapsed_ms,
            }

    async def _load_resource(
        self,
        trace_id: str,
        skill_name: str | None,
        resource_name: str | None,
        state_context: dict[str, Any],
    ) -> str:
        """加载资源文件内容。"""
        try:
            skill_registry = state_context.get("skill_registry")
            if not skill_registry or not skill_name or not resource_name:
                return ""
            content = await skill_registry.load_resource(skill_name, resource_name)
            return content
        except Exception as e:
            logger.warning(
                f"[TraceID:{trace_id}] 资源预加载失败: "
                f"skill={skill_name}, resource={resource_name}, error={e}"
            )
            return ""

    async def _extract_and_validate_params(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
        resource_context: str,
        retry_context: str,
    ) -> tuple[dict[str, Any], str]:
        """提取工具参数并做 Schema 校验。

        返回:
            (tool_parameters, error_message)
            - 成功时 error_message 为空字符串
            - 失败时 error_message 包含错误信息
        """
        try:
            # 获取工具 Schema
            tool_schema = await self._get_tool_schema(node_def.tool_name)

            # 渲染参数提取 Prompt
            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_TOOL_PARAMETER_EXTRACTION,
                variables={
                    "tool_name": node_def.tool_name or "",
                    "tool_schema": json.dumps(tool_schema, ensure_ascii=False),
                    "parameter_hint": node_def.parameter_hint,
                    "resource_context": resource_context,
                    "state_context": json.dumps(
                        state_context.get("current_step_context", {}),
                        ensure_ascii=False,
                    ),
                    "retry_context": retry_context,
                },
            )

            # 调用 LLM 提取参数
            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_param_schema(tool_schema),
            )

            # 解析参数
            params = self._parse_params(llm_response)

            # 机械层 Schema 校验
            validation_error = self._validate_params_against_schema(
                params, tool_schema
            )

            return params, validation_error

        except Exception as e:
            logger.error(
                f"[TraceID:{trace_id}] 参数提取失败: "
                f"tool={node_def.tool_name}, error={e}"
            )
            return {}, str(e)

    async def _get_tool_schema(self, tool_name: str | None) -> dict[str, Any]:
        """获取 MCP 工具的 input schema。"""
        if not tool_name:
            return {}
        tool = self.mcp_tool_registry.get_tool(tool_name)
        if tool and hasattr(tool, "input_schema"):
            return tool.input_schema
        return {}

    def _build_param_schema(
        self, tool_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """构建参数提取的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "parameters": {
                    "type": "object",
                    "description": "工具调用参数",
                },
            },
            "required": ["parameters"],
        }

    def _parse_params(self, llm_response: str | dict) -> dict[str, Any]:
        """解析 LLM 输出的参数。"""
        if isinstance(llm_response, dict):
            return llm_response.get("parameters", llm_response)
        try:
            data = json.loads(llm_response)
            return data.get("parameters", data)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data.get("parameters", data)
            return {}

    def _validate_params_against_schema(
        self,
        params: dict[str, Any],
        tool_schema: dict[str, Any],
    ) -> str:
        """机械层 Schema 校验。

        做什么：检查必填字段是否存在、类型是否匹配。
        返回:
            str: 错误信息，空字符串表示校验通过。
        """
        if not tool_schema:
            return ""

        required_fields = tool_schema.get("required", [])
        properties = tool_schema.get("properties", {})

        errors = []
        for field_name in required_fields:
            if field_name not in params:
                errors.append(f"缺少必填参数: {field_name}")

        for field_name, field_value in params.items():
            if field_name in properties:
                expected_type = properties[field_name].get("type", "")
                if expected_type == "string" and not isinstance(field_value, str):
                    errors.append(
                        f"参数 {field_name} 类型错误: 期望 string, "
                        f"实际 {type(field_value).__name__}"
                    )
                elif expected_type == "integer" and not isinstance(field_value, int):
                    errors.append(
                        f"参数 {field_name} 类型错误: 期望 integer, "
                        f"实际 {type(field_value).__name__}"
                    )
                elif expected_type == "number" and not isinstance(
                    field_value, (int, float)
                ):
                    errors.append(
                        f"参数 {field_name} 类型错误: 期望 number, "
                        f"实际 {type(field_value).__name__}"
                    )
                elif expected_type == "boolean" and not isinstance(
                    field_value, bool
                ):
                    errors.append(
                        f"参数 {field_name} 类型错误: 期望 boolean, "
                        f"实际 {type(field_value).__name__}"
                    )
                elif expected_type == "array" and not isinstance(
                    field_value, list
                ):
                    errors.append(
                        f"参数 {field_name} 类型错误: 期望 array, "
                        f"实际 {type(field_value).__name__}"
                    )
                elif expected_type == "object" and not isinstance(
                    field_value, dict
                ):
                    errors.append(
                        f"参数 {field_name} 类型错误: 期望 object, "
                        f"实际 {type(field_value).__name__}"
                    )

        return "; ".join(errors) if errors else ""

    async def _execute_tool(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        tool_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """执行 MCP 工具。"""
        try:
            from app.mcp.executor import execute_tool

            exec_result = await execute_tool(
                tool_name=node_def.tool_name,
                parameters=tool_parameters,
                trace_id=trace_id,
            )

            return {
                "success": exec_result.success,
                "tool_output": exec_result.output_text,
                "error_message": (
                    exec_result.error_message if not exec_result.success else ""
                ),
                "tool_parameters": tool_parameters,
                "gating_rejected": False,
            }

        except ImportError:
            # MCP executor 模块不可用时的降级处理
            logger.warning(
                f"[TraceID:{trace_id}] MCP executor 模块不可用，"
                f"工具 {node_def.tool_name} 无法执行"
            )
            return {
                "success": False,
                "tool_output": "",
                "error_message": f"MCP executor 模块不可用: {node_def.tool_name}",
                "tool_parameters": tool_parameters,
                "gating_rejected": False,
            }
