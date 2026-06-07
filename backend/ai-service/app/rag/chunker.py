"""
Luna RAG 切片引擎模块

做什么：实现 Phase 7 规划中的四维切片策略：滑动窗口、结构化 AST、语义父子级联、正则安全切片。
为什么这样做：不同来源的知识文本噪声与结构差异极大，必须在 Python 后端统一控制切片生命周期。
输入输出：输入清洗后的 UTF-8 文本，输出带 Snowflake ID、Token 估算和元数据的 ChunkUnit 列表。
边界条件：任何策略都不允许产生空切片或超过 max_fallback_tokens 的超长切片。
异常行为：策略参数非法、正则风险过高或文本为空时抛出明确异常。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.logger import logger
from app.rag.types import ChunkUnit
from app.types.constants import MemoryChunkType, RagChunkStrategy
from app.utils.snowflake import generate_string_id


class MemoryChunk(BaseModel):
    """
    长期记忆摘要切片。

    做什么：保留 Phase 6 长期记忆摘要拆分契约。
    为什么这样做：长期记忆与知识库 RAG 共用向量检索基础设施，但二者实体边界不同。
    输入输出：输入摘要中的梗概或事实文本，输出可向量化的记忆切片。
    边界条件：content 不能为空。
    异常行为：由 Pydantic 校验非法字段。
    """

    chunk_type: MemoryChunkType
    content: str


@dataclass(frozen=True)
class ChunkerConfig:
    """
    切片器配置。

    做什么：集中管理切片大小、重叠、正则阈值等运行参数。
    为什么这样做：避免魔法数字散落在切片算法中。
    """

    chunk_size: int = 500
    overlap: int = 50
    max_fallback_tokens: int = 1200
    regex_pattern: str | None = None


class TokenEstimator:
    """
    Token 估算器。

    做什么：优先使用 tiktoken 估算 Token，依赖不可用时使用中英文混合启发式估算。
    为什么这样做：切片安全阈值不能依赖固定字符数，否则中文与英文文本会出现严重偏差。
    异常行为：tiktoken 初始化失败会记录日志并使用启发式估算，不影响服务启动。
    """

    def __init__(self) -> None:
        self._encoding: Any | None = None
        try:
            import tiktoken

            self._encoding = tiktoken.get_encoding("cl100k_base")
        except Exception as exc:
            logger.warning(f"Token 编码器初始化失败，使用启发式估算 error={exc}")

    def estimate(self, text: str) -> int:
        """估算文本 Token 数，最小返回 1。"""
        if not text:
            return 0
        if self._encoding is not None:
            return max(1, len(self._encoding.encode(text)))
        ascii_count = sum(1 for char in text if ord(char) < 128)
        non_ascii_count = len(text) - ascii_count
        return max(1, int(ascii_count / 4) + non_ascii_count)


_TOKEN_ESTIMATOR = TokenEstimator()


def estimate_tokens(text: str) -> int:
    """模块级 Token 估算函数，供加载器、仓库和服务复用。"""
    return _TOKEN_ESTIMATOR.estimate(text)


class BaseChunker(ABC):
    """
    RAG 切片器基类。

    做什么：统一派生切片器的输入校验、切片 ID 生成与超限切分逻辑。
    为什么这样做：所有策略都必须遵守相同安全边界，避免超长污点数据注入 Embedding。
    """

    def __init__(self, config: ChunkerConfig | None = None) -> None:
        self.config = config or ChunkerConfig()
        if self.config.chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        if self.config.overlap < 0:
            raise ValueError("overlap 不能为负数")
        if self.config.overlap >= self.config.chunk_size:
            raise ValueError("overlap 必须小于 chunk_size")

    @abstractmethod
    def chunk(self, document_id: str, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkUnit]:
        """将输入文本切分为 ChunkUnit 列表。"""

    def _build_chunk(
        self,
        document_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        parent_id: str | None = None,
        chunk_id: str | None = None,
    ) -> ChunkUnit:
        """创建标准 ChunkUnit，并执行空文本与 Token 估算。"""
        import hashlib
        import json

        cleaned = self._normalize_text(text)
        if not cleaned:
            raise ValueError("不能创建空切片")
        
        meta = metadata or {}
        # 为了保证增量比对的 chunk_hash 一致性，我们将文本与关键元数据混合做 Hash
        # 提取会影响内容语义的 metadata，如 title，但忽略动态或可变的警告标识
        hash_payload = cleaned
        summary = meta.get("summary", "")
        title = meta.get("title", "")
        if summary:
            hash_payload += f"|summary:{summary}"
        if title:
            hash_payload += f"|title:{title}"
            
        chunk_hash = hashlib.sha256(hash_payload.encode('utf-8')).hexdigest()

        return ChunkUnit(
            chunk_id=chunk_id or generate_string_id(),
            document_id=document_id,
            parent_id=parent_id,
            text=cleaned,
            estimated_tokens=estimate_tokens(cleaned),
            metadata=meta,
            chunk_hash=chunk_hash,
        )

    def _split_oversized_text(
        self,
        document_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        parent_id: str | None = None,
    ) -> list[ChunkUnit]:
        """
        对超限文本进行安全强拆。

        做什么：按接近 max_fallback_tokens 的换行或句末标点切分文本。
        为什么这样做：正则和结构化段落都可能产生超长块，必须在进入向量化前兜底。
        """
        cleaned = self._normalize_text(text)
        if not cleaned:
            return []
        if estimate_tokens(cleaned) <= self.config.max_fallback_tokens:
            return [self._build_chunk(document_id, cleaned, metadata, parent_id)]

        chunks: list[ChunkUnit] = []
        remaining = cleaned
        warning_metadata = dict(metadata or {})
        warning_metadata["warning"] = "chunk_exceeded_threshold_and_was_force_split"
        while remaining:
            if estimate_tokens(remaining) <= self.config.max_fallback_tokens:
                chunks.append(self._build_chunk(document_id, remaining, warning_metadata, parent_id))
                break
            split_pos = self._find_safe_split_position(remaining, self.config.max_fallback_tokens)
            part = remaining[:split_pos].strip()
            remaining = remaining[split_pos:].strip()
            if part:
                chunks.append(self._build_chunk(document_id, part, warning_metadata, parent_id))
        return chunks

    def _find_safe_split_position(self, text: str, max_tokens: int) -> int:
        """寻找尽量靠近阈值的安全切断点。"""
        if not text:
            return 0
        approx_chars = max(1, int(len(text) * max_tokens / max(estimate_tokens(text), 1)))
        approx_chars = min(max(approx_chars, 1), len(text))
        window = text[:approx_chars]
        candidates = [window.rfind(mark) for mark in ("\n\n", "\n", "。", ".", "！", "!", "？", "?")]
        best = max(candidates)
        if best > max(20, approx_chars // 2):
            return best + 1
        return approx_chars

    @staticmethod
    def _normalize_text(text: str) -> str:
        """标准化文本空白，保留段落边界。"""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[\t\x0b\x0c]+", " ", text)
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()


class SlidingWindowChunker(BaseChunker):
    """
    滑动窗口切片器。

    做什么：按 Token 估算窗口步进，并保留 overlap 重叠区。
    为什么这样做：通用文本缺少可靠结构时，滑窗能避免关键术语在边界被腰斩。
    """

    def chunk(self, document_id: str, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkUnit]:
        """
        将输入文本按滑动窗口策略切分为ChunkUnit列表。

        该方法首先将文本按段落分割，然后尝试将段落逐个添加到缓冲区中，
        当缓冲区内容超过指定的块大小时，将其添加到结果列表中。
        
        参数:
            document_id: 文档唯一标识符，用于关联切片与原始文档
            text: 待切片的原始文本内容
            metadata: 可选的元数据字典，包含与文本相关的附加信息
            
        返回:
            list[ChunkUnit]: 切片单元对象列表，每个元素代表一个文本块
        """
        # 清洗和验证输入文本
        cleaned = self._normalize_text(text)
        if not cleaned:
            raise ValueError("待切片文本不能为空")
        
        # 按双换行符分割文本为段落列表
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", cleaned) if part.strip()]
        chunks: list[ChunkUnit] = []
        buffer = ""
        
        # 遍历每个段落，决定如何将其添加到当前缓冲区或结果列表中
        for paragraph in paragraphs:
            # 构建候选字符串（如果缓冲区有内容则合并，否则单独使用段落）
            candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
            # 尝试将候选字符串添加到缓冲区中（如果其Token数量未超过限制）
            if estimate_tokens(candidate) <= self.config.chunk_size:
                buffer = candidate
                continue
            
            # 当前缓冲区的内容需要被处理（添加到结果列表中）
            if buffer:
                chunks.extend(self._split_oversized_text(document_id, buffer, metadata))

            # 处理当前段落（如果它本身超过了块大小限制，则进行特殊处理）
            if estimate_tokens(paragraph) > self.config.chunk_size:
                chunks.extend(self._split_long_paragraph(document_id, paragraph, metadata))
                buffer = ""
            else:
                buffer = paragraph
        
        # 处理缓冲区中剩余的内容
        if buffer:
            chunks.extend(self._split_oversized_text(document_id, buffer, metadata))
        return chunks

    def _split_long_paragraph(
        self,
        document_id: str,
        paragraph: str,
        metadata: dict[str, Any] | None,
    ) -> list[ChunkUnit]:
        """按字符游标拆分超长段落，同时保留重叠上下文。"""
        chunks: list[ChunkUnit] = []
        start = 0
        text_length = len(paragraph)
        while start < text_length:
            end = min(text_length, start + self.config.chunk_size * 2)
            segment = paragraph[start:end]
            while estimate_tokens(segment) > self.config.chunk_size and len(segment) > 1:
                segment = segment[: max(1, int(len(segment) * 0.85))]
                end = start + len(segment)
            chunks.extend(self._split_oversized_text(document_id, segment, metadata))
            if end >= text_length:
                break
            overlap_chars = min(len(segment), max(0, self.config.overlap * 2))
            start = max(end - overlap_chars, start + 1)
        return chunks


class StructuredASTChunker(BaseChunker):
    """
    Markdown 结构化 AST 切片器。

    做什么：识别 Markdown 标题层级，将标题链路前缀注入子块正文。
    为什么这样做：子块脱离标题后会丢失语义归属，标题前缀能提升召回和生成可解释性。
    """

    _heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    def chunk(self, document_id: str, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkUnit]:
        """
        使用结构化AST策略将Markdown文本切分为ChunkUnit列表。

        该方法解析Markdown标题层级，将标题链路前缀注入子块正文以保持语义完整性。
        当遇到标题时，会清空当前内容并更新标题栈；当遇到普通内容时，将其加入当前内容行列表。
        最后通过flush_current函数处理累积的内容块，若无有效块则回退到滑动窗口策略。

        参数:
            document_id: 文档唯一标识符，用于关联切片与原始文档
            text: 待切片的Markdown格式文本内容
            metadata: 可选的元数据字典，包含与文本相关的附加信息
            
        返回:
            list[ChunkUnit]: 切片单元对象列表，每个元素代表一个文本块，带有标题层级信息
        """
        cleaned = self._normalize_text(text)
        if not cleaned:
            raise ValueError("待切片文本不能为空")
        lines = cleaned.split("\n")
        heading_stack: list[tuple[int, str]] = []
        current_lines: list[str] = []
        current_meta = dict(metadata or {})
        chunks: list[ChunkUnit] = []

        def flush_current() -> None:
            # 当前内容块的刷新处理函数，将累积的行转换为切片
            if not current_lines:
                return
            body = "\n".join(current_lines).strip()
            if not body:
                current_lines.clear()
                return
            prefix = self._build_heading_prefix(heading_stack)
            enriched = f"{prefix}\n\n{body}" if prefix else body
            chunk_meta = dict(current_meta)
            chunk_meta["headings"] = [title for _, title in heading_stack]
            chunk_meta["strategy"] = RagChunkStrategy.STRUCTURED_AST.value
            chunks.extend(self._split_oversized_text(document_id, enriched, chunk_meta))
            current_lines.clear()

        for line in lines:
            match = self._heading_pattern.match(line)
            if match:
                # 检测到标题行时，先刷新当前内容块，再更新标题栈
                flush_current()
                level = len(match.group(1))
                title = match.group(2).strip()
                heading_stack = [(lv, name) for lv, name in heading_stack if lv < level]
                heading_stack.append((level, title))
                current_meta = dict(metadata or {})
                current_meta["title_level"] = f"H{level}"
                continue
            current_lines.append(line)
        flush_current()
        if not chunks:
            # 若无有效块生成，则回退到滑动窗口策略进行切片
            return SlidingWindowChunker(self.config).chunk(document_id, cleaned, metadata)
        return chunks

    @staticmethod
    def _build_heading_prefix(heading_stack: list[tuple[int, str]]) -> str:
        """构建 [H1: ...] > [H2: ...] 形式的层级前缀。"""
        if not heading_stack:
            return ""
        return "[来源: 知识库] > " + " > ".join(f"[H{level}: {title}]" for level, title in heading_stack)


class SemanticParentChildChunker(BaseChunker):
    """
    语义父子级联切片器。

    做什么：先生成父段落，再按自然句法生成子切片，子切片携带 parent_id。
    为什么这样做：向量匹配使用短文本提高召回精度，召回后可通过 parent_id 取回更大上下文。
    """

    _sentence_split_pattern = re.compile(r"(?<=[。！？.!?])\s+|\n{2,}")

    def chunk(self, document_id: str, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkUnit]:
        cleaned = self._normalize_text(text)
        if not cleaned:
            raise ValueError("待切片文本不能为空")
        parent_texts = self._build_parent_segments(cleaned)
        chunks: list[ChunkUnit] = []
        for parent_index, parent_text in enumerate(parent_texts):
            parent_id = generate_string_id()
            parent_meta = dict(metadata or {})
            parent_meta.update({"strategy": RagChunkStrategy.SEMANTIC_PARENT_CHILD.value, "chunk_role": "parent", "parent_index": parent_index})
            chunks.append(self._build_chunk(document_id, parent_text, parent_meta, chunk_id=parent_id))
            child_texts = self._build_child_segments(parent_text)
            for child_index, child_text in enumerate(child_texts):
                child_meta = dict(metadata or {})
                child_meta.update({"strategy": RagChunkStrategy.SEMANTIC_PARENT_CHILD.value, "chunk_role": "child", "child_index": child_index})
                chunks.extend(self._split_oversized_text(document_id, child_text, child_meta, parent_id=parent_id))
        return chunks

    def _build_parent_segments(self, text: str) -> list[str]:
        """按段落聚合父块，控制父块不超过安全阈值。"""
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
        if not paragraphs:
            paragraphs = [text]
        parents: list[str] = []
        buffer = ""
        for paragraph in paragraphs:
            candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
            if estimate_tokens(candidate) <= self.config.max_fallback_tokens:
                buffer = candidate
            else:
                if buffer:
                    parents.append(buffer)
                buffer = paragraph
        if buffer:
            parents.append(buffer)
        return parents

    def _build_child_segments(self, parent_text: str) -> list[str]:
        """按自然标点构建子切片，确保句法尽量完整。"""
        sentences = [item.strip() for item in self._sentence_split_pattern.split(parent_text) if item.strip()]
        children: list[str] = []
        buffer = ""
        for sentence in sentences:
            candidate = f"{buffer} {sentence}".strip() if buffer else sentence
            if estimate_tokens(candidate) <= self.config.chunk_size:
                buffer = candidate
            else:
                if buffer:
                    children.append(buffer)
                buffer = sentence
        if buffer:
            children.append(buffer)
        return children or [parent_text]


class RegexChunker(BaseChunker):
    """
    正则安全切片器。

    做什么：按用户正则匹配结果生成切片，并对危险模式与超长 group 执行强保护。
    为什么这样做：用户可控正则最容易导致灾难性回溯或超长切片，必须进行预检与阈值兜底。
    """

    _dangerous_patterns = (
        re.compile(r"\([^)]*[+*][^)]*\)[+*]"),
        re.compile(r"\.\*[+*]"),
        re.compile(r"\(\.\*\)\*"),
    )

    def chunk(self, document_id: str, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkUnit]:
        cleaned = self._normalize_text(text)
        if not cleaned:
            raise ValueError("待切片文本不能为空")
        pattern = self.config.regex_pattern
        if not pattern:
            raise ValueError("正则切片必须提供 regex_pattern")
        self._validate_regex_pattern(pattern)
        compiled = re.compile(pattern, re.MULTILINE | re.DOTALL)
        chunks: list[ChunkUnit] = []
        for index, match in enumerate(compiled.finditer(cleaned)):
            group_text = match.group(1) if match.groups() else match.group(0)
            chunk_meta = dict(metadata or {})
            chunk_meta.update({"strategy": RagChunkStrategy.REGEX.value, "regex_match_index": index})
            chunks.extend(self._split_oversized_text(document_id, group_text, chunk_meta))
            if len(chunks) >= 500:
                logger.warning("正则切片命中过多，已按 500 个切片上限截断")
                break
        if not chunks:
            raise ValueError("正则未匹配到任何可用文本")
        return chunks

    def _validate_regex_pattern(self, pattern: str) -> None:
        """预检高风险正则，降低灾难性回溯风险。"""
        for dangerous_pattern in self._dangerous_patterns:
            if dangerous_pattern.search(pattern):
                raise ValueError("正则表达式存在灾难性回溯风险")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"正则表达式无法编译: {exc}") from exc


def build_chunker(strategy: RagChunkStrategy, config: ChunkerConfig | None = None) -> BaseChunker:
    """根据策略枚举创建切片器。"""
    if strategy == RagChunkStrategy.SLIDING_WINDOW:
        return SlidingWindowChunker(config)
    if strategy == RagChunkStrategy.STRUCTURED_AST:
        return StructuredASTChunker(config)
    if strategy == RagChunkStrategy.SEMANTIC_PARENT_CHILD:
        return SemanticParentChildChunker(config)
    if strategy == RagChunkStrategy.REGEX:
        return RegexChunker(config)
    raise ValueError(f"不支持的切片策略: {strategy}")


def parse_long_summary_to_chunks(full_summary: str) -> list[MemoryChunk]:
    """
    将结构化长期摘要拆分为独立语义块。

    做什么：解析“梗概：... 关键事实：1.xxx;2.xxx”格式，输出 SUMMARY 与 FACT 切片。
    为什么这样做：长期记忆向量化需要细粒度事实级召回，而不是只向量化整段摘要。
    输入输出：输入完整摘要字符串，输出 MemoryChunk 列表。
    边界条件：格式不匹配或事实为空时保留梗概切片。
    异常行为：解析异常会返回全文 SUMMARY 切片并记录可解释日志。
    """
    cleaned_summary = full_summary.strip()
    if not cleaned_summary:
        raise ValueError("长期摘要不能为空")

    chunks: list[MemoryChunk] = []
    try:
        match = re.search(r"梗概：\s*(.*?)\s*关键事实：\s*(.*)", cleaned_summary, re.DOTALL)
        if not match:
            logger.warning("长摘要解析未匹配到标准格式，使用全文作为梗概切片")
            return [MemoryChunk(chunk_type=MemoryChunkType.SUMMARY, content=cleaned_summary)]

        summary_content = match.group(1).strip()
        facts_content = match.group(2).strip()
        if summary_content:
            chunks.append(MemoryChunk(chunk_type=MemoryChunkType.SUMMARY, content=summary_content))

        if facts_content:
            facts_str = facts_content.rstrip(";")
            for raw_fact in facts_str.split(";"):
                raw_fact = raw_fact.strip()
                if not raw_fact:
                    continue
                fact_match = re.match(r"^\d+[\.、]\s*(.*)", raw_fact)
                clean_fact = fact_match.group(1).strip() if fact_match else raw_fact
                if clean_fact:
                    chunks.append(MemoryChunk(chunk_type=MemoryChunkType.FACT, content=clean_fact))
    except Exception as exc:
        logger.error(f"解析长摘要失败，使用全文作为梗概切片 error={exc}")
        return [MemoryChunk(chunk_type=MemoryChunkType.SUMMARY, content=cleaned_summary)]

    if not chunks:
        logger.warning("长摘要拆分结果为空，使用全文作为梗概切片")
        return [MemoryChunk(chunk_type=MemoryChunkType.SUMMARY, content=cleaned_summary)]
    return chunks
