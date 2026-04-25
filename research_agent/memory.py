"""
长期记忆模块 — SQLite + 结构化摘要（Mem0 思路）

两类记忆：
1. 用户画像（user_profile）：研究领域、偏好方法、技术栈等，持续更新
2. 研究档案（research_archive）：每次研究的课题、结论、关键发现，不断积累

每次研究完成后，LLM 自动提取记忆；每次新研究开始时，注入相关记忆到 prompt。
"""

from __future__ import annotations

import sqlite3
import json
import os
from datetime import datetime

from research_agent.logger import get_logger

log = get_logger("memory")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_memory_db():
    """初始化记忆表"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, key)
        );

        CREATE TABLE IF NOT EXISTS research_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            summary TEXT DEFAULT '',
            key_findings TEXT DEFAULT '',
            methods_used TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
    log.info("记忆数据库初始化完成")


# ── 用户画像 ──────────────────────────────────────────────────

def get_user_profile(user_id: int) -> dict[str, str]:
    """获取用户画像（所有 key-value）"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT key, value FROM user_profile WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def update_user_profile(user_id: int, updates: dict[str, str]):
    """更新用户画像（upsert）"""
    conn = _get_conn()
    for key, value in updates.items():
        if value.strip():
            conn.execute("""
                INSERT INTO user_profile (user_id, key, value)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value = excluded.value, updated_at = datetime('now')
            """, (user_id, key, value.strip()))
    conn.commit()
    conn.close()
    log.info(f"用户画像更新 | user={user_id} keys={list(updates.keys())}")


# ── 研究档案 ──────────────────────────────────────────────────

def save_research_archive(user_id: int, session_id: str, topic: str,
                          summary: str, key_findings: str, methods_used: str):
    """保存一次研究的档案"""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO research_archive (user_id, session_id, topic, summary, key_findings, methods_used)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, session_id, topic, summary, key_findings, methods_used))
    conn.commit()
    conn.close()
    log.info(f"研究档案保存 | user={user_id} session={session_id} topic={topic[:30]}")


def get_research_archives(user_id: int, limit: int = 10) -> list[dict]:
    """获取用户最近的研究档案"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT id, topic, summary, key_findings, methods_used, created_at
        FROM research_archive WHERE user_id = ?
        ORDER BY created_at DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 记忆提取（LLM 调用）──────────────────────────────────────

EXTRACT_PROFILE_PROMPT = """\
你是一个记忆提取助手。根据以下科研对话内容，提取用户的研究画像信息。

请以 JSON 格式输出，包含以下字段（如果能从对话中推断出来的话，推断不出就留空字符串）：
{
  "research_field": "用户的研究领域",
  "expertise_level": "专业水平（本科生/硕士/博士/教授等）",
  "preferred_methods": "偏好的研究方法或技术",
  "programming_skills": "编程技能和常用框架",
  "research_interests": "具体研究兴趣和关注方向",
  "writing_style": "论文写作偏好（中文/英文、风格等）"
}

只输出 JSON，不要其他内容。
"""

EXTRACT_ARCHIVE_PROMPT = """\
你是一个研究总结助手。根据以下科研流程的完整输出，提取研究档案。

请以 JSON 格式输出：
{
  "summary": "一句话总结这次研究的核心内容和结论（50字以内）",
  "key_findings": "关键发现，用分号分隔（3-5条）",
  "methods_used": "使用的主要方法和技术，用分号分隔"
}

只输出 JSON，不要其他内容。
"""


def extract_and_save_memory(user_id: int, session_id: str, topic: str,
                            literature: str, hypothesis: str,
                            experiment_code: str, analysis: str):
    """研究完成后，用 LLM 提取记忆并保存"""
    from research_agent.llm_utils import invoke_llm_streaming

    conversation = (
        f"课题：{topic}\n\n"
        f"文献综述（摘要）：{literature[:500]}\n\n"
        f"假设：{hypothesis[:300]}\n\n"
        f"分析结论：{analysis[:500]}"
    )

    # 提取用户画像
    try:
        profile_text = invoke_llm_streaming(
            "", EXTRACT_PROFILE_PROMPT,
            "对话内容：\n{conversation}", {"conversation": conversation},
        )
        profile_json = _parse_json(profile_text)
        if profile_json:
            # 只更新非空字段，不覆盖已有信息
            existing = get_user_profile(user_id)
            merged = {}
            for k, v in profile_json.items():
                if v and (k not in existing or not existing[k]):
                    merged[k] = v
                elif v and k in existing:
                    # 合并而不是覆盖
                    if v.lower() not in existing[k].lower():
                        merged[k] = f"{existing[k]}; {v}"
            if merged:
                update_user_profile(user_id, merged)
    except Exception as e:
        log.warning(f"用户画像提取失败: {e}")

    # 提取研究档案
    try:
        archive_text = invoke_llm_streaming(
            "", EXTRACT_ARCHIVE_PROMPT,
            "研究内容：\n{conversation}", {"conversation": conversation},
        )
        archive_json = _parse_json(archive_text)
        if archive_json:
            save_research_archive(
                user_id, session_id, topic,
                archive_json.get("summary", ""),
                archive_json.get("key_findings", ""),
                archive_json.get("methods_used", ""),
            )
    except Exception as e:
        log.warning(f"研究档案提取失败: {e}")


def _parse_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON"""
    text = text.strip()
    # 去掉 markdown 代码块
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试找到 { } 之间的内容
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return None
    return None


# ── 记忆注入（生成 prompt 片段）──────────────────────────────

def build_memory_context(user_id: int) -> str:
    """构建记忆上下文，注入到 agent 的 prompt 中"""
    parts = []

    # 用户画像
    profile = get_user_profile(user_id)
    if profile:
        parts.append("## 用户研究画像")
        for key, value in profile.items():
            label = {
                "research_field": "研究领域",
                "expertise_level": "专业水平",
                "preferred_methods": "偏好方法",
                "programming_skills": "编程技能",
                "research_interests": "研究兴趣",
                "writing_style": "写作偏好",
            }.get(key, key)
            parts.append(f"- {label}: {value}")

    # 历史研究
    archives = get_research_archives(user_id, limit=5)
    if archives:
        parts.append("\n## 历史研究档案")
        for i, a in enumerate(archives, 1):
            parts.append(f"### 研究 {i}: {a['topic']}")
            if a["summary"]:
                parts.append(f"- 摘要: {a['summary']}")
            if a["key_findings"]:
                parts.append(f"- 关键发现: {a['key_findings']}")
            if a["methods_used"]:
                parts.append(f"- 使用方法: {a['methods_used']}")
            parts.append(f"- 时间: {a['created_at']}")

    if not parts:
        return ""

    return (
        "\n\n---\n\n"
        "以下是该用户的长期记忆，请参考这些信息来更好地服务用户：\n\n"
        + "\n".join(parts)
    )
