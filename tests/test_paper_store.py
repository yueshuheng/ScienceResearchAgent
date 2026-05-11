"""
PaperStore 单元测试

测试论文存储模块的核心功能：元数据存储、下载跳过、会话关联。
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from research_agent.citation.paper_store import PaperStore


@pytest.fixture
def store(tmp_path):
    """创建临时 PaperStore 实例"""
    db_path = str(tmp_path / "test_citation.db")
    pdf_dir = str(tmp_path / "papers")
    return PaperStore(db_path=db_path, pdf_dir=pdf_dir)


class TestPaperStoreInit:
    def test_creates_pdf_directory(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        pdf_dir = str(tmp_path / "pdfs")
        assert not os.path.exists(pdf_dir)
        PaperStore(db_path=db_path, pdf_dir=pdf_dir)
        assert os.path.isdir(pdf_dir)


class TestDownloadPaper:
    @patch("research_agent.citation.paper_store.requests.get")
    def test_download_success(self, mock_get, store):
        """成功下载论文 PDF"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"fake pdf content"]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        record = store.download_paper(
            arxiv_id="2301.00001",
            title="Test Paper",
            authors=["Author A", "Author B"],
            year=2023,
            abstract="A test abstract",
        )

        assert record.arxiv_id == "2301.00001"
        assert record.title == "Test Paper"
        assert record.authors == ["Author A", "Author B"]
        assert record.year == 2023
        assert record.abstract == "A test abstract"
        assert record.download_status == "done"
        assert record.pdf_path.endswith("2301.00001.pdf")

    @patch("research_agent.citation.paper_store.requests.get")
    def test_download_skip_existing_done(self, mock_get, store):
        """已下载完成的论文应跳过下载"""
        # 先下载一次
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"pdf data"]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        store.download_paper(
            arxiv_id="2301.00002",
            title="Existing Paper",
            authors=["Author C"],
            year=2022,
        )

        # 重置 mock 调用计数
        mock_get.reset_mock()

        # 再次下载同一篇论文
        record = store.download_paper(
            arxiv_id="2301.00002",
            title="Existing Paper",
            authors=["Author C"],
            year=2022,
        )

        # 不应再次发起网络请求
        mock_get.assert_not_called()
        assert record.download_status == "done"

    @patch("research_agent.citation.paper_store.requests.get")
    def test_download_failure_sets_failed_status(self, mock_get, store):
        """下载失败时状态应为 failed"""
        import requests as req

        mock_get.side_effect = req.ConnectionError("Network error")

        record = store.download_paper(
            arxiv_id="2301.00003",
            title="Failing Paper",
            authors=["Author D"],
            year=2023,
        )

        assert record.download_status == "failed"


class TestGetPaper:
    @patch("research_agent.citation.paper_store.requests.get")
    def test_get_existing_paper(self, mock_get, store):
        """查询已存在的论文"""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"pdf"]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        store.download_paper(
            arxiv_id="2301.00004",
            title="Query Test",
            authors=["Author E"],
            year=2021,
        )

        record = store.get_paper("2301.00004")
        assert record is not None
        assert record.title == "Query Test"

    def test_get_nonexistent_paper(self, store):
        """查询不存在的论文返回 None"""
        record = store.get_paper("nonexistent_id")
        assert record is None


class TestSessionManagement:
    @patch("research_agent.citation.paper_store.requests.get")
    def test_link_and_get_papers_by_session(self, mock_get, store):
        """关联论文到会话并按会话查询"""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"pdf"]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # 下载两篇论文
        store.download_paper("2301.00005", "Paper A", ["Auth1"], 2023)
        store.download_paper("2301.00006", "Paper B", ["Auth2"], 2022)

        # 关联到同一会话
        store.link_paper_to_session("2301.00005", "session-1")
        store.link_paper_to_session("2301.00006", "session-1")

        # 查询会话论文
        papers = store.get_papers_by_session("session-1")
        assert len(papers) == 2
        ids = {p.arxiv_id for p in papers}
        assert "2301.00005" in ids
        assert "2301.00006" in ids

    def test_get_papers_empty_session(self, store):
        """空会话返回空列表"""
        papers = store.get_papers_by_session("empty-session")
        assert papers == []

    @patch("research_agent.citation.paper_store.requests.get")
    def test_link_idempotent(self, mock_get, store):
        """重复关联不报错"""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"pdf"]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        store.download_paper("2301.00007", "Paper C", ["Auth3"], 2023)
        store.link_paper_to_session("2301.00007", "session-2")
        store.link_paper_to_session("2301.00007", "session-2")  # 重复关联

        papers = store.get_papers_by_session("session-2")
        assert len(papers) == 1
