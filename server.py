"""
科研智能体 Web 服务 — SSE 流式输出版

API:
  POST /api/auth/register  — 注册
  POST /api/auth/login     — 登录
  GET  /api/auth/me        — 获取当前用户信息
  POST /api/start          — 开始新研究（返回 session_id）
  POST /api/continue       — 用户确认继续（返回 session_id）
  GET  /api/stream          — SSE 流式获取当前阶段输出
  GET  /api/status         — 获取会话状态
  GET  /api/sessions       — 获取用户的所有会话
  GET  /                   — 前端页面
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from research_agent.logger import setup_logging, get_logger
setup_logging()
log = get_logger("server")

import uuid
import queue
import threading
import sqlite3
import os
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
from langchain_moonshot import ChatMoonshot
from langchain_core.prompts import ChatPromptTemplate

from research_agent.main import create_app, STAGE_NAMES
from research_agent.auth import (
    init_user_db, create_user, authenticate_user,
    get_user_by_id, create_token, verify_token,
    UserRegister, UserLogin,
)

# ── 常量 ──────────────────────────────────────────────────────

AGENT_NAMES = {
    "literature_review": "@文献调研研究员",
    "hypothesis": "@假设生成研究员",
    "experiment_design": "@实验设计研究员",
    "experiment": "@代码实现研究员",
    "analysis": "@数据分析研究员",
    "paper": "@论文撰写研究员",
}

STAGE_OUTPUT_KEY = {
    "literature_review": "literature_review",
    "hypothesis": "hypothesis",
    "experiment_design": "experiment_design",
    "experiment": "experiment_code",
    "analysis": "analysis_result",
    "paper": "paper_draft",
}

STAGE_ORDER = [
    "literature_review", "hypothesis", "experiment_design",
    "experiment", "analysis", "paper",
]

INTERRUPT_TO_STAGE_IDX = {
    "human_after_literature": 0,
    "human_after_hypothesis": 1,
    "human_after_design": 2,
    "human_after_experiment": 3,
    "human_after_analysis": 4,
}

# ── 会话数据库 ────────────────────────────────────────────────

SESSIONS_DB = os.path.join(os.path.dirname(__file__), "sessions.db")


def _init_sessions_db():
    conn = sqlite3.connect(SESSIONS_DB, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            topic TEXT DEFAULT '',
            status TEXT DEFAULT 'idle',
            current_stage TEXT DEFAULT '',
            mode TEXT DEFAULT 'workflow',
            messages TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def _get_session_db():
    return sqlite3.connect(SESSIONS_DB, check_same_thread=False)


def _load_session(sid: str) -> dict | None:
    conn = _get_session_db()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"], "user_id": row["user_id"], "topic": row["topic"],
        "status": row["status"], "current_stage": row["current_stage"],
        "mode": row["mode"] if "mode" in row.keys() else "workflow",
        "messages": json.loads(row["messages"]), "created_at": row["created_at"],
    }


def _save_session(sid, user_id, topic, status, current_stage, messages):
    conn = _get_session_db()
    conn.execute("""
        INSERT INTO sessions (id, user_id, topic, status, current_stage, messages)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status=excluded.status, current_stage=excluded.current_stage,
            messages=excluded.messages, updated_at=datetime('now')
    """, (sid, user_id, topic, status, current_stage, json.dumps(messages, ensure_ascii=False)))
    conn.commit()
    conn.close()


def _get_user_sessions(user_id: int) -> list[dict]:
    conn = _get_session_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, topic, status, current_stage, created_at FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── SSE 流式队列管理 ─────────────────────────────────────────

from research_agent.streaming import push_status as _send_sse_status, push_end as _end_sse_raw


def _send_sse(sid: str, event: str, data: dict):
    """向指定 session 的 SSE 队列推送事件"""
    _send_sse_status(sid, event, data)


def _end_sse(sid: str):
    """结束 SSE 流"""
    _end_sse_raw(sid)


# ── Graph 执行（流式） ────────────────────────────────────────

def _run_graph_step_streaming(sid: str, user_id: int,
                              initial_state: dict | None = None, feedback: str = ""):
    """后台线程：运行 graph 一步，通过 SSE 流式推送 LLM 输出"""
    log.info(f"[{sid}] Graph step 开始 | initial={initial_state is not None} feedback={bool(feedback)}")
    session = _load_session(sid)
    if not session:
        _end_sse(sid)
        return

    messages = session["messages"]
    config = {"configurable": {"thread_id": sid}}
    _save_session(sid, user_id, session["topic"], "running", session["current_stage"], messages)

    try:
        if initial_state is not None:
            result = None
            for event in graph.stream(initial_state, config, stream_mode="values"):
                result = event
                # 检查是否有新的阶段输出，流式推送
                stage = event.get("current_stage", "")
                if stage:
                    output_key = STAGE_OUTPUT_KEY.get(stage, "")
                    content = event.get(output_key, "")
                    if content:
                        _send_sse(sid, "token", {
                            "agent": AGENT_NAMES.get(stage, f"@{stage}"),
                            "stage": stage,
                            "content": content,
                            "done": False,
                        })
        else:
            if feedback:
                graph.update_state(config, {"human_feedback": feedback})
            result = None
            for event in graph.stream(None, config, stream_mode="values"):
                result = event
                stage = event.get("current_stage", "")
                if stage:
                    output_key = STAGE_OUTPUT_KEY.get(stage, "")
                    content = event.get(output_key, "")
                    if content:
                        _send_sse(sid, "token", {
                            "agent": AGENT_NAMES.get(stage, f"@{stage}"),
                            "stage": stage,
                            "content": content,
                            "done": False,
                        })

        snapshot = graph.get_state(config)
        log.info(f"[{sid}] Graph step 完成 | next={snapshot.next}")

        if not snapshot.next:
            if result:
                stage = result.get("current_stage", "paper")
                output_key = STAGE_OUTPUT_KEY.get(stage, "")
                content = result.get(output_key, "") if output_key else ""
                if content:
                    messages.append({
                        "role": "agent",
                        "agent": AGENT_NAMES.get(stage, f"@{stage}"),
                        "stage": stage, "content": content,
                    })
            messages.append({
                "role": "system", "agent": "Mock", "stage": "",
                "content": "🎉 科研流程全部完成！论文初稿已生成。",
            })
            _save_session(sid, user_id, session["topic"], "done",
                          result.get("current_stage", "paper") if result else "paper", messages)
            _send_sse(sid, "done", {"status": "done"})

            # 提取长期记忆（后台执行，不阻塞）
            if result:
                try:
                    from research_agent.memory import extract_and_save_memory
                    log.info(f"[{sid}] 开始提取长期记忆...")
                    extract_and_save_memory(
                        user_id, sid, session["topic"],
                        result.get("literature_review", ""),
                        result.get("hypothesis", ""),
                        result.get("experiment_code", ""),
                        result.get("analysis_result", ""),
                    )
                    log.info(f"[{sid}] 长期记忆提取完成")
                except Exception as me:
                    log.warning(f"[{sid}] 长期记忆提取失败: {me}")
        else:
            next_node = snapshot.next[0]
            stage_idx = INTERRUPT_TO_STAGE_IDX.get(next_node)
            if stage_idx is not None:
                stage = STAGE_ORDER[stage_idx]
                output_key = STAGE_OUTPUT_KEY.get(stage, "")
                content = ""
                if result and output_key:
                    content = result.get(output_key, "")
                elif output_key:
                    content = snapshot.values.get(output_key, "")
                messages.append({
                    "role": "agent",
                    "agent": AGENT_NAMES.get(stage, f"@{stage}"),
                    "stage": stage, "content": content,
                })
                _save_session(sid, user_id, session["topic"], "waiting", stage, messages)
                _send_sse(sid, "stage_done", {
                    "status": "waiting", "stage": stage,
                    "agent": AGENT_NAMES.get(stage, ""),
                })
            else:
                _save_session(sid, user_id, session["topic"], "waiting",
                              session["current_stage"], messages)
                _send_sse(sid, "stage_done", {"status": "waiting", "stage": session["current_stage"]})

    except Exception as e:
        log.error(f"[{sid}] Graph step 异常: {e}", exc_info=True)
        messages.append({
            "role": "system", "agent": "Mock", "stage": "",
            "content": f"⚠️ 执行出错: {str(e)}",
        })
        _save_session(sid, user_id, session["topic"], "waiting",
                      session["current_stage"], messages)
        _send_sse(sid, "error", {"message": str(e)})

    # 延迟结束 SSE，确保前端有时间处理 stage_done 事件
    import time
    time.sleep(0.3)
    _end_sse(sid)
    log.info(f"[{sid}] SSE 流已结束")


# ── App 初始化 ────────────────────────────────────────────────

graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    init_user_db()
    _init_sessions_db()
    from research_agent.memory import init_memory_db
    init_memory_db()
    graph = create_app()
    yield


app = FastAPI(lifespan=lifespan)


def get_current_user(request: Request) -> int:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    user_id = verify_token(auth[7:])
    if user_id is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    return user_id


class StartRequest(BaseModel):
    topic: str

class ContinueRequest(BaseModel):
    session_id: str
    feedback: str = ""


# ── 认证 API ─────────────────────────────────────────────────

@app.post("/api/auth/register")
def register(req: UserRegister):
    log.info(f"注册请求 | username={req.username}")
    result = create_user(req.username, req.password, req.display_name)
    if isinstance(result, str):
        raise HTTPException(status_code=400, detail=result)
    token = create_token(result)
    return {"token": token, "user": result.model_dump()}

@app.post("/api/auth/login")
def login(req: UserLogin):
    log.info(f"登录请求 | username={req.username}")
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(user)
    return {"token": token, "user": user.model_dump()}

@app.get("/api/auth/me")
def get_me(request: Request):
    user_id = get_current_user(request)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"user": user.model_dump()}


# ── 研究 API ─────────────────────────────────────────────────

@app.post("/api/start")
def start_research(req: StartRequest, request: Request):
    user_id = get_current_user(request)
    sid = f"s-{uuid.uuid4().hex[:8]}"
    log.info(f"[{sid}] 新研究 | user={user_id} topic={req.topic[:50]}")

    messages = [
        {"role": "user", "agent": "用户", "stage": "", "content": f"研究课题：{req.topic}"},
        {"role": "system", "agent": "Mock", "stage": "",
         "content": "已收到课题，正在呼叫 @文献调研研究员 ..."},
    ]
    _save_session(sid, user_id, req.topic, "running", "", messages)

    initial_state = {
        "topic": req.topic,
        "literature_review": "", "hypothesis": "", "experiment_design": "",
        "experiment_code": "", "analysis_result": "", "paper_draft": "",
        "messages": [], "human_feedback": "", "current_stage": "",
        "session_id": sid,
        "user_id": user_id,
        "memory_context": "",
    }

    # 注入长期记忆
    from research_agent.memory import build_memory_context
    memory_ctx = build_memory_context(user_id)
    if memory_ctx:
        initial_state["memory_context"] = memory_ctx
        log.info(f"[{sid}] 注入长期记忆 | {len(memory_ctx)} 字符")

    from research_agent.streaming import create_stream
    create_stream(sid)

    t = threading.Thread(target=_run_graph_step_streaming, args=(sid, user_id, initial_state))
    t.start()

    return {"session_id": sid, "status": "running"}


@app.post("/api/continue")
def continue_research(req: ContinueRequest, request: Request):
    user_id = get_current_user(request)
    log.info(f"[{req.session_id}] 继续 | user={user_id} feedback={bool(req.feedback)}")
    session = _load_session(req.session_id)
    if not session or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["status"] == "done":
        return {"status": "done"}

    messages = session["messages"]
    if req.feedback:
        messages.append({"role": "user", "agent": "用户", "stage": "", "content": req.feedback})

    current_idx = STAGE_ORDER.index(session["current_stage"]) if session["current_stage"] in STAGE_ORDER else -1
    next_idx = current_idx + 1
    if next_idx < len(STAGE_ORDER):
        next_agent = AGENT_NAMES.get(STAGE_ORDER[next_idx], "")
        messages.append({"role": "system", "agent": "Mock", "stage": "",
                         "content": f"正在呼叫 {next_agent} ..."})

    _save_session(req.session_id, user_id, session["topic"], "running",
                  session["current_stage"], messages)

    from research_agent.streaming import create_stream
    create_stream(req.session_id)

    t = threading.Thread(
        target=_run_graph_step_streaming,
        args=(req.session_id, user_id, None, req.feedback),
    )
    t.start()

    return {"status": "running"}


@app.get("/api/stream")
def stream_sse(session_id: str, request: Request):
    """SSE 端点：流式推送 LLM 输出"""
    user_id = get_current_user(request)
    session = _load_session(session_id)
    if not session or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    from research_agent.streaming import get_stream, remove_stream

    def event_generator():
        q = get_stream(session_id)
        if not q:
            yield f"event: error\ndata: {{\"message\": \"no stream\"}}\n\n"
            return
        while True:
            try:
                item = q.get(timeout=120)
            except queue.Empty:
                yield f"event: ping\ndata: {{}}\n\n"
                continue
            if item is None:
                yield f"event: end\ndata: {{}}\n\n"
                remove_stream(session_id)
                break
            event = item["event"]
            data = item["data"]
            if isinstance(data, dict):
                data = json.dumps(data, ensure_ascii=True)
            # SSE 数据行不能包含真正的换行符
            # 将所有控制字符替换为转义形式
            data_escaped = data.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
            yield f"event: {event}\ndata: {data_escaped}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={
                                 "Cache-Control": "no-cache, no-store, must-revalidate",
                                 "X-Accel-Buffering": "no",
                                 "Connection": "keep-alive",
                                 "Content-Type": "text/event-stream; charset=utf-8",
                                 "ngrok-skip-browser-warning": "true",
                             })


@app.get("/api/status")
def get_status(session_id: str, request: Request):
    user_id = get_current_user(request)
    session = _load_session(session_id)
    if not session or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "status": session["status"], "topic": session["topic"],
        "current_stage": session["current_stage"], "messages": session["messages"],
    }


@app.get("/api/sessions")
def list_sessions(request: Request):
    user_id = get_current_user(request)
    return {"sessions": _get_user_sessions(user_id)}


# ── Chat 模式 API ────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    topic: str = ""


def _run_chat_turn(sid: str, user_id: int, message: str, topic: str):
    """后台线程：执行一轮 Chat 模式对话"""
    session = _load_session(sid)
    if not session:
        _end_sse(sid)
        return

    messages = session["messages"]
    log.info(f"[{sid}] Chat turn | message={message[:50]}")

    try:
        from research_agent.chat_mode import chat_turn
        from research_agent.memory import build_memory_context

        memory_ctx = build_memory_context(user_id)
        new_msgs = chat_turn(sid, user_id, message, messages, memory_ctx)

        messages.extend(new_msgs)
        current_stage = ""
        for m in reversed(new_msgs):
            if m.get("stage") and m["stage"] != "lead":
                current_stage = m["stage"]
                break

        _save_session(sid, user_id, topic or session["topic"], "waiting", current_stage, messages)
        _send_sse(sid, "stage_done", {"status": "waiting", "stage": current_stage})

    except Exception as e:
        log.error(f"[{sid}] Chat turn 异常: {e}", exc_info=True)
        messages.append({"role": "system", "agent": "Mock", "stage": "",
                         "content": f"⚠️ 错误: {str(e)}"})
        _save_session(sid, user_id, topic or session["topic"], "waiting", "", messages)
        _send_sse(sid, "error", {"message": str(e)})

    import time
    time.sleep(0.3)
    _end_sse(sid)
    log.info(f"[{sid}] Chat turn SSE 流结束")


# ── 讨论模式 API ─────────────────────────────────────────────

class DebateStartRequest(BaseModel):
    topic: str
    max_rounds: int = 5

class DebateMessageRequest(BaseModel):
    session_id: str
    message: str = ""


def _run_debate_round(sid: str, user_id: int, user_message: str | None = None):
    """后台线程：执行一轮讨论"""
    session = _load_session(sid)
    if not session:
        _end_sse(sid)
        return

    messages = session["messages"]
    topic = session["topic"]
    # max_rounds 存在 session 的 current_stage 字段里（复用）
    max_rounds = int(session.get("current_stage") or 5)

    try:
        from research_agent.debate import run_debate

        new_msgs = run_debate(
            sid=sid,
            topic=topic,
            max_rounds=max_rounds,
            history=messages,
            user_interrupt=user_message,
        )

        messages.extend(new_msgs)

        # 检查是否讨论结束
        from research_agent.debate import _count_rounds
        rounds_done = _count_rounds(messages)
        is_done = rounds_done >= max_rounds

        status = "done" if is_done else "waiting"
        _save_session(sid, user_id, topic, status, str(max_rounds), messages)

        if is_done:
            _send_sse(sid, "done", {"status": "done"})
        else:
            _send_sse(sid, "stage_done", {"status": "waiting", "stage": "debate"})

    except Exception as e:
        log.error(f"[{sid}] Debate 异常: {e}", exc_info=True)
        messages.append({"role": "system", "agent": "", "stage": "",
                         "content": f"⚠️ 讨论出错: {str(e)}"})
        _save_session(sid, user_id, topic, "waiting", str(max_rounds), messages)
        _send_sse(sid, "error", {"message": str(e)})

    import time
    time.sleep(0.3)
    _end_sse(sid)


@app.post("/api/debate/start")
def start_debate(req: DebateStartRequest, request: Request):
    """启动 Agent 讨论"""
    user_id = get_current_user(request)
    sid = f"d-{uuid.uuid4().hex[:8]}"
    log.info(f"[{sid}] 新讨论 | user={user_id} topic={req.topic[:50]} rounds={req.max_rounds}")

    messages = [
        {"role": "user", "agent": "用户", "stage": "", "content": f"讨论课题：{req.topic}"},
        {"role": "system", "agent": "", "stage": "",
         "content": f"🎯 讨论开始！最大 {req.max_rounds} 轮，目标：找到一个切实可行的创新点。"},
    ]
    # 用 current_stage 存 max_rounds
    _save_session(sid, user_id, req.topic, "running", str(req.max_rounds), messages)

    from research_agent.streaming import create_stream
    create_stream(sid)

    t = threading.Thread(target=_run_debate_round, args=(sid, user_id))
    t.start()

    return {"session_id": sid, "status": "running", "mode": "debate"}


@app.post("/api/debate/continue")
def continue_debate(req: DebateMessageRequest, request: Request):
    """继续讨论 / 用户插入发言（即使讨论已结束也可追问）"""
    user_id = get_current_user(request)
    session = _load_session(req.session_id)
    if not session or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = session["messages"]
    if req.message:
        messages.append({"role": "user", "agent": "用户", "stage": "", "content": req.message})

    # 如果已结束，重置 max_rounds 追加 2 轮继续讨论
    max_rounds = int(session.get("current_stage") or 5)
    if session["status"] == "done":
        from research_agent.debate import _count_rounds
        done_rounds = _count_rounds(messages)
        max_rounds = done_rounds + 2
        messages.append({"role": "system", "agent": "", "stage": "",
                         "content": f"📢 讨论重新开启，追加 2 轮。"})

    _save_session(req.session_id, user_id, session["topic"], "running",
                  str(max_rounds), messages)

    from research_agent.streaming import create_stream
    create_stream(req.session_id)

    t = threading.Thread(
        target=_run_debate_round,
        args=(req.session_id, user_id, req.message if req.message else None),
    )
    t.start()

    return {"status": "running"}


@app.post("/api/chat")
def chat_message(req: ChatRequest, request: Request):
    """Chat 模式：自由对话，Lead Agent 按需调用子智能体"""
    user_id = get_current_user(request)

    # 新会话或已有会话
    if req.session_id:
        sid = req.session_id
        session = _load_session(sid)
        if not session or session["user_id"] != user_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = session["messages"]
    else:
        sid = f"c-{uuid.uuid4().hex[:8]}"
        messages = []

    # 添加用户消息
    messages.append({"role": "user", "agent": "用户", "stage": "", "content": req.message})
    topic = req.topic or (messages[0]["content"][:50] if messages else req.message[:50])
    _save_session(sid, user_id, topic, "running", "", messages)

    log.info(f"[{sid}] Chat 模式 | user={user_id} msg={req.message[:50]}")

    from research_agent.streaming import create_stream
    create_stream(sid)

    t = threading.Thread(target=_run_chat_turn, args=(sid, user_id, req.message, topic))
    t.start()

    return {"session_id": sid, "status": "running", "mode": "chat"}


# ── 记忆 API ─────────────────────────────────────────────────

@app.get("/api/memory")
def get_memory(request: Request):
    """获取当前用户的长期记忆（画像 + 研究档案）"""
    user_id = get_current_user(request)
    from research_agent.memory import get_user_profile, get_research_archives
    profile = get_user_profile(user_id)
    archives = get_research_archives(user_id, limit=20)
    return {"profile": profile, "archives": archives}


@app.delete("/api/memory/profile/{key}")
def delete_profile_key(key: str, request: Request):
    """删除用户画像中的某个字段"""
    user_id = get_current_user(request)
    from research_agent.memory import _get_conn
    conn = _get_conn()
    conn.execute("DELETE FROM user_profile WHERE user_id = ? AND key = ?", (user_id, key))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/memory/archive/{archive_id}")
def delete_archive(archive_id: int, request: Request):
    """删除某条研究档案"""
    user_id = get_current_user(request)
    from research_agent.memory import _get_conn
    conn = _get_conn()
    conn.execute("DELETE FROM research_archive WHERE id = ? AND user_id = ?", (archive_id, user_id))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── 代码 Agent API ───────────────────────────────────────────

class CodeAgentRequest(BaseModel):
    session_id: str | None = None
    task: str
    context: str = ""


def _run_code_agent(sid: str, user_id: int, task: str, context: str):
    """后台线程：运行代码 Agent"""
    session = _load_session(sid)
    if not session:
        _end_sse(sid)
        return

    messages = session["messages"]
    log.info(f"[{sid}] Code Agent | task={task[:50]}")

    try:
        from research_agent.code_agent import run_code_agent
        from research_agent.memory import build_memory_context

        memory_ctx = build_memory_context(user_id)
        
        # 推送开始状态
        _send_sse(sid, "agent_start", {"agent": "@代码实现研究员", "task": task[:100]})
        
        result = run_code_agent(
            sid=sid,
            user_id=user_id,
            task=task,
            context=context,
            memory_context=memory_ctx,
        )

        # 构建响应消息
        if result["success"]:
            response_content = f"代码执行成功！\n\n```python\n{result['code']}\n```\n\n**执行输出：**\n```\n{result['output']}\n```"
        else:
            response_content = f"代码执行失败（尝试 {result['attempts']} 次）\n\n```python\n{result['code']}\n```\n\n**错误信息：**\n```\n{result['error']}\n```\n\n请告诉我需要如何调整，或者提供更多信息。"

        messages.append({
            "role": "agent",
            "agent": "@代码实现研究员",
            "stage": "experiment",
            "content": response_content,
            "agent_steps": result["steps"],  # 保存步骤供前端展示
        })

        _save_session(sid, user_id, session["topic"], "waiting", "experiment", messages)
        _send_sse(sid, "agent_done", {
            "success": result["success"],
            "steps": result["steps"],
        })

    except Exception as e:
        log.error(f"[{sid}] Code Agent 异常: {e}", exc_info=True)
        messages.append({
            "role": "system",
            "agent": "",
            "stage": "",
            "content": f"⚠️ 代码执行出错: {str(e)}",
        })
        _save_session(sid, user_id, session["topic"], "waiting", "", messages)
        _send_sse(sid, "error", {"message": str(e)})

    import time
    time.sleep(0.3)
    _end_sse(sid)
    log.info(f"[{sid}] Code Agent 完成")


@app.post("/api/code/agent")
def run_code_agent_api(req: CodeAgentRequest, request: Request):
    """运行代码 Agent：自动生成、验证、执行、修复代码"""
    user_id = get_current_user(request)

    # 新会话或已有会话
    if req.session_id:
        sid = req.session_id
        session = _load_session(sid)
        if not session or session["user_id"] != user_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = session["messages"]
    else:
        sid = f"code-{uuid.uuid4().hex[:8]}"
        messages = []

    # 添加用户消息
    messages.append({"role": "user", "agent": "用户", "stage": "", "content": req.task})
    topic = req.task[:50]
    _save_session(sid, user_id, topic, "running", "", messages)

    log.info(f"[{sid}] Code Agent 请求 | user={user_id} task={req.task[:50]}")

    from research_agent.streaming import create_stream
    create_stream(sid)

    t = threading.Thread(
        target=_run_code_agent,
        args=(sid, user_id, req.task, req.context),
    )
    t.start()

    return {"session_id": sid, "status": "running", "mode": "code"}


# ── 代码沙箱执行 API ─────────────────────────────────────────

class CodeExecuteRequest(BaseModel):
    code: str
    language: str = "python"
    timeout: int = 30


@app.post("/api/code/execute")
def execute_code_api(req: CodeExecuteRequest, request: Request):
    """在安全沙箱中执行代码"""
    user_id = get_current_user(request)
    log.info(f"代码执行请求 | user={user_id} lang={req.language} len={len(req.code)}")

    from research_agent.sandbox import execute_code
    result = execute_code(
        code=req.code,
        timeout=req.timeout,
        language=req.language,
    )

    log.info(f"代码执行结果 | user={user_id} success={result.success} duration={result.duration}s")
    return result.to_dict()


# ── 设置 API ─────────────────────────────────────────────────

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")


def _load_settings() -> dict:
    """加载设置"""
    defaults = {
        "python_path": "",
        "work_dir": "",
        "model_name": "kimi-k2.5",
        "model_base_url": os.environ.get("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1"),
        "model_api_key": os.environ.get("MOONSHOT_API_KEY", ""),
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # 合并，保留已保存的值
            for k, v in saved.items():
                if v:  # 只覆盖非空值
                    defaults[k] = v
        except Exception:
            pass
    return defaults


def _save_settings(settings: dict):
    """保存设置到文件"""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    # 同步更新环境变量
    if settings.get("model_api_key"):
        os.environ["MOONSHOT_API_KEY"] = settings["model_api_key"]
    if settings.get("model_base_url"):
        os.environ["MOONSHOT_API_BASE"] = settings["model_base_url"]


@app.get("/api/settings")
def get_settings(request: Request):
    """获取当前设置"""
    get_current_user(request)
    settings = _load_settings()
    # API Key 脱敏
    masked = dict(settings)
    if masked.get("model_api_key"):
        key = masked["model_api_key"]
        masked["model_api_key"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return {"settings": masked}


class SettingsRequest(BaseModel):
    python_path: str = ""
    work_dir: str = ""
    model_name: str = ""
    model_base_url: str = ""
    model_api_key: str = ""


@app.post("/api/settings")
def save_settings(req: SettingsRequest, request: Request):
    """保存设置"""
    get_current_user(request)
    current = _load_settings()
    
    # 更新字段
    if req.python_path is not None:
        current["python_path"] = req.python_path
    if req.work_dir is not None:
        current["work_dir"] = req.work_dir
    if req.model_name:
        current["model_name"] = req.model_name
    if req.model_base_url:
        current["model_base_url"] = req.model_base_url
    if req.model_api_key and "****" not in req.model_api_key:
        current["model_api_key"] = req.model_api_key
    
    _save_settings(current)
    log.info(f"设置已保存 | model={current['model_name']} base_url={current['model_base_url']}")
    return {"ok": True}


@app.post("/api/settings/reset")
def reset_settings(request: Request):
    """恢复默认设置"""
    get_current_user(request)
    defaults = {
        "python_path": "",
        "work_dir": "",
        "model_name": "kimi-k2.5",
        "model_base_url": "https://api.moonshot.cn/v1",
        "model_api_key": os.environ.get("MOONSHOT_API_KEY", ""),
    }
    _save_settings(defaults)
    # 脱敏返回
    masked = dict(defaults)
    if masked.get("model_api_key"):
        key = masked["model_api_key"]
        masked["model_api_key"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return {"settings": masked}


class BrowseDirRequest(BaseModel):
    path: str = ""


@app.post("/api/browse-dir")
def browse_directory(req: BrowseDirRequest, request: Request):
    """浏览目录，返回子目录列表"""
    get_current_user(request)
    
    # 默认从用户主目录开始
    base = req.path or os.path.expanduser("~")
    if not os.path.isdir(base):
        base = os.path.expanduser("~")
    
    items = []
    try:
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if os.path.isdir(full) and not name.startswith('.'):
                items.append(name)
    except PermissionError:
        pass
    
    # 获取父目录
    parent = os.path.dirname(base)
    
    return {
        "current": base,
        "parent": parent if parent != base else "",
        "dirs": items[:50],  # 最多 50 个
    }


# ── 前端页面 ──────────────────────────────────────────────────

# React 构建产物目录
REACT_DIST = os.path.join(os.path.dirname(__file__), "Futuristic AI Chat Interface", "dist")

@app.get("/assets/{path:path}")
def serve_assets(path: str):
    """Serve Vite build assets (JS/CSS chunks)"""
    file_path = os.path.join(REACT_DIST, "assets", path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404)

@app.get("/{path:path}")
def serve_spa(path: str):
    """SPA fallback: serve index.html for all non-API routes"""
    # Try to serve the exact file first (e.g. favicon.ico)
    file_path = os.path.join(REACT_DIST, path)
    if path and os.path.isfile(file_path):
        return FileResponse(file_path)
    # Fallback to index.html for SPA routing
    index = os.path.join(REACT_DIST, "index.html")
    if os.path.isfile(index):
        return FileResponse(index, media_type="text/html")
    # Dev fallback: serve old frontend if React not built yet
    return FileResponse("frontend/index.html", media_type="text/html")
