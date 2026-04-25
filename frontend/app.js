// ── 科研智能体前端 — SSE 流式 + Markdown 渲染 ────────────────

let token = localStorage.getItem("token");
let currentUser = null;
let currentSessionId = null;
let eventSource = null;
let streamingMsgEl = null;   // 当前正在流式写入的消息 DOM
let streamingText = "";      // 当前流式累积的文本

const STAGE_ORDER = [
  "literature_review", "hypothesis", "experiment_design",
  "experiment", "analysis", "paper"
];
const AGENT_AVATARS = {
  literature_review: "📚", hypothesis: "💡", experiment_design: "📋",
  experiment: "🧪", analysis: "📊", paper: "📝",
};
const AGENT_LABELS = {
  literature_review: "文献调研", hypothesis: "假设生成", experiment_design: "实验设计",
  experiment: "代码实现", analysis: "结果分析", paper: "论文撰写",
};

// ── marked 配置 ──────────────────────────────────────────────

const _hljs = typeof hljs !== "undefined" ? hljs : null;

marked.setOptions({
  highlight: function(code, lang) {
    if (!_hljs) return code;
    if (lang && _hljs.getLanguage(lang)) {
      return _hljs.highlight(code, { language: lang }).value;
    }
    return _hljs.highlightAuto(code).value;
  },
  breaks: true,
  gfm: true,
});

// ── 初始化 ───────────────────────────────────────────────────

window.addEventListener("DOMContentLoaded", async () => {
  if (token) {
    try {
      const resp = await api("GET", "/api/auth/me");
      currentUser = resp.user;
      showApp();
    } catch { localStorage.removeItem("token"); token = null; }
  }
});

// ── API ──────────────────────────────────────────────────────

async function api(method, url, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (token) opts.headers["Authorization"] = `Bearer ${token}`;
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(url, opts);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || "请求失败");
  return data;
}

// ── 认证 ─────────────────────────────────────────────────────

function showLogin() {
  document.getElementById("login-form").style.display = "flex";
  document.getElementById("register-form").style.display = "none";
}
function showRegister() {
  document.getElementById("login-form").style.display = "none";
  document.getElementById("register-form").style.display = "flex";
}

async function doLogin() {
  const u = document.getElementById("login-username").value.trim();
  const p = document.getElementById("login-password").value;
  const err = document.getElementById("login-error");
  err.textContent = "";
  if (!u || !p) { err.textContent = "请填写用户名和密码"; return; }
  try {
    const d = await api("POST", "/api/auth/login", { username: u, password: p });
    token = d.token; localStorage.setItem("token", token);
    currentUser = d.user; showApp();
  } catch (e) { err.textContent = e.message; }
}

async function doRegister() {
  const u = document.getElementById("reg-username").value.trim();
  const dn = document.getElementById("reg-display").value.trim();
  const p = document.getElementById("reg-password").value;
  const p2 = document.getElementById("reg-password2").value;
  const err = document.getElementById("reg-error");
  err.textContent = "";
  if (!u || !p) { err.textContent = "请填写用户名和密码"; return; }
  if (p !== p2) { err.textContent = "两次密码不一致"; return; }
  try {
    const d = await api("POST", "/api/auth/register", { username: u, password: p, display_name: dn || u });
    token = d.token; localStorage.setItem("token", token);
    currentUser = d.user; showApp();
  } catch (e) { err.textContent = e.message; }
}

function doLogout() {
  token = null; currentUser = null; localStorage.removeItem("token");
  closeSSE();
  document.getElementById("auth-page").style.display = "flex";
  document.getElementById("main-app").style.display = "none";
}

// ── 主应用 ───────────────────────────────────────────────────

function showApp() {
  document.getElementById("auth-page").style.display = "none";
  document.getElementById("main-app").style.display = "flex";
  document.getElementById("user-name").textContent = currentUser.display_name;
  document.getElementById("user-avatar").textContent = currentUser.display_name[0].toUpperCase();
  loadSessions();
  showWelcome();
}

async function loadSessions() {
  try {
    const d = await api("GET", "/api/sessions");
    renderSessionList(d.sessions);
  } catch {}
}

function renderSessionList(sessions) {
  const el = document.getElementById("session-list");
  el.innerHTML = "";
  sessions.forEach(s => {
    const div = document.createElement("div");
    div.className = `session-item${s.id === currentSessionId ? " active" : ""}`;
    div.onclick = () => openSession(s.id);
    div.innerHTML = `<div class="session-topic">${esc(s.topic || "新研究")}</div>
      <div class="session-meta"><span class="session-status ${s.status}"></span>${s.created_at || ""}</div>`;
    el.appendChild(div);
  });
}

function showWelcome() {
  document.getElementById("welcome-page").style.display = "flex";
  document.getElementById("chat-page").style.display = "none";
  currentSessionId = null; closeSSE();
}
function showChat() {
  document.getElementById("welcome-page").style.display = "none";
  document.getElementById("chat-page").style.display = "flex";
}
function toggleSidebar() { document.getElementById("sidebar").classList.toggle("collapsed"); }
function newChat() { showWelcome(); loadSessions(); }


// ── 开始研究 ─────────────────────────────────────────────────

async function startFromWelcome() {
  const ta = document.getElementById("welcome-topic");
  const topic = ta.value.trim();
  if (!topic) return;
  ta.value = "";
  try {
    const d = await api("POST", "/api/start", { topic });
    currentSessionId = d.session_id;
    showChat();
    document.getElementById("chat-title").textContent = topic.slice(0, 40);
    document.getElementById("messages").innerHTML = "";
    // 渲染初始消息
    appendMsg({ role: "user", agent: "用户", stage: "", content: `研究课题：${topic}` });
    appendMsg({ role: "system", agent: "Mock", stage: "", content: "已收到课题，正在呼叫 @文献调研研究员 ..." });
    setInputState("running", "@文献调研研究员 正在工作中...");
    connectSSE(currentSessionId);
    loadSessions();
  } catch (e) { alert("启动失败: " + e.message); }
}

// ── 打开已有会话 ─────────────────────────────────────────────

async function openSession(sid) {
  closeSSE();
  currentSessionId = sid;
  showChat();
  document.getElementById("messages").innerHTML = "";
  try {
    const d = await api("GET", `/api/status?session_id=${sid}`);
    document.getElementById("chat-title").textContent = (d.topic || "研究").slice(0, 40);
    d.messages.forEach(m => appendMsg(m));
    updatePills(d.current_stage, d.status);
    updateTeam(d.current_stage, d.status);
    if (d.status === "running") {
      setInputState("running");
      connectSSE(sid);
    } else if (d.status === "waiting") {
      setInputState("waiting");
    } else {
      setInputState("done");
    }
  } catch (e) { alert("加载失败: " + e.message); }
  loadSessions();
}

// ── 继续 ─────────────────────────────────────────────────────

async function doContinue() {
  const input = document.getElementById("chat-input");
  const fb = input.value.trim();
  input.value = "";
  if (fb) appendMsg({ role: "user", agent: "用户", stage: "", content: fb });
  try {
    await api("POST", "/api/continue", { session_id: currentSessionId, feedback: fb });
    setInputState("running");
    connectSSE(currentSessionId);
  } catch (e) { alert("操作失败: " + e.message); }
}

async function sendFeedback() {
  const input = document.getElementById("chat-input");
  const fb = input.value.trim();
  if (!fb) return;
  input.value = "";
  appendMsg({ role: "user", agent: "用户", stage: "", content: fb });
  try {
    await api("POST", "/api/continue", { session_id: currentSessionId, feedback: fb });
    setInputState("running");
    connectSSE(currentSessionId);
  } catch (e) { alert("操作失败: " + e.message); }
}

function doStop() {
  closeSSE();
  setInputState("done");
  appendMsg({ role: "system", agent: "Mock", stage: "", content: "⏹ 流程已终止。" });
}

// ── SSE 流式连接 ─────────────────────────────────────────────

function connectSSE(sid) {
  closeSSE();
  streamingMsgEl = null;
  streamingText = "";

  const url = `/api/stream?session_id=${sid}`;
  eventSource = new EventSource(url);

  // 需要带 token，EventSource 不支持自定义 header，改用 fetch
  eventSource.close();
  eventSource = null;

  // 用 fetch + ReadableStream 代替 EventSource（支持 Authorization header）
  fetchSSE(sid);
}

async function fetchSSE(sid) {
  try {
    const resp = await fetch(`/api/stream?session_id=${sid}`, {
      headers: { "Authorization": `Bearer ${token}` },
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // 解析 SSE 事件
      const lines = buffer.split("\n");
      buffer = lines.pop(); // 保留不完整的行

      let currentEvent = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          const rawData = line.slice(6);
          handleSSEEvent(currentEvent, rawData);
          currentEvent = "";
        }
      }
    }
  } catch (e) {
    console.error("SSE error:", e);
  }
}

function handleSSEEvent(event, rawData) {
  console.log("[SSE]", event, rawData.slice(0, 80));

  if (event === "token") {
    // 流式 token — 追加到当前消息
    const text = rawData.replace(/\\n/g, "\n");
    if (!streamingMsgEl) {
      // 创建新的 agent 消息气泡
      streamingMsgEl = createStreamingMsg();
      streamingText = "";
    }
    streamingText += text;
    // 实时渲染 Markdown
    const contentEl = streamingMsgEl.querySelector(".msg-content");
    contentEl.innerHTML = marked.parse(streamingText);
    // 高亮代码块
    contentEl.querySelectorAll("pre code").forEach(block => {
      _hljs && _hljs.highlightElement(block);
    });
    scrollToBottom();

  } else if (event === "stage_start") {
    const data = JSON.parse(rawData.replace(/\\n/g, "\n"));
    // 结束上一个流式消息
    finalizeStreamingMsg();
    // 更新 UI
    updatePills(data.stage, "running");
    updateTeam(data.stage, "running");
    document.getElementById("running-label").textContent = `${data.agent} 正在工作中...`;

  } else if (event === "info") {
    const data = JSON.parse(rawData.replace(/\\n/g, "\n"));
    appendMsg({ role: "system", agent: "Mock", stage: "", content: data.message });

  } else if (event === "stage_done") {
    const data = JSON.parse(rawData.replace(/\\n/g, "\n"));
    console.log("[SSE] stage_done received!", data);
    finalizeStreamingMsg();
    updatePills(data.stage, "waiting");
    updateTeam(data.stage, "waiting");
    setInputState("waiting");
    loadSessions();

  } else if (event === "done") {
    console.log("[SSE] done received!");
    finalizeStreamingMsg();
    appendMsg({ role: "system", agent: "Mock", stage: "", content: "🎉 科研流程全部完成！" });
    setInputState("done");
    loadSessions();

  } else if (event === "error") {
    const data = JSON.parse(rawData.replace(/\\n/g, "\n"));
    console.log("[SSE] error received!", data);
    finalizeStreamingMsg();
    appendMsg({ role: "system", agent: "Mock", stage: "", content: `⚠️ 错误: ${data.message}` });
    setInputState("waiting");

  } else if (event === "end") {
    console.log("[SSE] end received - stream closed");
    // 保底：SSE 结束后检查后端状态，确保 UI 同步
    setTimeout(async () => {
      if (!currentSessionId) return;
      try {
        const d = await api("GET", `/api/status?session_id=${currentSessionId}`);
        if (d.status === "waiting") {
          finalizeStreamingMsg();
          updatePills(d.current_stage, "waiting");
          updateTeam(d.current_stage, "waiting");
          setInputState("waiting");
        } else if (d.status === "done") {
          finalizeStreamingMsg();
          setInputState("done");
        }
        loadSessions();
      } catch {}
    }, 500);
  }
}

function createStreamingMsg() {
  const container = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = "message agent";
  div.innerHTML = `<div class="msg-inner">
    <div class="msg-avatar">🤖</div>
    <div class="msg-body">
      <div class="msg-header"><span class="msg-name">研究员</span></div>
      <div class="msg-content"></div>
    </div>
  </div>`;
  container.appendChild(div);
  return div;
}

function finalizeStreamingMsg() {
  if (streamingMsgEl && streamingText) {
    const contentEl = streamingMsgEl.querySelector(".msg-content");
    contentEl.innerHTML = marked.parse(streamingText);
    contentEl.querySelectorAll("pre code").forEach(block => _hljs && _hljs.highlightElement(block));
  }
  streamingMsgEl = null;
  streamingText = "";
}

function closeSSE() {
  if (eventSource) { eventSource.close(); eventSource = null; }
}


// ── 消息渲染 ─────────────────────────────────────────────────

function appendMsg(msg) {
  const container = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = `message ${msg.role}`;

  const avatarMap = { user: "👤", system: "⚙️" };
  const avatar = avatarMap[msg.role] || AGENT_AVATARS[msg.stage] || "🤖";
  const stageLabel = msg.stage ? (AGENT_LABELS[msg.stage] || msg.stage) : "";

  const renderedContent = msg.role === "system"
    ? esc(msg.content)
    : marked.parse(msg.content || "");

  div.innerHTML = `<div class="msg-inner">
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-body">
      <div class="msg-header">
        <span class="msg-name">${esc(msg.agent)}</span>
        ${stageLabel ? `<span class="msg-tag">${stageLabel}</span>` : ""}
      </div>
      <div class="msg-content">${renderedContent}</div>
    </div>
  </div>`;

  // 高亮代码
  div.querySelectorAll("pre code").forEach(block => _hljs && _hljs.highlightElement(block));

  container.appendChild(div);
  scrollToBottom();
}

function scrollToBottom() {
  const el = document.getElementById("messages");
  el.scrollTop = el.scrollHeight;
}

// ── UI 状态 ──────────────────────────────────────────────────

function setInputState(state, label) {
  const actionBar = document.getElementById("action-bar");
  const runningBar = document.getElementById("running-bar");
  const chatInput = document.getElementById("chat-input");
  const btnSend = document.getElementById("btn-send");

  if (state === "running") {
    actionBar.style.display = "none";
    runningBar.style.display = "flex";
    chatInput.disabled = true; btnSend.disabled = true;
    if (label) document.getElementById("running-label").textContent = label;
  } else if (state === "waiting") {
    actionBar.style.display = "flex";
    runningBar.style.display = "none";
    chatInput.disabled = false; btnSend.disabled = false;
    chatInput.placeholder = "可补充论文、修改意见等，或直接点击确认继续...";
    chatInput.focus();
  } else {
    actionBar.style.display = "none";
    runningBar.style.display = "none";
    chatInput.disabled = true; btnSend.disabled = true;
  }
}

function updatePills(currentStage, status) {
  const idx = STAGE_ORDER.indexOf(currentStage);
  document.querySelectorAll(".pill").forEach(p => {
    const si = STAGE_ORDER.indexOf(p.dataset.stage);
    p.classList.remove("active", "done");
    if (si < idx) p.classList.add("done");
    else if (si === idx) p.classList.add(status === "done" ? "done" : "active");
  });
}

function updateTeam(currentStage, status) {
  const idx = STAGE_ORDER.indexOf(currentStage);
  document.querySelectorAll(".team-member").forEach(el => {
    const si = STAGE_ORDER.indexOf(el.dataset.stage);
    el.classList.remove("active", "done");
    if (si < idx) el.classList.add("done");
    else if (si === idx) el.classList.add(status === "done" ? "done" : "active");
  });
}

function esc(t) {
  const d = document.createElement("div");
  d.textContent = t;
  return d.innerHTML;
}

// ── 键盘 ─────────────────────────────────────────────────────

document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.shiftKey) return;
  if (document.activeElement === document.getElementById("welcome-topic")) {
    e.preventDefault(); startFromWelcome();
  } else if (document.activeElement === document.getElementById("chat-input") &&
             !document.getElementById("chat-input").disabled) {
    e.preventDefault(); sendFeedback();
  }
});

document.addEventListener("input", (e) => {
  if (e.target.tagName === "TEXTAREA") {
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
  }
});


// ── 记忆面板 ─────────────────────────────────────────────────

let memoryPanelOpen = false;

async function toggleMemoryPanel() {
  const panel = document.getElementById("memory-panel");
  memoryPanelOpen = !memoryPanelOpen;
  panel.style.display = memoryPanelOpen ? "flex" : "none";
  if (memoryPanelOpen) await loadMemory();
}

async function loadMemory() {
  const el = document.getElementById("memory-content");
  el.innerHTML = '<p style="color:var(--text-muted)">加载中...</p>';
  try {
    const data = await api("GET", "/api/memory");
    renderMemory(data.profile, data.archives);
  } catch (e) {
    el.innerHTML = `<p style="color:var(--red)">加载失败: ${esc(e.message)}</p>`;
  }
}

function renderMemory(profile, archives) {
  const el = document.getElementById("memory-content");
  let html = "";

  // 用户画像
  const profileLabels = {
    research_field: "🔬 研究领域",
    expertise_level: "🎓 专业水平",
    preferred_methods: "⚙️ 偏好方法",
    programming_skills: "💻 编程技能",
    research_interests: "🎯 研究兴趣",
    writing_style: "✍️ 写作偏好",
  };

  html += '<div class="memory-section"><h4>用户画像</h4>';
  const keys = Object.keys(profile);
  if (keys.length === 0) {
    html += '<div class="memory-empty">暂无画像数据<br>完成一次完整研究后自动生成</div>';
  } else {
    keys.forEach(k => {
      const label = profileLabels[k] || k;
      html += `<div class="memory-item">
        <div class="mem-text">
          <div class="mem-label">${esc(label)}</div>
          <div class="mem-value">${esc(profile[k])}</div>
        </div>
        <button class="btn-del" onclick="deleteProfileKey('${esc(k)}')" title="删除">🗑</button>
      </div>`;
    });
  }
  html += '</div>';

  // 研究档案
  html += '<div class="memory-section"><h4>研究档案</h4>';
  if (archives.length === 0) {
    html += '<div class="memory-empty">暂无研究档案<br>完成一次完整研究后自动归档</div>';
  } else {
    archives.forEach(a => {
      html += `<div class="memory-item">
        <div class="mem-text">
          <div class="mem-label">📄 ${esc(a.topic)}</div>
          ${a.summary ? `<div class="mem-value">${esc(a.summary)}</div>` : ""}
          ${a.key_findings ? `<div class="mem-meta">发现: ${esc(a.key_findings)}</div>` : ""}
          ${a.methods_used ? `<div class="mem-meta">方法: ${esc(a.methods_used)}</div>` : ""}
          <div class="mem-meta">${a.created_at || ""}</div>
        </div>
        <button class="btn-del" onclick="deleteArchive(${a.id})" title="删除">🗑</button>
      </div>`;
    });
  }
  html += '</div>';

  el.innerHTML = html;
}

async function deleteProfileKey(key) {
  if (!confirm("确定删除这条画像记录？")) return;
  try {
    await api("DELETE", `/api/memory/profile/${key}`);
    await loadMemory();
  } catch (e) { alert("删除失败: " + e.message); }
}

async function deleteArchive(id) {
  if (!confirm("确定删除这条研究档案？")) return;
  try {
    await api("DELETE", `/api/memory/archive/${id}`);
    await loadMemory();
  } catch (e) { alert("删除失败: " + e.message); }
}
