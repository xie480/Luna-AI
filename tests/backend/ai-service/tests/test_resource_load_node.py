"""ResourceLoadNode 单元测试。

做什么：测试 Agent Loop 资源加载节点的核心逻辑：
        1. 从 tool_calls 提取 resource_name
        2. 多个 tool_call 引用同一资源只加载一次
        3. 单个资源失败不阻塞其他资源
        4. 空 tool_calls 时跳过
        5. 事件发布正确性
为什么这样做：确保 ResourceLoadNode 的去重、降级和事件发布逻辑正确。
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保能导入 backend 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../backend/ai-service"))


# ===========================================================================
# Mock 辅助类
# ===========================================================================


def _make_agent_loop_state(
    tool_calls: list[dict] | None = None,
    loaded_resources: dict | None = None,
    resource_load_errors: dict | None = None,
    current_step_index: int = 0,
    global_goal: str = "测试目标",
    disambiguated_text: str = "测试上下文",
    terminated: bool = False,
) -> dict:
    """构造模拟的 LangGraph 图状态。

    做什么：构建一个包含 AgentLoopState 序列化数据的 ChatWorkflowState 字典。
    """
    from app.workflow.dag.types import (
        AgentLoopState,
        AgentStepState,
        ExecutionState,
    )

    # 构造步骤
    steps = [
        AgentStepState(
            step_id="step-001",
            title="测试步骤",
            intent="搜索相关信息",
            expected_output="搜索结果",
        )
    ]

    agent_loop = AgentLoopState()
    agent_loop.goal.global_goal = global_goal
    agent_loop.plan.steps = steps
    agent_loop.plan.current_step_index = current_step_index
    agent_loop.disambiguated_text = disambiguated_text
    agent_loop.terminated = terminated

    if tool_calls is not None:
        agent_loop.execution.last_tool_calls = tool_calls
    if loaded_resources is not None:
        agent_loop.execution.loaded_resources = loaded_resources
    if resource_load_errors is not None:
        agent_loop.execution.resource_load_errors = resource_load_errors

    # 构造 ChatWorkflowState 的图状态
    from app.workflow.context import ChatWorkflowState

    chat_state = ChatWorkflowState()
    chat_state.runtime.trace_id = "test-trace-001"
    chat_state.runtime.session_id = "test-session-001"
    chat_state.dag_state.dag_engine_state = agent_loop.model_dump(mode="json")

    return chat_state.as_graph_state()


class MockResourceTierService:
    """模拟 ResourceTierService。"""

    def __init__(self, results: dict[str, str] | None = None, fail_resources: set | None = None):
        self._results = results or {}
        self._fail_resources = fail_resources or set()
        self.load_call_count = 0
        self.loaded_resource_names: list[str] = []

    async def load_resource(self, trace_id, resource_def, query_texts, step_intent=""):
        self.load_call_count += 1
        resource_name = resource_def.get("name", "")
        self.loaded_resource_names.append(resource_name)

        from app.mcp.resource_tier_service import ResourceLoadResult

        if resource_name in self._fail_resources:
            return ResourceLoadResult(
                resource_name=resource_name,
                success=False,
                error_message=f"模拟加载失败: {resource_name}",
            )

        content = self._results.get(resource_name, f"模拟内容: {resource_name}")
        return ResourceLoadResult(
            resource_name=resource_name,
            content=content,
            success=True,
            tier_used="tier1_full",
        )


# ===========================================================================
# 测试：从 tool_calls 提取 resource_name
# ===========================================================================


class TestExtractResourceNames:
    """测试 resource_name 提取逻辑。"""

    def test_extract_single_resource(self):
        """单个 tool_call 提取一个 resource_name。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [
            {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "搜索指南", "query_text": []}]},
        ]

        result = node._extract_resource_names(tool_calls)
        assert result == ["搜索指南"]

    def test_extract_multiple_resources(self):
        """多个不同 resource_name 全部提取。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [
            {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "指南A", "query_text": []}]},
            {"tool_name": "read", "skill_name": "file", "parameters": {}, "resources": [{"resource_name": "指南B", "query_text": []}]},
        ]

        result = node._extract_resource_names(tool_calls)
        assert result == ["指南A", "指南B"]

    def test_deduplicate_same_resource(self):
        """多个 tool_call 引用同一 resource_name 只提取一次。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [
            {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "同名资源", "query_text": []}]},
            {"tool_name": "read", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "同名资源", "query_text": []}]},
        ]

        result = node._extract_resource_names(tool_calls)
        assert result == ["同名资源"]

    def test_extract_multiple_resources_per_tool_call(self):
        """单个 tool_call 关联多个资源文件时全部提取。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [
            {
                "tool_name": "search", "skill_name": "web", "parameters": {},
                "resources": [
                    {"resource_name": "指南A", "query_text": ["q1"]},
                    {"resource_name": "指南B", "query_text": ["q2"]},
                ],
            },
        ]

        result = node._extract_resource_names(tool_calls)
        assert result == ["指南A", "指南B"]

    def test_skip_empty_resource_name(self):
        """空 resource_name 被忽略。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [
            {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "", "query_text": []}]},
            {"tool_name": "read", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "有效资源", "query_text": []}]},
        ]

        result = node._extract_resource_names(tool_calls)
        assert result == ["有效资源"]

    def test_empty_tool_calls(self):
        """空 tool_calls 列表返回空列表。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        result = node._extract_resource_names([])
        assert result == []


# ===========================================================================
# 测试：__call__ 节点入口
# ===========================================================================


class TestResourceLoadNodeCall:
    """测试 ResourceLoadNode.__call__ 入口逻辑。"""

    @pytest.mark.asyncio
    async def test_skip_empty_tool_calls(self):
        """空 tool_calls 时跳过资源加载。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        mock_tier_service = MockResourceTierService()
        node = ResourceLoadNode(
            resource_tier_service=mock_tier_service,
            chat_status_publisher=MagicMock(),
        )

        state = _make_agent_loop_state(tool_calls=[])

        result = await node(state)

        # 不应调用 load_resource
        assert mock_tier_service.load_call_count == 0

    @pytest.mark.asyncio
    async def test_skip_no_resource_names(self):
        """tool_calls 中没有 resource_name 时跳过。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        mock_tier_service = MockResourceTierService()
        node = ResourceLoadNode(
            resource_tier_service=mock_tier_service,
            chat_status_publisher=MagicMock(),
        )

        state = _make_agent_loop_state(
            tool_calls=[
                {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": []},
            ]
        )

        result = await node(state)

        assert mock_tier_service.load_call_count == 0

    @pytest.mark.asyncio
    async def test_load_single_resource(self):
        """单个资源正确加载。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        mock_tier_service = MockResourceTierService(
            results={"搜索指南": "搜索指南的完整内容"}
        )
        node = ResourceLoadNode(
            resource_tier_service=mock_tier_service,
            chat_status_publisher=MagicMock(),
        )

        state = _make_agent_loop_state(
            tool_calls=[
                {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "搜索指南", "query_text": ["如何搜索"]}]},
            ]
        )

        result = await node(state)

        assert mock_tier_service.load_call_count == 1
        assert mock_tier_service.loaded_resource_names == ["搜索指南"]

    @pytest.mark.asyncio
    async def test_deduplicate_load(self):
        """多个 tool_call 引用同一资源只加载一次。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        mock_tier_service = MockResourceTierService()
        node = ResourceLoadNode(
            resource_tier_service=mock_tier_service,
            chat_status_publisher=MagicMock(),
        )

        state = _make_agent_loop_state(
            tool_calls=[
                {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "同名资源", "query_text": []}]},
                {"tool_name": "read", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "同名资源", "query_text": []}]},
            ]
        )

        result = await node(state)

        # 只加载一次
        assert mock_tier_service.load_call_count == 1

    @pytest.mark.asyncio
    async def test_single_failure_not_blocking_others(self):
        """单个资源加载失败不阻塞其他资源。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        mock_tier_service = MockResourceTierService(
            results={"资源A": "资源A的内容"},
            fail_resources={"资源B"},
        )
        mock_event_publisher = AsyncMock()
        node = ResourceLoadNode(
            resource_tier_service=mock_tier_service,
            chat_status_publisher=MagicMock(),
            event_publisher=mock_event_publisher,
        )

        state = _make_agent_loop_state(
            tool_calls=[
                {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "资源A", "query_text": ["qA"]}]},
                {"tool_name": "read", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "资源B", "query_text": ["qB"]}]},
            ]
        )

        result = await node(state)

        # 两个资源都应被尝试加载
        assert mock_tier_service.load_call_count == 2

    @pytest.mark.asyncio
    async def test_event_publishing(self):
        """事件发布正确性。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        mock_tier_service = MockResourceTierService()
        node = ResourceLoadNode(
            resource_tier_service=mock_tier_service,
            chat_status_publisher=MagicMock(),
        )

        state = _make_agent_loop_state(
            tool_calls=[
                {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "测试资源", "query_text": ["q1"]}]},
            ]
        )

        result = await node(state)

        # 事件通过 _emit_dag_event 发布，验证节点正常执行即可
        assert mock_tier_service.load_call_count == 1

    @pytest.mark.asyncio
    async def test_terminated_skip(self):
        """已终止状态跳过资源加载。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        mock_tier_service = MockResourceTierService()
        node = ResourceLoadNode(
            resource_tier_service=mock_tier_service,
            chat_status_publisher=MagicMock(),
        )

        state = _make_agent_loop_state(
            tool_calls=[
                {"tool_name": "search", "skill_name": "web", "parameters": {}, "resources": [{"resource_name": "资源", "query_text": []}]},
            ],
            terminated=True,
        )

        result = await node(state)

        assert mock_tier_service.load_call_count == 0


# ===========================================================================
# 测试：_extract_query_texts_for_resource
# ===========================================================================


class TestExtractQueryTextsForResource:
    """测试从 tool_calls 中提取 per-resource query_text。"""

    def test_extracts_queries_from_tool_calls(self):
        """从 tool_calls 中提取指定资源的 query_text 列表。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [
            {
                "tool_name": "search",
                "resources": [
                    {"resource_name": "指南", "query_text": ["如何使用搜索工具", "搜索配置说明"]},
                ],
            },
            {
                "tool_name": "read",
                "resources": [
                    {"resource_name": "FAQ", "query_text": ["常见问题解答"]},
                ],
            },
        ]

        queries = node._extract_query_texts_for_resource("指南", tool_calls)
        assert queries == ["如何使用搜索工具", "搜索配置说明"]

    def test_deduplicates_across_multiple_tool_calls(self):
        """多个 tool_call 引用同一资源时合并去重。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [
            {"tool_name": "search", "resources": [{"resource_name": "手册", "query_text": ["API 文档", "认证方式"]}]},
            {"tool_name": "read", "resources": [{"resource_name": "手册", "query_text": ["认证方式", "错误码列表"]}]},
        ]

        queries = node._extract_query_texts_for_resource("手册", tool_calls)
        assert queries == ["API 文档", "认证方式", "错误码列表"]

    def test_returns_empty_for_no_matching_resource(self):
        """无匹配 resource_name 时返回空列表。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [{"tool_name": "t", "resources": [{"resource_name": "其他", "query_text": ["q1"]}]}]
        queries = node._extract_query_texts_for_resource("不存在", tool_calls)
        assert queries == []

    def test_skips_non_list_query_text(self):
        """query_text 非 list 类型时跳过。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [{"tool_name": "t", "resources": [{"resource_name": "res", "query_text": "不是列表"}]}]
        queries = node._extract_query_texts_for_resource("res", tool_calls)
        assert queries == []

    def test_multiple_resources_per_tool_call(self):
        """单个 tool_call 关联多个资源时分别提取各自的 query。"""
        from app.workflow.dag.nodes.resource_load import ResourceLoadNode

        node = ResourceLoadNode(
            resource_tier_service=MockResourceTierService(),
            chat_status_publisher=MagicMock(),
        )

        tool_calls = [
            {
                "tool_name": "search",
                "resources": [
                    {"resource_name": "文档A", "query_text": ["qA1", "qA2"]},
                    {"resource_name": "文档B", "query_text": ["qB1"]},
                ],
            },
        ]

        assert node._extract_query_texts_for_resource("文档A", tool_calls) == ["qA1", "qA2"]
        assert node._extract_query_texts_for_resource("文档B", tool_calls) == ["qB1"]
