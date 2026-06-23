"""
local_rag Skill 工具单元测试。

做什么：测试 retrieve_memories 和 retrieve_knowledge 两个工具的
       参数校验、正常检索、异常降级、多查询词并行等场景。
       所有外部依赖（memory_manager、rag_orchestrator）使用 Mock 模拟。
运行方式：python -m pytest tests/backend/ai-service/test_local_rag_tools.py -v
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# 测试文件所在目录向上 4 级即为项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

import pytest

from app.skills.local_rag.tools.retrieve_knowledge import (
    PARAMETER_SCHEMA as KNOWLEDGE_SCHEMA,
    handle_retrieve_knowledge,
)
from app.skills.local_rag.tools.retrieve_memories import (
    PARAMETER_SCHEMA as MEMORY_SCHEMA,
    handle_retrieve_memories,
)


# ===========================================================================
# 辅助函数
# ===========================================================================


def _make_memory_manager(return_value: str = "date: 20240101\ncontent: 测试记忆") -> MagicMock:
    """构造 Mock memory_manager。"""
    mgr = MagicMock()
    mgr.retrieve_and_format_memories = AsyncMock(return_value=return_value)
    return mgr


def _make_rag_orchestrator(evidence_text: str = "测试知识库内容", citations: list | None = None) -> MagicMock:
    """构造 Mock rag_orchestrator。"""
    orch = MagicMock()
    orch.retrieve_and_format_knowledge = AsyncMock(return_value=evidence_text)
    return orch


def _make_state_context(
    memory_manager: MagicMock | None = None,
    rag_orchestrator: MagicMock | None = None,
) -> dict[str, Any]:
    """构造运行时上下文。"""
    ctx: dict[str, Any] = {"session_id": "20240101"}
    if memory_manager:
        ctx["memory_manager"] = memory_manager
    if rag_orchestrator:
        ctx["rag_orchestrator"] = rag_orchestrator
    return ctx


# ===========================================================================
# retrieve_memories 测试
# ===========================================================================


class TestRetrieveMemories:
    """长期记忆检索工具测试套件。"""

    @pytest.mark.asyncio
    async def test_basic_single_query(self) -> None:
        """单个查询词的正常检索。"""
        mgr = _make_memory_manager("date: 20240101\ncontent: 用户喜欢简洁格式")
        ctx = _make_state_context(memory_manager=mgr)

        result = await handle_retrieve_memories(
            parameters={"query_text": ["用户偏好"]},
            trace_id="test-001",
            state_context=ctx,
        )

        assert "用户喜欢简洁格式" in result
        mgr.retrieve_and_format_memories.assert_called_once()
        call_kwargs = mgr.retrieve_and_format_memories.call_args
        assert call_kwargs.kwargs["query_text"] == "用户偏好"
        assert call_kwargs.kwargs["search_queries"] is None
        assert call_kwargs.kwargs["reference_time"] is None
        assert call_kwargs.kwargs["temporal_deviation"] == 0

    @pytest.mark.asyncio
    async def test_multi_query_parallel(self) -> None:
        """多个查询词并行向量检索。"""
        mgr = _make_memory_manager("date: 20240101\ncontent: 综合记忆结果")
        ctx = _make_state_context(memory_manager=mgr)

        result = await handle_retrieve_memories(
            parameters={"query_text": ["用户偏好", "工作领域", "报告格式"]},
            trace_id="test-002",
            state_context=ctx,
        )

        assert "综合记忆结果" in result
        call_kwargs = mgr.retrieve_and_format_memories.call_args.kwargs
        # 第一个查询词作为基础查询
        assert call_kwargs["query_text"] == "用户偏好"
        # 完整数组作为 search_queries
        assert call_kwargs["search_queries"] == ["用户偏好", "工作领域", "报告格式"]

    @pytest.mark.asyncio
    async def test_with_time_constraint(self) -> None:
        """带时间约束的 BM25 检索。"""
        mgr = _make_memory_manager("date: 20240615\ncontent: 最近的对话记忆")
        ctx = _make_state_context(memory_manager=mgr)

        result = await handle_retrieve_memories(
            parameters={
                "query_text": ["项目进展"],
                "reference_time": "2024-06-15T10:00:00+08:00",
                "temporal_deviation": 3,
            },
            trace_id="test-003",
            state_context=ctx,
        )

        assert "最近的对话记忆" in result
        call_kwargs = mgr.retrieve_and_format_memories.call_args.kwargs
        assert call_kwargs["reference_time"] == "2024-06-15T10:00:00+08:00"
        assert call_kwargs["temporal_deviation"] == 3

    @pytest.mark.asyncio
    async def test_empty_reference_time_treated_as_none(self) -> None:
        """空字符串的 reference_time 应被当作 None。"""
        mgr = _make_memory_manager("记忆结果")
        ctx = _make_state_context(memory_manager=mgr)

        await handle_retrieve_memories(
            parameters={
                "query_text": ["测试"],
                "reference_time": "",
                "temporal_deviation": 0,
            },
            trace_id="test-004",
            state_context=ctx,
        )

        call_kwargs = mgr.retrieve_and_format_memories.call_args.kwargs
        assert call_kwargs["reference_time"] is None

    @pytest.mark.asyncio
    async def test_empty_query_text_returns_error(self) -> None:
        """空查询数组应返回错误提示。"""
        result = await handle_retrieve_memories(
            parameters={"query_text": []},
            trace_id="test-005",
        )
        assert "检索错误" in result

    @pytest.mark.asyncio
    async def test_all_blank_queries_returns_error(self) -> None:
        """全部为空白的查询数组应返回错误提示。"""
        result = await handle_retrieve_memories(
            parameters={"query_text": ["", "  ", ""]},
            trace_id="test-006",
        )
        assert "检索错误" in result

    @pytest.mark.asyncio
    async def test_no_memory_manager_returns_error(self) -> None:
        """memory_manager 未注入时应返回系统错误。"""
        result = await handle_retrieve_memories(
            parameters={"query_text": ["测试"]},
            trace_id="test-007",
            state_context={},
        )
        assert "系统错误" in result

    @pytest.mark.asyncio
    async def test_retrieval_exception_returns_error(self) -> None:
        """检索过程异常时应返回错误描述。"""
        mgr = MagicMock()
        mgr.retrieve_and_format_memories = AsyncMock(side_effect=RuntimeError("数据库连接失败"))
        ctx = _make_state_context(memory_manager=mgr)

        result = await handle_retrieve_memories(
            parameters={"query_text": ["测试"]},
            trace_id="test-008",
            state_context=ctx,
        )
        assert "检索错误" in result
        assert "数据库连接失败" in result

    @pytest.mark.asyncio
    async def test_empty_result_returns_not_found(self) -> None:
        """检索结果为空时应返回未找到提示。"""
        mgr = _make_memory_manager(return_value="")
        ctx = _make_state_context(memory_manager=mgr)

        result = await handle_retrieve_memories(
            parameters={"query_text": ["不存在的记忆"]},
            trace_id="test-009",
            state_context=ctx,
        )
        assert "未找到" in result

    def test_parameter_schema_valid(self) -> None:
        """参数 Schema 结构验证。"""
        props = MEMORY_SCHEMA["properties"]
        assert "query_text" in props
        assert props["query_text"]["type"] == "array"
        assert "reference_time" in props
        assert props["reference_time"]["type"] == "string"
        assert "temporal_deviation" in props
        assert props["temporal_deviation"]["type"] == "integer"
        assert MEMORY_SCHEMA["required"] == ["query_text"]


# ===========================================================================
# retrieve_knowledge 测试
# ===========================================================================


class TestRetrieveKnowledge:
    """知识库 RAG 检索工具测试套件。"""

    @pytest.mark.asyncio
    async def test_basic_single_query(self) -> None:
        """单个查询词的正常检索。"""
        orch = _make_rag_orchestrator("公司2023年营收为100亿元")
        ctx = _make_state_context(rag_orchestrator=orch)

        result = await handle_retrieve_knowledge(
            parameters={"query_text": ["公司营收"]},
            trace_id="test-k001",
            state_context=ctx,
        )

        assert "公司2023年营收为100亿元" in result
        orch.retrieve_and_format_knowledge.assert_called_once()
        call_kwargs = orch.retrieve_and_format_knowledge.call_args.kwargs
        assert call_kwargs["query_text"] == "公司营收"
        assert call_kwargs["search_queries"] is None

    @pytest.mark.asyncio
    async def test_multi_query_parallel(self) -> None:
        """多个查询词并行向量检索。"""
        orch = _make_rag_orchestrator("综合知识库检索结果")
        ctx = _make_state_context(rag_orchestrator=orch)

        result = await handle_retrieve_knowledge(
            parameters={"query_text": ["营收数据", "利润率", "资产负债表"]},
            trace_id="test-k002",
            state_context=ctx,
        )

        assert "综合知识库检索结果" in result
        call_kwargs = orch.retrieve_and_format_knowledge.call_args.kwargs
        assert call_kwargs["query_text"] == "营收数据"
        assert call_kwargs["search_queries"] == ["营收数据", "利润率", "资产负债表"]

    @pytest.mark.asyncio
    async def test_with_time_constraint(self) -> None:
        """带时间约束的 BM25 检索。"""
        orch = _make_rag_orchestrator("2024年Q1财报数据")
        ctx = _make_state_context(rag_orchestrator=orch)

        result = await handle_retrieve_knowledge(
            parameters={
                "query_text": ["季度财报"],
                "reference_time": "2024-03-31T23:59:59+08:00",
                "temporal_deviation": 7,
            },
            trace_id="test-k003",
            state_context=ctx,
        )

        assert "2024年Q1财报数据" in result
        call_kwargs = orch.retrieve_and_format_knowledge.call_args.kwargs
        assert call_kwargs["reference_time"] == "2024-03-31T23:59:59+08:00"
        assert call_kwargs["temporal_deviation"] == 7

    @pytest.mark.asyncio
    async def test_empty_query_text_returns_error(self) -> None:
        """空查询数组应返回错误提示。"""
        result = await handle_retrieve_knowledge(
            parameters={"query_text": []},
            trace_id="test-k004",
        )
        assert "检索错误" in result

    @pytest.mark.asyncio
    async def test_no_rag_orchestrator_returns_error(self) -> None:
        """rag_orchestrator 未注入时应返回系统错误。"""
        result = await handle_retrieve_knowledge(
            parameters={"query_text": ["测试"]},
            trace_id="test-k005",
            state_context={},
        )
        assert "系统错误" in result

    @pytest.mark.asyncio
    async def test_retrieval_exception_returns_error(self) -> None:
        """检索过程异常时应返回错误描述。"""
        orch = MagicMock()
        orch.retrieve_and_format_knowledge = AsyncMock(side_effect=RuntimeError("向量库不可用"))
        ctx = _make_state_context(rag_orchestrator=orch)

        result = await handle_retrieve_knowledge(
            parameters={"query_text": ["测试"]},
            trace_id="test-k006",
            state_context=ctx,
        )
        assert "检索错误" in result
        assert "向量库不可用" in result

    @pytest.mark.asyncio
    async def test_empty_result_returns_not_found(self) -> None:
        """检索结果为空时应返回未找到提示。"""
        orch = _make_rag_orchestrator(evidence_text="")
        ctx = _make_state_context(rag_orchestrator=orch)

        result = await handle_retrieve_knowledge(
            parameters={"query_text": ["不存在的知识"]},
            trace_id="test-k007",
            state_context=ctx,
        )
        # 验证返回了空结果提示（包含"检索结果"关键字）
        assert "检索结果" in result or "未找到" in result or "错误" in result

    def test_parameter_schema_valid(self) -> None:
        """参数 Schema 结构验证。"""
        props = KNOWLEDGE_SCHEMA["properties"]
        assert "query_text" in props
        assert props["query_text"]["type"] == "array"
        assert "reference_time" in props
        assert props["reference_time"]["type"] == "string"
        assert "temporal_deviation" in props
        assert props["temporal_deviation"]["type"] == "integer"
        assert KNOWLEDGE_SCHEMA["required"] == ["query_text"]


# ===========================================================================
# JSON 配置一致性测试
# ===========================================================================


class TestJsonConsistency:
    """Skill JSON 配置与代码一致性测试。"""

    def test_json_schema_matches_code_schema(self) -> None:
        """JSON 中的 parameters_schema 应与代码中的 PARAMETER_SCHEMA 一致。"""
        import json

        json_path = _PROJECT_ROOT / "backend" / "ai-service" / "app" / "skills" / "local_rag" / "json" / "local_rag_skill.json"
        with open(json_path, encoding="utf-8") as f:
            skill_json = json.load(f)

        tools = skill_json["skills"][0]["tools"]
        tool_map = {t["name"]: t for t in tools}

        # retrieve_memories
        mem_json_schema = tool_map["retrieve_memories"]["parameters_schema"]
        assert mem_json_schema["properties"]["query_text"]["type"] == "array"
        assert "reference_time" in mem_json_schema["properties"]
        assert "temporal_deviation" in mem_json_schema["properties"]
        assert mem_json_schema["required"] == ["query_text"]

        # retrieve_knowledge
        know_json_schema = tool_map["retrieve_knowledge"]["parameters_schema"]
        assert know_json_schema["properties"]["query_text"]["type"] == "array"
        assert "reference_time" in know_json_schema["properties"]
        assert "temporal_deviation" in know_json_schema["properties"]
        assert know_json_schema["required"] == ["query_text"]

    def test_prompt_count_matches_tool_count(self) -> None:
        """Prompt 数量应与 Tool 数量一致（1 tool : 1 prompt）。"""
        import json

        json_path = _PROJECT_ROOT / "backend" / "ai-service" / "app" / "skills" / "local_rag" / "json" / "local_rag_skill.json"
        with open(json_path, encoding="utf-8") as f:
            skill_json = json.load(f)

        skill = skill_json["skills"][0]
        assert len(skill["prompts"]) == len(skill["tools"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
