"""子智能体：结果分析（流式输出）"""

from research_agent.state import ResearchState
from research_agent.llm_utils import invoke_llm_streaming
from research_agent.streaming import push_status

SYSTEM_PROMPT = """\
你是一位科研数据分析专家。基于实验代码和假设，完成以下工作：
1. 分析实验设计的合理性
2. 预测可能的实验结果和数据分布
3. 提供数据分析方法（统计检验、可视化方案等）
4. 讨论结果对假设的支持/反驳情况
5. 指出潜在的局限性和改进方向
请以结构化的 Markdown 格式输出。
"""


def analysis_agent(state: ResearchState) -> dict:
    sid = state.get("session_id", "")
    feedback = state.get("human_feedback", "") or "无"
    memory = state.get("memory_context", "")
    push_status(sid, "stage_start", {"stage": "analysis", "agent": "@数据分析研究员"})

    content = invoke_llm_streaming(
        sid, SYSTEM_PROMPT,
        "研究课题：{topic}\n\n研究假设：\n{hypothesis}\n\n实验代码：\n{code}\n\n用户补充信息：{feedback}",
        {"topic": state["topic"], "hypothesis": state["hypothesis"],
         "code": state["experiment_code"], "feedback": feedback},
        memory_context=memory,
    )
    return {"analysis_result": content, "current_stage": "analysis", "human_feedback": ""}
