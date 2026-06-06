"""
Luna RAG 内容加载与降噪模块

做什么：解析本地文件与 URL，输出经过 UTF-8 标准化和正文降噪后的纯文本/Markdown。
为什么这样做：RAG 入库质量决定检索质量，必须在摄入入口阻断乱码、页眉页脚、网页导航与评论污染。
输入输出：输入文件名与二进制内容或 URL，输出 CleanDocumentContent。
边界条件：仅允许明确支持的扩展名；URL 必须由 trafilatura 提取正文。
异常行为：依赖缺失、解析失败、有效正文过短时抛出可解释异常。
"""

from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass
from pathlib import Path

from app.logger import logger
from app.types.constants import RagSourceType


class ContentExtractionError(RuntimeError):
    """内容提取失败异常，表示输入源可访问但无法得到有效正文。"""


class ExternalFetchError(RuntimeError):
    """外部 URL 抓取失败异常，表示网络、反爬或 HTTP 层不可用。"""


@dataclass(frozen=True)
class CleanDocumentContent:
    """
    清洗后的知识内容。

    做什么：承载统一格式的正文、标题、来源类型与来源标识。
    为什么这样做：摄入服务不需要关心具体解析器细节，只处理标准化结果。
    """

    title: str
    text: str
    source_type: RagSourceType
    source_ref: str


class DocumentLoader:
    """
    本地异构文件加载器。

    做什么：根据扩展名调度 PDF、DOCX、Markdown、TXT 解析逻辑。
    为什么这样做：不同文件格式保留结构的方式不同，统一读取会丢失标题层级或引入噪声。
    """

    _supported_suffixes = {".txt", ".md", ".markdown", ".pdf", ".docx"}

    async def extract_from_bytes(self, filename: str, content: bytes) -> CleanDocumentContent:
        """
        从上传文件二进制提取正文。

        边界条件：文件名不能为空、内容不能为空、扩展名必须受支持。
        异常行为：解析依赖缺失或正文过短时抛出 ContentExtractionError。
        """
        if not filename.strip():
            raise ValueError("文件名不能为空")
        if not content:
            raise ValueError("文件内容不能为空")
        suffix = Path(filename).suffix.lower()
        if suffix not in self._supported_suffixes:
            raise ValueError(f"不支持的知识文件类型: {suffix}")

        if suffix in {".txt", ".md", ".markdown"}:
            text = self._decode_text(content)
        elif suffix == ".docx":
            text = await asyncio.to_thread(self._extract_docx, content)
        elif suffix == ".pdf":
            text = await asyncio.to_thread(self._extract_pdf, content)
        else:
            raise ValueError(f"不支持的知识文件类型: {suffix}")

        cleaned = self._normalize_text(text)
        if len(cleaned) < 20:
            raise ContentExtractionError("文件未提取到足够有效正文")
        return CleanDocumentContent(
            title=filename,
            text=cleaned,
            source_type=RagSourceType.LOCAL_FILE,
            source_ref=filename,
        )

    def _decode_text(self, content: bytes) -> str:
        """探测文本编码并统一转换为 UTF-8 字符串。"""
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                import chardet

                detected = chardet.detect(content)
                encoding = detected.get("encoding") or "utf-8"
                return content.decode(encoding, errors="replace")
            except ImportError:
                # 如果chardet未安装，则尝试常见编码
                for encoding in ['gbk', 'gb2312', 'latin-1', 'cp1252']:
                    try:
                        return content.decode(encoding)
                    except UnicodeDecodeError:
                        continue
                # 如果所有尝试都失败，使用默认处理
                return content.decode('utf-8', errors='replace')
            except Exception as exc:
                raise ContentExtractionError(f"文本编码探测失败: {exc}") from exc

    def _extract_docx(self, content: bytes) -> str:
        """解析 DOCX 并将标题样式转换为 Markdown 标题。"""
        try:
            from docx import Document
        except Exception as exc:
            raise ContentExtractionError("python-docx 依赖未安装，无法解析 DOCX") from exc

        doc = Document(io.BytesIO(content))
        parts: list[str] = []
        for paragraph in doc.paragraphs:
            raw_text = paragraph.text.strip()
            if not raw_text:
                continue
            style_name = paragraph.style.name if paragraph.style is not None else ""
            if style_name.startswith("Heading 1") or style_name.startswith("标题 1"):
                parts.append(f"# {raw_text}")
            elif style_name.startswith("Heading 2") or style_name.startswith("标题 2"):
                parts.append(f"## {raw_text}")
            elif style_name.startswith("Heading 3") or style_name.startswith("标题 3"):
                parts.append(f"### {raw_text}")
            else:
                parts.append(raw_text)
        return "\n\n".join(parts)

    def _extract_pdf(self, content: bytes) -> str:
        """解析 PDF 页面正文并去除常见页眉页脚区域。"""
        try:
            import pdfplumber
        except Exception as exc:
            raise ContentExtractionError("pdfplumber 依赖未安装，无法解析 PDF") from exc

        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page_index, page in enumerate(pdf.pages):
                height = float(page.height or 0)
                width = float(page.width or 0)
                if height > 0 and width > 0:
                    crop_box = (0, height * 0.06, width, height * 0.94)
                    page = page.crop(crop_box)
                page_text = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
                normalized_page = self._remove_repeated_page_noise(page_text, page_index)
                if normalized_page:
                    parts.append(normalized_page)
        return "\n\n".join(parts)

    @staticmethod
    def _remove_repeated_page_noise(text: str, page_index: int) -> str:
        """移除页码类低价值噪声，保留段落换行。"""
        lines = []
        for line in text.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            if re.fullmatch(r"第?\s*\d+\s*页?", cleaned, re.IGNORECASE):
                continue
            if cleaned.lower() in {"copyright", "all rights reserved"}:
                continue
            lines.append(cleaned)
        if page_index >= 0:
            return "\n".join(lines)
        return text

    @staticmethod
    def _normalize_text(text: str) -> str:
        """统一换行与空白，避免编码残留污染切片。"""
        text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()


class UrlContentLoader:
    """
    URL 正文抓取与去噪加载器。

    做什么：使用 trafilatura 提取网页 Main Content，明确关闭评论区摄入。
    为什么这样做：简单 HTML body 解析会混入导航、页脚和广告，严重污染 RAG 检索。
    """

    async def extract(self, url: str) -> CleanDocumentContent:
        """异步抓取 URL 并提取 Markdown 正文。"""
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        text = await asyncio.to_thread(self._extract_sync, url)
        return CleanDocumentContent(
            title=url,
            text=text,
            source_type=RagSourceType.URL,
            source_ref=url,
        )

    def _extract_sync(self, url: str) -> str:
        """在线程中执行 trafilatura 同步抓取，避免阻塞事件循环。"""
        try:
            import trafilatura
        except Exception as exc:
            raise ContentExtractionError("trafilatura 依赖未安装，无法抓取网页正文") from exc

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            raise ExternalFetchError("URL 无法访问或被目标站点拦截")
        clean_text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            output_format="markdown",
        )
        if not clean_text or len(clean_text.strip()) < 50:
            raise ContentExtractionError("未能从该网页提取到有效正文")
        logger.info(f"URL 正文提取完成 url={url} text_length={len(clean_text)}")
        return DocumentLoader._normalize_text(clean_text)
