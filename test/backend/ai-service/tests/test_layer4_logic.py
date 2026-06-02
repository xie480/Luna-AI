"""
第四阶段（Layer 4）综合测试

做什么：验证 Go backend/runtime/internal/prompt/* 和 memory/* 的 Python 端口
     与原始 Go 实现在行为、逻辑和边界条件上 100% 一致。

覆盖范围：
    - prompt/types.py: Prompt 相关的枚举、常量和辅助函数
    - prompt/manager.py: Prompt 模板与版本的管理
    - memory/manager.py: 长期记忆的完整生命周期管理

Go 原版参考文件：
    - backend/runtime/internal/prompt/types.go
    - backend/runtime/internal/prompt/manager.go
    - backend/runtime/internal/memory/manager.go
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.manager import Manager as MemoryManager
from app.memory.manager import MemoryEvent, MemoryEventType
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import (
    PLACEHOLDER_MEMORY,
    PLACEHOLDER_RUNTIME,
    PLACEHOLDER_SYSTEM,
    PromptCategory,
    SlotPosition,
    render_template,
)
from app.repository.chat_history_redis import ChatSummary, Interaction
from app.repository.models import LongTermMemory, MemoryStatus, PromptTemplate, PromptVersion


# ============================================================
# 1. Prompt Types 测试
# ============================================================

class TestPromptTypes:
    """验证 Prompt Types 与 Go types.go 一致"""

    def test_slot_position(self) -> None:
        assert SlotPosition.SYSTEM.value == "system"
        assert SlotPosition.MEMORY.value == "memory"
        assert SlotPosition.RUNTIME.value == "runtime"

    def test_prompt_category(self) -> None:
        assert PromptCategory.CHAT.value == "chat"
        assert PromptCategory.SHORT_SUMMARY.value == "short_summary"
        assert PromptCategory.LONG_SUMMARY.value == "long_summary"
        assert PromptCategory.INPUT_RECONSTRUCTION.value == "input_reconstruction"

    def test_placeholders(self) -> None:
        assert PLACEHOLDER_SYSTEM == "{system}"
        assert PLACEHOLDER_MEMORY == "{memory}"
        assert PLACEHOLDER_RUNTIME == "{runtime}"

    def test_render_template(self) -> None:
        template = "Hello {{ NAME }}, today is {{DAY}}."
        variables = {"NAME": "Luna", "DAY": "Monday"}
        result = render_template(template, variables)
        assert result == "Hello Luna, today is Monday."


# ============================================================
# 2. Prompt Manager 测试
# ============================================================

class TestPromptManager:
    """验证 Prompt Manager 与 Go manager.go 一致"""

    @pytest.fixture
    def mock_repo(self):
        return MagicMock()

    @pytest.fixture
    def mock_cache(self):
        cache = MagicMock()
        cache.get_assembled_prompt = AsyncMock()
        cache.invalidate_cache = AsyncMock()
        return cache

    @pytest.mark.asyncio
    async def test_assemble_prompt_with_cache(self, mock_repo, mock_cache):
        mgr = PromptManager(mock_repo, mock_cache)
        mock_cache.get_assembled_prompt.return_value = "System: {system}\nMemory: {memory}\nRuntime: {runtime}\nContent"
        
        result = await mgr.assemble_prompt(PromptCategory.CHAT, {})
        
        assert result == "System: \nMemory: \nRuntime: \nContent"
        mock_cache.get_assembled_prompt.assert_called_once_with(PromptCategory.CHAT, {})

    @pytest.mark.asyncio
    async def test_assemble_prompt_fallback(self, mock_repo, mock_cache):
        mgr = PromptManager(mock_repo, mock_cache)
        mock_cache.get_assembled_prompt.side_effect = Exception("Cache error")
        
        variables = {"CURRENT_TIME": "2023-10-27", "CURRENT_MESSAGE": "Hi"}
        result = await mgr.assemble_prompt(PromptCategory.CHAT, variables)
        
        expected = "你是一个 AI 助手。\n\n当前时间：2023-10-27\n\n用户输入：Hi"
        assert result == expected

    def test_clean_empty_lines(self):
        mgr = PromptManager(MagicMock())
        input_str = "Line 1\n\n\n\nLine 2\n\n\nLine 3"
        result = mgr._clean_empty_lines(input_str)
        assert result == "Line 1\n\nLine 2\n\nLine 3"

    @pytest.mark.asyncio
    async def test_create_template(self, mock_repo):
        mgr = PromptManager(mock_repo)
        mock_repo.create_template = AsyncMock()
        
        tmpl = await mgr.create_template("Test", "chat", "system", True)
        
        assert tmpl.name == "Test"
        assert tmpl.category == "chat"
        assert tmpl.slot_position == "system"
        assert tmpl.is_system is True
        mock_repo.create_template.assert_called_once_with(tmpl)

    @pytest.mark.asyncio
    async def test_create_version(self, mock_repo):
        mgr = PromptManager(mock_repo)
        mock_repo.get_versions_by_template = AsyncMock(return_value=[
            PromptVersion(version_num=2)
        ])
        mock_repo.create_version = AsyncMock()
        
        version = await mgr.create_version("tmpl-1", "content", "[\"var1\"]")
        
        assert version.template_id == "tmpl-1"
        assert version.version_num == 3
        assert version.content == "content"
        assert version.variables == ["var1"]
        assert version.status == "draft"
        mock_repo.create_version.assert_called_once_with(version)

    @pytest.mark.asyncio
    async def test_publish_version(self, mock_repo, mock_cache):
        mgr = PromptManager(mock_repo, mock_cache)
        
        # 模拟事务执行
        async def mock_run_in_transaction(fn):
            await fn(mock_repo)
            
        mock_repo.run_in_transaction = AsyncMock(side_effect=mock_run_in_transaction)
        
        tmpl = PromptTemplate(id="tmpl-1", category="chat")
        mock_repo.get_template = AsyncMock(return_value=tmpl)
        
        version = PromptVersion(id="ver-2", template_id="tmpl-1", status="draft")
        mock_repo.get_version = AsyncMock(return_value=version)
        
        old_version = PromptVersion(id="ver-1", template_id="tmpl-1", status="published")
        mock_repo.get_versions_by_template = AsyncMock(return_value=[old_version, version])
        
        mock_repo.update_version = AsyncMock()
        mock_repo.update_template = AsyncMock()
        
        await mgr.publish_version("tmpl-1", "ver-2")
        
        assert old_version.status == "deprecated"
        assert version.status == "published"
        assert tmpl.active_version_id == "ver-2"
        
        assert mock_repo.update_version.call_count == 2
        mock_repo.update_template.assert_called_once_with(tmpl)
        mock_cache.invalidate_cache.assert_called_once_with(PromptCategory.CHAT)


# ============================================================
# 3. Memory Manager 测试
# ============================================================

class TestMemoryManager:
    """验证 Memory Manager 与 Go manager.go 一致"""

    @pytest.fixture
    def mock_deps(self):
        redis_repo = MagicMock()
        ltm_pg_repo = MagicMock()
        ltm_qdrant_repo = MagicMock()
        prompt_mgr = MagicMock()
        qdrant_client = MagicMock()
        inference_svc = MagicMock()
        
        return {
            "redis_repo": redis_repo,
            "ltm_pg_repo": ltm_pg_repo,
            "ltm_qdrant_repo": ltm_qdrant_repo,
            "prompt_mgr": prompt_mgr,
            "qdrant_client": qdrant_client,
            "inference_svc": inference_svc,
            "retrieval_top_k": 5
        }

    @pytest.mark.asyncio
    async def test_init(self, mock_deps):
        mgr = MemoryManager(**mock_deps)
        
        mock_deps["ltm_qdrant_repo"].ensure_collection = AsyncMock()
        mgr._detect_and_cleanup_historical_sessions = AsyncMock()
        
        await mgr.init()
        
        mock_deps["ltm_qdrant_repo"].ensure_collection.assert_called_once_with(768)
        mgr._detect_and_cleanup_historical_sessions.assert_called_once()

    @pytest.mark.asyncio
    async def test_detect_and_cleanup_historical_sessions(self, mock_deps):
        mgr = MemoryManager(**mock_deps)
        
        today = datetime.now().strftime("%Y%m%d")
        mock_deps["redis_repo"].get_all_session_ids = AsyncMock(return_value=["old-session", today])
        
        mgr._compress_and_commit = AsyncMock()
        mock_deps["redis_repo"].delete_session = AsyncMock()
        
        await mgr._detect_and_cleanup_historical_sessions()
        
        mgr._compress_and_commit.assert_called_once_with("old-session")
        mock_deps["redis_repo"].delete_session.assert_called_once_with("old-session")

    @pytest.mark.asyncio
    async def test_compress_and_commit(self, mock_deps):
        mgr = MemoryManager(**mock_deps)
        
        # 模拟 Redis 数据
        summary = ChatSummary(core_summary="core", key_facts="facts")
        history = [
            Interaction(msgId="1", userContent="u1", assistantContent="a1", timestamp=1),
            Interaction(msgId="2", userContent="u2", assistantContent="a2", thought="t2", emotion="e2", timestamp=2)
        ]
        mock_deps["redis_repo"].get_context = AsyncMock(return_value=(summary, history))
        
        # 模拟 Prompt 组装
        mock_deps["prompt_mgr"].assemble_prompt = AsyncMock(return_value="full prompt")
        
        # 模拟 PG 保存
        mock_deps["ltm_pg_repo"].save = AsyncMock()
        
        # 模拟 Embedding 和 Qdrant 保存
        mock_deps["inference_svc"].get_embedding_vector = AsyncMock(return_value=[0.1, 0.2])
        mock_deps["ltm_qdrant_repo"].save_with_vector = AsyncMock()
        
        # 监听事件
        received_events = []
        async def handler(event):
            received_events.append(event)
        await mgr.on_event(handler)
        
        with patch("app.api.internal_service.internal_service") as mock_internal:
            mock_internal.long_summarize = AsyncMock(return_value="compressed summary")
            
            await mgr._compress_and_commit("session-1")
            
            # 验证 Prompt 组装参数
            mock_deps["prompt_mgr"].assemble_prompt.assert_called_once()
            args, _ = mock_deps["prompt_mgr"].assemble_prompt.call_args
            assert args[0] == PromptCategory.LONG_SUMMARY
            assert args[1]["CURRENT_CORE_SUMMARY"] == "core"
            assert args[1]["CURRENT_KEY_FACTS"] == "facts"
            assert "[对话 1]" in args[1]["MESSAGES_TEXT"]
            assert "(内心独白: t2)" in args[1]["MESSAGES_TEXT"]
            
            # 验证 PG 保存
            mock_deps["ltm_pg_repo"].save.assert_called_once()
            saved_memory = mock_deps["ltm_pg_repo"].save.call_args[0][0]
            assert saved_memory.session_id == "session-1"
            assert saved_memory.summary == "compressed summary"
            assert saved_memory.status == MemoryStatus.ACTIVE.value
            
            # 验证 Qdrant 保存
            mock_deps["ltm_qdrant_repo"].save_with_vector.assert_called_once_with(
                saved_memory.id, "session-1", [0.1, 0.2], MemoryStatus.ACTIVE.value
            )
            
            # 验证事件触发
            await asyncio.sleep(0.1)
            assert len(received_events) == 1
            assert received_events[0].type == MemoryEventType.EVENT_MEMORY_SYNC
            assert received_events[0].payload["session_id"] == "session-1"

    @pytest.mark.asyncio
    async def test_rollover_session(self, mock_deps):
        mgr = MemoryManager(**mock_deps)
        
        today = datetime.now().strftime("%Y%m%d")
        
        # 测试当天，不流转
        new_session = await mgr.rollover_session(today)
        assert new_session == today
        
        # 测试跨天，流转
        mgr._compress_and_commit = AsyncMock()
        mock_deps["redis_repo"].delete_session = AsyncMock()
        
        new_session = await mgr.rollover_session("old-session")
        assert new_session == today
        mgr._compress_and_commit.assert_called_once_with("old-session")
        mock_deps["redis_repo"].delete_session.assert_called_once_with("old-session")

    @pytest.mark.asyncio
    async def test_retrieve_long_term_memories(self, mock_deps):
        mgr = MemoryManager(**mock_deps)
        
        # 模拟 Embedding
        mock_deps["inference_svc"].get_embedding_vector = AsyncMock(return_value=[0.1, 0.2])
        
        # 模拟 Qdrant 检索
        mock_qdrant_result1 = MagicMock()
        mock_qdrant_result1.payload = {"memory_id": "mem-1"}
        mock_qdrant_result2 = MagicMock()
        mock_qdrant_result2.payload = {"memory_id": "mem-2"}
        mock_deps["ltm_qdrant_repo"].search_by_vector = AsyncMock(return_value=[mock_qdrant_result1, mock_qdrant_result2])
        
        # 模拟 PG 拉取
        mem1 = LongTermMemory(id="mem-1", summary="summary 1")
        mem2 = LongTermMemory(id="mem-2", summary="summary 2")
        mock_deps["ltm_pg_repo"].get_by_ids = AsyncMock(return_value=[mem1, mem2])
        
        # 模拟 Rerank
        mock_deps["inference_svc"].rerank_documents = AsyncMock(return_value=[
            {"index": 1, "score": 0.9}, # mem2 排前面
            {"index": 0, "score": 0.8}  # mem1 排后面
        ])
        
        results = await mgr.retrieve_long_term_memories("query", [])
        
        assert len(results) == 2
        assert results[0].id == "mem-2"
        assert results[1].id == "mem-1"
        
        mock_deps["inference_svc"].get_embedding_vector.assert_called_once_with("query")
        mock_deps["ltm_qdrant_repo"].search_by_vector.assert_called_once_with([0.1, 0.2], 15) # top_k * 3
        mock_deps["ltm_pg_repo"].get_by_ids.assert_called_once_with(["mem-1", "mem-2"])
        mock_deps["inference_svc"].rerank_documents.assert_called_once_with("query", ["summary 1", "summary 2"])
