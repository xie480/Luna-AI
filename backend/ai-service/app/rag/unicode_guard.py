"""
Luna RAG Unicode 污点检测与安全清洗模块

做什么：集中检测 PDF 抽取文本、Chunk 正文和 Prompt 注入文本中的异常 Unicode 字符。
为什么这样做：PDF 内嵌字体和 ToUnicode CMap 不完整时，pdfplumber 可能返回私用区字符、替代字符、
          康熙部首、兼容区字符或不可见控制字符；这些字符如果不在摄入入口识别，会被 PostgreSQL、
          检索和 Prompt 拼接原样继承，造成“看起来像日志乱码”的脏数据问题。
输入输出：输入 Python str，输出 UnicodeInspectionReport 或清洗后的 str。
边界条件：不对普通中文、中文标点、数学符号、货币符号和换行做破坏性替换；只移除明确不可作为正文的
        替代字符、私用区字符、孤立代理项和不可见控制/格式字符。
异常行为：本模块不抛业务异常；发现不可逆字符丢失时由调用方记录告警并继续摄入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata


@dataclass(frozen=True)
class UnicodeIssueSample:
    """
    Unicode 异常字符样本。

    做什么：记录异常字符的码点、类别、名称、出现次数和周边上下文。
    为什么这样做：日志不能只说“有乱码”，必须能定位是 U+FFFD、私用区还是 PDF 兼容字符。
    """

    char: str
    codepoint: str
    category: str
    name: str
    count: int
    context: str

    def to_log_text(self) -> str:
        """转换为紧凑日志文本，避免输出整段正文。"""
        safe_context = self.context.replace("\n", "\\n")
        return (
            f"char={self.char!r} codepoint={self.codepoint} category={self.category} "
            f"name={self.name} count={self.count} context={safe_context!r}"
        )


@dataclass(frozen=True)
class UnicodeInspectionReport:
    """
    Unicode 文本检测报告。

    做什么：统计文本中会影响 PDF RAG 的异常 Unicode 类型。
    为什么这样做：区分“真实字符串已经脏了”和“日志编码显示问题”，避免用替换问号掩盖根因。
    """

    stage: str
    text_length: int
    replacement_count: int = 0
    private_use_count: int = 0
    surrogate_count: int = 0
    invisible_format_count: int = 0
    control_count: int = 0
    suspicious_compat_count: int = 0
    literal_question_mark_count: int = 0
    normalized_changed_count: int = 0
    samples: list[UnicodeIssueSample] = field(default_factory=list)

    @property
    def has_anomaly(self) -> bool:
        """是否存在需要关注的 Unicode 污点。"""
        return any(
            count > 0
            for count in (
                self.replacement_count,
                self.private_use_count,
                self.surrogate_count,
                self.invisible_format_count,
                self.control_count,
                self.suspicious_compat_count,
                self.normalized_changed_count,
            )
        )

    def to_log_text(self) -> str:
        """转换为结构化但易读的中文日志片段。"""
        sample_text = "; ".join(sample.to_log_text() for sample in self.samples)
        return (
            f"stage={self.stage} text_length={self.text_length} "
            f"replacement={self.replacement_count} private_use={self.private_use_count} "
            f"surrogate={self.surrogate_count} invisible_format={self.invisible_format_count} "
            f"control={self.control_count} suspicious_compat={self.suspicious_compat_count} "
            f"literal_question_mark={self.literal_question_mark_count} "
            f"normalized_changed={self.normalized_changed_count} samples=[{sample_text}]"
        )


_ALLOWED_CONTROL_CHARS = {"\n", "\t"}
_ZERO_WIDTH_OR_FORMAT_CHARS = {
    "\ufeff",  # BOM / ZERO WIDTH NO-BREAK SPACE
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\u2060",  # WORD JOINER
}


def _is_private_use(char: str) -> bool:
    """判断字符是否属于 Unicode 私用区。"""
    codepoint = ord(char)
    return (
        0xE000 <= codepoint <= 0xF8FF
        or 0xF0000 <= codepoint <= 0xFFFFD
        or 0x100000 <= codepoint <= 0x10FFFD
    )


def _is_surrogate(char: str) -> bool:
    """判断字符是否为孤立代理项。"""
    return 0xD800 <= ord(char) <= 0xDFFF


def _is_suspicious_compat_char(char: str) -> bool:
    """
    判断是否为 PDF 中常见的可疑兼容/部首字符。

    做什么：仅标记 CJK 兼容表意文字、康熙部首和 CJK 部首补充区。
    为什么这样做：这些字符经常来自 PDF 字形映射错误；但普通生僻汉字不应被误删。
    """
    codepoint = ord(char)
    return (
        0x2E80 <= codepoint <= 0x2EFF  # CJK Radicals Supplement
        or 0x2F00 <= codepoint <= 0x2FDF  # Kangxi Radicals
        or 0xF900 <= codepoint <= 0xFAFF  # CJK Compatibility Ideographs
        or 0x2F800 <= codepoint <= 0x2FA1F  # CJK Compatibility Ideographs Supplement
    )


def _is_invisible_format_char(char: str) -> bool:
    """判断是否为不可见格式字符。"""
    return char in _ZERO_WIDTH_OR_FORMAT_CHARS or unicodedata.category(char) == "Cf"


def _is_disallowed_control_char(char: str) -> bool:
    """判断是否为正文中不允许保留的控制字符。"""
    return unicodedata.category(char) == "Cc" and char not in _ALLOWED_CONTROL_CHARS


def _context_at(text: str, index: int, radius: int = 8) -> str:
    """截取异常字符周边上下文，辅助定位 PDF 页内位置。"""
    start = max(0, index - radius)
    end = min(len(text), index + radius + 1)
    return text[start:end]


def _normalized_pdf_char(char: str) -> str:
    """
    对 PDF 常见兼容字符做定向正规化。

    做什么：只对可疑 CJK 兼容/部首字符应用 NFKC。
    为什么这样做：全量 NFKC 会把 ①、℃、全角中文标点等有意义符号改写，影响“特殊符号保持正常”。
    """
    if not _is_suspicious_compat_char(char):
        return char
    normalized = unicodedata.normalize("NFKC", char)
    return normalized if normalized else char


def inspect_unicode_text(text: str, stage: str, sample_limit: int = 8) -> UnicodeInspectionReport:
    """
    检测文本中的 Unicode 污点。

    输入输出：输入任意 str 和阶段名，输出统计报告。
    边界条件：空文本返回零计数；样本数量受 sample_limit 限制，避免日志过长。
    """
    counters = {
        "replacement": 0,
        "private_use": 0,
        "surrogate": 0,
        "invisible_format": 0,
        "control": 0,
        "suspicious_compat": 0,
        "literal_question_mark": text.count("?"),
        "normalized_changed": 0,
    }
    sample_map: dict[tuple[str, str], UnicodeIssueSample] = {}

    def add_sample(issue_type: str, char: str, index: int) -> None:
        if len(sample_map) >= sample_limit and (issue_type, char) not in sample_map:
            return
        key = (issue_type, char)
        existing = sample_map.get(key)
        if existing:
            sample_map[key] = UnicodeIssueSample(
                char=existing.char,
                codepoint=existing.codepoint,
                category=existing.category,
                name=existing.name,
                count=existing.count + 1,
                context=existing.context,
            )
            return
        sample_map[key] = UnicodeIssueSample(
            char=char,
            codepoint=f"U+{ord(char):04X}",
            category=unicodedata.category(char),
            name=unicodedata.name(char, "UNKNOWN"),
            count=1,
            context=_context_at(text, index),
        )

    for index, char in enumerate(text):
        if char == "\ufffd":
            counters["replacement"] += 1
            add_sample("replacement", char, index)
        if _is_private_use(char):
            counters["private_use"] += 1
            add_sample("private_use", char, index)
        if _is_surrogate(char):
            counters["surrogate"] += 1
            add_sample("surrogate", char, index)
        if _is_invisible_format_char(char):
            counters["invisible_format"] += 1
            add_sample("invisible_format", char, index)
        if _is_disallowed_control_char(char):
            counters["control"] += 1
            add_sample("control", char, index)
        if _is_suspicious_compat_char(char):
            counters["suspicious_compat"] += 1
            add_sample("suspicious_compat", char, index)
            if _normalized_pdf_char(char) != char:
                counters["normalized_changed"] += 1

    return UnicodeInspectionReport(
        stage=stage,
        text_length=len(text),
        replacement_count=counters["replacement"],
        private_use_count=counters["private_use"],
        surrogate_count=counters["surrogate"],
        invisible_format_count=counters["invisible_format"],
        control_count=counters["control"],
        suspicious_compat_count=counters["suspicious_compat"],
        literal_question_mark_count=counters["literal_question_mark"],
        normalized_changed_count=counters["normalized_changed"],
        samples=list(sample_map.values()),
    )


def sanitize_text_for_rag(text: str) -> str:
    """
    对 RAG 正文执行安全 Unicode 清洗。

    做什么：保留普通中文、中文标点、特殊符号和换行；移除不可见/不可逆脏字符；定向修复 PDF 兼容汉字。
    为什么这样做：避免把 PDF 字形映射错误产生的 Unicode 污点写入 PostgreSQL 和 Prompt。
    边界条件：不会把普通问号替换回中文，因为问号可能是合法正文，也可能是 PDF 已不可逆丢字。
    """
    if not text:
        return ""

    # 先统一换行，保证后续控制字符处理不会误删段落边界。
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_chars: list[str] = []

    for char in normalized_text:
        if char == "\ufffd":
            continue
        if _is_private_use(char) or _is_surrogate(char):
            continue
        if _is_invisible_format_char(char):
            continue
        if _is_disallowed_control_char(char):
            continue
        cleaned_chars.append(_normalized_pdf_char(char))

    cleaned = "".join(cleaned_chars)
    cleaned = cleaned.replace("\t", " ")
    cleaned = re.sub(r"[ \x0b\x0c]+", " ", cleaned)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned.strip()
