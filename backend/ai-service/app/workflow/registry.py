"""Phase 8.5 Chat Workflow 节点注册表。"""

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
            # --- Phase 9 新增：DAG 引擎节点 ---
            ChatWorkflowGraphNodeName.DAG_ENGINE.value: self._build_dag_engine_node(dependencies),
            # --- Phase 9 新增：简化输入重构节点 ---
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION_SIMPLIFIED.value: self._build_simplified_input_reconstruction_node(dependencies),
        }

    def _build_dag_engine_node(self, dependencies: WorkflowDependencies):
        """构建 DAG 引擎节点。

        做什么：创建 DagEngine 实例并包装为 LangGraph 节点。
        为什么这样做：DAG 引擎需要多个依赖注入，通过工厂方法集中构建。
        """
        from app.workflow.dag.engine import DagEngine
        from app.workflow.nodes.impl.dag_engine_node import DagEngineNode

        dag_engine = DagEngine(
            prompt_manager=dependencies.prompt_manager,
            llm_client=dependencies.prompt_manager.llm_client if dependencies.prompt_manager else None,
            mcp_tool_registry=dependencies.mcp_tool_registry,
            memory_manager=dependencies.memory_manager,
            rag_orchestrator=dependencies.rag_orchestrator,
            chat_status_publisher=dependencies.chat_status_publisher,
        )

        return DagEngineNode(
            dag_engine=dag_engine,
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
