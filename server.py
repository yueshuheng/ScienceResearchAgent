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
                data = json.dumps(data, ensure_ascii=False)
            # 转义换行符用于 SSE
            data_escaped = data.replace("\n", "\\n")
            yield f"event: {event}\ndata: {data_escaped}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


# ── 前端页面 ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/app.js")
def app_js():
    return FileResponse("frontend/app.js", media_type="application/javascript")

@app.get("/style.css")
def style_css():
    return FileResponse("frontend/style.css", media_type="text/css")
