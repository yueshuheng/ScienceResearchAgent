"""
科研智能体 - 基于 LangGraph 的多阶段科研工作流

流程：用户输入课题 → 文献调研 → 假设生成 → 实验设计 → 实验代码 → 结果分析 → 论文初稿
每个阶段结束后暂停，等待用户确认或补充信息后再继续。
"""

from __future__ import annotations

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from research_agent.state import ResearchState
from research_agent.agents import (
    literature_review_agent,
    hypothesis_agent,
    experiment_design_agent,
    experiment_code_agent,
    analysis_agent,
    paper_agent,
)

load_dotenv()

# ── 阶段展示名称 ──────────────────────────────────────────────
STAGE_NAMES = {
    "literature_review": "📚 文献调研",
    "hypothesis": "💡 假设生成",
    "experiment_design": "📋 实验方案设计",
    "experiment": "🧪 实验代码生成",
    "analysis": "📊 结果分析",
    "paper": "📝 论文初稿",
}

# ── Human-in-the-loop 节点 ────────────────────────────────────

def human_review_after_literature(state: ResearchState) -> dict:
    """文献调研后的人工审核断点 — 如果用户补充了论文，追加到文献综述"""
    feedback = state.get("human_feedback", "").strip()
    if not feedback:
        return {}
    # 把用户补充的论文/信息追加到文献综述末尾
    current = state.get("literature_review", "")
    supplement = f"\n\n---\n\n## 用户补充的参考文献/信息\n\n{feedback}"
    return {"literature_review": current + supplement, "human_feedback": ""}

def human_review_after_hypothesis(state: ResearchState) -> dict:
    """假设生成后的人工审核断点 — 补充信息追加到假设"""
    feedback = state.get("human_feedback", "").strip()
    if not feedback:
        return {}
    current = state.get("hypothesis", "")
    return {"hypothesis": current + f"\n\n---\n\n## 用户补充\n\n{feedback}", "human_feedback": ""}

def human_review_after_design(state: ResearchState) -> dict:
    """实验方案设计后的人工审核断点 — 补充信息追加到实验方案"""
    feedback = state.get("human_feedback", "").strip()
    if not feedback:
        return {}
    current = state.get("experiment_design", "")
    return {"experiment_design": current + f"\n\n---\n\n## 用户补充\n\n{feedback}", "human_feedback": ""}

def human_review_after_experiment(state: ResearchState) -> dict:
    """实验代码后的人工审核断点 — 补充信息追加到实验代码"""
    feedback = state.get("human_feedback", "").strip()
    if not feedback:
        return {}
    current = state.get("experiment_code", "")
    return {"experiment_code": current + f"\n\n---\n\n## 用户补充\n\n{feedback}", "human_feedback": ""}

def human_review_after_analysis(state: ResearchState) -> dict:
    """结果分析后的人工审核断点 — 补充信息追加到分析结果"""
    feedback = state.get("human_feedback", "").strip()
    if not feedback:
        return {}
    current = state.get("analysis_result", "")
    return {"analysis_result": current + f"\n\n---\n\n## 用户补充\n\n{feedback}", "human_feedback": ""}


# ── 构建 Graph ────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """构建科研工作流 Graph"""
    builder = StateGraph(ResearchState)

    # 添加所有节点
    builder.add_node("literature_review", literature_review_agent)
    builder.add_node("human_after_literature", human_review_after_literature)
    builder.add_node("hypothesis", hypothesis_agent)
    builder.add_node("human_after_hypothesis", human_review_after_hypothesis)
    builder.add_node("experiment_design", experiment_design_agent)
    builder.add_node("human_after_design", human_review_after_design)
    builder.add_node("experiment", experiment_code_agent)
    builder.add_node("human_after_experiment", human_review_after_experiment)
    builder.add_node("analysis", analysis_agent)
    builder.add_node("human_after_analysis", human_review_after_analysis)
    builder.add_node("paper", paper_agent)

    # 定义边
    builder.add_edge(START, "literature_review")
    builder.add_edge("literature_review", "human_after_literature")
    builder.add_edge("human_after_literature", "hypothesis")
    builder.add_edge("hypothesis", "human_after_hypothesis")
    builder.add_edge("human_after_hypothesis", "experiment_design")
    builder.add_edge("experiment_design", "human_after_design")
    builder.add_edge("human_after_design", "experiment")
    builder.add_edge("experiment", "human_after_experiment")
    builder.add_edge("human_after_experiment", "analysis")
    builder.add_edge("analysis", "human_after_analysis")
    builder.add_edge("human_after_analysis", "paper")
    builder.add_edge("paper", END)

    return builder


import os
import sqlite3

# checkpoint 数据库路径（项目根目录下）
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "checkpoints.db")


def create_app(db_path: str | None = None):
    """
    创建带持久化 checkpointer 的可运行 Graph 实例。

    Args:
        db_path: SQLite 数据库路径，默认为项目根目录下的 checkpoints.db
    """
    builder = build_graph()
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=[
            "human_after_literature",
            "human_after_hypothesis",
            "human_after_design",
            "human_after_experiment",
            "human_after_analysis",
        ],
    )
    return graph
