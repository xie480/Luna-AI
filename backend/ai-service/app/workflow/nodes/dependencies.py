"""Workflow 节点依赖容器。"""

from __future__ import annotations

from app.api.chat_status import ChatStatusPublisher
from app.mcp.registry import MCPToolRegistry
from app.memory.manager import Manager as MemoryManager
from app.prompt.manager import Manager as PromptManager
from app.rag.retrieval import RagRetrievalOrchestrator
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo
from app.user_profile.service import UserProfileService
from app.workflow.events import ChatWorkflowEventPublisher


class WorkflowDependencies:
    """Chat Workflow 节点依赖容器。"""

    def __init__(
        self,
        *,
        redis_repo: ChatHistoryRedisRepo | None,
        pg_repo: ChatHistoryPGRepo | None,
        prompt_manager: PromptManager | None,
        memory_manager: MemoryManager | None,
        rag_orchestrator: RagRetrievalOrchestrator | None,
        user_profile_service: UserProfileService | None,
        event_publisher: ChatWorkflowEventPublisher | None,
        chat_status_publisher: ChatStatusPublisher | None = None,
        # --- Phase 12 新增：MCP 工具注册中心 ---
        mcp_tool_registry: MCPToolRegistry | None = None,
    ):
        """保存节点运行依赖，依赖由 FastAPI lifespan 注入。"""
        self.redis_repo = redis_repo
        self.pg_repo = pg_repo
        self.prompt_manager = prompt_manager
        self.memory_manager = memory_manager
        self.rag_orchestrator = rag_orchestrator
        self.user_profile_service = user_profile_service
        self.event_publisher = event_publisher
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()
        # --- Phase 12 新增：MCP 工具注册中心默认实例 ---
        self.mcp_tool_registry = mcp_tool_registry or MCPToolRegistry()
