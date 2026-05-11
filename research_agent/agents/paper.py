"""子智能体：论文初稿生成（流式输出）"""

from research_agent.state import ResearchState
from research_agent.llm_utils import invoke_llm_streaming
from research_agent.streaming import push_status

SYSTEM_PROMPT = """\
你是一位学术论文写作专家。基于前面所有阶段的成果，撰写一篇完整的学术论文初稿。
论文结构：标题、摘要、引言、方法、实验与结果、讨论、结论、参考文献。

## 重要要求
- 以 Markdown 格式输出完整论文
- 用学术论文的正式语言，但行文流畅自然
- 综合前面各阶段的成果，但要**重新组织语言**，不要直接复制粘贴之前的输出
- 参考文献使用标准格式
"""


def paper_agent(state: ResearchState) -> dict:
    sid = state.get("session_id", "")
    feedback = state.get("human_feedback", "") or "无"
    memory = state.get("memory_context", "")
    push_status(sid, "stage_start", {"stage": "paper", "agent": "@论文撰写研究员"})

    content = invoke_llm_streaming(
        sid, SYSTEM_PROMPT,
        "研究课题：{topic}\n\n文献调研：\n{literature}\n\n研究假设：\n{hypothesis}\n\n"
        "实验代码：\n{code}\n\n结果分析：\n{analysis}\n\n用户补充信息：{feedback}",
        {"topic": state["topic"], "literature": state["literature_review"],
         "hypothesis": state["hypothesis"], "code": state["experiment_code"],
         "analysis": state["analysis_result"], "feedback": feedback},
        memory_context=memory,
    )
    return {"paper_draft": content, "current_stage": "paper", "human_feedback": ""}
