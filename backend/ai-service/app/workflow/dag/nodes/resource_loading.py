"""Phase 9 DAG 引擎 — 资源加载节点。

做什么：加载 Skill 定义的资源文件（如政策文档、模板文件），
        将资源内容注入到下游节点的上下文中。
为什么独立为节点：资源加载是耗时 IO 操作，独立为节点后可以与其他
                 无依赖节点并行执行，提升整体效率。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.workflow.dag.types import AtomicNodeDefinition


class ResourceLoadingNode:
    """资源加载节点。

    做什么：加载 Skill 定义的资源文件，将资源内容注入到下游上下文。
    """

    async def execute(
        self,
        trace_id: str,
        node_def: AtomicNodeDefinition,
        state_context: dict[str, Any],
    ) -> dict[str, Any]:
        """加载 Skill 资源文件。

        做什么：根据节点定义中的 skill_name 和 resource_name 加载资源。
        返回:
            dict: 包含 success、resource_content 的执行结果。
        """
        try:
            skill_registry = state_context.get("skill_registry")
            if not skill_registry:
                raise ValueError("skill_registry 未注入到 state_context 中")

            resource_content = await skill_registry.load_resource(
                node_def.skill_name, node_def.resource_name
            )

            logger.info(
                f"[TraceID:{trace_id}] 资源加载成功: "
                f"skill={node_def.skill_name}, "
                f"resource={node_def.resource_name}, "
                f"content={resource_content}"
            )

            return {
                "success": True,
                "resource_content": resource_content,
                "error_message": "",
            }

        except Exception as e:
            logger.error(
                f"[TraceID:{trace_id}] 资源加载失败: "
                f"skill={node_def.skill_name}, "
                f"resource={node_def.resource_name}, "
                f"error={e}"
            )
            return {
                "success": False,
                "resource_content": "",
                "error_message": str(e),
            }
