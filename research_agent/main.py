"""
科研智能体 - 基于 LangGraph 的多阶段科研工作流

流程由 Lead Agent 引导：
- 每个阶段结束后，Lead Agent 分析用户反馈，决定下一步走向
- 支持重做当前阶段、跳转到任意阶段、继续下一步、结束流程
- 用户通过自然语言描述需求，Lead Agent 理解并路由
"""

from __future__ import annotations

import json
import re
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

# 阶段顺序（默认流程）
STAGE_ORDER = [
    "literature_review", "hypothesis", "experiment_design",
    "experiment", "analysis", "paper",
]

# ── Lead Router 节点 ──────────────────────────────────────────

LEAD_ROUTER_PROMPT = """\
你是科研项目负责人。当前研究流程刚完成了一个阶段，你需要根据用户的反馈决定下一步。

## 当前状态
- 刚完成的阶段: {current_stage}
- 默认下一阶段: {next_stage}
- 用户反馈: {feedback}

## 可选的下一步
- literature_review: 文献调研（搜索论文、下载论文、扩展关键词、补充文献）
- hypothesis: 假设生成
- experiment_design: 实验方案设计
- experiment: 实验代码生成
- analysis: 结果分析
- paper: 论文初稿
- done: 结束流程

## 判断规则
1. 如果用户没有反馈或说"继续"、"下一步"、"好的" → 选择默认下一阶段
2. 如果用户提到论文相关操作（"下载论文"、"搜索更多"、"扩展关键词"、"补充文献"、"重新搜索"） → 选择 literature_review
3. 如果用户要求重做当前阶段（"重做"、"重新"、"换个方向"、"不满意"） → 选择当前阶段对应的名称
4. 如果用户明确指定了某个阶段（"帮我写代码"、"直接写论文"、"生成假设"） → 选择对应阶段
5. 如果用户说"结束"、"够了"、"完成" → 选择 done

请只输出一个 JSON：
{{"next": "阶段名称", "message": "给用户的简短回复（一句话，自然口语化）"}}
"""


def lead_router(state: ResearchState) -> dict:
    """Lead Agent 路由节点：用 LLM 分析用户反馈，决定下一步走向"""
    from langchain_moonshot import ChatMoonshot
    from research_agent.logger import get_logger
    _log = get_logger("lead_router")

    feedback = state.get("human_feedback", "").strip()
    current_stage = state.get("current_stage", "")

    _log.info(f"Lead Router | stage={current_stage} feedback='{feedback[:80] if feedback else ''}'")

    # 确定默认下一阶段
    if current_stage in STAGE_ORDER:
        idx = STAGE_ORDER.index(current_stage)
        next_stage = STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else "done"
    else:
        next_stage = "literature_review"

    # 唯一的快速路径：没有反馈 = 继续
    if not feedback:
        _log.info(f"Lead Router | 无反馈 → {next_stage}")
        return {"next_stage": next_stage, "human_feedback": ""}

    # 全部交给 LLM 判断
    try:
        llm = ChatMoonshot(model="kimi-k2.5", thinking=False, temperature=0.6)
        prompt = LEAD_ROUTER_PROMPT.format(
            current_stage=STAGE_NAMES.get(current_stage, current_stage),
            next_stage=STAGE_NAMES.get(next_stage, next_stage),
            feedback=feedback,
        )
        result = llm.invoke([("human", prompt)])
        content = result.content.strip()
        _log.info(f"Lead Router | LLM: {content[:120]}")

        # 解析 JSON
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            data = json.loads(match.group())
            target = data.get("next", next_stage)
            _log.info(f"Lead Router | 决策: {target}")
            if target in STAGE_ORDER or target == "done":
                keep_feedback = feedback if target == current_stage else ""
                return {"next_stage": target, "human_feedback": keep_feedback}
    except Exception as e:
        _log.error(f"Lead Router | 错误: {e}")

    # fallback: 默认继续
    _log.info(f"Lead Router | fallback → {next_stage}")
    return {"next_stage": next_stage, "human_feedback": ""}


def _route_from_lead(state: ResearchState) -> str:
    """从 lead_router 的输出决定走向哪个节点"""
    target = state.get("next_stage", "")
    if target == "done":
        return "end"
    if target in STAGE_ORDER:
        return target
    return "end"


# ── 构建 Graph ────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """构建科研工作流 Graph"""
    builder = StateGraph(ResearchState)

    # 添加研究员节点
    builder.add_node("literature_review", literature_review_agent)
    builder.add_node("hypothesis", hypothesis_agent)
    builder.add_node("experiment_design", experiment_design_agent)
    builder.add_node("experiment", experiment_code_agent)
    builder.add_node("analysis", analysis_agent)
    builder.add_node("paper", paper_agent)

    # Lead Router 节点
    builder.add_node("lead_router", lead_router)

    # 起始边
    builder.add_edge(START, "literature_review")

    # 每个研究员完成后 → lead_router（中断等待用户输入）
    for stage in STAGE_ORDER:
        builder.add_edge(stage, "lead_router")

    # lead_router 根据决策路由到下一个节点
    route_map = {stage: stage for stage in STAGE_ORDER}
    route_map["end"] = END
    builder.add_conditional_edges("lead_router", _route_from_lead, route_map)

    return builder


import os
import sqlite3

# checkpoint 数据库路径（项目根目录下）
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "checkpoints.db")


def create_app(db_path: str | None = None):
    """
    创建带持久化 checkpointer 的可运行 Graph 实例。
    """
    builder = build_graph()
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["lead_router"],  # 在 lead_router 前中断，等待用户输入
    )
    return graph
