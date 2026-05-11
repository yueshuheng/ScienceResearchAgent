"""
论文引用关系图 — CitationGraphService

引用图的核心业务逻辑层，组合 PaperStore 和 ReferenceParser，
提供批量下载、图查询、任务状态查询等功能。
"""

from __future__ import annotations

import threading
import uuid

from research_agent.citation.db import get_citation_conn
from research_agent.citation.models import (
    CitationGraph,
    DownloadTaskStatus,
    PaperDownloadRequest,
    PaperRecord,
)
from research_agent.citation.paper_store import PaperStore
from research_agent.citation.reference_parser import ReferenceParser
from research_agent.logger import get_logger
from research_agent.streaming import push_status

log = get_logger("graph_service")


class CitationGraphService:
    """引用图核心业务逻辑层，组合 PaperStore 和 ReferenceParser"""

    def __init__(self, paper_store: PaperStore, ref_parser: ReferenceParser):
        """初始化服务

        Args:
            paper_store: 论文存储模块实例
            ref_parser: 引用解析器实例
        """
        self.paper_store = paper_store
        self.ref_parser = ref_parser
        self.db_path = paper_store.db_path

    async def download_papers(
        self, session_id: str, papers: list[PaperDownloadRequest]
    ) -> str:
        """批量下载论文，返回 task_id。异步处理。

        生成唯一 task_id，在后台线程中逐个下载论文，
        每篇下载完成后自动触发引用解析和边创建，
        并通过 SSE 推送进度和图更新事件。

        Args:
            session_id: 研究会话 ID
            papers: 论文下载请求列表

        Returns:
            task_id: 下载任务唯一标识
        """
        task_id = uuid.uuid4().hex[:8]
        total = len(papers)

        # 在数据库中创建下载任务记录
        conn = get_citation_conn(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO download_tasks (task_id, session_id, total_papers, completed, failed, status)
                VALUES (?, ?, ?, 0, 0, 'running')
                """,
                (task_id, session_id, total),
            )
            conn.commit()
        finally:
            conn.close()

        # 启动后台线程处理下载
        t = threading.Thread(
            target=self._process_downloads,
            args=(task_id, session_id, papers),
            daemon=True,
        )
        t.start()

        return task_id

    def get_graph(self, session_id: str) -> CitationGraph:
        """获取会话的完整引用图

        查询该会话关联的所有论文作为节点，
        查询这些论文之间的引用边。

        Args:
            session_id: 研究会话 ID

        Returns:
            CitationGraph 包含节点和边
        """
        # 获取会话中的所有论文作为节点
        nodes = self.paper_store.get_papers_by_session(session_id)

        if not nodes:
            return CitationGraph(nodes=[], edges=[])

        # 获取会话内论文的 arxiv_id 集合
        arxiv_ids = [n.arxiv_id for n in nodes]

        # 查询这些论文之间的引用边
        conn = get_citation_conn(self.db_path)
        try:
            placeholders = ",".join("?" * len(arxiv_ids))
            cursor = conn.execute(
                f"""
                SELECT citing_paper_id, cited_paper_id, confidence
                FROM citation_edges
                WHERE citing_paper_id IN ({placeholders})
                  AND cited_paper_id IN ({placeholders})
                """,
                arxiv_ids + arxiv_ids,
            )
            edges = [
                {
                    "citing_paper_id": row["citing_paper_id"],
                    "cited_paper_id": row["cited_paper_id"],
                    "confidence": row["confidence"],
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

        return CitationGraph(nodes=nodes, edges=edges)

    def get_download_status(self, task_id: str) -> DownloadTaskStatus:
        """查询下载任务状态

        Args:
            task_id: 下载任务 ID

        Returns:
            DownloadTaskStatus 包含任务进度信息

        Raises:
            ValueError: 任务不存在时抛出
        """
        conn = get_citation_conn(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT task_id, total_papers, completed, failed, status FROM download_tasks WHERE task_id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if row is None:
            raise ValueError(f"下载任务不存在: {task_id}")

        return DownloadTaskStatus(
            task_id=row["task_id"],
            total=row["total_papers"],
            completed=row["completed"],
            failed=row["failed"],
            status=row["status"],
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _process_downloads(
        self, task_id: str, session_id: str, papers: list[PaperDownloadRequest]
    ) -> None:
        """后台线程：逐个下载论文并处理引用解析

        每篇论文下载完成后：
        1. 关联到会话
        2. 解析引用并创建边
        3. 推送 SSE 进度事件
        """
        completed = 0
        failed = 0

        for paper in papers:
            try:
                # 下载论文
                record = self.paper_store.download_paper(
                    arxiv_id=paper.arxiv_id,
                    title=paper.title,
                    authors=paper.authors,
                    year=paper.year,
                    abstract="",
                )

                # 无论下载是否成功，都关联到会话（这样图中能看到节点）
                self.paper_store.link_paper_to_session(paper.arxiv_id, session_id)

                if record.download_status == "done" and record.pdf_path:
                    # 解析引用并创建边
                    self._parse_and_create_edges(record)

                # 推送图更新事件
                push_status(session_id, "graph_update", {
                    "session_id": session_id,
                    "action": "paper_added",
                    "arxiv_id": paper.arxiv_id,
                })

                completed += 1

            except Exception as e:
                log.error(f"论文下载处理失败: {paper.arxiv_id}, 错误: {e}")
                failed += 1

            # 更新任务进度
            self._update_task_progress(task_id, completed, failed)

            # 推送下载进度事件
            push_status(session_id, "download_progress", {
                "task_id": task_id,
                "arxiv_id": paper.arxiv_id,
                "status": "done" if paper.arxiv_id and failed == 0 else "failed",
                "progress": (completed + failed) / len(papers),
            })

        # 标记任务完成
        final_status = "done" if failed < len(papers) else "failed"
        self._finalize_task(task_id, completed, failed, final_status)

        # 推送批量下载完成事件
        push_status(session_id, "download_complete", {
            "task_id": task_id,
            "total": len(papers),
            "success": completed,
            "failed": failed,
        })

        log.info(
            f"批量下载完成: task_id={task_id}, "
            f"total={len(papers)}, completed={completed}, failed={failed}"
        )

    def _parse_and_create_edges(self, paper: PaperRecord) -> None:
        """解析论文引用并创建引用边

        Args:
            paper: 已下载完成的论文记录
        """
        if not paper.pdf_path:
            return

        # 解析引用列表
        references = self.ref_parser.parse_references(paper.pdf_path)
        if not references:
            log.info(f"论文 {paper.arxiv_id} 未解析出引用")
            return

        # 匹配已知论文
        matched = self.ref_parser.match_references(references)

        # 创建引用边
        conn = get_citation_conn(self.db_path)
        try:
            edges_created = 0
            for match in matched:
                if match.matched_arxiv_id:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO citation_edges
                            (citing_paper_id, cited_paper_id, confidence)
                        VALUES (?, ?, ?)
                        """,
                        (paper.arxiv_id, match.matched_arxiv_id, match.confidence),
                    )
                    edges_created += 1
            conn.commit()
            if edges_created:
                log.info(
                    f"论文 {paper.arxiv_id} 创建了 {edges_created} 条引用边"
                )
        finally:
            conn.close()

    def _update_task_progress(
        self, task_id: str, completed: int, failed: int
    ) -> None:
        """更新下载任务进度"""
        conn = get_citation_conn(self.db_path)
        try:
            conn.execute(
                """
                UPDATE download_tasks
                SET completed = ?, failed = ?
                WHERE task_id = ?
                """,
                (completed, failed, task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _finalize_task(
        self, task_id: str, completed: int, failed: int, status: str
    ) -> None:
        """标记下载任务最终状态"""
        conn = get_citation_conn(self.db_path)
        try:
            conn.execute(
                """
                UPDATE download_tasks
                SET completed = ?, failed = ?, status = ?
                WHERE task_id = ?
                """,
                (completed, failed, status, task_id),
            )
            conn.commit()
        finally:
            conn.close()
