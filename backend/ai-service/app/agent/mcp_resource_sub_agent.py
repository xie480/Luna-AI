"""
MCP 资源加载子 Agent（SubAgent），基于 LLM 语义提取。

做什么：负责加载 Skill 中的资源文件。采用文件读写方式读取完整文件内容，
        对每一行文本追加括号行号标注后，调用 LLM 基于语义理解提取
        与当前阶段需求相关的关键信息。这些信息随后注入到对应 Tool 的
        Prompt 中供主 Agent 使用。不进行截断，保证信息完整性。
为什么这样做：将资源加载从主 Agent 中分离，多个资源可以并行加载，
            提升执行效率。每行追加行号标注使 LLM 输出的行号引用
            精确对应源文件。
边界条件：
    - 只处理 resource_type=file 的资源，其他类型跳过。
    - 文件不存在或读取失败时返回错误信息，不阻塞其他资源加载。
    - LLM 提取失败时降级返回文件结构化摘要，不抛出异常。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from app.logger import logger
from app.mcp.skill_types import ResourceLoadResult
from app.prompt.types import PromptCategory


class MCPResourceSubAgent:
    """MCP 资源加载子 Agent（并行执行，LLM 语义提取）。"""

    async def load_resource(
        self,
        trace_id: str,
        resource_def: dict[str, Any],
        load_purpose: str,
        prompt_manager: Any = None,
    ) -> ResourceLoadResult:
        """加载单个资源文件，使用 LLM 进行语义提取。

        参数:
            trace_id: 全链路追踪 ID。
            resource_def: 资源定义，包含 name、resource_type、uri、description。
            load_purpose: 加载此资源的目的说明。
            prompt_manager: Prompt Manager 实例，用于 LLM 语义提取。
        返回:
            ResourceLoadResult: 资源加载结果。
        """
        started_at = time.monotonic()

        resource_name = resource_def.get("name", "unknown")
        resource_type = resource_def.get("resource_type", "file")
        uri = resource_def.get("uri", "")

        # 非 file 类型的资源不进行文件读取
        if resource_type != "file":
            return ResourceLoadResult(
                resource_name=resource_name,
                success=True,
                extracted_info=f"资源类型为 {resource_type}，不涉及文件读取，"
                              f"资源 URI 为 {uri}，可直接使用",
                line_numbers=[],
                latency_ms=max(0, int((time.monotonic() - started_at) * 1000)),
            )

        # 检查文件是否存在
        if not os.path.exists(uri):
            logger.warning(
                f"MCP 资源加载子 Agent 文件不存在 trace_id={trace_id} "
                f"resource={resource_name} path={uri}"
            )
            return ResourceLoadResult(
                resource_name=resource_name,
                success=False,
                extracted_info="",
                error_message=f"文件不存在: {uri}",
                latency_ms=max(0, int((time.monotonic() - started_at) * 1000)),
            )

        try:
            # 读取完整文件内容（不截断）
            with open(uri, "r", encoding="utf-8") as f:
                content = f.read()

            file_lines = content.split("\n")
            total_lines = len(file_lines)

            # 对每一行追加括号行号标注，例如：[第 1 行]
            annotated_lines = []
            for idx, line in enumerate(file_lines, start=1):
                annotated_lines.append(f"{line}（第 {idx} 行）")
            annotated_content = "\n".join(annotated_lines)

            logger.info(
                f"MCP 资源加载子 Agent 读取文件完成 trace_id={trace_id} "
                f"resource={resource_name} path={uri} "
                f"total_lines={total_lines} total_chars={len(content)}"
            )

            # 使用 LLM 语义提取关键信息
            extracted_text, matched_lines = await self._extract_via_llm(
                trace_id=trace_id,
                annotated_content=annotated_content,
                file_lines=file_lines,
                resource_name=resource_name,
                total_lines=total_lines,
                load_purpose=load_purpose,
                prompt_manager=prompt_manager,
            )

            elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))
            logger.info(
                f"MCP 资源加载子 Agent 完成 trace_id={trace_id} "
                f"resource={resource_name} "
                f"matched_lines={matched_lines} "
                f"extracted_length={len(extracted_text)} "
                f"latency_ms={elapsed_ms}"
            )

            return ResourceLoadResult(
                resource_name=resource_name,
                success=True,
                extracted_info=extracted_text,
                line_numbers=matched_lines,
                latency_ms=elapsed_ms,
            )

        except Exception as exc:
            logger.warning(
                f"MCP 资源加载子 Agent 异常 trace_id={trace_id} "
                f"resource={resource_name} error={exc!s}"
            )
            return ResourceLoadResult(
                resource_name=resource_name,
                success=False,
                extracted_info="",
                error_message=f"文件读取或信息提取失败: {exc!s}",
                latency_ms=max(0, int((time.monotonic() - started_at) * 1000)),
            )

    async def _extract_via_llm(
        self,
        trace_id: str,
        annotated_content: str,
        file_lines: list[str],
        resource_name: str,
        total_lines: int,
        load_purpose: str,
        prompt_manager: Any,
    ) -> tuple[str, list[int]]:
        """使用 LLM 从文件中语义提取与加载目的相关的关键信息。

        做什么：通过 PromptManager 组装三槽位模板，调用 LLM 对文件内容
                进行语义分析，提取与 load_purpose 最相关的代码段、配置段
                或数据段，并标注其在文件中的行号。
        为什么这样做：将 Prompt 文本归入模板系统管理，避免在业务代码中
                    硬编码大段提示词。每行已附带括号行号标注，LLM
                    输出的行号引用与源文件精确对应。
        参数:
            annotated_content: 每行已追加括号行号标注的完整文件内容。
            file_lines: 原始文件行列表，用于行号范围校验。
            total_lines: 文件总行数。
        返回:
            tuple[str, list[int]]: (提取的关键信息文本, 匹配行号列表)。
        """
        from app.llm.client import llm_client

        # 通过 PromptManager 组装三槽位模板
        system_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_RESOURCE_EXTRACTION, {}
        )
        memory_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_RESOURCE_EXTRACTION,
            {
                "LOAD_PURPOSE": load_purpose,
                "RESOURCE_NAME": resource_name,
                "TOTAL_LINES": total_lines,
                "FILE_CONTENT": annotated_content,
            },
        )
        runtime_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_RESOURCE_EXTRACTION,
            {"LOAD_PURPOSE": load_purpose},
        )

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        try:
            response = await llm_client.generate_structured(
                model=prompt_manager.get_model_for_extraction(),
                messages=[{"role": "system", "content": full_prompt}],
                response_format={
                    "type": "json_object",
                    "properties": {
                        "has_relevant_info": {"type": "boolean"},
                        "extractions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "extracted_content": {"type": "string"},
                                    "matched_lines": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                    },
                                    "summary": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                timeout=60.0,
            )

            has_relevant_info = response.get("has_relevant_info", False)
            extractions = response.get("extractions", [])

            if not has_relevant_info or not extractions:
                return "", []

            # 合并所有提取片段的内容和行号
            merged_content_parts: list[str] = []
            merged_lines: list[int] = []
            for ext in extractions:
                content = ext.get("extracted_content", "")
                matched_lines = ext.get("matched_lines", [])
                if content:
                    merged_content_parts.append(content)
                # 校验返回的行号是否在文件范围内
                for ln in matched_lines:
                    if 1 <= ln <= len(file_lines) and ln not in merged_lines:
                        merged_lines.append(ln)

            merged_lines.sort()
            return "\n\n".join(merged_content_parts), merged_lines

        except Exception as exc:
            # LLM 提取失败时，降级为结构化摘要（不抛出异常）
            logger.warning(
                f"MCP 资源加载子 Agent LLM 提取失败 trace_id={trace_id} "
                f"resource={resource_name} error={exc!s}，降级为结构化摘要"
            )

            # 降级方案：首行 + 结构特征摘要
            head_lines = file_lines[:min(30, len(file_lines))]
            file_structure = {
                "file_name": resource_name,
                "total_lines": len(file_lines),
                "total_chars": len(annotated_content),
                "head_preview": head_lines,
                "extraction_note": f"LLM 提取失败，返回文件头 {len(head_lines)} 行作为预览",
            }
            return json.dumps(file_structure, ensure_ascii=False), list(range(1, len(head_lines) + 1))  # noqa: E501

    async def extract_fallback_info(
        self,
        trace_id: str,
        execution_plan: dict[str, Any],
        tool_results: list[dict[str, Any]],
        resource_results: list[ResourceLoadResult],
        prompt_manager: Any = None,
    ) -> dict[str, Any]:
        """提取退回所需的执行快照。

        做什么：当执行计划不足以完成任务时，将原执行计划各步骤与执行结果
                整合为完整快照，供退回后的 Agent 1 分析失败原因。
        参数:
            trace_id: 全链路追踪 ID。
            execution_plan: 原执行计划字典。
            tool_results: 已执行的工具结果列表。
            resource_results: 已加载的资源结果列表。
            prompt_manager: Prompt Manager 实例，用于 LLM 执行快照提取。
        返回:
            dict: 执行快照字典。格式为 {"state1": {"skill": "...", "resource": [...],
                   "tools": [...], "status": "...", "result": "..."}, ...}。
        """
        from app.llm.client import llm_client

        # 构建执行计划渲染文本
        execution_plan_rendered: dict[str, dict[str, Any]] = {}
        states = execution_plan.get("states", {})
        for state_key, state_val in states.items():
            execution_plan_rendered[state_key] = {
                "skill": state_val.get("skill", ""),
                "resource": state_val.get("resource", []),
                "tools": state_val.get("tools", []),
            }

        # 通过 PromptManager 组装三槽位模板
        tool_results_rendered = "\n".join(
            f"[工具 {r.get('tool_name', 'unknown')}]: "
            f"成功={r.get('success')} "
            f"输出={r.get('output_text', '')[:500]}"
            for r in tool_results
        ) if tool_results else "无已执行工具结果"

        resource_results_rendered = "\n".join(
            f"[资源 {rr.resource_name}]: "
            f"成功={rr.success} "
            f"提取={rr.extracted_info[:500] if rr.success else rr.error_message}"
            for rr in (resource_results or [])
        ) if resource_results else "无已加载资源"

        system_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_FALLBACK_EXTRACTION, {}
        )
        memory_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_FALLBACK_EXTRACTION,
            {
                "EXECUTION_PLAN": execution_plan_rendered,
                "TOOL_RESULTS": tool_results_rendered,
                "RESOURCE_RESULTS": resource_results_rendered,
            },
        )
        runtime_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_FALLBACK_EXTRACTION, {}
        )

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        mid_model = self._get_mid_model()
        try:
            fallback_response = await llm_client.generate_structured(
                model=mid_model,
                messages=[{"role": "system", "content": full_prompt}],
                response_format={
                    "type": "json_object",
                    "properties": {},
                },
                timeout=30.0,
            )

            # 确保返回的字典包含所有 state_key
            snapshot: dict[str, dict[str, Any]] = {}
            for state_key in execution_plan_rendered:
                state_data = execution_plan_rendered[state_key]
                llm_state = fallback_response.get(state_key, {})
                snapshot[state_key] = {
                    "skill": state_data["skill"],
                    "resource": state_data["resource"],
                    "tools": state_data["tools"],
                    "status": llm_state.get("status", "未执行"),
                    "result": llm_state.get("result", ""),
                }

            return snapshot

        except Exception as exc:
            # LLM 提取失败时的降级方案
            logger.warning(
                f"MCP 退回快照提取 LLM 调用失败 trace_id={trace_id} error={exc!s}，降级"
            )

            # 降级：直接返回原执行计划加空状态
            snapshot: dict[str, dict[str, Any]] = {}
            for state_key, state_data in execution_plan_rendered.items():
                snapshot[state_key] = {
                    "skill": state_data["skill"],
                    "resource": state_data["resource"],
                    "tools": state_data["tools"],
                    "status": "未执行（LLM 提取失败）",
                    "result": "",
                }

            # 尝试匹配工具执行结果
            for state_key, state_data in execution_plan_rendered.items():
                matched_tool_results = [
                    r for r in tool_results
                    if r.get("tool_name") in state_data.get("tools", [])
                ]
                matched_resource_results = [
                    rr for rr in (resource_results or [])
                    if rr.resource_name in state_data.get("resource", [])
                ]

                status_parts: list[str] = []
                result_parts: list[str] = []

                if matched_resource_results:
                    for rr in matched_resource_results:
                        if rr.success:
                            status_parts.append(f"资源{rr.resource_name}已加载")
                            result_parts.append(f"[资源{rr.resource_name}]: {rr.extracted_info[:200]}")
                        else:
                            status_parts.append(f"资源{rr.resource_name}加载失败")
                            result_parts.append(f"[资源{rr.resource_name}]: {rr.error_message}")

                if matched_tool_results:
                    for r in matched_tool_results:
                        if r.get("success"):
                            status_parts.append(f"工具{r['tool_name']}已执行")
                            result_parts.append(f"[工具{r['tool_name']}]: {r.get('output_text', '')[:200]}")
                        else:
                            status_parts.append(f"工具{r['tool_name']}执行失败")
                            result_parts.append(f"[工具{r['tool_name']}]: {r.get('error_message', '')}")

                if status_parts:
                    snapshot[state_key]["status"] = "，".join(status_parts)
                    snapshot[state_key]["result"] = "\n".join(result_parts)

            return snapshot

    def _get_mid_model(self) -> str:
        """获取中模型名称。"""
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")
