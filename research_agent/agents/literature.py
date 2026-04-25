"""子智能体：文献调研（arXiv 搜索 + 流式输出）"""

from research_agent.state import ResearchState
from research_agent.tools.scholar import search_arxiv_fast
from research_agent.llm_utils import invoke_llm_streaming
from research_agent.streaming import push_status
from research_agent.logger import get_logger

log = get_logger("agent.literature")

KEYWORD_PROMPT = """\
你是一位学术搜索专家。根据用户的研究课题，生成恰好 2 组英文搜索关键词。
严格要求：只输出 2 行，每行一组关键词，不要编号，不要解释，不要多余内容。
"""

REVIEW_PROMPT = """\
你是一位资深科研文献调研专家。用户给出了研究课题，我已经从 arXiv 搜索到了以下真实论文。

请基于这些真实论文完成文献综述：
1. 梳理该领域的研究背景和发展脉络
2. 总结当前主流的研究方法和技术路线
3. 指出现有研究的不足和空白
4. 从搜索结果中挑选最相关的 5-10 篇作为关键参考文献（保留真实的标题、作者、年份、链接）
5. 给出该课题的研究价值和可行性评估

重要：参考文献必须来自下面提供的搜索结果，不要编造不存在的论文。
请以结构化的 Markdown 格式输出。
"""


def literature_review_agent(state: ResearchState) -> dict:
    sid = state.get("session_id", "")
    topic = state["topic"]
    feedback = state.get("human_feedback", "") or "无"
    memory = state.get("memory_context", "")

    push_status(sid, "stage_start", {"stage": "literature_review", "agent": "@文献调研研究员"})
    log.info(f"[{sid}] 文献调研开始 | topic={topic[:50]}")

    # Step 1: 生成搜索关键词
    push_status(sid, "info", {"message": "正在生成搜索关键词..."})
    keyword_text = invoke_llm_streaming(
        sid, KEYWORD_PROMPT, "研究课题：{topic}", {"topic": topic},
        thinking=False, memory_context=memory,
    )
    # 硬截断：只取前 2 行非空关键词
    keywords = [line.strip() for line in keyword_text.strip().split("\n") if line.strip()][:2]
    log.info(f"[{sid}] 关键词: {keywords}")

    # Step 2: 只用 arXiv 搜索（快速、无限流）
    push_status(sid, "info", {"message": f"正在搜索 arXiv（{len(keywords)} 组关键词）..."})
    all_papers = []
    for kw in keywords:
        papers = search_arxiv_fast(kw, limit=10)
        all_papers.extend(papers)

    # 去重
    seen = set()
    unique_papers = []
    for p in all_papers:
        key = p.title.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique_papers.append(p)

    top_papers = unique_papers[:15]
    log.info(f"[{sid}] 搜索完成 | {len(unique_papers)} 篇去重，取前 {len(top_papers)} 篇")

    papers_text = "\n\n---\n\n".join(
        f"【论文 {i+1}】\n{p.to_text()}" for i, p in enumerate(top_papers)
    )
    if not top_papers:
        papers_text = "（未搜索到相关论文，请基于你的知识完成综述，但标注参考文献为待补充）"

    push_status(sid, "info", {"message": f"找到 {len(unique_papers)} 篇论文，正在生成综述..."})

    # Step 3: 流式生成综述
    content = invoke_llm_streaming(
        sid, REVIEW_PROMPT,
        "研究课题：{topic}\n\n用户补充信息：{feedback}\n\n===== 搜索到的论文 =====\n\n{papers}",
        {"topic": topic, "feedback": feedback, "papers": papers_text},
        thinking=False, memory_context=memory,
    )

    return {
        "literature_review": content,
        "current_stage": "literature_review",
        "human_feedback": "",
    }
