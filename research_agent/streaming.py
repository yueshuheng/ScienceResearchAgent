"""
流式输出管理器

每个 session 有一个 Queue，agent 内部流式调用 LLM 时，
把每个 token 推送到 Queue，前端通过 SSE 实时读取。
"""

from __future__ import annotations

import queue
import json

# session_id -> Queue
_queues: dict[str, queue.Queue] = {}


def create_stream(sid: str) -> queue.Queue:
    q = queue.Queue()
    _queues[sid] = q
    return q


def get_stream(sid: str) -> queue.Queue | None:
    return _queues.get(sid)


def remove_stream(sid: str):
    _queues.pop(sid, None)


def push_token(sid: str, token: str):
    """推送一个文本 token"""
    q = _queues.get(sid)
    if q:
        q.put({"event": "token", "data": token})


def push_status(sid: str, event: str, data: dict):
    """推送状态事件（stage_start, stage_done, error, done）"""
    q = _queues.get(sid)
    if q:
        q.put({"event": event, "data": json.dumps(data, ensure_ascii=False)})


def push_end(sid: str):
    """结束流"""
    q = _queues.get(sid)
    if q:
        q.put(None)
