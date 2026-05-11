# Implementation Plan: Paper Citation Graph

## Overview

为科研智能体添加论文引用关系图功能。实现分为后端（Python/FastAPI）和前端（React/TypeScript）两部分：后端负责论文 PDF 下载、引用解析、图数据管理；前端负责右侧可折叠面板中的力导向图可视化。实现按模块递进，从数据层到业务逻辑层再到 API 层和前端展示层。

## Tasks

- [x] 1. 后端数据层：数据模型与数据库表
  - [x] 1.1 创建 `research_agent/citation/__init__.py` 和数据模型定义
    - 创建 `research_agent/citation/` 目录
    - 在 `research_agent/citation/models.py` 中定义 `PaperRecord`、`ReferenceEntry`、`MatchedReference`、`CitationGraph` 数据类
    - _Requirements: 1.2, 3.2, 3.5_
  - [x] 1.2 创建数据库初始化模块 `research_agent/citation/db.py`
    - 实现 `init_citation_db()` 函数，创建 `papers`、`citation_edges`、`session_papers`、`download_tasks` 四张表
    - 使用 WAL 模式配置 SQLite
    - _Requirements: 1.2, 2.3, 3.1, 3.4_

- [x] 2. 后端核心模块：PaperStore
  - [x] 2.1 实现 `research_agent/citation/paper_store.py`
    - 实现 `PaperStore` 类，包含 `download_paper`、`get_paper`、`get_papers_by_session`、`link_paper_to_session` 方法
    - `download_paper` 从 arXiv 下载 PDF，保存到 `{pdf_dir}/{arxiv_id}.pdf`，已存在则跳过
    - 记录元数据到 `papers` 表，管理 `download_status` 状态流转
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - [ ]* 2.2 编写 PaperStore 属性测试
    - **Property 1: Paper metadata round-trip**
    - **Validates: Requirements 1.2, 3.5**
  - [ ]* 2.3 编写 PaperStore 属性测试
    - **Property 2: Download idempotence**
    - **Validates: Requirements 1.4**
  - [ ]* 2.4 编写 PaperStore 属性测试
    - **Property 3: File path determinism**
    - **Validates: Requirements 1.5**

- [x] 3. 后端核心模块：ReferenceParser
  - [x] 3.1 实现 `research_agent/citation/reference_parser.py`
    - 使用 PyMuPDF (fitz) 从 PDF 提取文本
    - 实现引用列表解析逻辑，提取标题和作者
    - 使用 `difflib.SequenceMatcher` 实现标题模糊匹配
    - 实现 `parse_references` 和 `match_references` 方法
    - _Requirements: 2.1, 2.2, 2.4, 2.5_
  - [ ]* 3.2 编写 ReferenceParser 属性测试
    - **Property 4: Title similarity matching**
    - **Validates: Requirements 2.2**
  - [ ]* 3.3 编写 ReferenceParser 属性测试
    - **Property 6: Parsed reference structure invariant**
    - **Validates: Requirements 2.5**

- [x] 4. Checkpoint - 确保后端核心模块测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. 后端业务逻辑层：CitationGraphService
  - [x] 5.1 实现 `research_agent/citation/graph_service.py`
    - 实现 `CitationGraphService` 类，组合 `PaperStore` 和 `ReferenceParser`
    - 实现 `download_papers` 异步批量下载（生成 task_id，后台处理）
    - 实现 `get_graph` 按 session_id 查询图数据
    - 实现 `get_download_status` 查询下载任务状态
    - 下载完成后自动触发引用解析和边创建
    - _Requirements: 2.3, 3.1, 3.3, 3.4, 5.1, 5.2, 5.4, 5.5_
  - [ ]* 5.2 编写 CitationGraphService 属性测试
    - **Property 5: Edge creation for matched references**
    - **Validates: Requirements 2.3**
  - [ ]* 5.3 编写 CitationGraphService 属性测试
    - **Property 7: Session-scoped graph completeness and isolation**
    - **Validates: Requirements 3.1, 3.4**
  - [ ]* 5.4 编写 CitationGraphService 属性测试
    - **Property 9: Batch download completeness**
    - **Validates: Requirements 5.2, 5.5**

- [x] 6. 后端 API 层：REST 端点与 SSE 事件
  - [x] 6.1 在 `server.py` 中添加引用图 REST API 端点
    - `POST /api/citation/download` — 批量下载论文（返回 202 + task_id）
    - `GET /api/citation/graph` — 获取会话引用图（nodes + edges）
    - `GET /api/citation/status/{task_id}` — 查询下载任务状态
    - `GET /api/citation/paper/{arxiv_id}` — 获取单篇论文详情
    - 在 `lifespan` 中初始化 `init_citation_db()` 和 `CitationGraphService` 实例
    - _Requirements: 3.1, 3.2, 3.5, 5.1, 5.2_
  - [x] 6.2 扩展 SSE 事件推送支持引用图事件
    - 在下载完成时推送 `graph_update` 事件
    - 在下载进度变化时推送 `download_progress` 事件
    - 在批量下载完成时推送 `download_complete` 事件
    - _Requirements: 3.3, 5.3, 5.4_

- [x] 7. Checkpoint - 确保后端 API 端点可用
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. 前端类型定义与 Context
  - [x] 8.1 创建 TypeScript 类型定义文件
    - 在 `Futuristic AI Chat Interface/src/app/types/citation.ts` 中定义 `PaperNode`、`CitationEdge`、`CitationGraph`、`PaperDownloadRequest`、`DownloadTaskStatus` 接口
    - _Requirements: 3.2_
  - [x] 8.2 创建 `CitationContext.tsx` 状态管理
    - 在 `Futuristic AI Chat Interface/src/app/contexts/CitationContext.tsx` 中实现
    - 管理 graph（nodes/edges）、loading、collapsed、downloadingPapers 状态
    - 实现 `downloadPapers`、`refreshGraph`、`togglePanel`、`selectNode` 方法
    - 监听 SSE `graph_update` 事件自动刷新图数据
    - _Requirements: 3.3, 4.1, 4.5, 5.3_

- [x] 9. 前端组件：ForceGraph 力导向图
  - [x] 9.1 实现 `ForceGraph.tsx` 组件
    - 在 `Futuristic AI Chat Interface/src/app/components/ForceGraph.tsx` 中实现
    - 使用 d3-force 创建力导向图模拟
    - 渲染 Paper_Nodes 为圆形节点，Citation_Edges 为有向箭头
    - 实现节点拖拽交互
    - 实现节点 hover 显示 tooltip（标题、作者、年份）
    - 实现节点点击高亮直接连接的边和节点
    - _Requirements: 4.2, 4.3, 4.4_
  - [ ]* 9.2 编写 ForceGraph 属性测试
    - **Property 8: Connected node set correctness**
    - **Validates: Requirements 4.4**

- [x] 10. 前端组件：GraphPanel 面板
  - [x] 10.1 实现 `GraphPanel.tsx` 组件
    - 在 `Futuristic AI Chat Interface/src/app/components/GraphPanel.tsx` 中实现
    - 右侧可折叠面板布局，包含 ForceGraph
    - 实现展开/折叠切换按钮
    - 折叠时显示论文数量 badge
    - 空图时显示引导提示
    - 加载失败时显示重试按钮
    - _Requirements: 4.1, 4.5, 4.6_

- [x] 11. 前端集成：将 GraphPanel 接入主界面
  - [x] 11.1 集成 CitationContext 和 GraphPanel 到应用
    - 在 `App.tsx` 中添加 `CitationProvider`
    - 在 `ChatWindow.tsx` 旁边渲染 `GraphPanel`
    - 确保面板展开/折叠不影响聊天窗口布局
    - _Requirements: 4.1, 4.5_
  - [x] 11.2 在搜索结果中添加论文下载触发
    - 在聊天消息中识别文献搜索结果，添加下载按钮
    - 点击下载按钮调用 `CitationContext.downloadPapers`
    - 下载中显示 loading 指示器
    - _Requirements: 5.1, 5.2, 5.3_

- [x] 12. Final checkpoint - 确保所有测试通过，功能完整
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- 后端使用 Python (pytest + hypothesis)，前端使用 TypeScript (vitest + fast-check)
- 依赖安装：后端需添加 `PyMuPDF` 到 requirements.txt，前端需添加 `d3-force` 和 `@types/d3-force`
