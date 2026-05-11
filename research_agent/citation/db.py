"""
论文引用关系图 — 数据库初始化模块

创建引用图所需的 SQLite 表，使用 WAL 模式提升并发性能。
"""

from __future__ import annotations

import os
import sqlite3

from research_agent.logger import get_logger

log = get_logger("citation_db")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "citation.db")


def get_citation_conn(db_path: str | None = None) -> sqlite3.Connection:
    """获取引用图数据库连接"""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # 启用 WAL 模式，提升并发读写性能
    conn.execute("PRAGMA journal_mode=WAL")
    # 确保表存在
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            arxiv_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT NOT NULL,
            year INTEGER,
            abstract TEXT DEFAULT '',
            pdf_path TEXT,
            download_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS citation_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            citing_paper_id TEXT NOT NULL,
            cited_paper_id TEXT NOT NULL,
            confidence REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (citing_paper_id) REFERENCES papers(arxiv_id),
            FOREIGN KEY (cited_paper_id) REFERENCES papers(arxiv_id),
            UNIQUE(citing_paper_id, cited_paper_id)
        );
        CREATE TABLE IF NOT EXISTS session_papers (
            session_id TEXT NOT NULL,
            arxiv_id TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (session_id, arxiv_id),
            FOREIGN KEY (arxiv_id) REFERENCES papers(arxiv_id)
        );
        CREATE TABLE IF NOT EXISTS download_tasks (
            task_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            total_papers INTEGER NOT NULL,
            completed INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    return conn


def init_citation_db(db_path: str | None = None) -> None:
    """初始化引用图数据库表

    创建以下四张表：
    - papers: 论文元数据
    - citation_edges: 引用关系边
    - session_papers: 会话-论文关联
    - download_tasks: 下载任务状态
    """
    conn = get_citation_conn(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            arxiv_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT NOT NULL,
            year INTEGER,
            abstract TEXT DEFAULT '',
            pdf_path TEXT,
            download_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS citation_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            citing_paper_id TEXT NOT NULL,
            cited_paper_id TEXT NOT NULL,
            confidence REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (citing_paper_id) REFERENCES papers(arxiv_id),
            FOREIGN KEY (cited_paper_id) REFERENCES papers(arxiv_id),
            UNIQUE(citing_paper_id, cited_paper_id)
        );

        CREATE TABLE IF NOT EXISTS session_papers (
            session_id TEXT NOT NULL,
            arxiv_id TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (session_id, arxiv_id),
            FOREIGN KEY (arxiv_id) REFERENCES papers(arxiv_id)
        );

        CREATE TABLE IF NOT EXISTS download_tasks (
            task_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            total_papers INTEGER NOT NULL,
            completed INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    log.info("引用图数据库初始化完成")
