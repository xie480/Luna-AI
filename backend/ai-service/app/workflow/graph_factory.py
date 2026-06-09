"""
Phase 8.5 LangGraph Chat Plan 工厂。

做什么：构建 daily_chat.default.v1 固定预设图。
为什么这样做：Phase 8.5 要求日常闲聊请求由 LangGraph chat plan 执行，并为 Phase 9 复用节点库与状态模型打基础。
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.workflow.constants import ChatWorkflowGraphNodeName
from app.workflow.nodes.adapters import WorkflowDependencies
from app.workflow.registry import ChatWorkflowNodeRegistry


class WorkflowGraphState(TypedDict):
    """LangGraph 外层状态通道。"""

    state: dict[str, Any]


class ChatGraphFactory:
    """Chat Workflow LangGraph 图工厂。"""

    def __init__(self, dependencies: WorkflowDependencies):
        """初始化图工厂并创建节点注册表。"""
        self.dependencies = dependencies
        self.registry = ChatWorkflowNodeRegistry(dependencies)

    def build_daily_chat_graph(self):
        """
        构建 daily_chat.default.v1 预设图。

        做什么：按 Phase 8.5 主图结构注册节点、条件边、汇合边和结束边。
        为什么这样做：固定 chat plan 先服务日常闲聊，不实现通用 Plan 自动生成。
        输入输出：输出已编译 LangGraph 图；输入状态使用 ChatWorkflowState 的 JSON dict。
        边界条件：长期记忆与知识库 RAG 由条件边决定是否进入；用户画像固定进入。
        异常行为：节点异常由节点适配器与 service 归一化处理。
        """
        # 创建状态图实例
        graph = StateGraph(WorkflowGraphState)
        
        # 注册所有工作流节点
        for node_name in ChatWorkflowGraphNodeName:
            graph.add_node(node_name.value, self.registry.get_node(node_name))

        # 设置入口点
        graph.set_entry_point(ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION.value)
        
        # 添加输入重建到会话上下文加载的边
        graph.add_edge(
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION.value,
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value,
        )
        
        # 添加会话上下文加载后的条件边，决定是否进行长期记忆RAG
        graph.add_conditional_edges(
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value,
            self.registry.router.route_long_term_memory,
            {
                ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value: ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value,
                ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value: ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value,
            },
        )
        
        # 连接长期记忆RAG和绕过路径到用户画像注入节点
        graph.add_edge(
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value,
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value,
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value,
        )
        
        # 添加用户画像注入后的条件边，决定是否进行知识库RAG
        graph.add_conditional_edges(
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value,
            self.registry.router.route_knowledge_rag,
            {
                ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value: ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value,
                ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value: ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value,
            },
        )
        
        # 连接知识库RAG和绕过路径到上下文治理节点
        graph.add_edge(
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
        )
        
        # 上下文治理连接到提示词组装节点
        graph.add_edge(
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
        )

        # 链接主要LLM chat节点
        graph.add_edge(
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
        )

        # 链接响应持久化节点
        graph.add_edge(
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
        )

        # 长期记忆压缩节点
        graph.add_edge(
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_COMPRESSION.value,
        )

        # 用户画像提取节点
        graph.add_edge(
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_COMPRESSION.value,
            ChatWorkflowGraphNodeName.USER_PROFILE_EXTRACTION.value,
        )

        # 持久化提交节点
        graph.add_edge(
            ChatWorkflowGraphNodeName.USER_PROFILE_EXTRACTION.value,
            ChatWorkflowGraphNodeName.POSTPROCESS_COMMIT.value,
        )

        # 结束节点
        graph.add_edge(
            ChatWorkflowGraphNodeName.POSTPROCESS_COMMIT.value,
            ChatWorkflowGraphNodeName.FINALIZE.value,
        )
        
        # 添加最终边到结束节点
        graph.add_edge(ChatWorkflowGraphNodeName.FINALIZE.value, END)
        
        return graph.compile()