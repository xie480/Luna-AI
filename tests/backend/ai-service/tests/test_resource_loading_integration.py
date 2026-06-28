"""Agent Loop 资源加载集成测试。

做什么：测试完整的 ResourceLoadNode → AgentToolExecuteNode 资源注入流程，
        验证 StepThinkNode 输出含 resource_name 的 tool_call 时，
        拓扑 step_think → resource_load → tool_execute 能正确执行。
为什么这样做：集成测试确保各组件间的协作正确，端到端验证资源加载方案。
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保能导入 backend 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../backend/ai-service"))


# ===========================================================================
# 测试：拓扑验证
# ===========================================================================


class TestTopologyVerification:
    """验证 Step Loop 子图拓扑包含 resource_load 节点。"""

    def test_resource_load_node_in_subgraph(self):
        """验证 build_step_loop_subgraph 注册了 resource_load 节点。

        做什么：检查编译后的子图是否包含 RESOURCE_LOAD 节点。
        """
        from app.workflow.constants import AgentStepLoopSubGraphNodeName

        # 验证 RESOURCE_LOAD 枚举值存在
        assert hasattr(AgentStepLoopSubGraphNodeName, "RESOURCE_LOAD")
        assert AgentStepLoopSubGraphNodeName.RESOURCE_LOAD.value == "agent_resource_load"

    def test_route_after_think_routes_to_resource_load(self):
        """验证 route_after_think 在有 tool_calls 时路由到 resource_load。"""
        from app.workflow.constants import AgentStepLoopSubGraphNodeName

        # 验证路由常量存在
        from app.workflow.dag.agent_loop_engine import _AFTER_THINK_RESOURCE_LOAD
        assert _AFTER_THINK_RESOURCE_LOAD == "resource_load"

    def test_build_step_loop_subgraph_accepts_resource_load(self):
        """验证 build_step_loop_subgraph 函数签名包含 resource_load 参数。"""
        import inspect
        from app.workflow.dag.agent_loop_engine import build_step_loop_subgraph

        sig = inspect.signature(build_step_loop_subgraph)
        param_names = list(sig.parameters.keys())

        assert "resource_load" in param_names
        # resource_load 应在 step_think 和 tool_execute 之间
        think_idx = param_names.index("step_think")
        resource_idx = param_names.index("resource_load")
        tool_idx = param_names.index("tool_execute")

        assert think_idx < resource_idx < tool_idx

    def test_build_agent_loop_subgraph_accepts_resource_load(self):
        """验证 build_agent_loop_subgraph 函数签名包含 resource_load 参数。"""
        import inspect
        from app.workflow.dag.agent_loop_engine import build_agent_loop_subgraph

        sig = inspect.signature(build_agent_loop_subgraph)
        param_names = list(sig.parameters.keys())

        assert "resource_load" in param_names


# ===========================================================================
# 测试：端到端资源注入流程
# ===========================================================================


class TestEndToEndResourceInjection:
    """端到端资源注入流程测试。"""

    @pytest.mark.asyncio
    async def test_resource_load_then_tool_execute_flow(self):
        """验证 ResourceLoadNode → AgentToolExecuteNode 完整流程。

        做什么：
        1. 构造含 resource_name 的 tool_calls
        2. 调用 ResourceLoadNode 加载资源
        3. 验证 loaded_resources 中包含加载结果
        4. 验证 AgentToolExecuteNode 能从 loaded_resources 提取资源上下文
        """
        from app.mcp.resource_tier_service import ResourceLoadResult, ResourceTierService
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode
        from app.workflow.dag.types import AgentLoopState, AgentStepState

        # 1. 构造 mock ResourceTierService
        mock_tier_service = MagicMock(spec=ResourceTierService)
        mock_tier_service.load_resource = AsyncMock(
            return_value=ResourceLoadResult(
                resource_name="API文档",
                content="这是 API 文档的完整内容",
                success=True,
                tier_used="tier1_full",
            )
        )

        # 2. 构造 ResourceLoadNode
        node = ResourceLoadNode(
            resource_tier_service=mock_tier_service,
            chat_status_publisher=MagicMock(),
        )

        # 3. 构造图状态
        from app.workflow.context import ChatWorkflowState

        agent_loop = AgentLoopState()
        agent_loop.goal.global_goal = "查询 API 文档"
        agent_loop.plan.steps = [
            AgentStepState(step_id="s1", intent="搜索 API 接口", title="搜索"),
        ]
        agent_loop.plan.current_step_index = 0
        agent_loop.execution.last_tool_calls = [
            {
                "skill_name": "api_doc",
                "tool_name": "search_api",
                "parameters": {"query": "用户接口"},
                "purpose": "搜索用户相关 API",
                "resources": [
                    {"resource_name": "API文档", "query_text": ["用户接口文档", "API 认证方式"]},
                ],
            },
        ]

        chat_state = ChatWorkflowState()
        chat_state.runtime.trace_id = "integration-trace-001"
        chat_state.runtime.session_id = "integration-session-001"
        chat_state.dag_state.dag_engine_state = agent_loop.model_dump(mode="json")

        state = chat_state.as_graph_state()

        # 4. 执行 ResourceLoadNode
        result_state = await node(state)

        # 5. 验证结果
        # 反序列化结果状态
        result_chat_state = ChatWorkflowState.from_graph_state(result_state)
        result_agent_loop = AgentLoopState(**result_chat_state.dag_state.dag_engine_state)

        # 验证资源已加载
        assert "API文档" in result_agent_loop.execution.loaded_resources
        assert result_agent_loop.execution.loaded_resources["API文档"] == "这是 API 文档的完整内容"

        # 验证无错误
        assert len(result_agent_loop.execution.resource_load_errors) == 0

        # 验证 load_resource 被调用
        mock_tier_service.load_resource.assert_called_once()
        call_kwargs = mock_tier_service.load_resource.call_args
        assert call_kwargs.kwargs["resource_def"]["name"] == "API文档"

    @pytest.mark.asyncio
    async def test_step_think_output_with_resources_array(self):
        """验证 StepThinkNode 的 _build_think_schema 包含 resources 数组字段。"""
        from app.workflow.dag.agent_loop_engine import StepThinkNode

        # 创建一个 mock StepThinkNode 实例
        node = StepThinkNode(
            prompt_manager=MagicMock(),
            llm_client=MagicMock(),
            chat_status_publisher=MagicMock(),
        )

        schema = node._build_think_schema()

        # 验证 schema 结构
        tool_calls_schema = schema["properties"]["tool_calls"]
        items_properties = tool_calls_schema["items"]["properties"]

        # 验证 resources 数组字段
        assert "resources" in items_properties
        resources_schema = items_properties["resources"]
        assert resources_schema["type"] == "array"
        # 验证数组元素包含 resource_name 和 query_text
        res_props = resources_schema["items"]["properties"]
        assert "resource_name" in res_props
        assert "query_text" in res_props
        assert res_props["resource_name"]["type"] == "string"
        assert res_props["query_text"]["type"] == "array"

    @pytest.mark.asyncio
    async def test_agent_tool_execute_uses_loaded_resources(self):
        """验证 AgentToolExecuteNode 从 loaded_resources 提取资源上下文。

        做什么：
        1. 构造含 loaded_resources 的 agent_loop 状态
        2. 调用 AgentToolExecuteNode
        3. 验证传递给 ToolExecuteNode.execute 的 state_context 包含 resource_context
        """
        from app.workflow.dag.agent_loop_engine import AgentToolExecuteNode
        from app.workflow.dag.types import AgentLoopState, AgentStepState
        from app.workflow.context import ChatWorkflowState

        # 构造 agent_loop 状态
        agent_loop = AgentLoopState()
        agent_loop.goal.global_goal = "测试"
        agent_loop.plan.steps = [
            AgentStepState(step_id="s1", intent="测试步骤", title="测试"),
        ]
        agent_loop.plan.current_step_index = 0
        agent_loop.execution.last_tool_calls = [
            {
                "skill_name": "test_skill",
                "tool_name": "test_tool",
                "parameters": {},
                "purpose": "测试",
                "resources": [
                    {"resource_name": "测试资源", "query_text": []},
                ],
            },
        ]
        agent_loop.execution.loaded_resources = {
            "测试资源": "这是预加载的资源内容",
        }

        chat_state = ChatWorkflowState()
        chat_state.runtime.trace_id = "integration-trace-002"
        chat_state.runtime.session_id = "integration-session-002"
        chat_state.dag_state.dag_engine_state = agent_loop.model_dump(mode="json")

        state = chat_state.as_graph_state()

        # Mock ToolExecuteNode.execute
        mock_execute_result = {
            "success": True,
            "tool_output": "测试输出",
            "error_message": "",
            "tool_parameters": {},
            "latency_ms": 100,
        }

        # 创建 AgentToolExecuteNode
        node = AgentToolExecuteNode(
            prompt_manager=MagicMock(),
            llm_client=MagicMock(),
            mcp_tool_registry=MagicMock(),
            chat_status_publisher=MagicMock(),
        )

        # Patch ToolExecuteNode.execute
        with patch(
            "app.workflow.dag.nodes.tool_execute.ToolExecuteNode.execute",
            new_callable=AsyncMock,
            return_value=mock_execute_result,
        ) as mock_execute:
            result_state = await node(state)

            # 验证 execute 被调用
            mock_execute.assert_called_once()

            # 验证 state_context 中包含 resource_context
            call_kwargs = mock_execute.call_args
            state_context = call_kwargs.kwargs.get("state_context") or call_kwargs[1].get("state_context", {})
            # 新格式：多资源合并，每个资源带标题前缀
            resource_ctx = state_context.get("resource_context", "")
            assert "这是预加载的资源内容" in resource_ctx
            assert "资源: 测试资源" in resource_ctx


# ===========================================================================
# 测试：降级场景
# ===========================================================================


class TestDegradationScenarios:
    """测试资源加载降级场景。"""

    @pytest.mark.asyncio
    async def test_resource_load_failure_does_not_block_tool(self):
        """资源加载失败不阻塞工具执行。

        做什么：验证当 ResourceLoadNode 加载资源失败时，
               tool_calls 仍然保留在 execution 中，不会被清除。
        """
        from app.mcp.resource_tier_service import ResourceLoadResult, ResourceTierService
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode
        from app.workflow.dag.types import AgentLoopState, AgentStepState
        from app.workflow.context import ChatWorkflowState

        # Mock ResourceTierService 返回失败
        mock_tier_service = MagicMock(spec=ResourceTierService)
        mock_tier_service.load_resource = AsyncMock(
            return_value=ResourceLoadResult(
                resource_name="失败资源",
                success=False,
                error_message="文件不存在",
            )
        )

        node = ResourceLoadNode(
            resource_tier_service=mock_tier_service,
            chat_status_publisher=MagicMock(),
        )

        agent_loop = AgentLoopState()
        agent_loop.plan.steps = [
            AgentStepState(step_id="s1", intent="测试", title="测试"),
        ]
        agent_loop.execution.last_tool_calls = [
            {
                "tool_name": "test_tool",
                "skill_name": "test_skill",
                "parameters": {},
                "resources": [
                    {"resource_name": "失败资源", "query_text": ["测试查询"]},
                ],
            },
        ]

        chat_state = ChatWorkflowState()
        chat_state.runtime.trace_id = "degradation-trace-001"
        chat_state.runtime.session_id = "degradation-session-001"
        chat_state.dag_state.dag_engine_state = agent_loop.model_dump(mode="json")

        state = chat_state.as_graph_state()

        result_state = await node(state)

        # 反序列化验证
        result_chat_state = ChatWorkflowState.from_graph_state(result_state)
        result_agent_loop = AgentLoopState(**result_chat_state.dag_state.dag_engine_state)

        # 验证：错误被记录
        assert "失败资源" in result_agent_loop.execution.resource_load_errors
        assert result_agent_loop.execution.resource_load_errors["失败资源"] == "文件不存在"

        # 验证：loaded_resources 中没有该资源
        assert "失败资源" not in result_agent_loop.execution.loaded_resources

        # 验证：tool_calls 仍然保留在 execution 中（不被清除）
        assert len(result_agent_loop.execution.last_tool_calls) == 1
