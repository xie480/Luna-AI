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
        }

    def get_node(self, name: ChatWorkflowGraphNodeName):
        return self.nodes[name.value]
