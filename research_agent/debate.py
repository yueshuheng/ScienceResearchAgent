"""
Agent 聊天室 — 多 Agent 讨论模式

多个 AI 研究员围绕一个课题方向进行多轮讨论，目标是讨论出一个切实可行的创新点。
支持用户随时打断加入，修改讨论方向。

上下文管理策略：滚动总结
- 每轮结束后主持人生成结构化总结
- 下一轮的上下文 = 课题 + 累积总结 + 用户插入 + 当前轮发言
- 避免历史消息无限膨胀导致跑偏和 token 溢出
"""

from __future__ import annotations

from langchain_moonshot import ChatMoonshot
from langchain_core.prompts import ChatPromptTemplate
from research_agent.streaming import push_token, push_status, get_stream
from research_agent.logger import get_logger

log = get_logger("debate")

# ── Agent 定义 ─────────────────────────────────────────────────

AGENTS = [
    {
        "id": "literature",
        "name": "📚 文献专家",
        "icon": "📚",
        "system": """\
你是一位文献调研专家，熟悉各领域最新研究进展。在讨论中你的职责是：
- 指出相关的已有工作和研究空白
- 评估提出的想法是否有文献支撑
- 提供具体的参考方向和对比基线
回复要简洁（200字以内），直接给出观点，不要客套。紧扣讨论目标，不要偏题。""",
    },
    {
        "id": "method",
        "name": "💡 方法专家",
        "icon": "💡",
        "system": """\
你是一位方法论专家，擅长设计创新的技术方案。在讨论中你的职责是：
- 提出具体的技术创新点和方法改进
- 分析不同方法的优劣和可行性
- 给出技术实现的关键思路
回复要简洁（200字以内），聚焦方法创新，不要泛泛而谈。紧扣讨论目标，不要偏题。""",
    },
    {
        "id": "experiment",
        "name": "🧪 实验专家",
        "icon": "🧪",
        "system": """\
你是一位实验设计专家，关注方法的可行性和可验证性。在讨论中你的职责是：
- 评估提出的方法是否可实验验证
- 指出实验设计中的潜在问题
- 建议合适的数据集、评估指标和实验方案
回复要简洁（200字以内），务实导向，关注可行性。紧扣讨论目标，不要偏题。""",
    },
    {
        "id": "critic",
        "name": "🔍 批判者",
        "icon": "🔍",
        "system": """\
你是一位严格的学术批判者，负责找出讨论中的漏洞。在讨论中你的职责是：
- 质疑创新点的真正新颖性
- 指出方法的局限性和潜在缺陷
- 提出尖锐但建设性的反对意见
回复要简洁（200字以内），犀利但有建设性。紧扣讨论目标，不要偏题。""",
    },
]

MODERATOR = {
    "id": "moderator",
    "name": "🎯 主持人",
    "icon": "🎯",
    "system": """\
你是讨论的主持人，负责引导讨论收敛到一个切实可行的创新点。你的职责是：
- 总结本轮讨论的关键共识和分歧点
- 提炼出目前最有潜力的创新方向
- 明确下一轮需要聚焦解决的具体问题
- 如果讨论发散，强力拉回到核心目标

输出格式：
**本轮共识：**（达成一致的观点）
**核心分歧：**（尚未解决的争议）
**当前最佳创新方向：**（目前最有潜力的方向）
**下轮聚焦：**（下一轮需要具体讨论的问题）""",
}

FINAL_SUMMARY_PROMPT = """\
经过多轮讨论，现在需要给出最终总结。请基于累积的讨论总结，输出一个结构化的创新点方案：

## 🎯 最终创新点

### 创新点名称
（一句话概括）

### 核心思路
（2-3句话描述技术方案）

### 创新性分析
- 与现有方法的区别
- 理论依据

### 可行性评估
- 所需数据集
- 实验方案
- 预期效果

### 潜在风险
- 主要挑战
- 应对策略
"""


# ── 滚动总结管理 ───────────────────────────────────────────────

def _extract_rolling_summary(history: list[dict]) -> str:
    """
    从历史消息中提取累积总结。
    总结存储在主持人消息的 content 中，取最后一条主持人消息作为最新总结。
    """
    last_moderator = ""
    for msg in reversed(history):
        if msg.get("stage") == "moderator" and msg.get("role") == "agent":
            last_moderator = msg.get("content", "")
            break
    return last_moderator


def _extract_user_interrupts(history: list[dict], since_round: int) -> list[str]:
    """提取指定轮次之后的用户插入"""
    interrupts = []
    for msg in history:
        if msg.get("role") == "user" and msg.get("round", 0) == 0:
            # round=0 表示用户插入（不属于任何轮次）
            interrupts.append(msg.get("content", ""))
    return interrupts


def _build_round_context(
    topic: str,
    rolling_summary: str,
    current_round: int,
    max_rounds: int,
    user_interrupt: str | None,
    current_round_messages: list[dict] | None = None,
) -> str:
    """
    构建当前轮次的上下文。
    结构：课题 → 累积总结 → 用户插入 → 当前轮已有发言
    """
    ctx = f"## 讨论课题\n{topic}\n\n"
    ctx += f"## 讨论目标\n通过多轮讨论，找到一个切实可行的创新点。\n\n"
    ctx += f"## 进度\n当前第 {current_round}/{max_rounds} 轮"
    remaining = max_rounds - current_round
    if remaining <= 2:
        ctx += f"（仅剩 {remaining} 轮，请聚焦收敛！）"
    ctx += "\n\n"

    if rolling_summary:
        ctx += f"## 前几轮讨论总结\n{rolling_summary}\n\n"

    if user_interrupt:
        ctx += f"## ⚡ 用户最新指示\n{user_interrupt}\n（请根据用户的指示调整讨论方向）\n\n"

    if current_round_messages:
        ctx += "## 本轮已有发言\n"
        for msg in current_round_messages:
            ctx += f"{msg['agent']}：{msg['content']}\n\n"

    return ctx


# ── 讨论引擎 ───────────────────────────────────────────────────

def run_debate(
    sid: str,
    topic: str,
    max_rounds: int,
    history: list[dict],
    user_interrupt: str | None = None,
) -> list[dict]:
    """
    执行一轮讨论。
    返回本轮新增的消息列表。
    """
    new_messages = []
    llm = ChatMoonshot(model="kimi-k2.5", thinking=False, temperature=0.6)

    current_round = _count_rounds(history) + 1
    rolling_summary = _extract_rolling_summary(history)

    log.info(f"[{sid}] 讨论第 {current_round}/{max_rounds} 轮 | 总结长度={len(rolling_summary)}")

    if user_interrupt:
        push_status(sid, "info", {"message": "👤 用户加入了讨论，调整方向"})

    # 判断是否是最后一轮
    is_final = current_round >= max_rounds

    if is_final:
        # 最后一轮：主持人做最终总结
        push_status(sid, "stage_start", {
            "stage": "moderator",
            "agent": MODERATOR["name"],
        })
        push_status(sid, "info", {
            "message": f"📢 第 {current_round}/{max_rounds} 轮（最终轮）— 主持人总结",
        })

        ctx = _build_round_context(topic, rolling_summary, current_round, max_rounds, user_interrupt)
        ctx += "\n\n这是最后一轮讨论。" + FINAL_SUMMARY_PROMPT

        summary = _agent_speak(sid, llm, MODERATOR, ctx, stream=True)
        new_messages.append({
            "role": "agent",
            "agent": MODERATOR["name"],
            "stage": "moderator",
            "content": summary,
            "round": current_round,
        })
        return new_messages

    # 正常轮次：每个 agent 依次发言
    push_status(sid, "info", {
        "message": f"📢 第 {current_round}/{max_rounds} 轮讨论开始",
    })

    round_msgs: list[dict] = []

    for agent in AGENTS:
        push_status(sid, "stage_start", {
            "stage": agent["id"],
            "agent": agent["name"],
        })

        ctx = _build_round_context(
            topic, rolling_summary, current_round, max_rounds,
            user_interrupt, round_msgs,
        )

        response = _agent_speak(sid, llm, agent, ctx, stream=True)
        msg = {
            "role": "agent",
            "agent": agent["name"],
            "stage": agent["id"],
            "content": response,
            "round": current_round,
        }
        new_messages.append(msg)
        round_msgs.append(msg)

    # 主持人总结本轮（这个总结会成为下一轮的 rolling_summary）
    push_status(sid, "stage_start", {
        "stage": "moderator",
        "agent": MODERATOR["name"],
    })

    ctx = _build_round_context(
        topic, rolling_summary, current_round, max_rounds,
        user_interrupt, round_msgs,
    )
    remaining = max_rounds - current_round
    ctx += f"\n\n请总结本轮讨论。还剩 {remaining} 轮。"
    if remaining <= 2:
        ctx += "\n讨论即将结束，请强力引导收敛到一个具体的、可执行的创新点。"

    summary = _agent_speak(sid, llm, MODERATOR, ctx, stream=True)
    new_messages.append({
        "role": "agent",
        "agent": MODERATOR["name"],
        "stage": "moderator",
        "content": summary,
        "round": current_round,
    })

    return new_messages


def _agent_speak(sid: str, llm, agent: dict, context: str, stream: bool = True) -> str:
    """让一个 agent 发言"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", agent["system"]),
        ("human", "{context}"),
    ])
    chain = prompt | llm

    q = get_stream(sid) if stream else None

    if q:
        full_text = ""
        for chunk in chain.stream({"context": context}):
            token = chunk.content
            if token:
                full_text += token
                push_token(sid, token)
        return full_text
    else:
        result = chain.invoke({"context": context})
        return result.content


def _count_rounds(history: list[dict]) -> int:
    """统计已完成的讨论轮次"""
    rounds = set()
    for msg in history:
        r = msg.get("round")
        if r and msg.get("stage") == "moderator":
            rounds.add(r)
    return len(rounds)
