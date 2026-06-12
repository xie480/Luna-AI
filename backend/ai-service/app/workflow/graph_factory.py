"""Phase 8.5 Chat Workflow LangGraph 图工厂。"""

from __future__ import annotations

from langgraph.graph import StateGraph

from app.workflow.constants import ChatWorkflowGraphNodeName
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.registry import ChatWorkflowNodeRegistry


class ChatGraphFactory:
    """Chat Workflow LangGraph 图工厂。"""

    def __init__(self, dependencies: WorkflowDependencies):
        self.dependencies = dependencies
        self.registry = ChatWorkflowNodeRegistry(dependencies)

    def build_daily_chat_graph(self):
        """
        构建 daily_chat.default.v1 主图。

        此方法创建一个 LangGraph 工作流，用于处理日常聊天任务。
        它设置了一系列节点和它们之间的边，形成一个有向无环图 (DAG)，
        用于管理聊天工作流的状态转换和执行逻辑。

        工作流流程概述（v3.0 重构）：
        1. 输入重构 -> 会话上下文加载
        2. 会话上下文加载 -> 长期记忆 RAG 或绕过（条件分支）
        3. 长期记忆 RAG/绕过 -> 用户资料注入
        4. 用户资料注入 -> 知识 RAG 或绕过（条件分支）
        5. 知识 RAG/绕过 -> MCP 意图判断或绕过（条件分支，v3.0 延迟判断）
        6. MCP 意图判断 -> MCP Skill 执行或绕过（条件分支，v3.0 基于意图结果）
        7. MCP Skill 执行/绕过 -> 上下文治理
        8. 上下文治理 -> 提示组装 -> 主聊天 LLM
        9. 主聊天 LLM -> 响应持久化 -> 最终化 -> 结束

        v3.0 变更要点：
        - 输入重构不再输出 MCP 判断，MCP 意图判断延迟到知识 RAG 之后
        - 新增 MCP_INTENT_JUDGE 节点，在知识 RAG 后基于更多上下文做判断
        - MCP 前置节点判断后路由到 Skill 执行或绕过

        Returns:
            CompiledGraph: 编译后的 LangGraph 图对象，可用于执行聊天工作流
        """
        graph = StateGraph(WorkflowGraphState)
        # 定义工作流中使用的所有活动节点
        active_nodes = [
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION,
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD,
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG,
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS,
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION,
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG,
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS,
            # --- Phase 12（v3.0）新增：MCP 意图判断与 Skill 执行节点 ---
            ChatWorkflowGraphNodeName.MCP_INTENT_JUDGE,
            ChatWorkflowGraphNodeName.MCP_INTENT_BYPASS,
            ChatWorkflowGraphNodeName.MCP_SKILL_EXECUTION,
            ChatWorkflowGraphNodeName.MCP_SKILL_BYPASS,
            # -------------------------------------------------
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE,
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY,
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM,
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE,
            ChatWorkflowGraphNodeName.FINALIZE,
        ]
        # 将所有活动节点添加到图中
        for node_name in active_nodes:
            graph.add_node(node_name.value, self.registry.get_node(node_name))

        # 设置入口点
        graph.set_entry_point(ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION.value)

        # 输入重构 -> 会话上下文加载
        graph.add_edge(
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION.value,
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value,
        )

        # 添加从会话上下文加载到长期记忆的条件边（RAG 或绕过）
        graph.add_conditional_edges(
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value,
            self.registry.router.route_long_term_memory,
            {
                ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value:
                    ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value,
                ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value:
                    ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value,
            },
        )
        # 添加从长期记忆 RAG 到用户资料注入的边
        graph.add_edge(
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value,
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value,
        )
        # 添加从长期记忆绕过到用户资料注入的边
        graph.add_edge(
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value,
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value,
        )
        # 添加从用户资料注入到知识 RAG 的条件边（RAG 或绕过）
        graph.add_conditional_edges(
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value,
            self.registry.router.route_knowledge_rag,
            {
                ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value:
                    ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value,
                ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value:
                    ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value,
            },
        )

        # v3.0：知识 RAG/绕过 -> MCP 意图判断（条件路由）
        graph.add_edge(
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value,
            ChatWorkflowGraphNodeName.MCP_INTENT_JUDGE.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value,
            ChatWorkflowGraphNodeName.MCP_INTENT_JUDGE.value,
        )

        # MCP 意图判断 -> MCP Skill 执行或绕过（条件路由）
        graph.add_conditional_edges(
            ChatWorkflowGraphNodeName.MCP_INTENT_JUDGE.value,
            self.registry.router.route_mcp_skill_from_judge,
            {
                ChatWorkflowGraphNodeName.MCP_SKILL_EXECUTION.value:
                    ChatWorkflowGraphNodeName.MCP_SKILL_EXECUTION.value,
                ChatWorkflowGraphNodeName.MCP_SKILL_BYPASS.value:
                    ChatWorkflowGraphNodeName.MCP_SKILL_BYPASS.value,
            },
        )

        # MCP Intent 绕过 -> 直接到上下文治理
        graph.add_edge(
            ChatWorkflowGraphNodeName.MCP_INTENT_BYPASS.value,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
        )

        # MCP Skill 执行/绕过汇合到上下文治理
        graph.add_edge(
            ChatWorkflowGraphNodeName.MCP_SKILL_EXECUTION.value,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.MCP_SKILL_BYPASS.value,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
        )

        # 添加从上下文治理到提示组装的边
        graph.add_edge(
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
        )
        # 添加从提示组装到主聊天 LLM 的边
        graph.add_edge(
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
        )
        # 添加从主聊天 LLM 到响应持久化的边
        graph.add_edge(
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
        )
        # 添加从响应持久化到最终化的边
        graph.add_edge(
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
            ChatWorkflowGraphNodeName.FINALIZE.value,
        )

        compiled = graph.compile()
        logger.info(
            "daily_chat 主图构建完成 | active_nodes=%d | entry_point=%s",
            len(active_nodes),
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION.value,
        )
        return compiled


from app.logger import logger
