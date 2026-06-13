import pytest
from app.workflow.context import ChatWorkflowState, ChatRuntimeState
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.api.chat_status import ChatStatusPublisher
from app.mcp.types import MCPToolResult
from app.workflow.nodes.impl.mcp_skill_execution_node import MCPSkillExecutionNode
from typing import Any

# ==============================================================================
# Mock classes
# ==============================================================================
class MockPublisher(ChatStatusPublisher):
    async def publish(self, *args, **kwargs):
        pass

class MockDependencies(WorkflowDependencies):
    def __init__(self):
        super().__init__(
            redis_repo=None,
            pg_repo=None,
            prompt_manager=None,
            memory_manager=None,
            rag_orchestrator=None,
            user_profile_service=None,
            event_publisher=None,
        )
        self.chat_status_publisher = MockPublisher()

@pytest.fixture
def mock_dependencies():
    return MockDependencies()

@pytest.fixture
def empty_state():
    runtime = ChatRuntimeState(
        trace_id="test-trace-id",
        session_id="test-session-id",
    )
    return ChatWorkflowState(runtime=runtime)

@pytest.mark.asyncio
async def test_mcp_skill_execution_node_initialization(mock_dependencies):
    node = MCPSkillExecutionNode(dependencies=mock_dependencies)
    assert node is not None
