# CLAUDE.md

项目在不断变动中，不用过分遵守，可灵活改变

## 项目简介

ScholarPilot：全领域科研情报检索平台。多学术/专利数据源并行检索 → AI 中文摘要 → 用户反馈驱动画像学习 → 每日监控。

## 常用命令

```bash
cp .env.example .env                    # 首次：填写密码和密钥
docker-compose up -d                    # 启动全部服务
docker-compose restart backend worker   # 改了后端 Python（有 volume 挂载）
docker-compose build frontend && docker-compose up -d frontend && docker-compose restart nginx  # 改了前端（无挂载，必须 build）
docker-compose build backend worker beat flower && docker-compose up -d  # 改了 requirements.txt/Dockerfile
docker-compose restart nginx            # 容器重建后必须刷新 nginx DNS
docker-compose logs -f backend          # 看 FastAPI 日志
docker-compose logs -f worker           # 看 Celery 任务日志
```

端口：`localhost`（前端）、`localhost:8000/docs`（Swagger）、`localhost:5555`（Flower）

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

15 个注册源，通过 `.env` `DISABLED_SOURCES` 控制。当前禁用：`pubmed,clinical_trials,semantic_scholar,uspto`

### LLM 提供商

**统一入口**：`await get_llm_manager()`（`services/core/llm_config_store.py`）
- 进程级单例 + 60s Redis TTL 缓存
- Redis key: `llm:config`
- 支持：Ollama / OpenAI / Anthropic / DeepSeek / Moonshot / jiekou.ai 中转
- 所有代码（API + Worker + Skills）统一调用，不再手动实例化

## 关键约定

### 后端
- **async 规则**：Celery 任务内用 `_run_async(coro)`，每次新 event loop
- **错误分层**：Fetcher → `return []`；API → `HTTPException`；Celery → 更新 status="failed" 再 raise
- **ORM 注意**：长时间操作后不要 `db.refresh(obj)`，用 `select()` 重新查询
- **DB 迁移**：`0001_initial.py` 不可改，新增字段建新 version 文件

### 前端
- API 调用统一走 `api/client.ts` 具名导出（authApi / projectApi / searchApi 等）
- Element Plus 国际化必须 `import zhCn` + `app.use(ElementPlus, { locale: zhCn })`
- el-table 内 el-select 必须用字符串 value，不能用数字

### Git
- **开发分支**：`feat/ai-powers`
- **生产目录**：服务器 `/opt/scholarpilot/prod/`
- **开发目录**：`D:\AI\scholarpilot-dev`
- Commit：`feat:` / `fix:` / `refactor:` / `docs:` / `chore:`

## 部署

- **服务器**：阿里云 2C2G，`8.138.174.28`，到期 2026-05-01
- **前端必须 rebuild**，后端 restart 即可（volume 挂载）
- **Dockerfile 国内加速**：apt 换阿里云、pip 换清华、npm 换 npmmirror
- `docker-compose down` 安全；`down -v` **删库！**
- 注册已关闭（nginx 拦截），内测账号 beta01~10@test.com

## Phase 状态

| Phase | 功能 | 状态 |
|-------|------|------|
| 1.0 MVP | 渐进检索、AI摘要、画像、部署 | ✅ |
| 1.5 | Harness（Tool Registry / Hook / Agent / Skills） | ✅ |
| 1.6 | Per-Source Query Adapters + 用户确认 | ✅ |
| 1.7 | Scoring Agent + Memory Agent + Deep Dive | ✅ |
| 1.8 | 4桶分类 + 开放轮次 + 监控解耦 | ✅ |
| 1.9 | LLM 单例重构 + DevView 更新 + 代码清理 | ✅ |
| 2 | 万方/百度、PDF全文、pgvector、邮件通知 | 待开发 |
