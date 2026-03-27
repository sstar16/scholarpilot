# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

ScholarPilot（内部名 URIP）：面向科研人员的全领域情报检索平台。用户描述研究方向后，系统通过 **5轮渐进式检索**（时间范围从近5年逐步扩展到全时间）从多个学术数据源并行抓取文献，AI生成中文摘要，用户反馈驱动画像学习，第5轮结束后自动转入每日监控模式。

## 启动与常用命令

```bash
# 首次启动前：复制环境变量文件
cp .env.example .env   # 然后填写 POSTGRES_PASSWORD 和 SECRET_KEY

# 启动所有服务（PostgreSQL + Redis + backend + worker + beat + flower + frontend + nginx）
docker-compose up -d

# 只在改了 requirements.txt 或 Dockerfile 时才需要重新构建
docker-compose build backend
docker-compose up -d

# 查看日志
docker-compose logs -f backend    # FastAPI 应用日志
docker-compose logs -f worker     # Celery worker 任务日志

# 手动触发数据库迁移（通常由 backend 容器启动时自动执行）
docker-compose exec backend alembic upgrade head

# 新建迁移文件（修改了 models/ 后）
docker-compose exec backend alembic revision --autogenerate -m "描述"
```

服务端口：`http://localhost`（前端）、`http://localhost:8000/docs`（Swagger）、`http://localhost:5555`（Flower 任务监控）

## 架构概览

### 请求生命周期

```
用户浏览器
  └─ nginx:80
      ├─ /api/* → FastAPI backend:8000   （HTTP + WebSocket）
      └─ /*     → Vue3 frontend:80
```

### 核心数据流：渐进式检索

```
POST /api/projects/{id}/rounds/start
  → create_next_round()          [progressive_search.py] 写入 search_rounds 表
  → execute_round.delay()        [Celery task]
      → build_query()            [query_builder.py] 构建 QueryPlan（关键词+年份+来源）
      → execute_search()         [search_engine.py] asyncio.gather 并行调用所有 fetcher
      → save_round_documents()   写入 documents + round_documents 表
      → chord(generate_summary_for_doc × N)(finalize_round_after_summaries)
                                 [search_tasks.py] 并行生成摘要，全部完成后回调
  → round.status = "awaiting_feedback"

POST /api/projects/{id}/rounds/{rid}/feedback
  → update_profile_from_feedbacks()  [profile_service.py] 更新用户画像关键词偏好
  → mark_round_complete()
  → 若 round < 5: create_next_round() + execute_round.delay()
  → 若 round = 5: activate_monitoring() → 写入 monitor_jobs 表

Celery Beat 每天早6点:
  → run_daily_monitors() → run_single_monitor() 检索近7天 → score → save → MonitorResult
```

### 数据源扩展点

所有数据源继承 `AbstractFetcher`（`fetchers/base.py`），实现 `fetch()` 方法后加入 `international.py` 的 `ALL_FETCHERS` 字典即可自动被 `search_engine.py` 调用。Phase 1 实现了 7 个国际来源；Phase 2 预留了万方、百度学术、USPTO、CNIPA 的注册占位。

### LLM 提供商

`LLMProviderManager`（`services/core/llm_providers.py`）统一管理多个 LLM 后端（Ollama / OpenAI兼容 / Anthropic / DeepSeek / Moonshot）。配置持久化在 Redis（`llm:providers` key）。所有 LLM 调用必须通过此管理器，不直接调用 SDK。Celery worker 内部直接实例化 `LLMProviderManager(default_ollama_host=settings.ollama_host)`。

## 开发约定

### 后端

- **async 规则**：Celery 任务（同步）内运行异步代码使用 `_run_async(coro)` helper（见 `search_tasks.py`），每次创建新 event loop，不复用。
- **错误处理分层**：Fetcher 层只 `print + return []`，不上抛；API 层抛 `HTTPException`；Celery 任务捕获异常后更新 `round.status = "failed"` 再 `raise`。
- **数据库迁移**：`alembic/versions/0001_initial.py` 不可修改（已部署）。新增字段创建新版本文件。
- **文档去重**：`(source, external_id)` 是唯一键，`save_round_documents()` 先查后插，不使用 `ON CONFLICT`。

### 前端

- 所有 API 调用通过 `frontend/src/api/client.ts` 的具名导出（`authApi` / `projectApi` / `searchApi` / `feedbackApi` / `llmApi`），不在组件内直接使用 axios。
- 轮次状态用 HTTP 轮询（2秒间隔），不用 WebSocket，见 `stores/search.ts:startPolling()`。
- Element Plus 图标已在 `main.ts` 全局注册，组件内直接用 `<el-icon><Setting /></el-icon>`。

### Git

- 分支：`feat/<功能名>` 或 `fix/<描述>` 从 `dev` 切出 → PR 到 `dev` → PR 到 `main`
- Commit 格式：`feat:` / `fix:` / `refactor:` / `docs:` / `chore:`

## Phase 规划

| Phase | 关键功能 | 状态 |
|-------|---------|------|
| 1 | 5轮渐进检索、AI摘要、用户画像、Docker部署 | ✅ 完成 |
| 2 | 万方/百度学术、USPTO专利、PDF全文、pgvector embedding、邮件通知 | 待开发 |
| 3 | EPO/WIPO专利、多语言检索、文献关系图、协作功能 | 规划中 |
