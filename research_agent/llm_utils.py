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
        log.info(f"[{session_id}] LLM 流式完成 | {len(full_text)} 字符")
        return full_text
    else:
        response = chain.invoke(variables)
        log.info(f"[{session_id}] LLM 普通完成 | {len(response.content)} 字符")
        return response.content
