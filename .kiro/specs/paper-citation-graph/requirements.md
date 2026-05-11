# Requirements Document

## Introduction

本功能为科研智能体添加"论文引用关系图"能力。当文献调研研究员搜索论文时，系统支持下载论文 PDF 并存储到本地，解析论文之间的引用关系，构建引用图数据结构，并在前端右侧面板以力导向图的形式展示论文关系网络。用户可以直观地看到论文之间的引用与被引用关系，辅助理解研究脉络。

## Glossary

- **Citation_Graph_Service**: 后端服务模块，负责论文下载、引用关系解析、图数据存储与查询
- **Paper_Store**: 论文存储模块，负责 PDF 文件的下载与本地持久化
- **Reference_Parser**: 引用解析器，从论文 PDF 或元数据中提取引用关系
- **Graph_Panel**: 前端右侧面板组件，展示论文引用关系的力导向图
- **Citation_Graph**: 由论文节点和引用边组成的有向图数据结构
- **Paper_Node**: 图中的节点，代表一篇论文，包含标题、作者、年份等元数据
- **Citation_Edge**: 图中的有向边，表示一篇论文引用了另一篇论文

## Requirements

### Requirement 1: 论文 PDF 下载与存储

**User Story:** As a 科研人员, I want to 在搜索论文时下载并存储论文 PDF, so that 我可以离线阅读并用于后续引用分析。

#### Acceptance Criteria

1. WHEN a user triggers paper download for a search result, THE Paper_Store SHALL download the PDF file from the arXiv source URL and save it to the local storage directory.
2. WHEN the PDF download completes successfully, THE Paper_Store SHALL record the paper metadata (title, authors, year, arXiv ID, local file path) in the SQLite database.
3. IF the PDF download fails due to network error or unavailable source, THEN THE Paper_Store SHALL return a descriptive error message indicating the failure reason.
4. WHEN a paper has already been downloaded, THE Paper_Store SHALL skip the download and return the existing local file path.
5. THE Paper_Store SHALL organize downloaded PDFs in a structured directory using the arXiv ID as the filename.

### Requirement 2: 论文引用关系解析

**User Story:** As a 科研人员, I want to 自动解析论文之间的引用关系, so that 我可以了解论文之间的学术脉络。

#### Acceptance Criteria

1. WHEN a paper PDF is downloaded, THE Reference_Parser SHALL extract the reference list from the PDF content.
2. WHEN references are extracted, THE Reference_Parser SHALL attempt to match each reference to known papers in the local database by title similarity.
3. WHEN a reference match is found, THE Citation_Graph_Service SHALL create a Citation_Edge from the citing paper to the cited paper in the database.
4. IF the PDF content is unreadable or the reference section is not parseable, THEN THE Reference_Parser SHALL log a warning and return an empty reference list.
5. THE Reference_Parser SHALL extract at minimum the title and authors from each reference entry.

### Requirement 3: 引用图数据管理

**User Story:** As a 科研人员, I want to 查询论文引用关系图数据, so that 前端可以渲染引用网络。

#### Acceptance Criteria

1. WHEN a client requests the citation graph for a session, THE Citation_Graph_Service SHALL return all Paper_Nodes and Citation_Edges associated with that session.
2. THE Citation_Graph_Service SHALL represent the graph as a JSON object containing a nodes array and an edges array.
3. WHEN a new paper is added to the graph, THE Citation_Graph_Service SHALL update the graph data and notify connected clients.
4. THE Citation_Graph_Service SHALL support querying the graph filtered by session ID, allowing each research session to maintain its own citation graph.
5. WHEN a paper node is requested, THE Citation_Graph_Service SHALL return the paper metadata including title, authors, year, abstract snippet, and download status.

### Requirement 4: 前端右侧引用图面板

**User Story:** As a 科研人员, I want to 在界面右侧看到论文引用关系的可视化图, so that 我可以直观理解论文之间的关联。

#### Acceptance Criteria

1. THE Graph_Panel SHALL render as a collapsible panel on the right side of the chat window.
2. WHEN the citation graph contains nodes, THE Graph_Panel SHALL render a force-directed graph visualization with Paper_Nodes as circles and Citation_Edges as directed arrows.
3. WHEN a user hovers over a Paper_Node, THE Graph_Panel SHALL display a tooltip showing the paper title, authors, and year.
4. WHEN a user clicks a Paper_Node, THE Graph_Panel SHALL highlight all directly connected edges and nodes.
5. THE Graph_Panel SHALL provide a toggle button to expand or collapse the panel without losing graph state.
6. WHILE the panel is collapsed, THE Graph_Panel SHALL display a small icon badge showing the number of papers in the current graph.

### Requirement 5: 论文下载触发与集成

**User Story:** As a 科研人员, I want to 在文献调研阶段方便地触发论文下载, so that 引用图可以随着研究进展自动构建。

#### Acceptance Criteria

1. WHEN the literature review agent returns search results, THE Citation_Graph_Service SHALL provide a download action for each paper in the results.
2. WHEN a user selects papers for download, THE Citation_Graph_Service SHALL queue the download tasks and process them asynchronously.
3. WHILE papers are being downloaded and parsed, THE Graph_Panel SHALL display a loading indicator for papers in progress.
4. WHEN all queued downloads complete, THE Citation_Graph_Service SHALL trigger a graph refresh event to update the Graph_Panel.
5. THE Citation_Graph_Service SHALL support batch download of multiple papers from a single search result set.
