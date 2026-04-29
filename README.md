# 🔬 科研智能体 (Research Agent)

基于 LangChain + LangGraph + Kimi K2.5 的多阶段科研工作流智能体，支持 Web 前端对话、流式输出、长期记忆。

## 功能特性

- 🤖 **6 位 AI 研究员**：文献调研、假设生成、实验设计、代码实现、数据分析、论文撰写
- 📚 **真实论文搜索**：arXiv 多策略搜索（最新 + 相关性），基于真实文献生成综述
- 🔄 **Human-in-the-loop**：每个阶段完成后暂停，用户可确认、补充信息或终止
- 📡 **SSE 流式输出**：LLM 逐 token 实时推送到前端，打字机效果
- 🧠 **长期记忆**：自动提取用户画像和研究档案，跨会话记忆
- 💾 **持久化存储**：SQLite 保存 checkpoint、会话、用户数据、记忆
- 👤 **用户系统**：注册/登录，JWT 认证，多用户隔离
- 🌐 **公网穿透**：一键 ngrok 穿透，分享链接即可访问
- 🎨 **React 前端**：基于 Vite + Tailwind + shadcn/ui 的现代化暗色界面

## 研究流程

```
用户输入课题
    ↓
📚 @文献调研研究员 → arXiv 搜索 + LLM 综述
    ↓ 用户确认（可补充论文）
💡 @假设生成研究员 → 提出可验证的科学假设
    ↓ 用户确认
📋 @实验设计研究员 → 数据集/模型/评估指标方案（thinking 模式）
    ↓ 用户确认
🧪 @代码实现研究员 → 生成实验代码 + 自动语法检查（thinking 模式）
    ↓ 用户确认
📊 @数据分析研究员 → 结果分析与讨论
    ↓ 用户确认
📝 @论文撰写研究员 → 完整论文初稿
    ↓
🧠 自动提取长期记忆
```

## 快速开始

### 1. 安装依赖

```bash
# Python 依赖
uv venv .venv
uv pip install -r research_agent/requirements.txt \
  --python .venv/Scripts/python.exe \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 前端依赖（需要 Node.js >= 18）
cd "Futuristic AI Chat Interface"
npm install
cd ..
```

### 2. 配置 API Key

```bash
cp research_agent/.env.example .env
```

编辑 `.env`，填入 Moonshot API Key（在 [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys) 获取）：

```env
MOONSHOT_API_KEY=sk-your-key-here
MOONSHOT_API_BASE=https://api.moonshot.cn/v1
```

### 3. 一键启动

```bash
# 本地启动（自动构建前端）
python start.py

# 公网穿透版（分享链接给他人访问）
python start.py --tunnel
python start.py --tunnel --token YOUR_NGROK_TOKEN

# 自定义端口
python start.py --port 9000

# 开发模式（后端热重载，前端需另开终端 npm run dev）
python start.py --dev
```

浏览器打开 `http://localhost:8000`，注册账号后即可使用。

### 4. 前端开发

```bash
# 终端 1：启动后端
python start.py --dev

# 终端 2：启动前端 dev server（热更新）
cd "Futuristic AI Chat Interface"
npm run dev
# 访问 http://localhost:5173，API 自动代理到后端
```

### 5. 桌面客户端（可选）

```bash
# 安装 Electron 依赖（首次）
cd desktop
npm install

# 启动桌面客户端（会自动启动后端）
npm start
# 或双击 desktop/start.bat
```

### 6. CLI 模式（可选）

```bash
python run.py                # 新建研究会话
python run.py --resume       # 恢复上次会话
```

## 项目结构

```
├── start.py                         # 🚀 一键启动脚本（本地 / 穿透）
├── server.py                        # FastAPI Web 服务（SSE 流式 + 认证）
├── run.py                           # CLI 交互入口
├── tunnel.py                        # 旧版穿透脚本（已被 start.py 替代）
├── desktop/                         # Electron 桌面客户端
│   ├── main.js                      # Electron 主进程（自动启动后端）
│   ├── preload.js                   # 预加载脚本
│   ├── start.bat                    # Windows 一键启动
│   └── package.json
├── Futuristic AI Chat Interface/    # React 前端（Vite + Tailwind + shadcn/ui）
│   ├── src/
│   │   ├── app/
│   │   │   ├── App.tsx              # 主应用（认证 + 路由）
│   │   │   ├── components/
│   │   │   │   ├── AuthPage.tsx     # 登录/注册页
│   │   │   │   ├── WelcomePage.tsx  # 欢迎页（模式选择 + 课题输入）
│   │   │   │   ├── ChatWindow.tsx   # 聊天窗口（SSE 流式 + Markdown）
│   │   │   │   ├── Sidebar.tsx      # 侧边栏（会话列表 + 团队 + 记忆）
│   │   │   │   ├── MemoryPanel.tsx  # 长期记忆面板
│   │   │   │   └── ui/             # shadcn/ui 基础组件
│   │   │   ├── contexts/
│   │   │   │   ├── AuthContext.tsx   # 认证状态管理
│   │   │   │   └── ChatContext.tsx   # 聊天/会话/SSE 状态管理
│   │   │   └── lib/
│   │   │       ├── api.ts           # API 请求工具
│   │   │       ├── constants.ts     # 阶段/头像/标签常量
│   │   │       └── markdown.ts      # Markdown 渲染
│   │   └── styles/                  # Tailwind + 主题 CSS
│   ├── dist/                        # 构建产物（由 server.py 托管）
│   ├── vite.config.ts               # Vite 配置（含 API 代理）
│   └── package.json
├── frontend/                        # 旧版原生 HTML/JS 前端（备份）
├── research_agent/
│   ├── main.py                      # LangGraph 工作流定义
│   ├── state.py                     # 共享状态（TypedDict）
│   ├── auth.py                      # 用户认证（JWT + bcrypt）
│   ├── memory.py                    # 长期记忆（用户画像 + 研究档案）
│   ├── streaming.py                 # SSE 流式队列管理
│   ├── chat_mode.py                 # Chat 自由对话模式
│   ├── llm_utils.py                 # LLM 调用工具（流式 + 记忆注入）
│   ├── logger.py                    # 日志配置
│   ├── agents/                      # 6 位 AI 研究员
│   └── tools/
│       └── scholar.py               # arXiv 论文搜索工具
└── research_agent/
    ├── requirements.txt             # Python 依赖
    └── .env.example                 # 环境变量模板
```

## 技术栈

| 组件 | 技术 |
|------|------|
| LLM | Kimi K2.5 (langchain-moonshot) |
| 工作流 | LangGraph (StateGraph + interrupt) |
| 持久化 | SQLite (langgraph-checkpoint-sqlite) |
| 后端 | FastAPI + uvicorn |
| 认证 | JWT (python-jose) + bcrypt |
| 论文搜索 | arXiv API |
| 流式输出 | SSE (Server-Sent Events) |
| 前端 | React + Vite + Tailwind CSS + shadcn/ui |
| 穿透 | ngrok (pyngrok) |
