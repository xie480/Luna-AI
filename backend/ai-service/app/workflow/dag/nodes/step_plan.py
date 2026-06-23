"""Phase 9 DAG 引擎 — Step Plan 生成节点。

做什么：根据 State 的 goal、筛选后的 Skill 列表，
        生成该 State 内部的 Step 执行计划。
Prompt：使用 dag_step_plan_generation 三槽位 Prompt。
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
from app.utils.snowflake import generate_string_id
from app.workflow.dag.types import (
    AtomicNodeDefinition,
    DagNodeType,
    StepDefinition,
)


class StepPlanNode:
    """State Step Plan 生成节点。

    做什么：根据 State 的 goal、筛选后的 Skill 列表，
            生成该 State 内部的 Step 执行计划。
    每个 Step 包含一组可以并行执行的原子节点。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 Step Plan 生成节点。"""
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def execute(
        self,
        trace_id: str,
        session_id: str,
        state_goal: str,
        state_intent: str,
        selected_skills: list[dict[str, Any]],
        state_context: dict[str, Any],
    ) -> list[StepDefinition]:
        """生成 Step 执行计划。

        做什么：调用 LLM 生成 State 内部的 Step 序列。
        返回:
            list[StepDefinition]: Step 定义列表。
        """
        # 发布 RUNNING 状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_STEP_PLAN_GENERATION,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_STEP_PLAN_GENERATION, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        try:
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

            # 构建包含 tool/resource 详情的 skill 信息
            skill_details = self._build_skill_details(selected_skills, state_context)

            # 构建可序列化的 state_context 快照
            # 为什么这样做：state_context 中包含 MCPToolRegistry、MemoryManager 等
            # 不可 JSON 序列化的对象，必须过滤掉只保留基础数据字段
            serializable_context = {
                k: v for k, v in state_context.items()
                if k not in ("skill_registry", "memory_manager", "rag_orchestrator")
            }

            # 渲染 Step Plan 生成 Prompt
            # 注意：available_node_types 变量已移除，节点类型说明已内化到 system.j2 的静态提示词中
            prompt_text = await self.prompt_manager.render(
                category=PromptCategory.DAG_STEP_PLAN_GENERATION,
                variables={
                    "state_goal": state_goal,
                    "state_intent": state_intent,
                    "selected_skills": skill_details,
                    "state_context": json.dumps(
                        serializable_context, ensure_ascii=False
                    ),
                    "CURRENT_TIME": current_time,
                },
            )

            logger.info(
                f"[TraceID:{trace_id}] Step Plan 开始请求: "
                f"prompt_text={prompt_text}"
            )

            # 调用 LLM 生成 Step Plan
            llm_response = await self.llm_client.invoke_structured(
                trace_id=trace_id,
                prompt=prompt_text,
                schema=self._build_step_plan_schema(),
            )

            # 解析并构建 StepDefinition 列表
            step_plan_data = self._parse_step_plan_response(llm_response)
            steps = self._build_step_definitions(step_plan_data)

            logger.info(
                f"[TraceID:{trace_id}] Step Plan 生成完成: "
                f"steps={len(steps)}, "
                f"total_nodes={sum(len(s.nodes) for s in steps)}"
                f"llm_response={llm_response}"
            )

            # 发布 SUCCEEDED 状态
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_STEP_PLAN_GENERATION,
                state=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_STEP_PLAN_GENERATION,
                    ChatStatusState.COMPLETED,
                ),
                is_visible=True,
                is_terminal=True,
            )

            return steps

        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] Step Plan 生成失败: {e}")
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_STEP_PLAN_GENERATION,
                state=ChatStatusState.ERROR,
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_STEP_PLAN_GENERATION,
                    ChatStatusState.ERROR,
                ),
                is_visible=True,
                is_terminal=True,
            )
            raise

    def _build_step_plan_schema(self) -> dict[str, Any]:
        """构建 Step Plan 生成的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "nodes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "node_type": {
                                            "type": "string",
                                            "enum": [t.value for t in DagNodeType],
                                        },
                                        "skill_name": {"type": "string"},
                                        "tool_name": {"type": "string"},
                                        "resource_name": {"type": "string"},
                                        "parameter_hint": {"type": "string"},
                                        "transform_instruction": {"type": "string"},
                                        "query_text": {"type": "string"},
                                        "depends_on": {
                                            "type": "array",
                                            "items": {"type": "integer"},
                                        },
                                        "gating_required": {"type": "boolean"},
                                    },
                                    "required": ["node_type"],
                                },
                            },
                        },
                        "required": ["description", "nodes"],
                    },
                },
            },
            "required": ["steps"],
        }

    def _parse_step_plan_response(
        self, llm_response: str | dict
    ) -> dict[str, Any]:
        """解析 Step Plan 的 LLM 输出。"""
        try:
            if isinstance(llm_response, dict):
                return llm_response
            return json.loads(llm_response)
        except json.JSONDecodeError as e:
            logger.error(f"Step Plan LLM 输出 JSON 解析失败: {e}")
            import re
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"steps": []}

    def _build_skill_details(
        self,
        selected_skills: list[dict[str, Any]],
        state_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """构建包含 tool/resource 详情的技能信息。

        做什么：从 MCPToolRegistry 和 SkillRegistry 中获取
               已筛选技能的工具列表和资源列表详情。
        为什么这样做：Step Plan 生成需要知道每个技能具体有哪些工具和资源可用。
        """
        from app.mcp.skill_registry import SkillRegistry

        skill_registry = SkillRegistry()
        details = []

        for skill_brief in selected_skills:
            skill_name = skill_brief.get("skill_name", "")
            detail_info = {
                "skill_name": skill_name,
                "description": skill_brief.get("description", skill_brief.get("relevance_reason", "")),
                "tools": [],
                "resources": [],
            }

            # 从 SkillRegistry 获取技能详情
            try:
                for sid, det in skill_registry._skills.items():
                    if det.name == skill_name:
                        # 填充工具列表
                        for tool in det.tools:
                            detail_info["tools"].append({
                                "name": tool.get("name", ""),
                                "description": tool.get("description", ""),
                                "risk_level": tool.get("risk_level", "L0"),
                            })
                        # 填充资源列表
                        for res in det.resources:
                            detail_info["resources"].append({
                                "name": res.get("name", ""),
                                "resource_type": res.get("resource_type", "file"),
                            })
                        break
            except Exception as e:
                logger.warning(f"获取技能详情失败: skill={skill_name}, error={e}")

            details.append(detail_info)

        return details

    def _build_step_definitions(
        self, step_plan_data: dict[str, Any]
    ) -> list[StepDefinition]:
        """从 LLM 输出构建 StepDefinition 列表。"""
        steps = []
        for step_index, step_data in enumerate(step_plan_data.get("steps", [])):
            nodes = []
            node_ids = []

            # 第一遍：生成 node_id
            for _ in step_data.get("nodes", []):
                node_ids.append(generate_string_id())

            # 第二遍：构建节点并处理 depends_on
            for node_index, node_data in enumerate(step_data.get("nodes", [])):
                # 处理 depends_on：将相对索引转换为 node_id
                depends_on = []
                for dep_index in node_data.get("depends_on", []):
                    if isinstance(dep_index, int) and 0 <= dep_index < len(node_ids):
                        depends_on.append(node_ids[dep_index])

                node_type_str = node_data.get("node_type", "tool_execute")
                try:
                    node_type = DagNodeType(node_type_str)
                except ValueError:
                    node_type = DagNodeType.TOOL_EXECUTE

                # 防御性字符串转换：LLM 输出有时会将 string 字段返回为 list，
                # 如 query_text: ["2026年世界杯热点...", "世界杯最新动态"]
                # 必须转换为字符串，否则 Pydantic 校验失败
                def _safe_str(value: Any) -> str:
                    if isinstance(value, str):
                        return value
                    if isinstance(value, list):
                        return "；".join(str(v) for v in value)
                    if value is None:
                        return ""
                    return str(value)

                node = AtomicNodeDefinition(
                    node_id=node_ids[node_index],
                    node_type=node_type,
                    skill_name=_safe_str(node_data.get("skill_name")),
                    tool_name=_safe_str(node_data.get("tool_name")),
                    resource_name=_safe_str(node_data.get("resource_name")),
                    parameter_hint=_safe_str(node_data.get("parameter_hint", "")),
                    transform_instruction=_safe_str(node_data.get("transform_instruction", "")),
                    query_text=_safe_str(node_data.get("query_text", "")),
                    depends_on=depends_on,
                    gating_required=node_data.get("gating_required", False),
                )
                nodes.append(node)

            step = StepDefinition(
                step_index=step_index,
                nodes=nodes,
                description=step_data.get("description", ""),
            )
            steps.append(step)

        return steps
