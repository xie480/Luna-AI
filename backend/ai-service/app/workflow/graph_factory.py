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

        工作流流程概述（v3.0 重构 + v3.1 修复）：
        1. 会话上下文加载 -> 输入重构（v3.1 修复：交换执行顺序，确保记忆数据先就绪）
        2. 输入重构 -> 长期记忆 RAG 或绕过（条件分支）
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
        graph = StateGraph(ChatWorkflowState)
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

        # 设置入口点：会话上下文加载必须先于输入重构执行。
        # 为什么这样做：输入重构需要使用 short_summary、key_facts、recent_messages
        # 等短期记忆数据来进行代词消歧和路由决策。如果先运行输入重构，这些
        # state.session_state 字段均为空默认值，导致 memory.j2 模板变量
        # {{ CORE_SUMMARY }}、{{ KEY_FACTS }}、{{ MEMORY_SNIPPETS }} 虽正确渲染但值为空。
        graph.set_entry_point(ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value)

        # 会话上下文加载 -> 输入重构
        graph.add_edge(
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value,
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION.value,
        )

        # 输入重构后，根据路由结果（should_enter_long_term_memory_rag 等）决定
        # 进入长期记忆 RAG 或绕过。此 conditional_edges 原关联于 SESSION_CONTEXT_LOAD，
        # 交换节点顺序后移至 INPUT_RECONSTRUCTION。
        graph.add_conditional_edges(
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION.value,
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
            f"daily_chat 主图构建完成 | active_nodes={len(active_nodes)} | entry_point={ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value}"
        )
        return compiled

    def build_casual_chat_graph(self):
        """
        构建 casual_chat.default.v1 闲聊最短化执行链路图。

        做什么：构建一条最短化执行链路，仅保留必要节点：
                会话上下文加载 -> 长期记忆 RAG（强制关闭 Rerank）
                -> 用户画像注入 -> 上下文治理 -> 提示组装 -> 主聊天 LLM
                -> 响应持久化 -> 最终化。
                跳过 输入重构、知识库 RAG、MCP 意图判断、MCP Skill 执行。
        为什么这样做：闲聊模式下用户只期望快速反馈，不需要动用重型分析链。
                     此图为静态链接拓扑，不涉及条件评估分支节点。
        注意：必须包含上下文治理节点，因为它是唯一填充 prompt_variables
             （含 TTS_LANGUAGE、CURRENT_TIME 等运行时变量）的地方。
             缺少该节点会导致 runtime.j2 模板中的 `{% if %}` 条件分支
             因变量缺失而无法正确渲染（如 TTS 日语分支不生效）。
        """
        graph = StateGraph(ChatWorkflowState)
        active_nodes = [
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD,
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG,
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE,
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY,
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM,
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE,
            ChatWorkflowGraphNodeName.FINALIZE,
        ]
        for node_name in active_nodes:
            graph.add_node(node_name.value, self.registry.get_node(node_name))

        # 闲聊图入口点：会话上下文加载
        graph.set_entry_point(ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value)

        # 静态硬链接，无条件分支
        graph.add_edge(
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value,
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value,
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.USER_PROFILE_INJECTION.value,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
            ChatWorkflowGraphNodeName.FINALIZE.value,
        )

        compiled = graph.compile()
        logger.info(
            f"casual_chat 闲聊图构建完成 | active_nodes={len(active_nodes)} | entry_point={ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value}"
        )
        return compiled

    def build_plan_state_node_graph(self):
        """
        构建 plan_state_node.default.v1 Phase 9 智能规划链路图。

        做什么：构建 Phase 9 Plan-State-Node 完整路径图。
                流程：会话上下文加载 -> 简化输入重构 -> DAG 引擎
                      （Plan 生成 + Plan + Cursor 循环 + 结果汇总）
                      -> 上下文治理 -> Prompt 装配 -> 主 Chat LLM
                      -> 响应持久化 -> 最终化。
        为什么这样做：
            1. 简化输入重构作为独立 LangGraph 节点存在于图中，
               负责代词消歧，输出写入 dag_state 供 DAG 引擎读取。
            2. DAG 引擎在简化输入重构之后执行，读取消歧后的文本。
        """
        graph = StateGraph(ChatWorkflowState)

        # 定义 Phase 9 专用活动节点
        active_nodes = [
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD,
            # 简化输入重构节点：代词消歧，不做路由决策（Phase 9 专用简化版）
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION_SIMPLIFIED,
            # DAG 引擎入口节点（包含 Plan 生成 + DAG 循环 + 汇总）
            ChatWorkflowGraphNodeName.DAG_ENGINE,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE,
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY,
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM,
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE,
            ChatWorkflowGraphNodeName.FINALIZE,
        ]
        for node_name in active_nodes:
            graph.add_node(node_name.value, self.registry.get_node(node_name))

        # Phase 9 图入口点：会话上下文加载
        # 为什么这样做：输入重构需要使用 short_summary、key_facts、recent_messages
        # 等短期记忆数据来进行代词消歧。如果先运行输入重构，这些字段均为空默认值。
        graph.set_entry_point(ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value)

        # 会话上下文加载 -> 简化输入重构
        graph.add_edge(
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value,
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION_SIMPLIFIED.value,
        )

        # 简化输入重构 -> DAG 引擎
        graph.add_edge(
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION_SIMPLIFIED.value,
            ChatWorkflowGraphNodeName.DAG_ENGINE.value,
        )

        # DAG 引擎 -> 上下文治理
        # Plan + Cursor DAG 引擎 -> 条件路由（Phase 13 Gating 审批挂起时跳过 LLM 生成）
        # 做什么：与 agent_loop 图相同的 gating 条件路由逻辑。
        #         dag_engine 完成后检查 gating_suspended，挂起时跳过 LLM 生成。
        graph.add_conditional_edges(
            ChatWorkflowGraphNodeName.DAG_ENGINE.value,
            self.registry.router.route_after_dag_engine,
            {
                ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value:
                    ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
                ChatWorkflowGraphNodeName.FINALIZE.value:
                    ChatWorkflowGraphNodeName.FINALIZE.value,
            },
        )

        # 以下与 daily_chat 共享相同的后半段链路
        graph.add_edge(
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
            ChatWorkflowGraphNodeName.FINALIZE.value,
        )

        compiled = graph.compile()
        logger.info(
            f"plan_state_node 智能规划图构建完成 | active_nodes={len(active_nodes)} | entry_point={ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value}"
        )
        return compiled

    def build_agent_loop_graph(self):
        """
        构建 agent_loop.default.v1 Agent Loop 智能规划链路图。

        做什么：构建 Agent Loop 架构的完整路径图。
                流程：会话上下文加载 -> 简化输入重构 -> Agent Loop DAG 引擎
                      （GoalLock -> GlobalPlanner -> StepLoop -> FinalVerify）
                      -> 上下文治理 -> Prompt 装配 -> 主 Chat LLM
                      -> 响应持久化 -> 最终化。
        为什么这样做：Agent Loop 是独立的第四种模式，
                      实现 Goal-Stable / Plan-Mutable 的 6 层架构，
                      与原 plan_state_node 模式（Plan + Cursor）并存。
        """
        graph = StateGraph(ChatWorkflowState)

        # 定义 Agent Loop 专用活动节点
        active_nodes = [
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD,
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION_SIMPLIFIED,
            # Agent Loop DAG 引擎节点（GoalLock -> GlobalPlanner -> StepLoop -> FinalVerify）
            ChatWorkflowGraphNodeName.DAG_ENGINE_AGENT_LOOP,
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE,
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY,
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM,
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE,
            ChatWorkflowGraphNodeName.FINALIZE,
        ]
        for node_name in active_nodes:
            graph.add_node(node_name.value, self.registry.get_node(node_name))

        # 入口点：会话上下文加载
        graph.set_entry_point(ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value)

        # 会话上下文加载 -> 简化输入重构
        graph.add_edge(
            ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value,
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION_SIMPLIFIED.value,
        )

        # 简化输入重构 -> Agent Loop DAG 引擎
        graph.add_edge(
            ChatWorkflowGraphNodeName.INPUT_RECONSTRUCTION_SIMPLIFIED.value,
            ChatWorkflowGraphNodeName.DAG_ENGINE_AGENT_LOOP.value,
        )

        # Agent Loop DAG 引擎 -> 条件路由（Phase 13 Gating 审批挂起时跳过 LLM 生成）
        # 做什么：dag_engine_agent_loop 完成后，检查 gating_suspended 标志。
        #         如果 L2/L3 工具触发了 Gating 审批，跳过后续的上下文治理和 LLM 生成，
        #         直接进入 FINALIZE，等待用户在前端审批面板做出决策。
        # 为什么这样做：内层 Agent Loop 子图在 gating 挂起时正确退出（到达 END），
        #              但如果不加条件路由，外层图会继续执行 context_governance → main_chat_llm，
        #              主 Chat LLM 会生成回复，造成"自动同意"的假象。
        graph.add_conditional_edges(
            ChatWorkflowGraphNodeName.DAG_ENGINE_AGENT_LOOP.value,
            self.registry.router.route_after_dag_engine,
            {
                ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value:
                    ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
                ChatWorkflowGraphNodeName.FINALIZE.value:
                    ChatWorkflowGraphNodeName.FINALIZE.value,
            },
        )

        # 以下与 daily_chat / plan_state_node 共享相同的后半段链路
        graph.add_edge(
            ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value,
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.PROMPT_ASSEMBLY.value,
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.MAIN_CHAT_LLM.value,
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
        )
        graph.add_edge(
            ChatWorkflowGraphNodeName.RESPONSE_PERSISTENCE.value,
            ChatWorkflowGraphNodeName.FINALIZE.value,
        )

        compiled = graph.compile()
        logger.info(
            f"agent_loop 万能循环图构建完成 | active_nodes={len(active_nodes)} | entry_point={ChatWorkflowGraphNodeName.SESSION_CONTEXT_LOAD.value}"
        )
        return compiled


from app.logger import logger