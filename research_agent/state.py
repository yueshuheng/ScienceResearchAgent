"""科研智能体共享状态定义"""

from __future__ import annotations
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class ResearchState(TypedDict):
    """贯穿整个科研流程的共享状态"""
    # 用户输入的研究课题
    topic: str
    # 各阶段产出
    literature_review: str
    hypothesis: str
    experiment_design: str
    experiment_code: str
    analysis_result: str
    paper_draft: str
    # 对话消息历史（用于 human-in-the-loop）
    messages: Annotated[list[BaseMessage], add_messages]
    # 用户在每个阶段的补充信息
    human_feedback: str
    # 当前阶段名称
    current_stage: str
    # 会话 ID（用于流式输出）
    session_id: str
    # 用户 ID（用于长期记忆）
    user_id: int
    # 长期记忆上下文（注入到 prompt）
    memory_context: str
