# CLAUDE.md

> 给 AI Coding agent 看的项目指南。本仓库 `main0` 为公开版冻结分支，活跃开发在 fork/branch 上继续。

## 项目简介

ScholarPilot：全领域科研情报检索平台。多国学术/专利数据源并行检索 → AI 处理 → 用户反馈驱动画像学习 → 每日监控。

**目的**：帮助科研人员快速获取相关领域最新研究进展，节省文献搜集和初步筛选的时间，并基于收集的数据进行 AI 辅助研究。

> **架构详解** 见 `docs/architecture/`。

## 当前焦点（main0 冻结）

**Web frontend/* 已冻结，桌面客户端为主**：所有 UX 优化、新功能落地都在 `client/`（Tauri 2 桌面）；`frontend/*` 仅 bug fix；`backend/` 维持，client 通过 API 接入；`sp-api/` 是 client-only 的轻量 fetcher 网关（无 LLM 依赖，BYOK 全部走客户端）。

**MEMORY.md 设计**：受 Claude Code 启发的索引 + 多 .md 详情结构，存于客户端文件系统 `<AppData>/scholarpilot/projects/<id>/memory/`，不放 backend DB。

## 核心框架

应用基本单元是项目，每个项目维护一个研究方向。每个项目有自己的 MEMORY.md 索引（AI 可读写），还有用户级 MEMORY.md 跨项目共享。

### 3 大核心功能
1. **检索**（接近完成）
2. **共同研究模式**（基于已有文献库做协作分析）
3. **定时推送**（每天自动检索 + 更新文献库；尚未完成）

### 用户进入对话后的 3 场景分支

| 场景 | 判定条件 | 可选入口 |
|---|---|---|
| 1 · 项目刚创建 | `project.current_round == 0` | 走检索流程建立画像 |
| 2 · 有项目，文献库空 | `current_round > 0` 且 文献库为空 | 新一轮检索 / 定时推送 |
| 3 · 有项目，文献库非空 | `current_round > 0` 且 文献库非空 | 新一轮检索 / 定时推送 / **协作研究** |

3 个模块都是对话中的事件（工具调用）：可显式调用，也可通过自然语言触发（hook）。触发后进入对应流程，流程内用户只能跟着流程走，除非强制中断。

### 对话状态机原则

通常默认态。触发功能后进入对应流程，流程内用户只能跟着流程走，除非强制中断或结束（AI 认为功能结束自动返回默认态，无需手动结束）。默认态做引导气泡，每个气泡是 AI 推断的能触发功能的自然语言。

## 常用命令

> 生产用 Docker Compose v2（`docker compose` 空格），dev 本地 v1 也支持。

```bash
cp .env.example .env                    # 首次：填写密码和密钥
docker compose up -d                    # 启动全部服务
docker compose restart backend worker   # 改后端 Python（有 volume 挂载）
docker compose build frontend && docker compose up -d frontend && docker compose restart nginx  # 改前端
docker compose build backend worker beat flower && docker compose up -d  # 改 requirements.txt/Dockerfile
docker compose logs -f backend          # FastAPI 日志
docker compose logs -f worker           # Celery 日志
```

端口：`localhost`（前端）、`localhost:8000/docs`（Swagger）、`localhost:5555`（Flower）

### 客户端开发（Tauri 2 + Vue3）

> 完整架构见 [docs/architecture/06-desktop-client.md](docs/architecture/06-desktop-client.md)。

```bash
cd client && npm install                # 首次（~80MB）
cd client && npm run tauri:dev          # 启 Tauri 窗口（首次 cargo 5-10 分钟）
cd client && npm run tauri:build        # 打包 .msi/.exe/.dmg/.deb
cd client && npm test                   # vitest
cd client && npx vue-tsc --noEmit       # 类型检查
```

**摘要**：
- 认证：OAuth2 双 token（access 短 / refresh 30d），存 OS keychain；401 拦截器自动 refresh 一次
- 客户端识别：所有请求带 `X-Client-Type: desktop` + `X-Client-Version`；backend `ClientMetaMiddleware` 解析
- 本地数据：`<AppData>/scholarpilot/scholarpilot.db`（SQLite，11 表对齐 backend 模型）+ 文件系统沙盒；UI 本地优先
- BYOK：客户端注入 `X-User-LLM-*` header → backend `ClientLLMOverrideMiddleware` → ContextVar → `LLMProviderManager` 替换 active_provider；handler 一行不改；Web 零影响。**main0 起 BYOK 100%：sp-api 无 LLM 依赖**

## 架构

```
nginx:80 → /api/* → FastAPI backend:8000 | /* → Vue3 frontend
```

### 检索流程（Two-Phase）

```
POST /rounds/prepare → QueryPlanAgent → per-source 关键词优化 → Redis 暂存
  ↓ 用户确认/编辑关键词
POST /rounds/{id}/confirm-keywords → Celery execute_round
  → asyncio.gather 并行检索所有源
  → ScoringAgent 逐篇 LLM 评分 → 斩杀线过滤
  → chord(摘要生成 × N)(finalize)
  → round.status = "awaiting_feedback"
  ↓ 用户分类到 4 桶 → Memory Agent 更新记忆 → 下轮更准
```

### 数据源

14 个注册源（含可禁用）：OpenAlex / OpenAlex_zh / EuropePMC / Crossref / DBLP / arXiv / EPO OPS / Lens.org / PatentHub / PubMed / ClinicalTrials / 等。通过 `.env` `DISABLED_SOURCES` 控制。

**付费源**（如 PatentHub）走 `services/patenthub_budget.py` 预算守门，单轮 5 篇软上限，超额前端二次确认可 `force=true` 越权。自动路径**跳过付费 PDF 源**，只响应用户手动点击。

### LLM 提供商

**统一入口**：`await get_llm_manager()`（`services/core/llm_config_store.py`）
- 进程级单例 + 60s Redis TTL 缓存
- 支持：Ollama / OpenAI / Anthropic / DeepSeek / Moonshot / OpenAI-compatible 中转
- 客户端 BYOK：用户用自己的 Key，平台不背 LLM 成本

## 关键约定

### 后端
- **async 规则**：Celery 任务内用 `_run_async(coro)`，每次新 event loop
- **错误分层**：Fetcher → `return []`；API → `HTTPException`；Celery → 更新 status="failed" 再 raise
- **ORM 注意**：长时间操作后不要 `db.refresh(obj)`，用 `select()` 重新查询
- **DB 迁移**：`0001_initial.py` 不可改，新增字段建新 version 文件
- **Agent 位置**：所有 specialized agent 在 `app/harness/agents/`
- **Phase 跳过**：声明 `phase.skip_if(ctx) -> bool`（声明式比 raise PhaseSkipped 优雅）

### 前端
- API 调用统一走 `api/client.ts` 具名导出（authApi / projectApi / searchApi 等）
- Element Plus 国际化必须 `import zhCn` + `app.use(ElementPlus, { locale: zhCn })`
- el-table 内 el-select 用字符串 value，不能用数字

### Git
- Commit 格式：`feat:` / `fix:` / `refactor:` / `docs:` / `chore:`
- Trunk-based：`main` 是唯一活跃分支

## HTTPS / 安全

生产推荐 **Cloudflare Tunnel**（cloudflared 容器主动 outbound 到 CF Edge → 容器内 `nginx:80`），源站不对外暴露任何端口。Tunnel Token 通过 `.env` 的 `CLOUDFLARE_TUNNEL_TOKEN` 注入，严禁入库。反代感知：uvicorn `--proxy-headers --forwarded-allow-ips='*'`。

## 里程碑

- 检索流程：完成
- DevTools 日志可视化：完成
- 本地知识库（DuckDB + SQLite FTS5）：完成
- 对话主体化（Chat-Centric）：完成
- 桌面客户端（M1 壳 / M2 本地数据层 / M3 BYOK）：完成
- sp-api 重构（HK gateway，BYOK 100%）：进行中

记住：写/更新操作前先读；能自动测试的就自动测试（前端可用 Playwright）；多派 subagent 并行调查。
