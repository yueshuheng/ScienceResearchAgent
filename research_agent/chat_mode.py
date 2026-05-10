"""
Chat 模式 — Lead Agent 自由对话

Lead Agent 与用户对话，根据需要 @研究员 调用子智能体。
不走固定流程，由 Lead Agent 判断何时调用谁。
"""

from __future__ import annotations

import json
from research_agent.llm_utils import invoke_llm_streaming
from research_agent.streaming import push_status, push_token, get_stream
from research_agent.tools.scholar import search_arxiv_fast
from research_agent.logger import get_logger

log = get_logger("chat_mode")

LEAD_SYSTEM = """\
你是一位资深科研项目负责人（Lead Researcher），负责与用户对话并协调研究团队完成科研任务。

## 你的团队
- @文献调研研究员：搜索 arXiv 真实论文并撰写文献综述
- @假设生成研究员：基于文献提出可验证的科学假设
- @实验设计研究员：设计完整实验方案（数据集、模型、评估指标）
- @代码实现研究员：生成、验证、执行 Python 代码，自动修复错误（支持文件操作和 Shell 命令）
- @数据分析研究员：分析实验结果、统计检验、可视化
- @论文撰写研究员：撰写学术论文或论文片段

## 工作原则

1. **先理解再行动**：如果用户的需求不够清晰，主动追问以补全关键信息。例如：
   - 研究领域/方向不明确 → 追问具体方向
   - 缺少约束条件 → 追问数据规模、计算资源、时间限制等
   - 目标模糊 → 追问期望的产出形式（综述？代码？论文？）

2. **自主判断调用时机**：根据对话上下文判断是否需要调用研究员，以及调用谁。不需要用户明确指示。例如：
   - 用户提到一个研究课题 → 你可以主动建议先做文献调研
   - 用户说"帮我写个实验" → 你判断是否已有足够背景信息，不够就先追问或先调文献
   - 用户说"写个代码"、"实现一个算法"、"运行一下" → 调用 @代码实现研究员
   - 用户问一个简单问题 → 直接回答，不调用任何研究员

3. **一次只调用一个研究员**：每轮对话最多调用一个研究员，等结果出来后再决定下一步。

4. **保持对话自然**：像一个真正的项目负责人一样交流，给出你的专业判断和建议。

5. **简洁不重复**：回复要简洁有条理，绝对不要重复相同的内容。如果信息已经说过，直接推进到下一步。

## 调用格式

当你决定调用研究员时，在回复末尾输出一个 JSON 代码块：

```json
{{"call": "研究员名称", "task": "给研究员的具体任务描述，要详细"}}
```

研究员名称必须是：literature, hypothesis, experiment_design, experiment_code, analysis, paper

如果不需要调用研究员（直接回答或追问），就不要输出 JSON 代码块。
"""

AGENT_PROMPTS = {
    "literature": """\
你是 @文献调研研究员。根据任务要求，搜索和综述相关学术论文。
基于提供的真实论文数据完成综述，不要编造论文。
以 Markdown 格式输出。""",

    "hypothesis": """\
你是 @假设生成研究员。根据任务要求和已有研究背景，提出 2-3 个可验证的科学假设。
为每个假设说明理论依据、创新性和可行性。以 Markdown 格式输出。""",

    "experiment_design": """\
你是 @实验设计研究员。根据任务要求，设计详细的实验方案。
包含数据集选择、模型方法、评估指标、实验流程。以 Markdown 格式输出。""",

    "experiment_code": """\
你是 @代码实现研究员。根据任务要求，生成完整可运行的 Python 实验代码。
代码要有详细注释、依赖说明、运行说明。以 Markdown 格式输出。""",

    "analysis": """\
你是 @数据分析研究员。根据任务要求，分析实验设计和预期结果。
提供统计方法、可视化方案、局限性讨论。以 Markdown 格式输出。""",

    "paper": """\
你是 @论文撰写研究员。根据任务要求，撰写学术论文或论文片段。
遵循标准学术论文结构。以 Markdown 格式输出。""",
}

AGENT_DISPLAY = {
    "literature": ("@文献调研研究员", "📚", "literature_review"),
    "hypothesis": ("@假设生成研究员", "💡", "hypothesis"),
    "experiment_design": ("@实验设计研究员", "📋", "experiment_design"),
    "experiment_code": ("@代码实现研究员", "🧪", "experiment"),
    "analysis": ("@数据分析研究员", "📊", "analysis"),
    "paper": ("@论文撰写研究员", "📝", "paper"),
}


def _parse_call(text: str) -> dict | None:
    """从 Lead Agent 回复中提取 JSON 调用指令"""
    import re
    match = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1).strip())
        if "call" in data and "task" in data:
            return data
    except json.JSONDecodeError:
        pass
    return None


def chat_turn(sid: str, user_id: int, user_message: str,
              chat_history: list[dict], memory_context: str = "") -> list[dict]:
    """
    处理一轮 Chat 模式对话。

    Args:
        sid: 会话 ID
        user_id: 用户 ID
        user_message: 用户输入
        chat_history: 之前的对话历史 [{role, content}]
        memory_context: 长期记忆

    Returns:
        新增的消息列表 [{role, agent, stage, content}]
    """
    new_messages = []

    # 构建对话历史给 Lead Agent
    history_text = ""
    for msg in chat_history[-20:]:
        role = "用户" if msg.get("role") == "user" else msg.get("agent", "系统")
        history_text += f"{role}: {msg.get('content', '')[:500]}\n\n"

    # Step 1: Lead Agent 分析（不流式，避免 JSON 指令泄露到前端）
    push_status(sid, "stage_start", {"stage": "lead", "agent": "@项目负责人"})
    push_status(sid, "info", {"message": "@项目负责人 正在分析你的需求..."})

    from langchain_moonshot import ChatMoonshot
    from langchain_core.prompts import ChatPromptTemplate

    lead_llm = ChatMoonshot(model="kimi-k2.5", thinking=False, temperature=0.6)
    lead_prompt = ChatPromptTemplate.from_messages([
        ("system", LEAD_SYSTEM + (memory_context or "")),
        ("human", "对话历史：\n{history}\n\n用户最新消息：{message}"),
    ])
    lead_chain = lead_prompt | lead_llm
    lead_result = lead_chain.invoke({"history": history_text, "message": user_message})
    lead_response = lead_result.content

    # 重复检测：截断退化重复
    from research_agent.llm_utils import _is_repeating, _truncate_repetition
    if len(lead_response) > 600 and _is_repeating(lead_response):
        log.warning(f"[{sid}] Lead 回复检测到重复，截断 | {len(lead_response)} 字符")
        lead_response = _truncate_repetition(lead_response)

    log.info(f"[{sid}] Lead 回复: {lead_response[:100]}...")

    # 解析是否需要调用子 agent
    call_info = _parse_call(lead_response)

    # 去掉 JSON 代码块，只保留文字回复推送到前端
    import re
    clean_response = re.sub(r"```json\s*\n.*?```", "", lead_response, flags=re.DOTALL).strip()

    if clean_response:
        # 批量推送 Lead 的回复（避免逐字符推送在 ngrok 下产生问题）
        # 按 50 字符一批推送，减少 SSE 事件数量
        chunk_size = 50
        for i in range(0, len(clean_response), chunk_size):
            chunk = clean_response[i:i+chunk_size]
            push_token(sid, chunk)
        new_messages.append({
            "role": "agent", "agent": "@项目负责人",
            "stage": "lead", "content": clean_response,
        })

    # Step 2: 如果需要调用子 agent
    if call_info:
        agent_key = call_info["call"]
        task = call_info["task"]

        if agent_key not in AGENT_PROMPTS:
            log.warning(f"[{sid}] 未知研究员: {agent_key}")
            return new_messages

        display_name, emoji, stage = AGENT_DISPLAY[agent_key]
        log.info(f"[{sid}] Lead 调用 {display_name} | task={task[:50]}")

        push_status(sid, "stage_start", {"stage": stage, "agent": display_name})

        # 代码研究员使用 Agent Loop（自动生成、验证、执行、修复）
        if agent_key == "experiment_code":
            push_status(sid, "info", {"message": "@代码实现研究员 正在工作中..."})
            push_status(sid, "agent_start", {"agent": display_name, "task": task[:100]})
            
            try:
                from research_agent.code_agent import run_code_agent
                result = run_code_agent(
                    sid=sid,
                    user_id=user_id,
                    task=task,
                    context=history_text[-2000:],
                    memory_context=memory_context,
                )
                
                # 构建响应消息
                if result["success"]:
                    agent_response = f"代码执行成功！\n\n```python\n{result['code']}\n```\n\n**执行输出：**\n```\n{result['output']}\n```"
                else:
                    agent_response = f"代码执行失败（尝试 {result['attempts']} 次）\n\n```python\n{result['code']}\n```\n\n**错误信息：**\n```\n{result['error']}\n```\n\n请告诉我需要如何调整，或者提供更多信息。"
                
                # 推送完成状态
                push_status(sid, "agent_done", {
                    "success": result["success"],
                    "steps": result["steps"],
                })
                
                new_messages.append({
                    "role": "agent", "agent": display_name,
                    "stage": stage, "content": agent_response,
                    "agent_steps": result["steps"],
                })
            except Exception as e:
                log.error(f"[{sid}] 代码研究员执行异常: {e}", exc_info=True)
                push_status(sid, "agent_done", {"success": False, "steps": []})
                new_messages.append({
                    "role": "agent", "agent": display_name,
                    "stage": stage, "content": f"代码执行出错：{str(e)}\n\n请稍后重试或换一种方式描述需求。",
                })
            
            return new_messages

        # 文献调研需要先搜索论文
        extra_context = ""
        if agent_key == "literature":
            push_status(sid, "info", {"message": "正在搜索 arXiv 论文..."})
            # 用任务描述作为搜索关键词
            papers = search_arxiv_fast(task[:100], limit=10)
            if papers:
                extra_context = "\n\n===== 搜索到的论文 =====\n\n" + "\n\n---\n\n".join(
                    f"【论文 {i+1}】\n{p.to_text()}" for i, p in enumerate(papers[:10])
                )
                push_status(sid, "info", {"message": f"找到 {len(papers)} 篇论文"})

        # 调用子 agent
        agent_prompt = AGENT_PROMPTS[agent_key]
        agent_response = invoke_llm_streaming(
            sid, agent_prompt,
            "任务：{task}\n\n相关背景：\n{context}{extra}",
            {
                "task": task,
                "context": history_text[-2000:],
                "extra": extra_context,
            },
            thinking=agent_key in ("experiment_design", "experiment_code"),
            memory_context=memory_context,
        )

        new_messages.append({
            "role": "agent", "agent": display_name,
            "stage": stage, "content": agent_response,
        })

    return new_messages
