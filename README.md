# 🔬 科研智能体 (Research Agent)

基于 LangChain + LangGraph + Kimi K2.5 的多阶段科研工作流智能体，支持 Web 前端对话、流式输出、代码沙箱执行、长期记忆。

## 功能特性

- 🤖 **6 位 AI 研究员**：文献调研、假设生成、实验设计、代码实现、数据分析、论文撰写
- 💻 **代码沙箱**：自动生成、验证、执行、修复代码（Agent Loop），实时终端输出
- 📚 **真实论文搜索**：arXiv 多策略搜索（最新 + 相关性），基于真实文献生成综述
- 🏟️ **多 Agent 讨论**：文献专家、方法专家、实验专家、批判者围绕课题讨论创新点
- 🔄 **Human-in-the-loop**：每个阶段完成后暂停，用户可确认、补充信息或终止
- 📡 **SSE 流式输出**：LLM 逐 token 实时推送到前端，打字机效果
- 🧠 **长期记忆**：自动提取用户画像和研究档案，跨会话记忆
- ⚙️ **可配置**：前端设置面板配置 Python 环境、工作目录、大模型参数
- 💾 **持久化存储**：SQLite 保存 checkpoint、会话、用户数据、记忆
- 👤 **用户系统**：注册/登录，JWT 认证，多用户隔离

## 环境要求

- **Python** >= 3.10（推荐 3.11+）
- **Node.js** >= 18
- **操作系统**：Windows / macOS / Linux

## 快速开始

### 1. 克隆项目

```bash
git clone <repo-url>
cd ScienceResearchAgent
```

### 2. 创建 Python 虚拟环境

```bash
# 使用 uv（推荐）
uv venv .venv

# 或使用标准 venv
python -m venv .venv
```

### 3. 激活虚拟环境

```bash
# Windows (CMD)
.venv\Scripts\activate.bat

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

### 4. 安装 Python 依赖

```bash
pip install -r research_agent/requirements.txt
```

完整依赖列表：

```
langchain>=0.2.0
langgraph>=0.2.0
langchain-moonshot>=0.1.0
langgraph-checkpoint-sqlite>=1.0.0
python-dotenv>=1.0.0
fastapi>=0.100.0
uvicorn>=0.20.0
python-jose[cryptography]>=3.3.0
passlib>=1.7.0
bcrypt>=4.0.0
```

如果需要使用代码研究员运行 PyTorch 等科学计算代码，还需安装：

```bash
pip install torch torchvision numpy pandas matplotlib scikit-learn
```

### 5. 安装前端依赖并构建

```bash
cd "Futuristic AI Chat Interface"
npm install
npm run build
cd ..
```

### 6. 配置环境变量

创建 `.env` 文件（项目根目录）：

```env
MOONSHOT_API_KEY=sk-your-key-here
MOONSHOT_API_BASE=https://api.moonshot.cn/v1
```

API Key 在 [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys) 获取。

也支持其他 OpenAI 兼容接口（DeepSeek、OpenAI 等），启动后在前端 **设置** 面板中修改。

### 7. 一键启动

```bash
# Windows - 双击 start.bat
start.bat

# 或手动启动
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

浏览器打开 `http://localhost:8000`，注册账号后即可使用。

## 使用模式

| 模式 | 说明 |
|------|------|
| 📋 Workflow | 固定流程：文献→假设→实验→分析→论文，每步确认 |
| 💬 Chat | 自由对话：@项目负责人 按需调用研究员（含代码研究员） |
| 🏟️ 讨论室 | 多 Agent 讨论：围绕课题讨论创新点 |

### 代码研究员

在 Chat 模式中，当你请求编写或运行代码时，项目负责人会自动调用 **@代码实现研究员**：

1. 🤔 分析需求
2. ✍️ 生成代码
3. 🔍 语法检查（AST 解析）
4. ▶️ 在沙箱中执行（实时终端输出）
5. 🔧 如果失败，自动分析错误并修复（最多 3 次）
6. ✅ 返回结果

沙箱支持：
- `pip_install()` 安装依赖
- `shell_exec()` 执行 shell 命令
- `fs_read()` / `fs_write()` 文件读写
- 指定工作目录访问本地数据

## 前端设置

点击侧边栏 **⚙️ 设置** 按钮，可配置：

- **Python 解释器路径**：指定 venv/conda 环境
- **工作目录**：代码执行的工作目录（可访问本地数据）
- **模型名称**：如 `kimi-k2.5`、`gpt-4o`、`deepseek-chat`
- **API Base URL**：模型服务地址
- **API Key**：模型 API 密钥

## 项目结构

```
├── start.bat                        # 🚀 Windows 一键启动
├── start.ps1                        # 🚀 PowerShell 启动脚本
├── server.py                        # FastAPI Web 服务
├── .env                             # 环境变量（API Key）
├── settings.json                    # 用户设置（自动生成）
├── Futuristic AI Chat Interface/    # React 前端
│   ├── src/app/
│   │   ├── components/
│   │   │   ├── ChatWindow.tsx       # 聊天窗口
│   │   │   ├── AgentSteps.tsx       # Agent 步骤面板（终端输出）
│   │   │   ├── CodeBlock.tsx        # 代码块（可运行）
│   │   │   ├── SettingsPanel.tsx    # 设置面板
│   │   │   ├── Sidebar.tsx          # 侧边栏
│   │   │   └── MemoryPanel.tsx      # 长期记忆面板
│   │   ├── contexts/
│   │   │   ├── ChatContext.tsx      # 聊天/SSE 状态管理
│   │   │   └── AuthContext.tsx      # 认证状态
│   │   └── lib/
│   │       ├── api.ts              # API 工具
│   │       └── markdown.ts         # Markdown 渲染
│   └── dist/                        # 构建产物
├── research_agent/
│   ├── main.py                      # LangGraph 工作流
│   ├── code_agent.py                # 代码研究员 Agent Loop
│   ├── sandbox.py                   # 代码沙箱（安全执行）
│   ├── chat_mode.py                 # Chat 模式（Lead Agent）
│   ├── debate.py                    # 讨论模式
│   ├── memory.py                    # 长期记忆
│   ├── streaming.py                 # SSE 流式管理
│   ├── auth.py                      # 用户认证
│   ├── llm_utils.py                 # LLM 调用工具
│   ├── agents/                      # 6 位 AI 研究员
│   └── tools/
│       └── scholar.py               # arXiv 搜索
└── desktop/                         # Electron 桌面客户端（可选）
```

## 技术栈

| 组件 | 技术 |
|------|------|
| LLM | Kimi K2.5 / OpenAI 兼容接口 |
| 工作流 | LangGraph (StateGraph + interrupt) |
| 代码执行 | 子进程沙箱 + 实时输出流 |
| 后端 | FastAPI + uvicorn |
| 认证 | JWT + bcrypt |
| 论文搜索 | arXiv API |
| 流式输出 | SSE (Server-Sent Events) |
| 前端 | React + Vite + Tailwind CSS |
| 持久化 | SQLite |

## 常见问题

**Q: 代码研究员执行时报 `ModuleNotFoundError`？**

在设置中配置正确的 Python 解释器路径，确保该环境已安装所需包。或者代码研究员会自动尝试 `pip_install()` 安装。

**Q: 如何让代码访问本地数据文件？**

在设置中配置"工作目录"为你的数据所在文件夹，代码执行时会以该目录为工作目录。

**Q: 支持哪些大模型？**

支持所有 OpenAI 兼容接口，包括 Moonshot (Kimi)、DeepSeek、OpenAI、Azure OpenAI 等。在设置中修改 model name 和 base URL 即可。
