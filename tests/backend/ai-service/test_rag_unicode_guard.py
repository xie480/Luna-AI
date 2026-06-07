import pytest

from app.rag.loaders import DocumentLoader
from app.rag.retrieval import RagRetrievalOrchestrator
from app.rag.types import RagEvidence
from app.rag.unicode_guard import inspect_unicode_text, sanitize_text_for_rag
from app.types.constants import RagSourceType


def test_unicode_guard_reports_pdf_dirty_unicode_without_flagging_plain_chinese():
    """验证 Unicode Guard 能区分正常中文与 PDF 抽取产生的脏字符。"""
    clean_text = "这是正常中文，包含特殊符号①℃™和换行。\n第二行保持。"
    clean_report = inspect_unicode_text(clean_text, "正常中文样本")

    assert not clean_report.has_anomaly
    assert clean_report.literal_question_mark_count == 0

    dirty_text = "中\ufffd文\ue000脏字\u200b和康熙部首：\u2f34\u2f6c"
    dirty_report = inspect_unicode_text(dirty_text, "PDF脏字符样本")

    assert dirty_report.has_anomaly
    assert dirty_report.replacement_count == 1
    assert dirty_report.private_use_count == 1
    assert dirty_report.invisible_format_count >= 1
    assert dirty_report.suspicious_compat_count == 2


def test_sanitize_text_for_rag_removes_irreversible_pdf_garbage_and_preserves_symbols():
    """验证安全清洗不回填问号，只移除不可逆脏字符并保留合法特殊符号与换行。"""
    dirty_text = "标题①℃™：中\ufffd文\ue000\u200b\x00\n路径? 保留问号\n部首\u2f34\u2f6c"

    cleaned = sanitize_text_for_rag(dirty_text)

    assert "�" not in cleaned
    assert "\ue000" not in cleaned
    assert "\u200b" not in cleaned
    assert "\x00" not in cleaned
    assert "①℃™" in cleaned
    assert "路径? 保留问号" in cleaned
    assert "广目" in cleaned
    assert "\n" in cleaned

    report = inspect_unicode_text(cleaned, "清洗后样本")
    assert not report.has_anomaly


def test_document_loader_normalize_text_applies_safe_pdf_unicode_cleanup():
    """验证加载器归一化阶段会清理 PDF Unicode 污点并保留段落边界。"""
    raw_text = "第一段：正常中文①℃™\r\n\r\n第二段：\ufffd\ue000\u200b康熙部首\u2f34\u2f6c"

    cleaned = DocumentLoader._normalize_text(raw_text)

    assert "第一段：正常中文①℃™" in cleaned
    assert "第二段：康熙部首广目" in cleaned
    assert "�" not in cleaned
    assert "\ue000" not in cleaned
    assert "\u200b" not in cleaned
    assert "\n\n" in cleaned


def test_prompt_context_sanitizes_dirty_pdf_evidence_before_injection():
    """验证 Prompt 注入前会再次清洗 PDF 脏字符，避免最终提示词继承不可逆 Unicode 污点。"""
    evidence = RagEvidence(
        citation_id=1,
        document_id="2001",
        document_name="测试PDF.pdf",
        chunk_id="3001",
        parent_id=None,
        content="PDF正文：中\ufffd文\ue000\u200b部首\u2f34\u2f6c\n特殊符号①℃™",
        score=0.9,
        source_type=RagSourceType.LOCAL_FILE,
        metadata={"source_type": "local_file"},
    )

    prompt_context = RagRetrievalOrchestrator._format_prompt_context([evidence])

    assert "PDF正文：中文部首广目" in prompt_context
    assert "特殊符号①℃™" in prompt_context
    assert "�" not in prompt_context
    assert "\ue000" not in prompt_context
    assert "\u200b" not in prompt_context

    report = inspect_unicode_text(prompt_context, "Prompt上下文测试")
    assert not report.has_anomaly
