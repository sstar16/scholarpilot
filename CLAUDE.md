# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
项目在不断变动中，不用过分遵守，可灵活改变
## 项目简介

ScholarPilot（内部名 URIP）：面向科研人员或公司技术部的全领域情报检索平台。用户描述研究方向后，系统通过 **渐进式检索**（时间范围从近5年逐步扩展到全时间）从多个学术或专利数据源并行抓取文献和专利，AI生成中文摘要，用户反馈驱动画像学习，结束后自动转入每日监控模式。

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

所有数据源继承 `AbstractFetcher`（`fetchers/base.py`），实现 `fetch()` 方法后加入 `international.py` 的 `ALL_FETCHERS` 字典即可自动被 `search_engine.py` 调用。当前共 15 个注册数据源。

**国内 Docker/WSL2 环境网络限制（2026-03-31 docker exec 实测）：**

| 数据源 | 状态 | 说明 |
|--------|------|------|
| OpenAlex | ✅ 可访问 | 主力来源（0篇时查 worker 日志看翻译结果） |
| EuropePMC | ✅ 可访问 | PubMed 的欧洲镜像，内容相同且有完整摘要 |
| Crossref | ✅ 可访问 | 期刊引用数据，稳定 |
| DBLP | ✅ 可访问 | CS 顶会论文（CVPR/NeurIPS/ACL 等），免费 JSON API |
| arXiv | ✅ 可访问 | 预印本，实测可达（之前误标为封锁） |
| bioRxiv | ✅ 可访问 | 生物/医学预印本 |
| medRxiv | ✅ 可访问 | 医学预印本 |
| openalex_zh | ✅ 可访问 | OpenAlex language:zh 过滤，中文描述+chinese_first scope 触发 |
| SemanticScholar | ❌ 禁用 | 免费 API 频繁 429，已加入 DISABLED_SOURCES |
| PubMed (NCBI) | ❌ 封锁 | TLS ConnectError（GFW封锁），已加入 DISABLED_SOURCES |
| ClinicalTrials.gov | ❌ 封锁 | TLS ConnectError（clinicaltrials.gov 被封），已加入 DISABLED_SOURCES |
| USPTO (PatentsView) | ❌ API停用 | HTTP 410 discontinued；新 API 需 `PATENTSVIEW_API_KEY`（patentsview.org/api/signup 免费申请），已加入 DISABLED_SOURCES |
| Lens.org 专利 | ⚠️ token 已过期 | 需到 lens.org/lens/user/subscriptions 重新申请 Trial token |
| EPO OPS | ✅ 可访问 | 欧洲专利局，EP/WO，`EPO_CONSUMER_KEY` + `EPO_CONSUMER_SECRET` 已配置 |
| SooPat | ⚠️ 需账号 | 中国专利 CN，需 `SOOPAT_EMAIL` + `SOOPAT_PASSWORD` |

通过 `.env` 的 `DISABLED_SOURCES` 控制禁用列表，无需改代码。`query_builder._select_sources()` 读取此变量过滤。当前配置：`DISABLED_SOURCES=pubmed,clinical_trials,semantic_scholar,uspto`

**中文查询流程**：`_get_english_query()` 用 LLM 将中文描述翻译为英文关键词供国际数据源使用；`original_chinese_query` 字段保留原始中文核心词，中文数据源（百度学术）使用此字段而非翻译词。

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

- **当前开发分支**：`feat/phase2-revision-knowledge`（Phase 2 起，2026-03-30）
- **生产目录**：`D:\AI\scholarpilot`（用户正在使用，不要随便 `git pull`）
- **开发目录**：`D:\AI\scholarpilot-dev`（本文件所在，Phase 2 开发在这里进行）
- Commit 格式：`feat:` / `fix:` / `refactor:` / `docs:` / `chore:`

### 双环境管理（重要）

- **生产和开发用两个独立目录**，不能用 docker-compose override 来隔离——因为 volume 挂载的代码路径相同，改代码会同时影响两个容器。
- **端口隔离**：生产占用 80/5555，开发在服务器上用 `docker-compose.override.yml` 覆盖为 8080/5556，此文件已加入 `.gitignore` 不提交。
- **卷隔离**：Docker Compose 项目名默认取目录名。`prod/` 目录的卷是 `prod_pgdata`，`dev/` 的卷是 `dev_pgdata`，天然不同，数据不会串。
- **cloudflared 只走 80 端口**：`cloudflared tunnel --url http://localhost` 只指向 80，不会暴露开发环境（8080）。
- **在生产目录误操作 git pull**：用 `git reset --hard <上一个commit hash>` 回退，然后 `docker-compose restart backend worker`。
- **访问服务器开发环境**：用 SSH 隧道 `ssh -L 8080:localhost:8080 deploy@<IP>`，不对外开放 8080 端口。

### 服务器部署注意事项（2026-03-30 首次部署）

- **服务器**：阿里云轻量 2C2G，IP `8.138.174.28`，到期 2026-05-01，生产代码在 `/opt/scholarpilot/prod/`
- **内存只有 2 GiB**：必须先建 Swap：`fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab`
- **阿里云 Linux 无 `sudo` 组**：普通用户加入 `wheel` 组，不是 `sudo` 组
- **Dockerfile 国内加速**（必须，否则 apt-get 要 50 分钟以上）：
  ```dockerfile
  # apt 换阿里云源（在 apt-get update 前加）
  RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true && \
      apt-get update && apt-get install -y ...
  # pip 换清华源
  RUN pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  # npm 换 npmmirror
  RUN npm install --registry=https://registry.npmmirror.com
  ```
- **Dockerfile 编辑踩坑**：VS Code 粘贴长行会自动换行导致 `unknown instruction` 错误；必须手动逐行修改，不能整段粘贴含长命令的内容
- **关闭公开注册**：nginx 加 `location = /api/auth/register { return 403 '{"detail":"注册已关闭"}'; add_header Content-Type application/json; }`，放在 `location /api/` 前面
- **Flower 不能暴露公网**：`docker-compose.yml` 中 flower 用 `expose` 而不是 `ports`
- **内测账号**：beta01~beta10@test.com，密码 Scholar2026#01~#10，注册已关闭

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
- Token 未配置时 `LensPatentFetcher.fetch()` 返回 `[]` 并记录 `logger.warning`

### 评分引擎 v2（2026-03-30）

- **keyword_score** 升级：同义词扩展（`SYNONYM_MAP`）、词干级部分匹配、IDF 加权（批次内高频词降权）、无摘要文档 ×0.7 降权
- **元数据补全链**（`metadata_enricher.py`）：缺少 abstract 的文档自动从 OpenAlex/Crossref 补全，每轮最多 10 篇
- **LLM Reranking**（可选）：通过 `search_config.enable_llm_rerank: true` 启用，对 top-20 文档用 LLM 做二次排序
- **跨源去重增强**：DOI 相同的文档自动合并为元数据最完整版本
- **0 篇保底**：`execute_search` 返回空时自动放宽条件（忽略跨轮去重）重试；`exclude_terms` 命中 >80% 文档时自动忽略
- **可观测性**：`SearchRound.source_stats` JSON 列记录各数据源返回统计，前端展示数据源贡献
- **日志统一**：所有 fetcher 和 worker 使用 `logging.getLogger(__name__)` 替代 `print`

### Harness Engineering（2026-04-01，ai-powers 分支）

受 Claude Code 源码 12 层 harness 机制启发，ScholarPilot 接入了 6 个适配机制，将系统从"硬编码管线"升级为"AI agent 驱动的可扩展平台"。

**新增包：`backend/app/harness/`**

| 组件 | 文件 | 说明 |
|------|------|------|
| Tool Registry | `harness/tool_registry.py` | 统一 15 个 fetcher 为注册工具，带运行时统计（延迟、可靠性） |
| Hook Engine | `harness/hook_engine.py` | 11 个生命周期 hook 点（ROUND_START / POST_SEARCH / PRE_FEEDBACK 等） |
| Agent Orchestrator | `harness/agent_orchestrator.py` | LLM 动态规划搜索策略（feature flag: `ENABLE_AGENT_PLANNING`） |
| Skill System | `harness/skill_registry.py` + `skills/` | 3 个可复用工作流（Deep Dive / Trend Spotter / Gap Finder） |

**Feature Flags（`.env`，默认全部 ON）：**
- `ENABLE_AGENT_PLANNING=true` — AI 动态规划搜索策略（DeepSeek）
- `ENABLE_AUTONOMOUS_ROUNDS=true` — Agent 决定何时停止搜索（突破固定5轮）
- `ENABLE_AUTO_SKILLS=true` — Agent 自动触发技能（如高引文献自动 Deep Dive）
- `MAX_AUTONOMOUS_ROUNDS=15` — 自主模式安全上限
- `MAX_LLM_COST_PER_ROUND=0.10`（每轮 LLM 成本上限）

**多 Agent 并行架构：**
- **Search Strategy Agent** — 动态规划搜索策略（每轮启动前）
- **Quality Agent** — 评估搜索结果质量（与摘要生成并行）
- **Profile Pre-Analyzer** — 预分析结果中的新关键词/主题簇（与摘要并行）
- **Auto Skill Trigger** — 检测高引文献自动建议 Deep Dive（与摘要并行）
- **Round Controller** — 每轮反馈后决定继续/停止搜索（替代固定5轮）

**新增 API：**
- `GET /api/skills` — 列出可用技能
- `POST /api/skills/{project_id}/{skill_id}/run` — 执行技能
- `GET /health` 新增 `harness` 字段（tool_registry 统计 + metrics）

**`.claude/` 目录结构：**
```
.claude/
  agents/search_strategist.md  — Agent prompt 文档
  skills/deep_dive.md 等       — Skill 文档
  hooks/README.md              — Hook 使用指南
  rules/cost_budget.md         — LLM 成本规则
  rules/source_policy.md       — 数据源策略
```

### Per-Source Query Adapters（2026-04-01，ai-powers 分支）

每个数据源拥有独立的查询词优化 adapter，用户可在搜索前确认/编辑每个源的查询词。

**Feature Flag**: `enable_per_source_keywords: bool = True`（默认开启，`.env` 中 `ENABLE_PER_SOURCE_KEYWORDS=false` 可关闭）

**Two-Phase Round Flow**（feature 开启时）:
```
POST /rounds/prepare → 创建 round + 生成 per-source 关键词 → 返回方案
  ↓ 用户在前端 KeywordConfirmPanel 确认/编辑
POST /rounds/{id}/confirm-keywords → 存入 Redis → 启动 Celery 检索任务
```

**新增文件**:
| 文件 | 说明 |
|------|------|
| `backend/app/services/source_query_adapters.py` | Adapter 注册表 + LLM 批量优化 + heuristic fallback |
| `backend/app/schemas/keywords.py` | Pydantic schemas |
| `frontend/src/components/search/KeywordConfirmPanel.vue` | 可编辑的 per-source 关键词确认面板 |

**Adapter 清单**: EPOQueryAdapter(CQL)、ArXivQueryAdapter(category)、DBLPQueryAdapter(精简)、ChineseSourceAdapter(soopat/openalex_zh)、DefaultAdapter(passthrough)

**新增 API**:
- `POST /api/projects/{id}/rounds/prepare` — Phase 1: 生成关键词方案
- `GET /api/projects/{id}/rounds/{rid}/keyword-plan` — 获取已生成方案（页面刷新恢复）
- `POST /api/projects/{id}/rounds/{rid}/confirm-keywords` — Phase 2: 确认后启动搜索

**关键词存储**: Redis `keyword_plan:{round_id}`，TTL 10 分钟

## Phase 规划

| Phase | 关键功能 | 状态 |
|-------|---------|------|
| 1 MVP | 5轮渐进检索、AI摘要、用户画像、Docker部署 | ✅ **dev0 发布**（2026-03-29）|
| 1.5 AI Powers | Harness Engineering（Tool Registry / Hook / Agent / Skills） | ✅ **ai-powers 分支**（2026-04-01）|
| 1.6 Per-Source Keywords | Per-Source Query Adapters + 用户确认 UI | ✅ **ai-powers 分支**（2026-04-01）|
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
