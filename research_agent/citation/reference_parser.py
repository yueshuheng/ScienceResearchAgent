"""
论文引用关系图 — ReferenceParser

从论文 PDF 中提取引用列表，并与本地数据库中的已知论文进行标题模糊匹配。
"""

from __future__ import annotations

import json
import re
import sqlite3
from difflib import SequenceMatcher

import fitz  # PyMuPDF

from research_agent.citation.db import get_citation_conn, init_citation_db
from research_agent.citation.models import MatchedReference, ReferenceEntry
from research_agent.logger import get_logger

log = get_logger("reference_parser")

# 引用列表区域的标题关键词
_REFERENCE_HEADINGS = re.compile(
    r"^\s*(References|Bibliography|REFERENCES|BIBLIOGRAPHY|参考文献)\s*$",
    re.MULTILINE,
)

# 匹配编号引用条目，如 [1], [2] 等
_NUMBERED_REF_PATTERN = re.compile(r"^\s*\[(\d+)\]\s*")

# 匹配置信度阈值
MATCH_THRESHOLD = 0.8


class ReferenceParser:
    """从 PDF 中提取引用列表并匹配已知论文"""

    def __init__(self, db_path: str):
        """初始化解析器

        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        init_citation_db(self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return get_citation_conn(self.db_path)

    def parse_references(self, pdf_path: str) -> list[ReferenceEntry]:
        """从 PDF 提取引用列表（标题 + 作者）

        使用 PyMuPDF 提取 PDF 全文，定位引用列表区域，
        解析每条引用条目的标题和作者信息。

        Args:
            pdf_path: PDF 文件路径

        Returns:
            解析出的引用条目列表。如果 PDF 不可读或未找到引用区域，返回空列表。
        """
        try:
            text = self._extract_text(pdf_path)
        except Exception as e:
            log.warning(f"PDF 文本提取失败: {pdf_path}, 错误: {e}")
            return []

        if not text:
            log.warning(f"PDF 文本为空: {pdf_path}")
            return []

        # 定位引用列表区域
        ref_section = self._find_references_section(text)
        if not ref_section:
            log.warning(f"未找到引用列表区域: {pdf_path}")
            return []

        # 解析各条引用
        entries = self._parse_entries(ref_section)
        log.info(f"从 {pdf_path} 解析出 {len(entries)} 条引用")
        return entries

    def match_references(
        self, references: list[ReferenceEntry]
    ) -> list[MatchedReference]:
        """将引用条目与本地数据库中的已知论文匹配

        使用 difflib.SequenceMatcher 对引用标题与数据库中论文标题进行
        模糊匹配，阈值为 0.8。

        Args:
            references: 解析出的引用条目列表

        Returns:
            匹配结果列表，每条包含原始引用、匹配到的 arxiv_id 和置信度
        """
        if not references:
            return []

        # 从数据库获取所有已知论文
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT arxiv_id, title FROM papers")
            known_papers = cursor.fetchall()
        finally:
            conn.close()

        if not known_papers:
            return [
                MatchedReference(reference=ref, matched_arxiv_id=None, confidence=0.0)
                for ref in references
            ]

        results: list[MatchedReference] = []
        for ref in references:
            best_match_id: str | None = None
            best_score: float = 0.0

            ref_title_lower = ref.title.lower().strip()

            for row in known_papers:
                paper_title_lower = row["title"].lower().strip()
                score = SequenceMatcher(
                    None, ref_title_lower, paper_title_lower
                ).ratio()
                if score > best_score:
                    best_score = score
                    best_match_id = row["arxiv_id"]

            if best_score >= MATCH_THRESHOLD:
                results.append(
                    MatchedReference(
                        reference=ref,
                        matched_arxiv_id=best_match_id,
                        confidence=best_score,
                    )
                )
            else:
                results.append(
                    MatchedReference(
                        reference=ref, matched_arxiv_id=None, confidence=best_score
                    )
                )

        return results

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _extract_text(self, pdf_path: str) -> str:
        """使用 PyMuPDF 从 PDF 提取全部文本"""
        doc = fitz.open(pdf_path)
        try:
            pages_text: list[str] = []
            for page in doc:
                pages_text.append(page.get_text())
            return "\n".join(pages_text)
        finally:
            doc.close()

    def _find_references_section(self, text: str) -> str | None:
        """在全文中定位引用列表区域

        查找 "References"、"Bibliography"、"REFERENCES" 等标题，
        返回从该标题之后到文末的文本。
        """
        match = _REFERENCE_HEADINGS.search(text)
        if not match:
            return None
        return text[match.end():]

    def _parse_entries(self, ref_text: str) -> list[ReferenceEntry]:
        """解析引用区域文本，提取各条引用

        支持两种格式：
        1. 编号格式: [1] Author(s). Title. ...
        2. 非编号格式: 按空行或换行分隔的段落
        """
        # 先尝试编号格式
        entries = self._parse_numbered_entries(ref_text)
        if entries:
            return entries

        # 回退到段落分隔格式
        return self._parse_paragraph_entries(ref_text)

    def _parse_numbered_entries(self, ref_text: str) -> list[ReferenceEntry]:
        """解析编号格式的引用条目 [1], [2], ..."""
        lines = ref_text.split("\n")
        raw_entries: list[str] = []
        current_entry: list[str] = []

        for line in lines:
            if _NUMBERED_REF_PATTERN.match(line):
                if current_entry:
                    raw_entries.append(" ".join(current_entry))
                # 去掉编号前缀
                cleaned = _NUMBERED_REF_PATTERN.sub("", line).strip()
                current_entry = [cleaned] if cleaned else []
            elif current_entry:
                stripped = line.strip()
                if stripped:
                    current_entry.append(stripped)

        if current_entry:
            raw_entries.append(" ".join(current_entry))

        if not raw_entries:
            return []

        results: list[ReferenceEntry] = []
        for raw in raw_entries:
            entry = self._extract_title_authors(raw)
            if entry:
                results.append(entry)

        return results

    def _parse_paragraph_entries(self, ref_text: str) -> list[ReferenceEntry]:
        """解析段落分隔格式的引用条目"""
        # 按双换行或单换行后跟大写字母开头分隔
        paragraphs = re.split(r"\n\s*\n", ref_text)

        results: list[ReferenceEntry] = []
        for para in paragraphs:
            para = para.strip()
            if not para or len(para) < 20:
                continue
            entry = self._extract_title_authors(para)
            if entry:
                results.append(entry)

        return results

    def _extract_title_authors(self, raw_text: str) -> ReferenceEntry | None:
        """从单条引用原始文本中提取标题和作者

        常见格式:
        - Author(s). Title. Journal/Conference, Year.
        - Author(s), "Title," Journal, Year.
        - Author(s) (Year). Title. ...

        策略：
        1. 尝试匹配引号中的标题
        2. 尝试按句号分隔，第二段为标题
        3. 回退：取第一个句号前的内容作为作者，之后到下一个句号为标题
        """
        if not raw_text or len(raw_text.strip()) < 10:
            return None

        title = ""
        authors: list[str] = []

        # 策略 1: 引号中的标题 ("Title" 或 "Title")
        quoted = re.search(r'["\u201c](.+?)["\u201d]', raw_text)
        if quoted:
            title = quoted.group(1).strip()
            # 引号前的部分通常是作者
            before_quote = raw_text[: quoted.start()].strip().rstrip(",").rstrip(".")
            if before_quote:
                authors = self._parse_authors(before_quote)
        else:
            # 策略 2: 按句号分隔
            # 常见格式: Authors. Title. Venue, Year.
            parts = re.split(r"\.\s+", raw_text, maxsplit=2)
            if len(parts) >= 2:
                authors = self._parse_authors(parts[0])
                # 标题是第二部分（去掉末尾句号）
                title = parts[1].rstrip(".").strip()
            else:
                # 策略 3: 回退 — 整段作为标题
                title = raw_text.strip().rstrip(".")

        # 清理标题
        title = title.strip()
        if not title:
            return None

        # 如果作者为空，尝试从标题前提取
        if not authors:
            authors = ["Unknown"]

        return ReferenceEntry(title=title, authors=authors, raw_text=raw_text)

    def _parse_authors(self, author_text: str) -> list[str]:
        """解析作者字符串为作者列表

        支持 "and"、","、"&" 分隔的作者列表，以及 "et al." 缩写。
        """
        if not author_text:
            return []

        # 去掉年份括号，如 (2020)
        author_text = re.sub(r"\(\d{4}\)", "", author_text).strip()

        # 处理 "et al."
        author_text = re.sub(r"\s+et\s+al\.?", "", author_text).strip()

        # 按 "and"、"&"、"," 分隔
        parts = re.split(r"\s*(?:,\s*and\s+|,\s*&\s*|\s+and\s+|\s*&\s*|,\s*)", author_text)

        authors = []
        for part in parts:
            part = part.strip().rstrip(".").strip()
            if part and len(part) > 1:
                authors.append(part)

        return authors if authors else []
