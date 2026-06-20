"""Phase 9 DAG 引擎 — MCP 工具执行节点。

做什么：接收 Step Plan 产出的节点定义，结合当前上下文提取工具参数，
        执行参数 Schema 机械校验，调用 execute_tool。
改造自 MCPSkillExecutionNode：移除内部规划和评估逻辑，只保留
        参数提取 + 机械层校验 + 工具调用 + Gating 审批 + memory_schema 提取。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory, render_template
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
        - 保留：memory_schema 提取 + 参数提取 + 机械层校验 + 工具调用 + Gating 审批
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

        做什么：
        1. 检查工具是否有 memory_schema，如果有则提取记忆变量
        2. 加载工具专属 Prompt（如果有）
        3. 渲染通用 memory 上下文并注入到工具 Prompt
        4. LLM 提取参数 -> Schema 校验 -> 工具调用

        返回:
            dict: 包含 success、tool_output、error_message、tool_parameters。
        """
        started_at_ms = int(time.time() * 1000)

        try:
            # ============================================================
            # Step 1: 检查 memory_schema 并提取记忆变量
            # ============================================================
            skill_memory_context = None
            tool_memory_schema = await self._get_tool_memory_schema(
                node_def.tool_name
            )

            if tool_memory_schema:
                logger.info(
                    f"[TraceID:{trace_id}] 工具 {node_def.tool_name} "
                    f"声明了 memory_schema，开始提取记忆变量"
                )
                skill_memory_context = await self._extract_memory_variables(
                    trace_id=trace_id,
                    node_def=node_def,
                    state_context=state_context,
                    memory_schema=tool_memory_schema,
                )

            # ============================================================
            # Step 2: 资源预加载（如果有 resource 依赖）
            # ============================================================
            resource_context = ""
            if node_def.resource_name:
                resource_context = await self._load_resource(
                    trace_id, node_def.skill_name, node_def.resource_name,
                    state_context,
                )

            # ============================================================
            # Step 3: 构建工具专属 Prompt（如果有的话）
            # ============================================================
            tool_specific_prompt = await self._load_tool_specific_prompt(
                trace_id=trace_id,
                node_def=node_def,
                state_context=state_context,
                resource_context=resource_context,
                skill_memory_context=skill_memory_context,
            )

            # ============================================================
            # Step 4: LLM 提取工具参数
            # ============================================================
            tool_parameters, param_error = await self._extract_and_validate_params(
                trace_id=trace_id,
                node_def=node_def,
                state_context=state_context,
                resource_context=resource_context,
                retry_context="",
                tool_specific_prompt=tool_specific_prompt,
            )

            # ============================================================
            # Step 5: 机械层参数 Schema 校验 + 1次重试
            # ============================================================
            if param_error:
                tool_parameters, param_error = await self._extract_and_validate_params(
                    trace_id=trace_id,
                    node_def=node_def,
                    state_context=state_context,
                    resource_context=resource_context,
                    retry_context=(
                        f"上一次参数校验失败，错误信息：{param_error}。"
                        f"请修正参数后重新生成。"
                    ),
                    tool_specific_prompt=tool_specific_prompt,
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

            # ============================================================
            # Step 6: 执行工具
            # ============================================================
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

    async def _get_tool_memory_schema(
        self, tool_name: str | None
    ) -> dict[str, Any] | None:
        """获取工具的 memory_schema。

        做什么：从 MCPToolRegistry 中查找工具是否声明了 memory_schema。
        返回:
            dict | None: memory_schema，未声明时返回 None。
        """
        if not tool_name:
            return None
        try:
            registered_tool = self.mcp_tool_registry.get_tool(tool_name)
            if registered_tool and hasattr(registered_tool, 'schema'):
                return registered_tool.schema.memory_schema
        except Exception as e:
            logger.warning(f"获取工具 memory_schema 失败: tool={tool_name}, error={e}")
        return None

    async def _extract_memory_variables(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
        memory_schema: dict[str, Any],
    ) -> dict[str, Any] | None:
        """提取工具专属记忆变量。

        做什么：仿照 MCPSkillMemoryAgent，基于 memory_schema 和历史执行数据
               提取键值对，用于注入到工具专属 Prompt 中。
        """
        try:
            from app.agent.mcp_skill_memory import MCPSkillMemoryAgent

            memory_agent = MCPSkillMemoryAgent(prompt_manager=self.prompt_manager)

            # 构建 all_round_data（当前 State 的历史执行数据）
            all_round_data = state_context.get("all_round_data", [])
            mcp_intent = state_context.get("mcp_intent", node_def.parameter_hint)

            skill_memory_context = await memory_agent.extract_memory_variables(
                trace_id=trace_id,
                skill_name=node_def.skill_name or "",
                memory_schema=memory_schema,
                mcp_intent=mcp_intent,
                all_round_data=all_round_data,
                inner_suggestion=state_context.get("_step_retry_context", ""),
            )

            logger.info(
                f"[TraceID:{trace_id}] 工具记忆变量提取完成: "
                f"tool={node_def.tool_name}, "
                f"variables={list(skill_memory_context.keys()) if skill_memory_context else []}"
            )

            return skill_memory_context

        except Exception as e:
            logger.warning(
                f"[TraceID:{trace_id}] 工具记忆变量提取失败: "
                f"tool={node_def.tool_name}, error={e}"
            )
            return None

    async def _load_tool_specific_prompt(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
        resource_context: str,
        skill_memory_context: dict[str, Any] | None,
    ) -> str:
        """加载工具专属 Prompt。

        做什么：仿照 MCPSkillExecutionAgent 的 Prompt 装配方式：
        1. 从 skill 定义的 execution 阶段 content_path 加载工具专属 Prompt 文件
        2. 渲染 mcp_skill_execution 的 memory 槽位作为 system_context
        3. 将 system_context + skill_memory_context 注入到工具专属 Prompt
        """
        if not self.prompt_manager or not node_def.skill_name:
            return ""

        try:
            from app.mcp.skill_registry import SkillRegistry

            registry = SkillRegistry()
            detail = None
            tool_id = ""

            # 查找 Skill 详情
            for sid, det in registry._skills.items():
                if det.name == node_def.skill_name:
                    detail = det
                    for t in det.tools:
                        if t.get("name") == node_def.tool_name:
                            tool_id = t.get("tool_id", "")
                            break
                    break

            if not detail:
                return ""

            # 从 skill 定义的 prompts 中获取 execution 阶段的 Prompt 定义
            exec_prompts_by_tool = detail.prompts.get("execution", {})
            if not isinstance(exec_prompts_by_tool, dict):
                exec_prompts_by_tool = {}

            # 优先查找工具专属 prompt
            exec_prompt_def = exec_prompts_by_tool.get(tool_id, {})
            # 如果没找到工具专属的，降级到 skill 级通用 prompt
            if not exec_prompt_def:
                exec_prompt_def = exec_prompts_by_tool.get("", {})
            content_path = (
                exec_prompt_def.get("content_path", "")
                if isinstance(exec_prompt_def, dict)
                else ""
            )

            if not content_path:
                return ""

            # 加载工具专属 Prompt 文件
            base_dir = os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            )
            full_path = os.path.join(base_dir, content_path)
            if not os.path.exists(full_path):
                logger.warning(
                    f"[TraceID:{trace_id}] 工具专属 Prompt 文件不存在: {full_path}"
                )
                return ""

            with open(full_path, encoding="utf-8") as f:
                tool_template = f.read()

            # 渲染 mcp_skill_execution 的 memory 槽位作为 system_context
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

            # 收集前序节点结果
            partitioned_outputs = state_context.get("partitioned_outputs", {})
            previous_results = []
            for dep_id in node_def.depends_on:
                dep_output = partitioned_outputs.get(dep_id, {})
                previous_results.append({
                    "node_id": dep_id,
                    "success": dep_output.get("success", True),
                    "output_text": (
                        dep_output.get("tool_output", "")
                        or dep_output.get("resource_content", "")
                        or dep_output.get("transformed_data", "")
                        or ""
                    ),
                    "error_message": dep_output.get("error_message", ""),
                })

            # 使用 render_prompt 仅获取 memory 槽位
            try:
                prompt_payload = await self.prompt_manager.render_prompt(
                    PromptCategory.MCP_SKILL_EXECUTION,
                    {
                        "CURRENT_TIME": current_time,
                        "STEP_TOOL": node_def.tool_name or "",
                        "STEP_GOAL": node_def.parameter_hint,
                        "REQUIRED_RESOURCES": json.dumps(
                            [node_def.resource_name] if node_def.resource_name else [],
                            ensure_ascii=False,
                        ),
                        "DEPENDS_ON_TOOLS": json.dumps(
                            [d for d in node_def.depends_on],
                            ensure_ascii=False,
                        ),
                        "RESOURCE_CONTEXT": {"resource": resource_context} if resource_context else {},
                        "PREVIOUS_TOOL_RESULTS": previous_results,
                        "MCP_INTENT": node_def.parameter_hint,
                    },
                )
                system_context_str = prompt_payload.memory
            except Exception:
                # 降级：使用 assemble_prompt
                system_context_str = await self.prompt_manager.assemble_prompt(
                    PromptCategory.MCP_SKILL_EXECUTION,
                    {
                        "CURRENT_TIME": current_time,
                        "STEP_TOOL": node_def.tool_name or "",
                        "STEP_GOAL": node_def.parameter_hint,
                        "REQUIRED_RESOURCES": json.dumps(
                            [node_def.resource_name] if node_def.resource_name else [],
                            ensure_ascii=False,
                        ),
                        "DEPENDS_ON_TOOLS": json.dumps(
                            [d for d in node_def.depends_on],
                            ensure_ascii=False,
                        ),
                        "RESOURCE_CONTEXT": {"resource": resource_context} if resource_context else {},
                        "PREVIOUS_TOOL_RESULTS": previous_results,
                        "MCP_INTENT": node_def.parameter_hint,
                    },
                )

            # 合并变量注入到工具专属 Prompt
            merged_context: dict[str, Any] = {
                "system_context": system_context_str,
                "user_input": node_def.parameter_hint,
            }
            if skill_memory_context is not None:
                merged_context.update(skill_memory_context)

            full_prompt = render_template(tool_template, merged_context)

            logger.info(
                f"[TraceID:{trace_id}] 工具专属 Prompt 加载成功: "
                f"tool={node_def.tool_name}, content_path={content_path}"
            )

            return full_prompt

        except Exception as e:
            logger.warning(
                f"[TraceID:{trace_id}] 工具专属 Prompt 加载失败: "
                f"tool={node_def.tool_name}, error={e}"
            )
            return ""

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
        tool_specific_prompt: str = "",
    ) -> tuple[dict[str, Any], str]:
        """提取工具参数并做 Schema 校验。

        做什么：
        1. 如果有工具专属 Prompt，使用它作为完整 Prompt 直接调用 LLM
        2. 如果没有，使用通用 dag_tool_parameter_extraction Prompt
        3. 解析 LLM 输出并做机械层 Schema 校验

        返回:
            (tool_parameters, error_message)
        """
        try:
            # 获取工具 Schema
            tool_schema = await self._get_tool_schema(node_def.tool_name)

            if tool_specific_prompt:
                # 使用工具专属 Prompt（已包含 system_context）
                full_prompt = tool_specific_prompt

                # 附加 Schema 约束和重试信息
                schema_prompt = (
                    f"\n\n## 工具参数 Schema\n"
                    f"{json.dumps(tool_schema, ensure_ascii=False, indent=2)}\n\n"
                    "请输出 JSON：\n"
                    '{"parameters": {参数名: 参数值}}\n'
                    "参数必须严格遵循上述 Schema 的类型定义。"
                )
                if retry_context:
                    schema_prompt += f"\n\n## 重试修正指令\n{retry_context}"

                full_prompt += schema_prompt

                # 调用 LLM
                response_text = await self.llm_client.invoke(
                    trace_id=trace_id,
                    prompt=full_prompt,
                )
            else:
                # 使用通用 Prompt
                prompt_text = await self.prompt_manager.render(
                    category=PromptCategory.DAG_TOOL_PARAMETER_EXTRACTION,
                    variables={
                        "STEP_TOOL": node_def.tool_name or "",
                        "STEP_GOAL": node_def.parameter_hint,
                        "PARAMETER_HINT": node_def.parameter_hint,
                        "tool_schema": json.dumps(tool_schema, ensure_ascii=False),
                        "tool_name": node_def.tool_name or "",
                        "parameter_hint": node_def.parameter_hint,
                        "resource_context": resource_context,
                        "STATE_CONTEXT": json.dumps(
                            state_context.get("current_step_context", {}),
                            ensure_ascii=False,
                        ),
                        "state_context": json.dumps(
                            state_context.get("current_step_context", {}),
                            ensure_ascii=False,
                        ),
                        "retry_context": retry_context,
                        "RESOURCE_CONTEXT": resource_context,
                        "PREVIOUS_NODE_RESULTS": self._collect_previous_results(
                            node_def, state_context
                        ),
                        "CURRENT_TIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S %A"),
                    },
                )

                response_text = await self.llm_client.invoke_structured(
                    trace_id=trace_id,
                    prompt=prompt_text,
                    schema=self._build_param_schema(tool_schema),
                )

            # 解析参数
            params = self._parse_params(response_text)

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

    def _collect_previous_results(
        self,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """收集前序节点的执行结果。"""
        partitioned_outputs = state_context.get("partitioned_outputs", {})
        results = []
        for dep_id in node_def.depends_on:
            dep_output = partitioned_outputs.get(dep_id, {})
            results.append({
                "node_id": dep_id,
                "success": dep_output.get("success", True),
                "output_text": (
                    dep_output.get("tool_output", "")
                    or dep_output.get("resource_content", "")
                    or dep_output.get("transformed_data", "")
                    or ""
                ),
                "output": (
                    dep_output.get("tool_output", "")
                    or dep_output.get("resource_content", "")
                    or dep_output.get("transformed_data", "")
                    or ""
                ),
                "error_message": dep_output.get("error_message", ""),
            })
        return results

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
            # 清理可能的 markdown 代码块
            cleaned = llm_response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
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
