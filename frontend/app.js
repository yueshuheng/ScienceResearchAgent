// ── 科研智能体前端 ──────────────────────────────────────────

let token = localStorage.getItem("token");
let currentUser = null;
let currentSessionId = null;
let streamingMsgEl = null;
let streamingText = "";

const STAGE_ORDER = [
  "literature_review","hypothesis","experiment_design",
  "experiment","analysis","paper"
];
const AVATARS = {
  literature_review:"📚",hypothesis:"💡",experiment_design:"📋",
  experiment:"🧪",analysis:"📊",paper:"📝"
};
const LABELS = {
  literature_review:"文献调研",hypothesis:"假设生成",experiment_design:"实验设计",
  experiment:"代码实现",analysis:"结果分析",paper:"论文撰写"
};

// ── marked ───────────────────────────────────────────────────
const _hljs = typeof hljs !== "undefined" ? hljs : null;
marked.setOptions({
  highlight(code, lang) {
    if (!_hljs) return code;
    if (lang && _hljs.getLanguage(lang)) return _hljs.highlight(code,{language:lang}).value;
    return _hljs.highlightAuto(code).value;
  },
  breaks: true, gfm: true,
});

// ── Init ─────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  if (token) {
    try {
      const r = await api("GET","/api/auth/me");
      currentUser = r.user; showApp();
    } catch { localStorage.removeItem("token"); token = null; }
  }
});

// ── API ──────────────────────────────────────────────────────
async function api(method, url, body) {
  const o = { method, headers: {"Content-Type":"application/json","ngrok-skip-browser-warning":"true"} };
  if (token) o.headers["Authorization"] = `Bearer ${token}`;
  if (body) o.body = JSON.stringify(body);
  const r = await fetch(url, o);
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || "请求失败");
  return d;
}

// ── Auth ─────────────────────────────────────────────────────
function showLogin() {
  document.getElementById("login-form").style.display="flex";
  document.getElementById("register-form").style.display="none";
}
function showRegister() {
  document.getElementById("login-form").style.display="none";
  document.getElementById("register-form").style.display="flex";
}
async function doLogin() {
  const u=document.getElementById("login-username").value.trim();
  const p=document.getElementById("login-password").value;
  const e=document.getElementById("login-error"); e.textContent="";
  if(!u||!p){e.textContent="请填写用户名和密码";return}
  try{const d=await api("POST","/api/auth/login",{username:u,password:p});
    token=d.token;localStorage.setItem("token",token);currentUser=d.user;showApp();
  }catch(x){e.textContent=x.message}
}
async function doRegister() {
  const u=document.getElementById("reg-username").value.trim();
  const dn=document.getElementById("reg-display").value.trim();
  const p=document.getElementById("reg-password").value;
  const p2=document.getElementById("reg-password2").value;
  const e=document.getElementById("reg-error"); e.textContent="";
  if(!u||!p){e.textContent="请填写用户名和密码";return}
  if(p!==p2){e.textContent="两次密码不一致";return}
  try{const d=await api("POST","/api/auth/register",{username:u,password:p,display_name:dn||u});
    token=d.token;localStorage.setItem("token",token);currentUser=d.user;showApp();
  }catch(x){e.textContent=x.message}
}
function doLogout() {
  token=null;currentUser=null;localStorage.removeItem("token");
  document.getElementById("auth-page").style.display="flex";
  document.getElementById("main-app").style.display="none";
}

// ── App ──────────────────────────────────────────────────────
function showApp() {
  document.getElementById("auth-page").style.display="none";
  document.getElementById("main-app").style.display="flex";
  document.getElementById("user-name").textContent=currentUser.display_name;
  document.getElementById("user-avatar").textContent=currentUser.display_name[0].toUpperCase();
  loadSessions(); showWelcome();
}
async function loadSessions() {
  try{const d=await api("GET","/api/sessions");renderSessionList(d.sessions)}catch{}
}
function renderSessionList(sessions) {
  const el=document.getElementById("session-list"); el.innerHTML="";
  sessions.forEach(s=>{
    const d=document.createElement("div");
    d.className=`session-item${s.id===currentSessionId?" active":""}`;
    d.onclick=()=>openSession(s.id);
    d.innerHTML=`<div class="session-topic">${esc(s.topic||"新研究")}</div>
      <div class="session-meta"><span class="session-status ${s.status}"></span>${s.created_at||""}</div>`;
    el.appendChild(d);
  });
}
function showWelcome(){document.getElementById("welcome-page").style.display="flex";document.getElementById("chat-page").style.display="none";currentSessionId=null}
function showChat(){document.getElementById("welcome-page").style.display="none";document.getElementById("chat-page").style.display="flex"}
function toggleSidebar(){document.getElementById("sidebar").classList.toggle("collapsed")}
function newChat(){showWelcome();loadSessions()}

// ── Mode ─────────────────────────────────────────────────────
let currentMode = "workflow";

function setMode(mode) {
  currentMode = mode;
  const wf = document.getElementById("mode-workflow");
  const ch = document.getElementById("mode-chat");
  if(mode==="workflow"){
    wf.className="mode-btn active";
    ch.className="mode-btn inactive";
  }else{
    ch.className="mode-btn active";
    wf.className="mode-btn inactive";
  }
  document.getElementById("mode-desc").textContent = mode==="workflow"
    ? "固定流程：文献→假设→实验→分析→论文，每步确认"
    : "自由对话：@项目负责人 按需调用研究员，灵活探索";
  document.getElementById("welcome-topic").placeholder = mode==="workflow"
    ? "描述你的研究课题..." : "输入你的问题或研究需求...";
}

// ── Start ────────────────────────────────────────────────────
async function startFromWelcome() {
  const ta=document.getElementById("welcome-topic");
  const topic=ta.value.trim(); if(!topic)return; ta.value="";

  if(currentMode==="chat") {
    await startChatMode(topic);
  } else {
    await startWorkflowMode(topic);
  }
}

async function startWorkflowMode(topic) {
  try{
    const d=await api("POST","/api/start",{topic});
    currentSessionId=d.session_id; currentMode="workflow"; showChat();
    document.getElementById("chat-title").textContent=topic.slice(0,40);
    document.getElementById("messages").innerHTML="";
    appendMsg({role:"user",agent:"用户",stage:"",content:`研究课题：${topic}`});
    appendMsg({role:"system",agent:"Mock",stage:"",content:"已收到课题，正在呼叫 @文献调研研究员 ..."});
    setInputState("running","@文献调研研究员 正在工作中...");
    connectSSE(currentSessionId); loadSessions();
  }catch(e){alert("启动失败: "+e.message)}
}

async function startChatMode(message) {
  try{
    const d=await api("POST","/api/chat",{message, topic:message.slice(0,50)});
    currentSessionId=d.session_id; currentMode="chat"; showChat();
    document.getElementById("chat-title").textContent="💬 "+message.slice(0,35);
    document.getElementById("messages").innerHTML="";
    appendMsg({role:"user",agent:"用户",stage:"",content:message});
    setInputState("running","@项目负责人 正在分析...");
    connectSSE(currentSessionId); loadSessions();
  }catch(e){alert("启动失败: "+e.message)}
}

// ── Open Session ─────────────────────────────────────────────
async function openSession(sid) {
  currentSessionId=sid; showChat();
  // Detect mode from session ID prefix
  currentMode = sid.startsWith("c-") ? "chat" : "workflow";
  document.getElementById("messages").innerHTML="";
  try{
    const d=await api("GET",`/api/status?session_id=${sid}`);
    document.getElementById("chat-title").textContent=(d.topic||"研究").slice(0,40);
    d.messages.forEach(m=>appendMsg(m));
    updatePills(d.current_stage,d.status); updateTeam(d.current_stage,d.status);
    if(d.status==="running"){setInputState("running");connectSSE(sid)}
    else if(d.status==="waiting"){setInputState("waiting")}
    else{setInputState("done")}
  }catch(e){alert("加载失败: "+e.message)}
  loadSessions();
}

// ── Continue ─────────────────────────────────────────────────
async function doContinue() {
  const inp=document.getElementById("chat-input");
  const fb=inp.value.trim(); inp.value="";
  if(fb) appendMsg({role:"user",agent:"用户",stage:"",content:fb});

  if(currentMode==="chat") {
    await sendChatMessage(fb || "继续");
  } else {
    try{await api("POST","/api/continue",{session_id:currentSessionId,feedback:fb});
      setInputState("running"); connectSSE(currentSessionId);
    }catch(e){alert("操作失败: "+e.message)}
  }
}
async function sendFeedback() {
  const inp=document.getElementById("chat-input");
  const fb=inp.value.trim(); if(!fb)return; inp.value="";
  appendMsg({role:"user",agent:"用户",stage:"",content:fb});

  if(currentMode==="chat") {
    await sendChatMessage(fb);
  } else {
    try{await api("POST","/api/continue",{session_id:currentSessionId,feedback:fb});
      setInputState("running"); connectSSE(currentSessionId);
    }catch(e){alert("操作失败: "+e.message)}
  }
}

async function sendChatMessage(message) {
  try{
    await api("POST","/api/chat",{session_id:currentSessionId,message});
    setInputState("running","@项目负责人 正在思考...");
    connectSSE(currentSessionId);
  }catch(e){alert("发送失败: "+e.message)}
}
function doStop() {
  setInputState("done");
  appendMsg({role:"system",agent:"Mock",stage:"",content:"⏹ 流程已终止。"});
}

// ── SSE ──────────────────────────────────────────────────────
let sseAbort = null;

function connectSSE(sid) {
  if(sseAbort) sseAbort.abort();
  sseAbort = new AbortController();
  streamingMsgEl=null; streamingText="";
  fetchSSE(sid, sseAbort.signal);
}

async function fetchSSE(sid, signal) {
  try{
    const resp=await fetch(`/api/stream?session_id=${sid}`,{
      headers:{"Authorization":`Bearer ${token}`,"ngrok-skip-browser-warning":"true"}, signal
    });
    const reader=resp.body.getReader();
    const dec=new TextDecoder();
    let buf="", curEvt="";

    while(true){
      const{done,value}=await reader.read();
      if(done)break;
      buf+=dec.decode(value,{stream:true});
      const lines=buf.split("\n"); buf=lines.pop();
      for(const line of lines){
        if(line.startsWith("event: ")){curEvt=line.slice(7).trim()}
        else if(line.startsWith("data: ")){handleSSE(curEvt,line.slice(6));curEvt=""}
      }
    }
  }catch(e){
    if(e.name!=="AbortError") console.error("SSE error:",e);
  }
  // 保底：SSE 结束后同步状态（只更新 UI 状态，不重复追加消息）
  setTimeout(async()=>{
    if(!currentSessionId)return;
    try{
      const d=await api("GET",`/api/status?session_id=${currentSessionId}`);
      if(d.status==="waiting"){finalizeStream();updatePills(d.current_stage,"waiting");updateTeam(d.current_stage,"waiting");setInputState("waiting")}
      else if(d.status==="done"){finalizeStream();setInputState("done")}
      loadSessions();
    }catch{}
  },300);
}

function handleSSE(evt, raw) {
  if(evt==="token"){
    const t=raw.replace(/\\n/g,"\n");
    if(!streamingMsgEl){streamingMsgEl=createStreamEl();streamingText=""}
    streamingText+=t;
    const el=streamingMsgEl.querySelector(".msg-content");
    el.innerHTML=marked.parse(streamingText);
    addCopyButtons(el); scrollBottom();
  }else if(evt==="stage_start"){
    const d=JSON.parse(raw.replace(/\\n/g,"\n"));
    finalizeStream();
    updatePills(d.stage,"running"); updateTeam(d.stage,"running");
    document.getElementById("running-label").textContent=`${d.agent} 正在工作中...`;
  }else if(evt==="info"){
    const d=JSON.parse(raw.replace(/\\n/g,"\n"));
    appendMsg({role:"system",agent:"Mock",stage:"",content:d.message});
  }else if(evt==="stage_done"){
    const d=JSON.parse(raw.replace(/\\n/g,"\n"));
    finalizeStream();
    updatePills(d.stage,"waiting"); updateTeam(d.stage,"waiting");
    setInputState("waiting"); loadSessions();
  }else if(evt==="done"){
    finalizeStream();
    appendMsg({role:"system",agent:"Mock",stage:"",content:"🎉 科研流程全部完成！"});
    setInputState("done"); loadSessions();
  }else if(evt==="error"){
    const d=JSON.parse(raw.replace(/\\n/g,"\n"));
    finalizeStream();
    appendMsg({role:"system",agent:"Mock",stage:"",content:`⚠️ 错误: ${d.message}`});
    setInputState("waiting");
  }
}

function createStreamEl() {
  const c=document.getElementById("messages");
  const d=document.createElement("div"); d.className="message flex justify-start";
  d.innerHTML=`<div class="msg-inner"><div class="max-w-2xl">
    <div class="flex items-center gap-2 mb-2">
      <div class="p-1.5 rounded-lg bg-gradient-to-br from-purple-500/30 to-blue-500/30 flex items-center justify-center text-sm">✨</div>
      <span class="text-xs text-purple-400 font-semibold">研究员</span>
    </div>
    <div class="msg-bubble-agent"><div class="msg-content"></div></div>
  </div></div>`;
  c.appendChild(d); return d;
}

function finalizeStream() {
  if(streamingMsgEl&&streamingText){
    const el=streamingMsgEl.querySelector(".msg-content");
    el.innerHTML=marked.parse(streamingText);
    addCopyButtons(streamingMsgEl);
  }
  streamingMsgEl=null; streamingText="";
}

// ── Messages ─────────────────────────────────────────────────
function appendMsg(msg) {
  const c=document.getElementById("messages");
  const d=document.createElement("div"); d.className=`message flex ${msg.role==="user"?"justify-end":"justify-start"}`;
  const av={user:"👤",system:"⚙️"}[msg.role]||AVATARS[msg.stage]||"✨";
  const tag=msg.stage?(LABELS[msg.stage]||msg.stage):"";
  const html=msg.role==="system"?`<span class="text-xs text-slate-500">${esc(msg.content)}</span>`:marked.parse(msg.content||"");
  const bubbleClass=msg.role==="user"?"msg-bubble-user":msg.role==="agent"?"msg-bubble-agent":"msg-bubble-system";
  const nameColor=msg.role==="agent"?"text-purple-400":msg.role==="user"?"text-slate-200":"text-slate-500";
  const avatarBg=msg.role==="user"
    ?"bg-gradient-to-br from-purple-500/30 to-blue-600/30 ring-2 ring-purple-400/30"
    :msg.role==="agent"?"bg-gradient-to-br from-purple-500/30 to-blue-500/30":"bg-white/5";

  d.innerHTML=`<div class="msg-inner"><div class="max-w-2xl">
    ${msg.role!=="system"?`<div class="flex items-center gap-2 mb-2">
      <div class="p-1.5 rounded-lg ${avatarBg} flex items-center justify-center text-sm">${av}</div>
      <span class="text-xs ${nameColor} font-semibold">${esc(msg.agent)}</span>
      ${tag?`<span class="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-400 border border-purple-500/20">${tag}</span>`:""}
    </div>`:""}
    <div class="${bubbleClass}"><div class="msg-content">${html}</div></div>
  </div></div>`;
  addCopyButtons(d); c.appendChild(d); scrollBottom();
}

function addCopyButtons(el) {
  el.querySelectorAll("pre").forEach(pre=>{
    if(pre.querySelector(".code-copy"))return;
    const btn=document.createElement("button");
    btn.className="code-copy"; btn.textContent="复制";
    btn.onclick=()=>{
      const code=pre.querySelector("code");
      navigator.clipboard.writeText(code?.textContent||pre.textContent);
      btn.textContent="已复制✓"; setTimeout(()=>btn.textContent="复制",1500);
    };
    pre.style.position="relative"; pre.appendChild(btn);
  });
  if(_hljs) el.querySelectorAll("pre code").forEach(b=>_hljs.highlightElement(b));
}

function scrollBottom(){const el=document.getElementById("messages");el.scrollTop=el.scrollHeight}

// ── UI State ─────────────────────────────────────────────────
function setInputState(state,label) {
  const ab=document.getElementById("action-bar");
  const rb=document.getElementById("running-bar");
  const ci=document.getElementById("chat-input");
  const bs=document.getElementById("btn-send");
  if(state==="running"){
    ab.style.display="none";rb.style.display="flex";ci.disabled=true;bs.disabled=true;
    if(label)document.getElementById("running-label").textContent=label;
  }else if(state==="waiting"){
    rb.style.display="none";ci.disabled=false;bs.disabled=false;
    if(currentMode==="chat"){
      ab.style.display="none";
      ci.placeholder="继续对话，或 @研究员 指定任务...";
    }else{
      ab.style.display="flex";
      ci.placeholder="可补充论文、修改意见等，或直接点击确认继续...";
    }
    ci.focus();
  }else{
    ab.style.display="none";rb.style.display="none";ci.disabled=true;bs.disabled=true;
  }
}

function updatePills(stage,status) {
  const idx=STAGE_ORDER.indexOf(stage);
  document.querySelectorAll(".pill").forEach(p=>{
    const si=STAGE_ORDER.indexOf(p.dataset.stage);
    p.classList.remove("active","done");
    if(si<idx)p.classList.add("done");
    else if(si===idx)p.classList.add(status==="done"?"done":"active");
  });
}
function updateTeam(stage,status) {
  const idx=STAGE_ORDER.indexOf(stage);
  document.querySelectorAll(".team-member").forEach(el=>{
    const si=STAGE_ORDER.indexOf(el.dataset.stage);
    el.classList.remove("active","done");
    if(si<idx)el.classList.add("done");
    else if(si===idx)el.classList.add(status==="done"?"done":"active");
  });
}

function esc(t){const d=document.createElement("div");d.textContent=t;return d.innerHTML}

// ── Keyboard ─────────────────────────────────────────────────
document.addEventListener("keydown",e=>{
  if(e.key!=="Enter"||e.shiftKey)return;
  if(document.activeElement===document.getElementById("welcome-topic")){e.preventDefault();startFromWelcome()}
  else if(document.activeElement===document.getElementById("chat-input")&&!document.getElementById("chat-input").disabled){e.preventDefault();sendFeedback()}
});
document.addEventListener("input",e=>{
  if(e.target.tagName==="TEXTAREA"){e.target.style.height="auto";e.target.style.height=Math.min(e.target.scrollHeight,120)+"px"}
});

// ── Memory Panel ─────────────────────────────────────────────
let memOpen=false;
async function toggleMemoryPanel(){
  const p=document.getElementById("memory-panel"); memOpen=!memOpen;
  p.style.display=memOpen?"flex":"none"; if(memOpen)await loadMemory();
}
async function loadMemory(){
  const el=document.getElementById("memory-content");
  el.innerHTML='<p style="color:var(--text-3)">加载中...</p>';
  try{const d=await api("GET","/api/memory");renderMemory(d.profile,d.archives)}
  catch(e){el.innerHTML=`<p style="color:var(--red)">加载失败</p>`}
}
function renderMemory(profile,archives){
  const el=document.getElementById("memory-content");
  const pl={research_field:"🔬 研究领域",expertise_level:"🎓 专业水平",preferred_methods:"⚙️ 偏好方法",programming_skills:"💻 编程技能",research_interests:"🎯 研究兴趣",writing_style:"✍️ 写作偏好"};
  let h='<div class="memory-section"><h4>用户画像</h4>';
  const ks=Object.keys(profile);
  if(!ks.length)h+='<div class="memory-empty">暂无画像数据</div>';
  else ks.forEach(k=>{h+=`<div class="memory-item"><div class="mem-text"><div class="mem-label">${esc(pl[k]||k)}</div><div class="mem-value">${esc(profile[k])}</div></div><button class="btn-del" onclick="delProfile('${esc(k)}')">🗑</button></div>`});
  h+='</div><div class="memory-section"><h4>研究档案</h4>';
  if(!archives.length)h+='<div class="memory-empty">暂无研究档案</div>';
  else archives.forEach(a=>{h+=`<div class="memory-item"><div class="mem-text"><div class="mem-label">📄 ${esc(a.topic)}</div>${a.summary?`<div class="mem-value">${esc(a.summary)}</div>`:""}${a.key_findings?`<div class="mem-meta">发现: ${esc(a.key_findings)}</div>`:""}${a.methods_used?`<div class="mem-meta">方法: ${esc(a.methods_used)}</div>`:""}<div class="mem-meta">${a.created_at||""}</div></div><button class="btn-del" onclick="delArchive(${a.id})">🗑</button></div>`});
  h+='</div>'; el.innerHTML=h;
}
async function delProfile(k){if(!confirm("确定删除？"))return;try{await api("DELETE",`/api/memory/profile/${k}`);await loadMemory()}catch(e){alert(e.message)}}
async function delArchive(id){if(!confirm("确定删除？"))return;try{await api("DELETE",`/api/memory/archive/${id}`);await loadMemory()}catch(e){alert(e.message)}}
