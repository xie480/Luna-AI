import pytest

from app.rag.chunker import (
    ChunkerConfig,
    RegexChunker,
    SemanticParentChildChunker,
    SlidingWindowChunker,
    StructuredASTChunker,
    parse_long_summary_to_chunks,
)
from app.types.constants import MemoryChunkType


def test_parse_long_summary_standard_format():
    """验证长期摘要按梗概与事实拆分，保障 Phase 6 记忆切片契约不回退。"""
    full_summary = "梗概：这是测试梗概内容。 \n 关键事实：1.事实1;2.事实2;3.事实3;"
    chunks = parse_long_summary_to_chunks(full_summary)

    assert len(chunks) == 4
    assert chunks[0].chunk_type == MemoryChunkType.SUMMARY
    assert chunks[0].content == "这是测试梗概内容。"
    assert chunks[1].chunk_type == MemoryChunkType.FACT
    assert chunks[1].content == "事实1"
    assert chunks[2].content == "事实2"
    assert chunks[3].content == "事实3"


def test_parse_long_summary_invalid_format_uses_summary_chunk():
    """验证非标准长期摘要不会伪造事实，而是保留全文作为梗概。"""
    full_summary = "这是一段完全不符合格式的长文本。没有特征符。"
    chunks = parse_long_summary_to_chunks(full_summary)

    assert len(chunks) == 1
    assert chunks[0].chunk_type == MemoryChunkType.SUMMARY
    assert chunks[0].content == full_summary


def test_structured_ast_chunker_injects_heading_prefix():
    """验证 Markdown 标题链路会注入正文，避免子块脱离标题后语义丢失。"""
    text = "# 系统架构\n\n## 数据库初始化\n\n执行 PostgreSQL 初始化命令。"
    chunks = StructuredASTChunker(ChunkerConfig(chunk_size=120, overlap=10)).chunk("1001", text)

    assert chunks
    assert "[H1: 系统架构]" in chunks[0].text
    assert "[H2: 数据库初始化]" in chunks[0].text
    assert chunks[0].metadata["strategy"] == "structured_ast"


def test_semantic_parent_child_chunker_generates_parent_and_child_links():
    """验证父子级联切片会同时生成 parent 与 child，并让 child 关联 parent_id。"""
    text = "第一段说明系统目标。第二句补充边界。\n\n第二段说明执行步骤。"
    chunks = SemanticParentChildChunker(ChunkerConfig(chunk_size=30, overlap=5)).chunk("1002", text)

    parent_ids = {chunk.chunk_id for chunk in chunks if chunk.metadata.get("chunk_role") == "parent"}
    child_parent_ids = {chunk.parent_id for chunk in chunks if chunk.metadata.get("chunk_role") == "child"}
    assert parent_ids
    assert child_parent_ids - {None}
    assert (child_parent_ids - {None}).issubset(parent_ids)


def test_regex_chunker_rejects_catastrophic_pattern():
    """验证高风险正则会被预检拒绝，避免灾难性回溯锁死服务。"""
    chunker = RegexChunker(ChunkerConfig(regex_pattern="(.*)*", max_fallback_tokens=80))

    with pytest.raises(ValueError, match="灾难性回溯"):
        chunker.chunk("1003", "任意文本")


def test_sliding_window_chunker_force_splits_oversized_text():
    """验证滑动窗口对超长文本执行安全拆分并写入警告元数据。"""
    text = "\n\n".join(["这是一段较长的知识内容，用于触发安全切分。" for _ in range(80)])
    chunks = SlidingWindowChunker(
        ChunkerConfig(chunk_size=80, overlap=10, max_fallback_tokens=120)
    ).chunk("1004", text)

    assert len(chunks) > 1
    assert all(chunk.estimated_tokens <= 120 for chunk in chunks)
