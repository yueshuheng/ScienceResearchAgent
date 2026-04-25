"""子智能体：假设生成（流式输出）"""

from research_agent.state import ResearchState
from research_agent.llm_utils import invoke_llm_streaming
from research_agent.streaming import push_status

SYSTEM_PROMPT = """\
你是一位科研假设生成专家。基于文献调研结果，完成以下工作：
1. 提出 2-3 个可验证的科学假设
2. 为每个假设说明理论依据
3. 分析每个假设的创新性和可行性
4. 设计验证每个假设所需的实验思路概要
5. 推荐最优假设并给出理由
请以结构化的 Markdown 格式输出。
"""


def hypothesis_agent(state: ResearchState) -> dict:
    sid = state.get("session_id", "")
    feedback = state.get("human_feedback", "") or "无"
    memory = state.get("memory_context", "")
    push_status(sid, "stage_start", {"stage": "hypothesis", "agent": "@假设生成研究员"})

    content = invoke_llm_streaming(
        sid, SYSTEM_PROMPT,
        "研究课题：{topic}\n\n文献调研结果：\n{literature}\n\n用户补充信息：{feedback}",
        {"topic": state["topic"], "literature": state["literature_review"], "feedback": feedback},
        memory_context=memory,
    )
    return {"hypothesis": content, "current_stage": "hypothesis", "human_feedback": ""}
