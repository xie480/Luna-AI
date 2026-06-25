"""Phase 8.5 + Agent Loop Chat Workflow 节点注册表。

做什么：注册所有 LangGraph 节点，包括日常聊天、闲聊、
        原 Plan + Cursor 智能规划和新 Agent Loop 智能规划四种模式的节点。
为什么这样做：集中管理节点创建和依赖注入，避免散落在各处。
"""

from __future__ import annotations

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
        self.nodes = {
            # --- Phase 12（v3.0）新增：MCP Skill 相关节点 ---
            ChatWorkflowGraphNodeName.MCP_SKILL_EXECUTION.value: MCPSkillExecutionNode(dependencies),
            ChatWorkflowGraphNodeName.MCP_SKILL_BYPASS.value: self.router.bypass_mcp_skill,
            # -------------------------------------------------
            # --- Phase 12（v3.0）新增：MCP 前置判断相关节点 ---
            ChatWorkflowGraphNodeName.MCP_INTENT_JUDGE.value: MCPIntentJudgeNode(dependencies),
            ChatWorkflowGraphNodeName.MCP_INTENT_BYPASS.value: self.router.bypass_mcp_intent,
            # -------------------------------------------------
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION.value: InputReconstructionNode(dependencies),
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value: SessionContextLoadNode(dependencies),
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value: LongTermMemoryNode(dependencies),
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value: self.router.bypass_long_term_memory,
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value: UserProfileInjectionNode(dependencies),
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value: KnowledgeRagNode(dependencies),
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value: self.router.bypass_knowledge_rag,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value: ContextGovernanceNode(dependencies),
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value: PromptAssemblyNode(dependencies),
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value: MainChatLlmNode(dependencies),
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value: ResponsePersistenceNode(dependencies),
            ChatWorkflowGraphNodeName.FINALIZE.value: FinalizeNode(dependencies),
            # --- Phase 9 新增：原 Plan + Cursor DAG 引擎节点 ---
            ChatWorkflowGraphNodeName.DAG_ENGINE.value: self._build_dag_engine_node(dependencies),
            # --- Agent Loop 新增：Agent Loop DAG 引擎节点 ---
            ChatWorkflowGraphNodeName.DAG_ENGINE_AGENT_LOOP.value: self._build_agent_loop_engine_node(dependencies),
            # --- Phase 9 新增：简化输入重构节点 ---
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION_SIMPLIFIED.value: self._build_simplified_input_reconstruction_node(dependencies),
        }

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
        observe = ObserveNode()
        step_evaluate = AgentStepEvaluateNode(
            prompt_manager=dependencies.prompt_manager,
            llm_client=_llm_client,
            chat_status_publisher=dependencies.chat_status_publisher,
            event_publisher=dependencies.event_publisher,
        )
        step_repair = StepRepairNode(
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

        # 构建 Agent Loop 子图
        subgraph = build_agent_loop_subgraph(
            goal_lock=goal_lock,
            global_planner=global_planner,
            step_think=step_think,
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
        return self.nodes[name.value]
