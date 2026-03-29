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

# 改了 Python 代码后（无需重建，因有 volume 挂载）
docker-compose restart backend worker

# 改了 requirements.txt 或 Dockerfile 才需要重建——必须同时指定所有共用 Dockerfile 的服务
docker-compose build backend worker beat flower
docker-compose up -d

# ⚠️ 容器被 up -d 重建后（新 IP），nginx 必须重启才能刷新 DNS 缓存，否则 502
docker-compose restart nginx
# 完整重建流程（改了 .env 环境变量也要走这个）：
# docker-compose up -d backend worker && docker-compose restart nginx

# 改了前端代码（无 volume 挂载，需 build）
docker-compose build frontend && docker-compose up -d frontend && docker-compose restart nginx

# 查看日志
docker-compose logs -f backend    # FastAPI 应用日志
docker-compose logs -f worker     # Celery worker 任务日志

# 手动触发数据库迁移（通常由 backend 容器启动时自动执行）
docker-compose exec backend alembic upgrade head

# 新建迁移文件（修改了 models/ 后）——注意：--autogenerate 因缺少 mako 模板会报错
# 改为手动创建文件：backend/alembic/versions/XXXX_描述.py，参考 0002_add_embedding_cols.py
# alembic/ 目录已挂载到 backend 容器（./backend/alembic:/app/alembic），无需重建即可生效
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

**国内 Docker/WSL2 环境网络限制（已验证）：**

| 数据源 | 状态 | 说明 |
|--------|------|------|
| OpenAlex | ✅ 可访问 | 主力来源 |
| EuropePMC | ✅ 可访问 | PubMed 的欧洲镜像，内容相同且有完整摘要 |
| SemanticScholar | ⚠️ 限速 | 公开 API 频繁 429，默认禁用 |
| PubMed (NCBI) | ❌ 封锁 | `eutils.ncbi.nlm.nih.gov` TLS 握手超时，用 EuropePMC 替代 |
| arXiv | ❌ 封锁 | `export.arxiv.org` 超时，默认禁用 |

通过 `.env` 的 `DISABLED_SOURCES=pubmed,arxiv,biorxiv,medrxiv,semantic_scholar` 控制禁用列表，无需改代码。`query_builder._select_sources()` 读取此变量过滤。

### LLM 提供商

`LLMProviderManager`（`services/core/llm_providers.py`）统一管理多个 LLM 后端（Ollama / OpenAI兼容 / Anthropic / DeepSeek / Moonshot）。配置持久化在 Redis（`llm:providers` key）。所有 LLM 调用必须通过此管理器，不直接调用 SDK。Celery worker 内部直接实例化 `LLMProviderManager(default_ollama_host=settings.ollama_host)`。

## 开发约定

### 后端

- **async 规则**：Celery 任务（同步）内运行异步代码使用 `_run_async(coro)` helper（见 `search_tasks.py`），每次创建新 event loop，不复用。
- **错误处理分层**：Fetcher 层只 `print + return []`，不上抛；API 层抛 `HTTPException`；Celery 任务捕获异常后更新 `round.status = "failed"` 再 `raise`。
- **数据库迁移**：`alembic/versions/0001_initial.py` 不可修改（已部署）。新增字段创建新版本文件。
- **文档去重**：`(source, external_id)` 是唯一键，`save_round_documents()` 先查后插，不使用 `ON CONFLICT`。
- **ORM 级联删除**：async SQLAlchemy 的 `db.delete(obj)` 不加载关联数据时 cascade 不触发。删除含关联数据的记录必须用 `db.execute(delete(Model).where(...))` 走 DB 级联（`ON DELETE CASCADE`）。
- **LLM 跨进程配置**：FastAPI 进程内存中的 LLM 配置不会传递给 Celery worker（独立进程）。所有 LLM 配置操作（configure/switch/delete）必须同时调用 `save_llm_config()` 持久化到 Redis；worker 启动时通过 `load_llm_config()` 读取。

### 前端

- 所有 API 调用通过 `frontend/src/api/client.ts` 的具名导出（`authApi` / `projectApi` / `searchApi` / `feedbackApi` / `llmApi`），不在组件内直接使用 axios。
- 轮次状态用 HTTP 轮询（2秒间隔），不用 WebSocket，见 `stores/search.ts:startPolling()`。
- Element Plus 图标已在 `main.ts` 全局注册，组件内直接用 `<el-icon><Setting /></el-icon>`。
- **Element Plus 国际化**：必须 `import zhCn from 'element-plus/es/locale/lang/zh-cn'`，然后 `app.use(ElementPlus, { locale: zhCn })`。写 `{ locale: { name: 'zh-cn' } }` 不起作用，按钮会显示翻译 key 原文。

### 评分引擎注意事项

- `keyword_score()` 在 `relevance_engine.py` 逐词遍历 `query_terms` 列表做子串匹配。传入的列表里每个元素必须是单个关键词，绝不能把整句话作为一个元素——否则匹配永远失败，所有文档得分为 0。
- `query_builder.py` 的 `build_query()` 将 `base_query.split()` 后传入，确保是词列表。

### 中文查询翻译

- 所有已接入数据源（PubMed、OpenAlex、arXiv 等）均为英文，中文描述必须先翻译为英文关键词。
- `query_builder._get_english_query()` 会调用 LLM 翻译，LLM 不可用时自动回退到 `_extract_core_query()`。
- Worker 在执行检索前必须先 `load_llm_config()` 加载用户配置的 LLM，否则回退 Ollama 且通常不可用。

### Git

- 分支：直接提交到 `feat/mvp-bugfix-and-run`，不再走 worktree 分支 merge（2026-03-29 起）
- Commit 格式：`feat:` / `fix:` / `refactor:` / `docs:` / `chore:`

### el-table 内 el-select 的值绑定

- **问题**：`el-table` scoped slot 内，`el-select` 使用 `:value="10"`（数字）时，v-model 绑定失效——所有行都显示第一个选项。
- **规则**：el-table 内的 el-select 选项 **必须用字符串 value**（`value="10"`），提交时再 `parseInt` 转回数字。null 改为 `"all"` 等字符串占位。

### 前端改动必须 rebuild

- 后端 Python 文件有 volume 挂载，改完 `restart backend worker` 即可热更新。
- 前端代码 **没有** volume 挂载，每次改动都必须：
  ```bash
  docker-compose build frontend && docker-compose up -d frontend && docker-compose restart nginx
  ```

### 临时公网访问

开发期间对外共享，使用 Cloudflare Quick Tunnel（无需账号）：
```bash
cloudflared tunnel --url http://localhost
# 输出一个 https://xxx.trycloudflare.com，每次重启URL会变
```

### 数据持久化

- `docker-compose down` — 安全，保留 pgdata/redisdata volume
- `docker-compose down -v` — **危险！** 删除所有 volume，数据库清空
- 永远不要在生产/演示环境运行 `docker volume prune`

### Lens.org 专利 API

- 免费试用：[lens.org/lens/user/subscriptions](https://www.lens.org/lens/user/subscriptions) → Patent API → Trial Access
- 配置：`.env` 中填 `LENS_API_TOKEN=<token>`
- 覆盖：CN/US/EP/WO/JP/KR 等 90+ 国家，1.6亿+ 专利记录
- Token 未配置时 `LensPatentFetcher.fetch()` 直接返回 `[]`，不报错

## Phase 规划

| Phase | 关键功能 | 状态 |
|-------|---------|------|
| 1 MVP | 5轮渐进检索、AI摘要、用户画像、Docker部署 | ✅ **dev0 发布**（2026-03-29）|
| 2 | 万方/百度学术、PDF全文、pgvector embedding、邮件通知 | 待开发 |
| 3 | EPO/WIPO专利、多语言检索、文献关系图、协作功能 | 规划中 |

### Phase 1 已完成

- [x] PubMed 报错无详细信息 — 已加详细异常日志 + traceback（2026-03-29）
- [x] Semantic Scholar 持续 429 — 指数退避重试 + DISABLED_SOURCES 禁用（2026-03-29）
- [x] 清理 `relevance_engine.py` 中的调试 print（2026-03-29）
- [x] 非燃烧香料测试用例：Round 1 跑通，反馈提交后 Round 2 自动轮询（2026-03-29）
- [x] 多领域选择、跨轮去重、综合评分（引用+时效）（2026-03-29）
- [x] 可配置搜索流程：每轮独立设置年份/语言/Top K（2026-03-29）
- [x] Lens.org 全球专利数据源（CN/US/EP/WO）（2026-03-29）
- [x] 文献数 ≤ 3 时动态最低评分，不再卡住（2026-03-29）

### Phase 2 待办

- [ ] 爆珠生产线 / 新型烟草 / 牙髓干细胞 三个测试用例验证
- [ ] Round 2–5 完整流程端到端验证
- [ ] 万方 / 百度学术 中文数据源
- [ ] PDF 全文抓取 + pgvector embedding
- [ ] 邮件通知（每日监控结果推送）
