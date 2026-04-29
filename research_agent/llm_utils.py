"""
LLM 工具函数 — 支持流式输出 + 长期记忆注入
"""

from __future__ import annotations

from langchain_moonshot import ChatMoonshot
from langchain_core.prompts import ChatPromptTemplate
from research_agent.streaming import push_token, get_stream
from research_agent.logger import get_logger

log = get_logger("llm")


def invoke_llm_streaming(
    session_id: str,
    system_prompt: str,
    human_template: str,
    variables: dict,
    thinking: bool = False,
    memory_context: str = "",
) -> str:
    """
    调用 LLM，如果 session 有 SSE stream 则逐 token 推送，否则普通调用。

    Args:
        memory_context: 长期记忆上下文，会追加到 system prompt 末尾
    """
    llm = ChatMoonshot(
        model="kimi-k2.5",
        thinking=thinking,
        temperature=1.0 if thinking else 0.6,
    )

    # 注入记忆到 system prompt
    full_system = system_prompt
    if memory_context:
        full_system = system_prompt + memory_context

    prompt = ChatPromptTemplate.from_messages([
        ("system", full_system),
        ("human", human_template),
    ])
    chain = prompt | llm

    q = get_stream(session_id)
    log.info(f"[{session_id}] LLM 调用 | thinking={thinking} stream={q is not None} memory={bool(memory_context)}")

    if q:
        full_text = ""
        for chunk in chain.stream(variables):
            token = chunk.content
            if token:
                full_text += token
                push_token(session_id, token)
                # 重复检测：如果最近输出中出现大段重复，提前截断
                if len(full_text) > 600 and _is_repeating(full_text):
                    log.warning(f"[{session_id}] 检测到重复输出，提前截断 | {len(full_text)} 字符")
                    full_text = _truncate_repetition(full_text)
                    break
        log.info(f"[{session_id}] LLM 流式完成 | {len(full_text)} 字符")
        return full_text
    else:
        response = chain.invoke(variables)
        log.info(f"[{session_id}] LLM 普通完成 | {len(response.content)} 字符")
        return response.content


def _is_repeating(text: str, window: int = 200, threshold: float = 0.85) -> bool:
    """
    检测文本末尾是否出现重复模式。
    取最后 window 个字符，检查它是否在之前的文本中大量出现。
    """
    if len(text) < window * 2:
        return False
    tail = text[-window:]
    body = text[:-window]
    # 检查 tail 是否在 body 中出现过
    if tail in body:
        return True
    # 检查较短的重复片段（至少 80 字符）
    for seg_len in (150, 100, 80):
        seg = text[-seg_len:]
        count = text[:-seg_len].count(seg)
        if count >= 2:
            return True
    return False


def _truncate_repetition(text: str) -> str:
    """截断重复部分，保留第一次出现的完整内容"""
    # 尝试找到重复的起始点
    for seg_len in (200, 150, 100, 80):
        if len(text) < seg_len * 2:
            continue
        seg = text[-seg_len:]
        first_pos = text.find(seg)
        if first_pos >= 0 and first_pos < len(text) - seg_len:
            # 在第一次出现后截断
            return text[:first_pos + seg_len].rstrip() + "\n\n---\n*（检测到重复输出，已自动截断）*"
    # fallback: 截掉后半段
    return text[:len(text) // 2].rstrip() + "\n\n---\n*（检测到重复输出，已自动截断）*"
