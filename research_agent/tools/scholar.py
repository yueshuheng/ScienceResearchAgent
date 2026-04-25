"""
论文搜索工具 — 纯 arXiv

两次搜索合并：按最新 + 按相关性，去重后返回。
快速、无限流、免费。
"""

from __future__ import annotations

import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass
class Paper:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    citation_count: int = 0
    url: str = ""
    source: str = "arxiv"

    def to_text(self) -> str:
        authors_str = ", ".join(self.authors[:3])
        if len(self.authors) > 3:
            authors_str += " et al."
        parts = [
            f"标题: {self.title}",
            f"作者: {authors_str}",
            f"年份: {self.year or '未知'}",
            f"链接: {self.url}",
            f"摘要: {self.abstract[:200]}{'...' if len(self.abstract) > 200 else ''}",
        ]
        return "\n".join(parts)


def _arxiv_query(query: str, limit: int, sort_by: str) -> list[Paper]:
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": sort_by,
        "sortOrder": "descending",
    })
    req = urllib.request.Request(
        f"{ARXIV_API}?{params}",
        headers={"User-Agent": "ResearchAgent/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as resp:
            xml_data = resp.read().decode()
    except Exception as e:
        print(f"  ⚠️ arXiv 搜索失败: {e}")
        return []

    papers = []
    root = ET.fromstring(xml_data)
    for entry in root.findall("atom:entry", ARXIV_NS):
        title = entry.findtext("atom:title", "", ARXIV_NS).strip().replace("\n", " ")
        abstract = entry.findtext("atom:summary", "", ARXIV_NS).strip().replace("\n", " ")
        authors = [
            a.findtext("atom:name", "", ARXIV_NS)
            for a in entry.findall("atom:author", ARXIV_NS)
        ]
        published = entry.findtext("atom:published", "", ARXIV_NS)
        year = int(published[:4]) if published else None
        link = entry.findtext("atom:id", "", ARXIV_NS)
        papers.append(Paper(
            title=title, authors=authors, year=year,
            abstract=abstract, url=link,
        ))
    return papers


def search_arxiv_fast(query: str, limit: int = 10) -> list[Paper]:
    """
    快速搜索 arXiv：最新 + 相关性两路合并去重。
    单组关键词通常 2-3 秒完成。
    """
    print(f"  🔍 arXiv: {query}")

    latest = _arxiv_query(query, limit, "submittedDate")
    relevant = _arxiv_query(query, limit, "relevance")

    # 去重合并
    seen: set[str] = set()
    merged: list[Paper] = []
    for p in latest + relevant:
        key = p.title.lower().strip()
        if key and key not in seen:
            seen.add(key)
            merged.append(p)

    print(f"     找到 {len(merged)} 篇（去重后）")
    return merged
