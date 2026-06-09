"""
Phase 8.5 Chat Workflow 节点注册表。

做什么：集中创建 daily_chat.default.v1 图需要的节点适配器与路由器。
为什么这样做：为 Phase 9 Node Registry 迁移提供稳定入口，并避免 graph_factory 直接散落构造逻辑。
"""

from __future__ import annotations

from app.workflow.constants import ChatWorkflowGraphNodeName
from app.workflow.nodes.adapters import (
    ContextGovernanceNode,
    FinalizeNode,
    InputReconstructionNode,
    KnowledgeRagNode,
    LongTermMemoryCompressionNode,
    LongTermMemoryNode,
    MainChatLlmNode,
    PostprocessCommitNode,
    PromptAssemblyNode,
    ResponsePersistenceNode,
    SessionContextLoadNode,
    UserProfileExtractionNode,
    UserProfileInjectionNode,
    WorkflowDependencies,
)
from app.workflow.routers import ChatWorkflowRouter


class ChatWorkflowNodeRegistry:
    """Chat Workflow 节点注册表。"""

    def __init__(self, dependencies: WorkflowDependencies):
        """根据依赖创建节点实例，节点无跨请求可变状态，可安全复用。"""
        self.dependencies = dependencies
        self.router = ChatWorkflowRouter(dependencies.event_publisher)
        self.nodes = {
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
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_COMPRESSION.value: LongTermMemoryCompressionNode(dependencies),
            ChatWorkflowGraphNodeName.USER_PROFILE_EXTRACTION.value: UserProfileExtractionNode(dependencies),
            ChatWorkflowGraphNodeName.POSTPROCESS_COMMIT.value: PostprocessCommitNode(dependencies),
            ChatWorkflowGraphNodeName.FINALIZE.value: FinalizeNode(dependencies),
        }

    def get_node(self, name: ChatWorkflowGraphNodeName):
        """按图节点名读取节点适配器。"""
        return self.nodes[name.value]
