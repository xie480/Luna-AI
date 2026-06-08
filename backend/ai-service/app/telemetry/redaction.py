"""
压缩审计预览脱敏工具。

做什么：为上下文压缩审计与回放生成最小必要、可解释、可展示的脱敏预览文本。
为什么这样做：压缩回放必须说明“压缩了什么”，但不能完整保存敏感原文。
输入输出：
    - 输入原始文本与预览长度限制。
    - 输出统一清洗、脱敏、折叠后的短预览文本。
边界条件：
    - 空文本返回空字符串。
    - 超长文本只保留头尾片段，避免审计详情膨胀。
异常行为：
    - 本模块不抛业务异常；正则处理失败时由 Python 运行时异常直接暴露给调用方记录。
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED_EMAIL = "[REDACTED_EMAIL]"
REDACTED_SECRET = "[REDACTED_SECRET]"
REDACTED_QUERY = "[REDACTED_QUERY]"
WHITESPACE_PATTERN = re.compile(r"\s+")
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
# 做什么：识别常见 Bearer、sk-、token、apikey 等高风险凭证片段。
# 为什么这样做：压缩预览中最容易泄露的是复制进上下文的临时令牌和 API Key。
SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9._\-]{8,}|sk-[a-z0-9\-_]{8,}|api[_-]?key\s*[:=]\s*[^\s]+|token\s*[:=]\s*[^\s]+|secret\s*[:=]\s*[^\s]+)"
)
URL_PATTERN = re.compile(r"https?://[^\s]+")


def _redact_url_query(url: str) -> str:
    """
    脱敏 URL 查询参数。

    做什么：保留协议、域名与路径，统一替换查询参数的 value。
    为什么这样做：查询参数中常含签名、token、邮箱等敏感信息，但路径本身对定位问题仍有价值。
    输入输出：输入完整 URL，输出查询参数已脱敏的 URL。
    边界条件：没有查询参数时原样返回。
    异常行为：URL 解析异常时返回原始 URL，由上游继续其它脱敏步骤。
    """
    try:
        parts = urlsplit(url)
        if not parts.query:
            return url
        query_items = parse_qsl(parts.query, keep_blank_values=True)
        redacted_query = "&".join([f"{key}={REDACTED_QUERY}" for key, _ in query_items])
        return urlunsplit((parts.scheme, parts.netloc, parts.path, redacted_query, parts.fragment))
    except Exception:
        return url


def _collapse_whitespace(text: str) -> str:
    """
    折叠空白字符。

    做什么：把换行、制表与连续空格压缩为单空格。
    为什么这样做：审计预览目标是解释问题，不需要保留原文排版细节。
    输入输出：输入任意文本，输出单行紧凑文本。
    边界条件：空字符串返回空字符串。
    异常行为：本函数不主动抛业务异常。
    """
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def redact_preview_text(text: str, max_chars: int) -> str:
    """
    生成脱敏后的压缩预览文本。

    做什么：统一执行邮箱、密钥、URL 查询参数脱敏，并按长度限制裁剪为头尾预览。
    为什么这样做：回放需要最小可解释文本，不能直接把完整原始上下文写入审计日志。
    输入输出：输入原始文本和最大预览字符数，输出脱敏预览。
    边界条件：max_chars 小于等于 16 时仍返回最多 max_chars 个字符，避免空结果。
    异常行为：正则处理异常由调用方捕获并写日志，不在此处吞错。
    """
    if not text:
        return ""

    normalized_text = _collapse_whitespace(text)
    normalized_text = EMAIL_PATTERN.sub(REDACTED_EMAIL, normalized_text)
    normalized_text = SECRET_PATTERN.sub(REDACTED_SECRET, normalized_text)
    normalized_text = URL_PATTERN.sub(lambda match: _redact_url_query(match.group(0)), normalized_text)

    if max_chars <= 0:
        return ""
    if len(normalized_text) <= max_chars:
        return normalized_text
    if max_chars <= 16:
        return normalized_text[:max_chars]

    head_length = max_chars // 2
    tail_length = max_chars - head_length - 5
    if tail_length <= 0:
        return normalized_text[:max_chars]
    return f"{normalized_text[:head_length]} ... {normalized_text[-tail_length:]}"
