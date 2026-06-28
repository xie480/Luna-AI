"""Phase 8.5 + Agent Loop Chat Workflow 节点注册表。

做什么：注册所有 LangGraph 节点，包括日常聊天、闲聊、
        原 Plan + Cursor 智能规划和新 Agent Loop 智能规划四种模式的节点。
为什么这样做：集中管理节点创建和依赖注入，避免散落在各处。
"""

from __future__ import annotations

from app.logger import logger
from app.workflow.constants import ChatWorkflowGraphNodeName
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.impl.context_governance_node import ContextGovernanceNode
from app.workflow.nodes.impl.finalize_node import FinalizeNode
from app.workflow.nodes.impl.input_reconstruction_node import InputReconstructionNode
from app.workflow.nodes.impl.knowledge_rag_node import KnowledgeRagNode
from app.workflow.nodes.impl.long_term_memory_node import LongTermMemoryNode
from app.workflow.nodes.impl.main_chat_llm_node import MainChatLlmNode
from app.workflow.nodes.impl.prompt_assembly_node import PromptAssemblyNode
from app.workflow.nodes.impl.response_persistence_node import ResponsePersistenceNode
from app.workflow.nodes.impl.session_context_load_node import SessionContextLoadNode
from app.workflow.nodes.impl.user_profile_injection_node import UserProfileInjectionNode
# --- Phase 12（v3.0）新增：MCP Skill 工作流节点导入 ---
from app.workflow.nodes.impl.mcp_skill_execution_node import MCPSkillExecutionNode
# --- Phase 12（v3.0）新增：MCP 前置判断节点导入 ---
from app.workflow.nodes.impl.mcp_intent_judge_node import MCPIntentJudgeNode
from app.workflow.routers import ChatWorkflowRouter


class ChatWorkflowNodeRegistry:
    """Chat Workflow 节点注册表。"""

    def __init__(self, dependencies: WorkflowDependencies):
        self.router = ChatWorkflowRouter(
            event_publisher=dependencies.event_publisher,
            chat_status_publisher=dependencies.chat_status_publisher,
        )
        # 做什么：独立注册每个节点，单个节点构建失败不影响其他节点。
        # 为什么这样做：之前所有节点在一个 dict 字面量中构建，任何一个节点的
        #              _build_*_node 方法抛出异常（如 import 错误、依赖缺失），
        #              都会导致整个 self.nodes 字典创建失败，进而导致所有四种
        #              聊天模式图都无法构建，最终 chat_workflow_service = None，前端收到 503。
        #              改为逐个构建，失败的节点记录错误日志并跳过，
        #              图构建时通过 get_node 方法检查节点是否存在。
        self.nodes: dict[str, object] = {}

        # --- Phase 12（v3.0）：MCP Skill 相关节点 ---
        self._safe_register_node(
            ChatWorkflowGraphNodeName.MCP_SKILL_EXECUTION.value,
            lambda: MCPSkillExecutionNode(dependencies),
        )
        self.nodes[ChatWorkflowGraphNodeName.MCP_SKILL_BYPASS.value] = self.router.bypass_mcp_skill
        self._safe_register_node(
            ChatWorkflowGraphNodeName.MCP_INTENT_JUDGE.value,
            lambda: MCPIntentJudgeNode(dependencies),
        )
        self.nodes[ChatWorkflowGraphNodeName.MCP_INTENT_BYPASS.value] = self.router.bypass_mcp_intent

        # --- 日常聊天 / 闲聊核心节点 ---
        self._safe_register_node(
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION.value,
            lambda: InputReconstructionNode(dependencies),
        )
        self.nodes[ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value] = SessionContextLoadNode(dependencies)
        self.nodes[ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value] = LongTermMemoryNode(dependencies)
        self.nodes[ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value] = self.router.bypass_long_term_memory
        self.nodes[ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value] = UserProfileInjectionNode(dependencies)
        self._safe_register_node(
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value,
            lambda: KnowledgeRagNode(dependencies),
        )
        self.nodes[ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value] = self.router.bypass_knowledge_rag
        self.nodes[ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value] = ContextGovernanceNode(dependencies)
        self.nodes[ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value] = PromptAssemblyNode(dependencies)
        self.nodes[ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value] = MainChatLlmNode(dependencies)
        self.nodes[ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value] = ResponsePersistenceNode(dependencies)
        self.nodes[ChatWorkflowGraphNodeName.FINALIZE.value] = FinalizeNode(dependencies)

        # --- Phase 9：原 Plan + Cursor DAG 引擎节点 ---
        self._safe_register_node(
            ChatWorkflowGraphNodeName.DAG_ENGINE.value,
            lambda: self._build_dag_engine_node(dependencies),
        )
        # --- Agent Loop：Agent Loop DAG 引擎节点 ---
        self._safe_register_node(
            ChatWorkflowGraphNodeName.DAG_ENGINE_AGENT_LOOP.value,
            lambda: self._build_agent_loop_engine_node(dependencies),
        )
        # --- Phase 9：简化输入重构节点 ---
        self._safe_register_node(
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION_SIMPLIFIED.value,
            lambda: self._build_simplified_input_reconstruction_node(dependencies),
        )

    def _safe_register_node(self, name: str, builder) -> None:
        """安全注册单个节点，捕获构建异常并记录日志。

        做什么：调用节点构建函数，成功则注册到 self.nodes，失败则记录错误日志并跳过。
        输入：name - 节点名称；builder - 构建函数（lambda 或 callable）。
        为什么这样做：防止某个复杂节点（如 agent_loop_engine）的构建失败导致
                     整个节点注册表崩溃，进而导致所有聊天模式不可用。
        """
        try:
            self.nodes[name] = builder()
        except Exception as e:
            logger.error(
                f"[NodeRegistry] 节点构建失败，已跳过 name={name} error={e}",
                exc_info=True,
            )

    def _build_dag_engine_node(self, dependencies: WorkflowDependencies):
        """构建 DAG 引擎节点（原 Plan + Cursor 子图版本）。

        做什么：创建 Plan + Cursor 子图并包装为 LangGraph 外层节点。
        为什么这样做：Phase 9 将 DagEngine 单体引擎拆分为 4 个独立 LangGraph 节点，
                      子图通过 build_plan_cursor_subgraph() 工厂函数构建。
                      保留此方法以维持 plan_state_node 模式的完整功能。
        """
        from app.llm.client import llm_client as _llm_client
        from app.workflow.dag.engine import build_plan_cursor_subgraph
        from app.workflow.dag.evaluation import StateResultCompressor
        from app.workflow.dag.nodes.plan_generation import PlanGenerationNode
        from app.workflow.dag.nodes.plan_replan import PlanReplanNode
        from app.workflow.dag.nodes.plan_summary import PlanResultSummaryNode
        from app.workflow.dag.nodes.skill_screening import SkillScreeningNode
        from app.workflow.dag.nodes.state_evaluation import StateEvaluationNode
        from app.workflow.dag.nodes.step_executor import StepExecutor, StepRetryPolicy
        from app.workflow.dag.nodes.step_merge import StepMergeNode
        from app.workflow.dag.nodes.step_plan import StepPlanNode
        from app.workflow.nodes.impl.dag_engine_node import DagEngineNode

        # 创建子节点实例
        plan_generation = PlanGenerationNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
        )
        skill_screening = SkillScreeningNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
        )
        step_plan = StepPlanNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
        )
        step_executor = StepExecutor(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            mcp_tool_registry=dependencies.mcp_tool_registry,
            chat_status_publisher=dependencies.chat_status_publisher,
        )
        step_retry = StepRetryPolicy(step_executor)
        step_merge = StepMergeNode(
            chat_status_publisher=dependencies.chat_status_publisher,
        )
        state_evaluation = StateEvaluationNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
        )
        state_compressor = StateResultCompressor(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
        )
        plan_replan = PlanReplanNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
        )
        plan_summary = PlanResultSummaryNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
        )

        # 构建 Plan + Cursor 子图
        subgraph = build_plan_cursor_subgraph(
            plan_generation=plan_generation,
            skill_screening=skill_screening,
            step_plan=step_plan,
            step_executor=step_executor,
            step_retry=step_retry,
            step_merge=step_merge,
            state_evaluation=state_evaluation,
            state_compressor=state_compressor,
            plan_replan=plan_replan,
            plan_summary=plan_summary,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
            memory_manager=dependencies.memory_manager,
            rag_orchestrator=dependencies.rag_orchestrator,
            mcp_tool_registry=dependencies.mcp_tool_registry,
            gating_service=dependencies.gating_service,
            snapshot_manager=dependencies.snapshot_manager,
        )

        return DagEngineNode(
            plan_cursor_subgraph=subgraph,
            event_publisher=dependencies.event_publisher,
            chat_status_publisher=dependencies.chat_status_publisher,
        )

    def _build_agent_loop_engine_node(self, dependencies: WorkflowDependencies):
        """构建 Agent Loop DAG 引擎节点。

        做什么：创建 Agent Loop 子图并包装为 LangGraph 外层节点。
        为什么这样做：agent-loop-langgraph-design.md 将原 Plan + Cursor 双层子图
                      重构为 Goal-Stable / Plan-Mutable 的 6 层 Agent Loop 架构。
                      作为独立的第四种模式（agent_loop）与原 plan_state_node 并存。
        改动：新增 ResourceTierService 和 ResourceLoadNode，实现资源预加载。
        """
        from app.llm.client import llm_client as _llm_client
        from app.workflow.dag.agent_loop_engine import (
            AgentFinalVerifyNode,
            AgentReplanNode,
            AgentStepEvaluateNode,
            AgentToolExecuteNode,
            GlobalPlannerNode,
            GoalLockNode,
            ObserveNode,
            StepRepairNode,
            StepThinkNode,
            build_agent_loop_subgraph,
        )
        from app.workflow.nodes.impl.dag_engine_node import DagEngineNode

        # 创建 Agent Loop 各节点实例
        goal_lock = GoalLockNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )
        global_planner = GlobalPlannerNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )
        step_think = StepThinkNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
            mcp_tool_registry=dependencies.mcp_tool_registry,
        )

        # 创建 ResourceTierService 和 ResourceLoadNode
        # 为什么这样做：在 step_think 和 tool_execute 之间插入资源加载环节，
        #               根据资源大小自动选择 Tier 1/2/3 策略。
        # 降级：Qdrant 客户端和 Embedding 服务通过 app.state 获取，
        #       不可用时 ResourceTierService 自动降级为 Tier 1 全量加载。
        from app.mcp.resource_tier_service import ResourceTierService
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        # 尝试获取 Qdrant 客户端和 Embedding 服务（延迟注入，启动时可能不可用）
        _qdrant_client = None
        _embedding_service = None
        try:
            from app.main import app as _fastapi_app
            _qdrant_client = getattr(_fastapi_app.state, "qdrant_client", None)
            _embedding_service = getattr(_fastapi_app.state, "embedding_service", None)
        except Exception:
            # FastAPI app 未初始化时（如测试环境），跳过
            pass

        resource_tier_service = ResourceTierService(
            qdrant_client=_qdrant_client,
            embedding_service=_embedding_service,
            skill_registry=dependencies.mcp_tool_registry,
        )
        resource_load = ResourceLoadNode(
            resource_tier_service=resource_tier_service,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )

        tool_execute = AgentToolExecuteNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            mcp_tool_registry=dependencies.mcp_tool_registry,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
            gating_service=dependencies.gating_service,
            snapshot_manager=dependencies.snapshot_manager,
        )
        observe = ObserveNode(
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )
        step_evaluate = AgentStepEvaluateNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )
        step_repair = StepRepairNode(
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )
        replan = AgentReplanNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )
        final_verify = AgentFinalVerifyNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )

        # 构建 Agent Loop 子图（传递 resource_load 节点）
        subgraph = build_agent_loop_subgraph(
            goal_lock=goal_lock,
            global_planner=global_planner,
            step_think=step_think,
            resource_load=resource_load,
            tool_execute=tool_execute,
            observe=observe,
            step_evaluate=step_evaluate,
            step_repair=step_repair,
            replan=replan,
            final_verify=final_verify,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )

        return DagEngineNode(
            agent_loop_subgraph=subgraph,
            event_publisher=dependencies.event_publisher,
            chat_status_publisher=dependencies.chat_status_publisher,
        )

    def _build_simplified_input_reconstruction_node(self, dependencies: WorkflowDependencies):
        """构建简化输入重构节点。

        做什么：创建 SimplifiedInputReconstructionNode 的 LangGraph 适配节点。
        为什么这样做：Phase 9 路径使用简化版输入重构，只做代词消歧不做路由决策。
        """
        from app.workflow.dag.nodes.input_reconstruction_simplified import (
            SimplifiedInputReconstructionNode,
        )
        from app.workflow.nodes.impl.simplified_input_reconstruction_impl import (
            SimplifiedInputReconstructionImpl,
        )

        return SimplifiedInputReconstructionImpl(dependencies)

    def get_node(self, name: ChatWorkflowGraphNodeName):
        """获取已注册的节点。

        输入：name - 节点名称枚举。
        输出：节点实例。
        异常行为：节点不存在时抛出 KeyError 并给出明确提示。
        """
        node_key = name.value
        if node_key not in self.nodes:
            raise KeyError(
                f"节点 '{node_key}' 未注册（可能因构建失败被跳过），"
                f"请检查启动日志中的 [NodeRegistry] 错误信息"
            )
        return self.nodes[node_key]
