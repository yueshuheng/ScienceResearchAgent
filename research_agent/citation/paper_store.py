"""
论文引用关系图 — PaperStore

负责论文 PDF 的下载与本地存储管理，以及论文元数据的数据库操作。
"""

from __future__ import annotations

import json
import os
import sqlite3

import requests

from research_agent.citation.db import get_citation_conn, init_citation_db
from research_agent.citation.models import PaperRecord
from research_agent.logger import get_logger

log = get_logger("paper_store")

ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}.pdf"


class PaperStore:
    """论文 PDF 下载与本地存储管理"""

    def __init__(self, db_path: str, pdf_dir: str):
        """初始化存储，创建 PDF 目录和数据库表

        Args:
            db_path: SQLite 数据库文件路径
            pdf_dir: PDF 文件存储目录
        """
        self.db_path = db_path
        self.pdf_dir = pdf_dir
        os.makedirs(self.pdf_dir, exist_ok=True)
        init_citation_db(self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return get_citation_conn(self.db_path)

    def _row_to_record(self, row: sqlite3.Row) -> PaperRecord:
        """将数据库行转换为 PaperRecord"""
        authors_raw = row["authors"]
        try:
            authors = json.loads(authors_raw)
        except (json.JSONDecodeError, TypeError):
            authors = []
        return PaperRecord(
            arxiv_id=row["arxiv_id"],
            title=row["title"],
            authors=authors,
            year=row["year"],
            abstract=row["abstract"] or "",
            pdf_path=row["pdf_path"],
            download_status=row["download_status"],
        )

    def download_paper(
        self,
        arxiv_id: str,
        title: str,
        authors: list[str],
        year: int | None,
        abstract: str = "",
    ) -> PaperRecord:
        """下载论文 PDF 并记录元数据。已存在且状态为 done 则跳过下载。

        Args:
            arxiv_id: arXiv 论文 ID
            title: 论文标题
            authors: 作者列表
            year: 发表年份
            abstract: 摘要

        Returns:
            PaperRecord 包含论文元数据和下载状态
        """
        # 如果 title 是默认占位符，尝试从 arXiv API 获取真实元数据
        if not title or title.startswith("Paper "):
            fetched = self._fetch_arxiv_metadata(arxiv_id)
            if fetched:
                title = fetched.get("title", title)
                authors = fetched.get("authors", authors)
                year = fetched.get("year", year)
                abstract = fetched.get("abstract", abstract)

        # 检查是否已存在且下载完成
        existing = self.get_paper(arxiv_id)
        if existing and existing.download_status == "done":
            log.info(f"论文已存在，跳过下载: {arxiv_id}")
            return existing

        pdf_path = os.path.join(self.pdf_dir, f"{arxiv_id}.pdf")
        authors_json = json.dumps(authors, ensure_ascii=False)

        conn = self._get_conn()
        try:
            # 插入或更新元数据，设置状态为 downloading
            conn.execute(
                """
                INSERT INTO papers (arxiv_id, title, authors, year, abstract, pdf_path, download_status)
                VALUES (?, ?, ?, ?, ?, ?, 'downloading')
                ON CONFLICT(arxiv_id) DO UPDATE SET
                    title = excluded.title,
                    authors = excluded.authors,
                    year = excluded.year,
                    abstract = excluded.abstract,
                    pdf_path = excluded.pdf_path,
                    download_status = 'downloading'
                """,
                (arxiv_id, title, authors_json, year, abstract, pdf_path),
            )
            conn.commit()

            # 如果文件已存在于磁盘，直接标记完成
            if os.path.exists(pdf_path):
                log.info(f"PDF 文件已存在，标记完成: {pdf_path}")
                conn.execute(
                    "UPDATE papers SET download_status = 'done' WHERE arxiv_id = ?",
                    (arxiv_id,),
                )
                conn.commit()
                return self._fetch_paper(conn, arxiv_id)

            # 从 arXiv 下载 PDF
            url = ARXIV_PDF_URL.format(arxiv_id=arxiv_id)
            log.info(f"开始下载论文 PDF: {url}")
            try:
                resp = requests.get(url, timeout=60, stream=True)
                resp.raise_for_status()
                with open(pdf_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                # 下载成功，更新状态
                conn.execute(
                    "UPDATE papers SET download_status = 'done' WHERE arxiv_id = ?",
                    (arxiv_id,),
                )
                conn.commit()
                log.info(f"论文下载完成: {arxiv_id}")
            except (requests.RequestException, OSError) as e:
                # 下载失败，更新状态
                log.error(f"论文下载失败: {arxiv_id}, 错误: {e}")
                conn.execute(
                    "UPDATE papers SET download_status = 'failed' WHERE arxiv_id = ?",
                    (arxiv_id,),
                )
                conn.commit()

            return self._fetch_paper(conn, arxiv_id)
        finally:
            conn.close()

    def get_paper(self, arxiv_id: str) -> PaperRecord | None:
        """按 arXiv ID 查询论文记录

        Args:
            arxiv_id: arXiv 论文 ID

        Returns:
            PaperRecord 或 None（不存在时）
        """
        conn = self._get_conn()
        try:
            return self._fetch_paper(conn, arxiv_id)
        finally:
            conn.close()

    def _fetch_arxiv_metadata(self, arxiv_id: str) -> dict | None:
        """从 arXiv API 获取论文元数据"""
        import xml.etree.ElementTree as ET
        # 去掉版本号用于 API 查询
        clean_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
        url = f"http://export.arxiv.org/api/query?id_list={clean_id}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return None
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entry = root.find("atom:entry", ns)
            if entry is None:
                return None
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            published_el = entry.find("atom:published", ns)
            author_els = entry.findall("atom:author/atom:name", ns)

            title = title_el.text.strip().replace("\n", " ") if title_el is not None else ""
            abstract = summary_el.text.strip().replace("\n", " ") if summary_el is not None else ""
            authors = [a.text.strip() for a in author_els] if author_els else []
            year = int(published_el.text[:4]) if published_el is not None else None

            return {"title": title, "authors": authors, "year": year, "abstract": abstract}
        except Exception as e:
            log.warning(f"获取 arXiv 元数据失败: {arxiv_id}, {e}")
            return None

    def get_papers_by_session(self, session_id: str) -> list[PaperRecord]:
        """获取会话关联的所有论文

        Args:
            session_id: 研究会话 ID

        Returns:
            该会话关联的所有 PaperRecord 列表
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT p.* FROM papers p
                INNER JOIN session_papers sp ON p.arxiv_id = sp.arxiv_id
                WHERE sp.session_id = ?
                ORDER BY sp.added_at DESC
                """,
                (session_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def link_paper_to_session(self, arxiv_id: str, session_id: str) -> None:
        """将论文关联到研究会话

        Args:
            arxiv_id: arXiv 论文 ID
            session_id: 研究会话 ID
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO session_papers (session_id, arxiv_id)
                VALUES (?, ?)
                """,
                (session_id, arxiv_id),
            )
            conn.commit()
            log.info(f"论文 {arxiv_id} 已关联到会话 {session_id}")
        finally:
            conn.close()

    def _fetch_paper(self, conn: sqlite3.Connection, arxiv_id: str) -> PaperRecord | None:
        """从数据库获取单篇论文记录（内部方法）"""
        cursor = conn.execute(
            "SELECT * FROM papers WHERE arxiv_id = ?",
            (arxiv_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)
