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
# 创建虚拟环境
uv venv .venv

# 安装依赖（清华镜像）
uv pip install -r research_agent/requirements.txt \
  --python .venv/Scripts/python.exe \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
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

### 3. 启动 Web 服务

```bash
.venv/Scripts/python.exe -m uvicorn server:app --reload --port 8000
```

浏览器打开 `http://localhost:8000`，注册账号后即可使用。

### 4. 公网穿透（可选）

```bash
# 首次运行自动下载 ngrok
.venv/Scripts/python.exe tunnel.py

# 带 token（去 https://dashboard.ngrok.com/signup 免费注册）
.venv/Scripts/python.exe tunnel.py --token YOUR_NGROK_TOKEN
```

### 5. CLI 模式（可选）

```bash
.venv/Scripts/python.exe run.py
.venv/Scripts/python.exe run.py --resume  # 恢复上次会话
```

## 项目结构

```
├── server.py                    # FastAPI Web 服务（SSE 流式 + 认证）
├── run.py                       # CLI 交互入口
├── tunnel.py                    # 公网穿透启动脚本
├── frontend/
│   ├── index.html               # 前端页面
│   ├── app.js                   # 前端逻辑（SSE + Markdown 渲染）
│   └── style.css                # 样式（暗色主题）
├── research_agent/
│   ├── main.py                  # LangGraph 工作流定义
│   ├── state.py                 # 共享状态（TypedDict）
│   ├── auth.py                  # 用户认证（JWT + bcrypt）
│   ├── memory.py                # 长期记忆（用户画像 + 研究档案）
│   ├── streaming.py             # SSE 流式队列管理
│   ├── llm_utils.py             # LLM 调用工具（流式 + 记忆注入）
│   ├── logger.py                # 日志配置
│   ├── agents/
│   │   ├── literature.py        # @文献调研研究员（arXiv 搜索）
│   │   ├── hypothesis.py        # @假设生成研究员
│   │   ├── experiment.py        # @实验设计研究员 + @代码实现研究员
│   │   ├── analysis.py          # @数据分析研究员
│   │   └── paper.py             # @论文撰写研究员
│   └── tools/
│       └── scholar.py           # arXiv 论文搜索工具
├── test_graph.py                # Graph 结构测试
├── test_api.py                  # API 集成测试
└── research_agent/
    ├── requirements.txt         # Python 依赖
    └── .env.example             # 环境变量模板
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
| 前端 | 原生 JS + marked.js + highlight.js |
| 穿透 | ngrok (pyngrok) |
