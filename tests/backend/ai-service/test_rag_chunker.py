import pytest
from app.rag.chunker import parse_long_summary_to_chunks
from app.types.constants import MemoryChunkType

def test_parse_long_summary_standard_format():
    full_summary = "梗概：这是测试梗概内容。 \n 关键事实：1.事实1;2.事实2;3.事实3;"
    chunks = parse_long_summary_to_chunks(full_summary)
    
    assert len(chunks) == 4
    assert chunks[0].chunk_type == MemoryChunkType.SUMMARY
    assert chunks[0].content == "这是测试梗概内容。"
    
    assert chunks[1].chunk_type == MemoryChunkType.FACT
    assert chunks[1].content == "事实1"
    
    assert chunks[2].chunk_type == MemoryChunkType.FACT
    assert chunks[2].content == "事实2"
    
    assert chunks[3].chunk_type == MemoryChunkType.FACT
    assert chunks[3].content == "事实3"

def test_parse_long_summary_without_trailing_semicolon():
    full_summary = "梗概：测试\n关键事实：1. A; 2. B"
    chunks = parse_long_summary_to_chunks(full_summary)
    
    assert len(chunks) == 3
    assert chunks[0].chunk_type == MemoryChunkType.SUMMARY
    assert chunks[0].content == "测试"
    
    assert chunks[1].chunk_type == MemoryChunkType.FACT
    assert chunks[1].content == "A"
    
    assert chunks[2].chunk_type == MemoryChunkType.FACT
    assert chunks[2].content == "B"

def test_parse_long_summary_invalid_format_fallback():
    full_summary = "这是一段完全不符合格式的长文本。没有特征符。"
    chunks = parse_long_summary_to_chunks(full_summary)
    
    assert len(chunks) == 1
    assert chunks[0].chunk_type == MemoryChunkType.SUMMARY
    assert chunks[0].content == full_summary

def test_parse_long_summary_empty_facts():
    full_summary = "梗概：有梗概没事实\n关键事实："
    chunks = parse_long_summary_to_chunks(full_summary)
    
    assert len(chunks) == 1
    assert chunks[0].chunk_type == MemoryChunkType.SUMMARY
    assert chunks[0].content == "有梗概没事实"

def test_parse_long_summary_no_numbering_facts():
    full_summary = "梗概：测试\n关键事实：事实A;事实B;"
    chunks = parse_long_summary_to_chunks(full_summary)
    
    assert len(chunks) == 3
    assert chunks[1].chunk_type == MemoryChunkType.FACT
    assert chunks[1].content == "事实A"
    assert chunks[2].chunk_type == MemoryChunkType.FACT
    assert chunks[2].content == "事实B"
