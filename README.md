# ScholarPilot

> 全领域科研情报检索平台 — 多源并行检索、AI 评分摘要、双层 Markdown 记忆驱动画像学习。

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Tag](https://img.shields.io/badge/tag-main0-green.svg)](https://github.com/sstar16/scholarpilot/releases/tag/main0)

ScholarPilot 帮助科研人员从海量学术文献和专利中快速定位最相关的研究情报。用户在对话里自然描述研究方向，系统通过 AI Agent 驱动的多轮检索从 14+ 数据源并行抓取，LLM 逐篇评分 + 中文摘要，用户反馈驱动双层 Markdown 记忆学习，可转入协作研究或每日自动监控。

> **本仓库 `main0` 为公开版冻结分支**（2026-05-08）。这是 ScholarPilot 工程化、产品化阶段的开源快照，用于学习和参考。

---

## 形态

| 形态 | 路径 | 用途 |
|---|---|---|
| **Web Frontend**（已冻结） | `frontend/` | Vue 3 + Element Plus，浏览器 SPA |
| **Desktop Client**（活跃） | `client/` | Tauri 2 + Vue 3，BYOK 全托管，本地 SQLite + 文件沙盒 |
| **Backend**（CN 节点） | `backend/` | FastAPI + Celery + PostgreSQL，提供 web SPA 的全栈 API |
| **sp-api**（HK 节点） | `sp-api/` | 客户端专用轻量网关，仅负责 fetcher 调度 + 付费源预算守门，**无 LLM 依赖** |

> **架构演进**：从单一 web 应用 →「Web + 桌面 + 双 backend」三件套。Web 用平台 LLM key（自管成本），桌面客户端 100% BYOK（成本归用户）。详见 [`docs/architecture/`](./docs/architecture/)。

---

## 核心能力

### 检索（已完成）

- **对话主体化**：所有流程（建项目 / 检索 / 协作 / 推送）都在对话气泡里完成，自然语言驱动
- **Agent-First 关键词规划**：QueryPlanAgent 自动规划策略，per-source 关键词优化（每源独立适配 API 语法）
- **两阶段用户确认**：AI 生成关键词方案 → 用户编辑确认 → 执行检索
- **LLM 逐篇评分**：ScoringAgent 每篇 0-10 分 + 一句话总结，斩杀线过滤
- **AI 中文摘要**：对过线文献生成中文摘要、关键要点、与项目的关联理由
- **4 桶分类**：非常相关 / 相关 / 不确定 / 不相关，跨轮次持久化
- **三层关键词降级**：复杂 boolean → 中等 AND → 简单兜底，每源 API 不同适配
- **14+ 数据源**：学术（OpenAlex / arXiv / EuropePMC / Crossref / DBLP / PubMed / ClinicalTrials / OpenAlex_zh）+ 专利（EPO OPS / Lens.org / PatentHub）

### 协作研究（已完成）

- 勾选已有文献进入协作模式，基于文献库做深度问答
- ResearchAgent 边读边查边引用，section-level probe 精读探针
- 协作上下文持久化到对话状态机

### 双层 Markdown 记忆（已完成）

- 学 [Claude Code](https://claude.com/claude-code) 的 MEMORY.md 设计
- **用户级**：身份/职业/研究大方向，跨项目共享
- **项目级**：本项目研究方向/子问题，仅当前项目生效
- AI 可读可写，用户可见可编辑，防跨项目污染

### 知识图谱（已完成）

- LLM 抽实体/关系，cytoscape.js 力导向布局（fcose）
- 节点类型：document / author / concept / topic / journal
- 社区检测、hubs / gaps 分析

### 本地知识库（已完成）

- DuckDB + SQLite FTS5，支持千万级文献离线检索
- 静态 / API / 混合三种检索模式

### 桌面客户端（M1 / M2 / M3 完成）

- Tauri 2 原生窗口（Windows / macOS / Linux）
- OS Keychain 存 OAuth2 双 token，绝不入 localStorage
- 本地 SQLite（11 表对齐 backend）+ 文件系统沙盒
- BYOK：用户自带 LLM key 写 OS Keychain，所有评分 / 摘要 / 协作研究本地完成
- Rust 端原生 PDF 抓取（reqwest + cookie store），绕过部分学术站点反爬

### 定时推送（开发中）

- 后台进程基于 MEMORY 定时爬最新进展
- 桌面通知 / Email / Telegram 推送（计划）

---

## Harness Engineering

受 Claude Code 12 层 harness 启发，系统内置可扩展 AI 基础设施：

| 组件 | 说明 |
|---|---|
| Tool Registry | 14+ fetcher 统一注册为工具，带运行时统计 + 可靠性报告 |
| Hook Engine | 11 个生命周期钩子（ROUND_START / POST_SEARCH / PRE_FEEDBACK 等） |
| Skill System | 8 个可复用工作流：Deep Dive / Trend Spotter / Gap Finder / Quality Audit / Outline Synth 等 |
| Agent Pipeline | IntentAgent → QueryPlanAgent → ScoringAgent → MemoryAgent → CollaborationAgent → GraphAgent 全链路 |
| Memory | 双层 Markdown（user + project）+ bucket-driven structured memory |

---

## 技术栈

| 层级 | 技术 |
|---|---|
| 桌面客户端 | Tauri 2 + Vue 3 + Element Plus + cytoscape.js + p-queue + zod |
| Web 前端（冻结） | Vue 3 + TypeScript + Element Plus + Vite + vis-network |
| 客户端 Rust 后端 | reqwest + reqwest_cookie_store + sqlx + tauri-plugin-sql v2 |
| 服务端 | FastAPI + SQLAlchemy (async) + Alembic + Pydantic v2 |
| 任务队列 | Celery + Redis |
| 数据库 | PostgreSQL 16（主库）+ DuckDB + SQLite FTS5（本地知识库） |
| AI / LLM | Anthropic Claude SDK / OpenAI SDK / DeepSeek / Moonshot / Ollama / OpenAI-compatible 中转 |
| 文档解析 | markitdown（PDF / DOCX → Markdown） |
| 部署 | Docker Compose + Cloudflare Tunnel + nginx |

---

## 快速开始

### 1. Web + Backend（自部署完整版）

```bash
git clone https://github.com/sstar16/scholarpilot
cd scholarpilot
cp .env.example .env
# 编辑 .env，至少填 POSTGRES_PASSWORD、SECRET_KEY、DISABLED_SOURCES
docker compose up -d
```

打开 `http://localhost`，注册账号（首次跑需手动建邀请码或在 backend 改邀请码逻辑），右上角设置配置 LLM。

### 2. Desktop Client（推荐，BYOK 自洽）

```bash
cd client
npm install
npm run tauri:dev   # 启 Tauri 开发窗口（首次 cargo 5-10 分钟）
# 或者打包：
npm run tauri:build  # 产物在 src-tauri/target/release/bundle/{msi,dmg,deb,appimage}/
```

客户端默认连 sp-api 网关；本地 dev 改 `client/.env` 的 `VITE_API_BASE_URL` 指向自己的 backend。

### 3. sp-api（HK 客户端网关，可选）

```bash
cd sp-api
docker compose -f docker-compose.sp-api.yml up -d
# 客户端 client/.env 改 VITE_API_BASE_URL 指向这个 sp-api
```

---

## 目录结构

```
scholarpilot/
├── backend/                    # FastAPI + Celery + Postgres（CN 节点）
│   ├── app/
│   │   ├── api/                # FastAPI 路由
│   │   ├── models/             # SQLAlchemy ORM
│   │   ├── schemas/            # Pydantic schemas
│   │   ├── services/
│   │   │   ├── fetchers/       # 14+ 数据源 Fetcher
│   │   │   ├── core/           # LLM 管理器 + Redis 持久化
│   │   │   └── ...
│   │   ├── harness/            # AI Agent 基础设施（10 agent）
│   │   ├── knowledge_base/     # DuckDB + SQLite FTS5
│   │   ├── prompts/            # per-source + per-agent prompt
│   │   └── workers/            # Celery 任务
│   └── alembic/versions/       # 数据库迁移
├── frontend/                   # Vue 3 web SPA（冻结）
├── client/                     # Tauri 2 桌面客户端（活跃）
│   ├── src/                    # Vue 3 源码（pipeline 11 phase 移植自 backend workers）
│   ├── src-tauri/              # Rust 后端（commands / fs sandbox / pdf fetcher）
│   ├── e2e/                    # Playwright 用例
│   └── README.md
├── sp-api/                     # HK 客户端网关（fetcher only，无 LLM）
├── nginx/                      # nginx 配置（反代 frontend / backend）
├── docs/
│   └── architecture/           # 5 张 Mermaid 架构图 + viewer
├── scripts/                    # 通用脚本（备份、邀请码生成等）
├── docker-compose.yml
├── docker-compose.sp-api.yml
├── .env.example
├── CLAUDE.md                   # 给 AI 编码 agent 看的项目指南
└── LICENSE
```

---

## 开发工作流

```bash
# 后端
docker compose restart backend worker beat flower
docker compose logs -f backend
docker compose exec backend alembic upgrade head

# Web 前端
docker compose build frontend && docker compose up -d frontend && docker compose restart nginx

# 桌面客户端
cd client && npm test                  # vitest
cd client && npx vue-tsc --noEmit      # 类型检查
cd client && npx playwright test       # e2e
cd client/src-tauri && cargo check     # Rust 类型检查
```

---

## 参考与致谢

ScholarPilot 在设计与实现过程中对标、借鉴和直接依赖了多个优秀开源项目，特此鸣谢。

### 同类项目对标

- **[LearningCircuit/local-deep-research](https://github.com/LearningCircuit/local-deep-research)** — 本地优先深度研究助手。我们参考了它的反幻觉 prompt 约束（`Never make up sources`）、报告生成防重复机制、citation handler 三档策略、News Subscriptions 模式、MCP server 暴露思路。

### 直接依赖（核心技术栈）

桌面客户端：

- [Tauri 2](https://tauri.app/) — Rust 原生窗口框架
- [Vue 3](https://vuejs.org/) + [Element Plus](https://element-plus.org/) — UI 框架
- [Vite](https://vitejs.dev/) — 构建工具
- [cytoscape.js](https://js.cytoscape.org/) + [cytoscape-fcose](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose) — 知识图谱可视化（500+ 节点流畅渲染）
- [p-queue](https://github.com/sindresorhus/p-queue) — LLM 并发队列（priority + intervalCap + pause/resume）
- [zod](https://zod.dev/) — TS-first schema 校验
- [@tauri-apps/plugin-sql v2](https://v2.tauri.app/plugin/sql/) — sqlx-backed SQLite migration
- [reqwest](https://github.com/seanmonstar/reqwest) + [reqwest_cookie_store](https://github.com/pfernie/reqwest_cookie_store) — Rust HTTP（学术 PDF 抓取）

服务端：

- [FastAPI](https://fastapi.tiangolo.com/) — async Python web 框架
- [SQLAlchemy](https://www.sqlalchemy.org/) + [Alembic](https://alembic.sqlalchemy.org/) — ORM + 迁移
- [Celery](https://docs.celeryq.dev/) + [Redis](https://redis.io/) — 异步任务队列
- [PostgreSQL 16](https://www.postgresql.org/) — 主库
- [DuckDB](https://duckdb.org/) + SQLite FTS5 — 本地知识库
- [Pydantic v2](https://docs.pydantic.dev/) — 校验与序列化
- [markitdown](https://github.com/microsoft/markitdown) — PDF/DOCX → Markdown

LLM 提供商：

- [Anthropic Claude SDK](https://github.com/anthropics/anthropic-sdk-python)
- [OpenAI SDK](https://github.com/openai/openai-python)
- [DeepSeek](https://platform.deepseek.com/)
- [Moonshot Kimi](https://www.moonshot.cn/)
- [Ollama](https://ollama.ai/) — 本地 LLM
- 任意 OpenAI-compatible 中转

数据源 API（向他们的开放数据致敬）：

- [OpenAlex](https://openalex.org/) — 2.5 亿+ 学术文献
- [arXiv](https://arxiv.org/) — CS / 物理预印本
- [EuropePMC](https://europepmc.org/) — PubMed 全量
- [Crossref](https://www.crossref.org/) — 引用数据
- [DBLP](https://dblp.org/) — CS 顶会论文
- [PubMed](https://pubmed.ncbi.nlm.nih.gov/) — 生物医学
- [ClinicalTrials.gov](https://clinicaltrials.gov/) — 临床试验
- [EPO OPS](https://www.epo.org/searching-for-patents/data/web-services/ops.html) — 欧洲专利
- [Lens.org](https://www.lens.org/) — 全球专利学术聚合
- [PatentHub 专利汇](https://www.patenthub.cn/) — 中国专利

部署与基础设施：

- [Docker / Docker Compose](https://www.docker.com/)
- [Cloudflare Tunnel (cloudflared)](https://www.cloudflare.com/products/tunnel/) — 零暴露 HTTPS
- [nginx](https://nginx.org/)

### 设计与方法论灵感

- **[Claude Code](https://claude.com/claude-code)** — MEMORY.md 索引 + 多 .md 详情的可解释记忆机制启发了我们的双层 Markdown 记忆设计；也启发了 Harness Engineering（Hook / Tool Registry / Skill）的多层 harness 模式。
- **[Anthropic Engineering 公开博客](https://www.anthropic.com/engineering)** — Agent 设计模式、prompt caching、tool use 协议参考。

### 技术决策与对比研究

我们在选型阶段做了详尽的横评：

- 知识图谱可视化：cytoscape.js（≈ 6.6M 周下载） vs vue-flow（200K） vs vis-network（269K，已替代）
- LLM 并发：p-queue vs p-limit（p-queue 胜在 priority + intervalCap）
- TS schema：zod vs typia vs ajv（zod 胜在 DX）
- Rust PDF：reqwest + cookie store + 可选 rquest（boring-tls）fallback
- SQLite migration：tauri-plugin-sql v2 forward-only（接受 Down 不可用约束）

---

## 路线图

主要功能均已完成或进行中：

- ✅ 检索流程（11 phase 状态机，客户端化）
- ✅ DevTools 日志可视化平台
- ✅ 本地知识库（DuckDB + SQLite FTS5）
- ✅ 对话主体化 / 协作研究 / 双层 Markdown 记忆
- ✅ 知识图谱（cytoscape）
- ✅ 桌面客户端（M1 / M2 / M3 BYOK 100%）
- 🚧 sp-api 重构（CN/HK 双 backend，BYOK 接管业务/LLM）
- 🚧 定时推送（基于 MEMORY 的后台监控）
- ⬜ MCP server（暴露 fetcher + agent 给 Claude Desktop / Cursor）
- ⬜ 多用户 / 团队共享项目
- ⬜ 客户端 SQLCipher 加密（企业客群）

---

## 贡献

欢迎 PR、Issue、对标讨论。提交前建议跑 `npx vue-tsc --noEmit`（client）/ `pytest`（backend）确保不破坏。Commit 格式：`feat:` / `fix:` / `refactor:` / `docs:` / `chore:`。

---

## License

[MIT](./LICENSE) © 2026 sstar16
