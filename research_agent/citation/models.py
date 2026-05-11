"""
论文引用关系图 — 数据模型定义

定义引用图系统中使用的核心数据类。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PaperRecord:
    """论文记录，包含元数据和下载状态"""

    arxiv_id: str
    title: str
    authors: list[str]
    year: int | None
    abstract: str
    pdf_path: str | None
    download_status: str  # pending | downloading | done | failed


@dataclass
class ReferenceEntry:
    """从 PDF 中解析出的单条引用条目"""

    title: str
    authors: list[str]
    raw_text: str  # 原始引用文本


@dataclass
class MatchedReference:
    """引用条目与本地已知论文的匹配结果"""

    reference: ReferenceEntry
    matched_arxiv_id: str | None
    confidence: float  # 0-1 匹配置信度


@dataclass
class CitationGraph:
    """引用关系图，由论文节点和引用边组成"""

    nodes: list[PaperRecord] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    # edges 中每个 dict 结构: {citing_paper_id, cited_paper_id, confidence}


@dataclass
class PaperDownloadRequest:
    """论文下载请求"""

    arxiv_id: str
    title: str
    authors: list[str]
    year: int | None
    url: str


@dataclass
class DownloadTaskStatus:
    """下载任务状态"""

    task_id: str
    total: int
    completed: int
    failed: int
    status: str  # running | done | failed
