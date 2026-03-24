# 科研情报平台 — 完整工程规划

> 产品名称：URIP（Universal Research Intelligence Platform）
> 规划日期：2026-03-23
> 基于：bioinfo-search-system v2.1（现有系统继承）

---

## 产品定位

服务于科研人员的全领域情报平台。核心价值：

- **AI读全文**，生成自己的摘要（不是原文摘要）
- **渐进式检索**：从近到远，从窄到宽，每轮根据用户反馈演化
- **用户画像学习**：反馈越多，推荐越准
- **全球自动监控**：每天抓取新内容，AI判断相关性后推送
- **极简UX**：一眼就懂，无需手册

覆盖领域：不限生物技术，涵盖化学、材料科学、CS、物理、经济等所有科研领域。

---

## 一、继承现有系统的内容

| 现有文件 | 继承方式 |
|---|---|
| `backend/services/llm_providers.py` | **直接复制**，零改动。已支持 Ollama/OpenAI/Anthropic/DeepSeek/Moonshot/Custom，用户自选 |
| `backend/services/enhanced_data_fetcher.py` | 提取 `_safe_fetch` + `asyncio.gather` 并行模式，作为新 `fetchers/base.py` 的 AbstractFetcher 基类 |
| `backend/services/data_cleaner.py` | 保留所有源特定清洗规则，扩展新数据源清洗器 |
| `backend/services/relevance_scorer.py` | 作为关键词打分基线（Phase 1），Phase 2 叠加 embedding 向量打分 |
| `backend/services/task_manager.py` | 接口不变（create/update/complete/fail/get），内部替换为 Redis 后端 |
| `backend/app.py` 的 lifespan 模式 | 沿用 FastAPI lifespan context manager 模式 |

---

## 二、技术栈

| 层级 | 技术 | 理由 |
|---|---|---|
| Web 框架 | FastAPI（保留） | 无迁移成本，async 原生 |
| 数据库 | PostgreSQL 16 + pgvector | 多用户并发安全、向量相似度、JSONB |
| ORM/迁移 | SQLAlchemy 2.0 async + Alembic | 标准生产选择 |
| 任务队列 | Celery 5 + Redis | 持久化任务、cron 调度（celery-beat）、重试、Flower 监控 |
| PDF 解析 | pdfplumber + pypdf2 | 无 GPU 依赖，支持中文多栏布局 |
| 向量嵌入 | sentence-transformers (paraphrase-multilingual-MiniLM-L6-v2) | 384维，中英文均支持，CPU 可运行 |
| 中文分词 | jieba | 轻量，无 GPU，关键词提取用 |
| 认证 | JWT (python-jose + passlib) | 无状态，FastAPI 原生 |
| 前端框架 | Vue 3 + Vite + Pinia + Element Plus | 中文优先组件库，Composition API 处理复杂状态 |
| 图表 | ECharts | 中文生态最佳 |
| HTTP 客户端 | httpx（保留） | 异步，支持代理，已在用 |
| 通知（Phase 2+） | 邮件 + Telegram Bot + QQ Bot | Phase 1 先做站内消息 |
| 部署 | Docker Compose（Linux 云服务器 / Windows Docker Desktop 均可） | 单命令启动，开发生产同构 |

---

## 三、目录结构

```
urip/
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── .gitattributes                        # *.sh eol=lf 防止 Windows 行尾符问题
├── README.md
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/                    # 数据库迁移脚本
│   │
│   └── app/
│       ├── main.py                       # FastAPI app factory + lifespan
│       ├── config.py                     # Pydantic Settings（从 .env 读取）
│       ├── dependencies.py               # JWT 验证、DB session 注入
│       │
│       ├── api/                          # 薄控制器层，只做路由和参数校验
│       │   ├── auth.py
│       │   ├── projects.py
│       │   ├── search.py                 # 渐进式搜索轮次
│       │   ├── feedback.py
│       │   ├── monitoring.py
│       │   ├── documents.py              # 全文获取、摘要状态
│       │   └── llm.py                    # LLM配置（与v1相同）
│       │
│       ├── models/                       # SQLAlchemy ORM 模型
│       │   ├── user.py
│       │   ├── project.py
│       │   ├── search_round.py
│       │   ├── document.py
│       │   ├── feedback.py
│       │   ├── user_profile.py
│       │   └── monitor_job.py
│       │
│       ├── schemas/                      # Pydantic 请求/响应模型
│       │   ├── auth.py
│       │   ├── project.py
│       │   ├── search.py
│       │   ├── feedback.py
│       │   └── monitoring.py
│       │
│       ├── services/
│       │   ├── core/
│       │   │   ├── llm_providers.py      # 从 v1 直接复制，零改动
│       │   │   ├── data_cleaner.py       # 从 v1 扩展，新增数据源清洗器
│       │   │   └── task_manager.py       # 接口同 v1，内部改为 Redis 后端
│       │   │
│       │   ├── fetchers/
│       │   │   ├── base.py               # AbstractFetcher，_safe_fetch + asyncio.gather
│       │   │   ├── international.py      # PubMed / OpenAlex / SemanticScholar / EuropePMC / arXiv / bioRxiv / medRxiv
│       │   │   ├── patents.py            # USPTO PatentsView + EPO OPS + CNIPA（Phase 2）
│       │   │   └── chinese.py            # 万方 Open API + 百度学术爬虫（Phase 2）
│       │   │
│       │   ├── progressive_search.py     # 渐进式检索状态机：管理轮次生命周期
│       │   ├── search_engine.py          # 协调 fetchers + scoring，执行单轮检索
│       │   ├── fulltext_pipeline.py      # PDF 获取 → 解析 → 文本提取（Phase 2）
│       │   ├── llm_summarizer.py         # 全文/摘要 → AI 中文摘要生成
│       │   ├── query_builder.py          # 基于用户画像演化查询词
│       │   ├── relevance_engine.py       # 关键词 + embedding 混合打分
│       │   ├── profile_service.py        # 反馈 → embedding 均值 → 偏好模型更新
│       │   ├── monitoring_service.py     # 定时检索 + 去重 + 投递
│       │   └── notification_service.py   # 站内消息 / 邮件 / Telegram / QQ（Phase 2+）
│       │
│       └── workers/                      # Celery 任务定义
│           ├── celery_app.py
│           ├── search_tasks.py           # execute_round：fetch→clean→score→summarize
│           ├── fulltext_tasks.py         # PDF 下载/解析（慢任务，独立队列）
│           └── monitor_tasks.py          # 每日/每周监控任务
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router/
│       │   └── index.ts
│       ├── stores/
│       │   ├── auth.ts
│       │   ├── project.ts
│       │   └── search.ts                 # 渐进式搜索状态（轮次、文档、反馈草稿）
│       ├── views/
│       │   ├── Dashboard.vue             # 项目列表 + 最近动态
│       │   ├── ProjectCreate.vue         # 项目创建向导（描述研究方向）
│       │   ├── ProjectView.vue           # 主工作视图（含轮次时间线）
│       │   ├── SearchRound.vue           # 单轮检索视图（搜索中/摘要中/等待反馈）
│       │   ├── Monitoring.vue            # 监控管理 + 历史推送
│       │   └── Settings.vue              # LLM配置、通知设置
│       ├── components/
│       │   ├── DocumentCard.vue          # 核心组件：AI摘要 + 反馈控件
│       │   ├── RoundTimeline.vue         # 左侧步骤条（第1-5轮 + 监控中）
│       │   ├── FeedbackPanel.vue         # 相关度选择 + 原因文本框
│       │   ├── SourceBadge.vue           # 数据源标签
│       │   └── ProfileInsight.vue        # AI已学到的用户偏好展示
│       └── api/
│           └── client.ts                 # Axios 实例 + JWT 注入 + 类型化端点
│
└── nginx/
    └── nginx.conf
```

---

## 四、数据库 Schema

### 关系概览

```
users
  └── projects
        ├── search_rounds
        │     ├── round_documents ──▶ documents
        │     └── feedback ────────▶ documents
        ├── user_profiles
        └── monitor_jobs
              └── monitor_results
```

### 核心表定义

```sql
-- 用户
users (
  id UUID PK, email UNIQUE, name TEXT,
  hashed_pw TEXT, created_at TIMESTAMPTZ, is_active BOOLEAN
)

-- 项目（顶层实体）
projects (
  id UUID PK, user_id→users,
  title TEXT, description TEXT,        -- 研究方向描述
  domain TEXT,                         -- biology/chemistry/cs/economics/...
  current_round INT DEFAULT 0,
  status TEXT DEFAULT 'active',        -- active|monitoring|archived
  created_at, updated_at
)

-- 渐进式检索的每一轮
search_rounds (
  id UUID PK, project_id→projects,
  round_number INT,                    -- 1~5
  status TEXT,                         -- pending|searching|summarizing|awaiting_feedback|complete
  time_horizon_years INT,              -- 5/10/20/NULL(全时间)
  max_results INT DEFAULT 10,
  language_scope TEXT DEFAULT 'chinese', -- chinese|global
  sources_used TEXT[],
  search_queries JSONB,                -- 实际发出的查询词（各源）
  total_candidates INT,                -- 原始候选数
  selected_count INT,                  -- 展示给用户数
  started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
  UNIQUE(project_id, round_number)
)

-- 规范化文档（跨轮次、跨源去重）
documents (
  id UUID PK,
  source TEXT,                         -- pubmed|openalex|arxiv|cnipa|...
  external_id TEXT,                    -- PMID/DOI/专利号等
  doc_type TEXT,                       -- paper|patent|preprint|news|conference
  title TEXT, title_zh TEXT,           -- 原标题 + 中文翻译（全球模式）
  authors TEXT, abstract TEXT,
  publication_date DATE, url TEXT,
  -- 全文状态
  fulltext_status TEXT DEFAULT 'not_attempted', -- not_attempted|downloading|available|failed
  fulltext_path TEXT,                  -- 本地 PDF 路径
  fulltext_text TEXT,                  -- 提取的纯文本（≤50,000字）
  -- AI生成内容（核心差异化）
  ai_summary TEXT,                     -- AI自写摘要（200-300字中文）
  ai_key_points TEXT[],                -- 3-5条关键要点
  ai_relevance_reason TEXT,            -- 与项目的关联说明（1句话）
  -- 评分
  quality_score REAL,
  embedding vector(384),               -- sentence-transformers embedding
  content_hash TEXT,                   -- sha256(title+authors) 用于去重
  created_at TIMESTAMPTZ,
  UNIQUE(source, external_id)
)
CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops);

-- 轮次与文档的关联（多对多）
round_documents (
  id UUID PK, round_id→search_rounds, document_id→documents,
  rank_in_round INT,                   -- AI选出的排名
  initial_score REAL,
  UNIQUE(round_id, document_id)
)

-- 研究者对每篇文档的反馈
feedback (
  id UUID PK,
  user_id→users, project_id→projects, round_id→search_rounds, document_id→documents,
  relevance INT CHECK(-1..2),          -- -1无关 / 0不确定 / 1相关 / 2非常相关
  reason TEXT,                         -- 研究者自由文本说明
  positive_signals JSONB,              -- LLM从reason中提取的正向特征
  negative_signals JSONB,              -- LLM从reason中提取的负向特征
  created_at TIMESTAMPTZ,
  UNIQUE(user_id, document_id, round_id)
)

-- 用户偏好画像（每个项目一份，随反馈演化）
user_profiles (
  id UUID PK, user_id→users, project_id→projects,
  positive_embedding vector(384),      -- 正向反馈文档 embedding 的滚动均值
  negative_embedding vector(384),      -- 负向反馈文档 embedding 的滚动均值
  preferred_keywords TEXT[],
  excluded_keywords TEXT[],
  preferred_sources TEXT[],
  preferred_doc_types TEXT[],
  preferred_authors TEXT[],
  feedback_count INT DEFAULT 0,
  last_updated TIMESTAMPTZ,
  UNIQUE(user_id, project_id)
)

-- 每日监控任务
monitor_jobs (
  id UUID PK, project_id→projects, user_id→users,
  schedule TEXT,                       -- 'daily'|'weekly'
  is_active BOOLEAN DEFAULT true,
  last_run_at TIMESTAMPTZ, next_run_at TIMESTAMPTZ,
  search_config JSONB,                 -- 最终轮次状态导出的查询配置
  created_at TIMESTAMPTZ
)

-- 监控运行结果
monitor_results (
  id UUID PK, job_id→monitor_jobs,
  run_at TIMESTAMPTZ, new_docs_found INT,
  docs JSONB,                          -- [{document_id, score, summary}]
  notified BOOLEAN DEFAULT false,
  notified_at TIMESTAMPTZ
)
```

---

## 五、渐进式检索状态机

### 轮次参数表

| 轮次 | 时间范围 | 展示数量 | 语言范围 | 摘要语言 |
|---|---|---|---|---|
| 1 | 近5年 | Top 10 | 中文库（+PubMed等） | 原语言 |
| 2 | 近10年 | Top 10 | 中文库 | 原语言 |
| 3 | 近20年 | Top 20 | 中文 + 国际 | 原语言 |
| 4 | 全时间 | 全部相关 | 中文 + 国际 | 原语言 |
| 5 | 全时间 | 全部相关 | 全球多语言 | **AI生成中文摘要** |
| → | 监控 | 每日新文献 | 全球 | AI中文摘要 + 推送 |

### 状态转移

```
POST /projects/{id}/rounds/start
    ↓
pending → searching（Celery: execute_round）
    ↓
searching → summarizing（Celery: generate_summaries，异步填入）
    ↓
summarizing → awaiting_feedback（前端展示 DocumentCard）
    ↓
POST /rounds/{id}/feedback
    ↓
更新 user_profile → mark round complete
    ↓
project.current_round < 5 ?
  是 → 创建下一轮，重新 start
  否 → project.status = 'monitoring'，创建 monitor_job
```

### 混合相关度打分

```python
hybrid_score = (
    0.4 * keyword_score(doc, query_terms)          # 继承自 v1
  + 0.4 * cosine_sim(doc.embedding, profile.positive_embedding)
  - 0.2 * cosine_sim(doc.embedding, profile.negative_embedding)
)
# 第1轮 profile.positive_embedding 为零向量，自动退化为纯关键词打分
```

### 查询词演化

```python
def evolve_query(original_query, profile, round_number):
    return ExpandedQuery(
        base_terms = [original_query] + profile.preferred_keywords[:5],
        exclude_terms = profile.excluded_keywords[:3],
        preferred_sources = profile.preferred_sources,
    )
```

---

## 六、数据源规划

### Phase 1 — 国际学术（继承 v1，新增年份过滤和 arXiv）

| 数据源 | API | 领域 |
|---|---|---|
| PubMed | NCBI E-utilities（免费）| 生物医学 |
| OpenAlex | REST API（免费）| 全领域 |
| Semantic Scholar | REST API（免费）| 全领域 |
| Europe PMC | REST API（免费）| 生物医学 |
| bioRxiv / medRxiv | 官方 API（免费）| 预印本 |
| **arXiv** | REST API（免费）| CS/物理/数学/经济 |

### Phase 2 — 专利 + 中文学术

| 数据源 | 接入方式 | 说明 |
|---|---|---|
| USPTO | PatentsView REST API（免费，无需注册）| 美国专利 |
| EPO | OPS API（注册后免费，OAuth2）| 欧洲专利 |
| CNIPA / SooPAT | SooPAT API 或爬虫 | 中国专利 |
| 万方数据 | 官方 Open API（需注册）| 中文学术 |
| 百度学术 | HTTP 爬虫（简单 HTML）| 中文学术 |

### Phase 3 — 全球扩展

| 数据源 | 说明 |
|---|---|
| WIPO PATENTSCOPE | 全球专利 |
| Google Patents | SerpApi（付费）或 HTML 爬虫 |
| RSS 新闻源 | 36Kr、Science Daily 等 |
| CNKI | Playwright 爬虫（最复杂，用户提供凭证）|

---

## 七、AI 全文摘要流水线

```
阶段1 — 获取 PDF：
  直接 PDF URL（Semantic Scholar/bioRxiv 已提供）
  → Unpaywall DOI 查询（开放获取）
  → Europe PMC 全文 XML
  → 专利 PDF（USPTO/CNIPA 直接提供下载链接）
  → 降级：无全文时用 abstract（透明标注）

阶段2 — 解析（pdfplumber）：
  提取前30页，≤50,000字符，处理多栏中文布局

阶段3 — LLM 生成（llm_summarizer.py）：
  输入：[项目描述] + [全文/摘要片段]
  输出 JSON：{
    "summary": "200-300字中文摘要（AI自写，非原文复制）",
    "key_points": ["关键要点1", "关键要点2", "关键要点3"],
    "relevance_reason": "与项目关联说明（1句话）"
  }

阶段4 — 异步投递：
  Celery 后台生成，前端骨架屏占位，摘要完成后 WebSocket 推送填入
  用户可边浏览卡片边评分，无需等待全部摘要完成
```

---

## 八、每日监控架构

```python
# celery-beat 调度
"daily-monitor": crontab(hour=6, minute=0)    # 每天早6点
"weekly-monitor": crontab(hour=7, day_of_week=1)  # 每周一早7点

# 单个监控任务逻辑
def run_single_monitor(job_id):
    1. 用 search_config 检索各数据源（时间过滤：近7天，有7天重叠防漏）
    2. 去重（排除 round_documents + monitor_results 中已见文档）
    3. 计算 hybrid_score（对照 user_profile）
    4. score > 0.6 的文档 → Celery 生成 AI 摘要
    5. 投递：
       Phase 1 → 站内消息（前端 badge）
       Phase 2 → 邮件 + Telegram Bot + QQ Bot
    6. 更新 monitor_job.last_run_at / next_run_at
```

---

## 九、关键 API 端点

### 认证
```
POST /api/auth/register
POST /api/auth/login        → { access_token }
GET  /api/auth/me
```

### 项目管理
```
GET    /api/projects
POST   /api/projects        ← { title, description, domain }
GET    /api/projects/{id}
DELETE /api/projects/{id}
```

### 渐进式检索（核心）
```
POST /api/projects/{id}/rounds/start           → 创建并启动下一轮
GET  /api/projects/{id}/rounds/{rid}/status    → 轮询状态和进度
GET  /api/projects/{id}/rounds/{rid}/results   → 获取文档列表（含摘要）
POST /api/projects/{id}/rounds/{rid}/feedback  ← { feedbacks: [{doc_id, relevance, reason}] }
GET  /api/projects/{id}/rounds                 → 所有轮次汇总（时间线用）

WS   /ws/rounds/{round_id}                     → 实时进度推送
```

### 全文与摘要
```
POST /api/documents/{id}/fetch-fulltext        → 触发 PDF 下载（Celery）
GET  /api/documents/{id}/fulltext              → 查询状态和文本片段
```

### 监控
```
GET    /api/projects/{id}/monitor
POST   /api/projects/{id}/monitor              → 激活监控
PATCH  /api/projects/{id}/monitor              → 修改频率
DELETE /api/projects/{id}/monitor              → 停止监控
GET    /api/projects/{id}/monitor/history      → 历史推送记录
```

### 用户画像
```
GET /api/projects/{id}/profile                 → 当前偏好状态
GET /api/projects/{id}/profile/insights        → AI生成的人类可读偏好摘要
```

### LLM 配置（同 v1）
```
GET    /api/llm/providers
POST   /api/llm/configure
POST   /api/llm/switch/{provider_id}
DELETE /api/llm/{provider_id}
```

---

## 十、前端 UX 核心原则

1. **零学习成本**：首屏只有一个大按钮"开始新项目"，引导填写研究方向
2. **情景化引导**：每轮顶部1句话（"这是第2轮，AI正在检索10年内的文献，参考了您上次的反馈"）
3. **非阻塞反馈**：最少评3篇即可点击"提交并继续"，不强迫全部评完
4. **摘要异步填入**：文档卡先出现（骨架屏），摘要生成完毕后 WebSocket 推入，用户边读边评
5. **可视化进度**：左侧步骤条（第1~5轮 + 监控中），整体流程一目了然
6. **透明标注**：无全文时显示"摘要来源：原文摘要（非全文）"

---

## 十一、分阶段实施计划

### Phase 1（第1-8周）— 核心渐进检索 MVP

**目标**：可用的多轮搜索系统，AI摘要，用户反馈驱动画像，支持国际学术数据源

| 周 | 交付物 |
|---|---|
| 1-2 | Docker Compose 脚手架（FastAPI + PostgreSQL + Redis + Celery + Nginx），Alembic 迁移，JWT 认证，项目 CRUD |
| 3-4 | 继承 v1 国际数据源，接入 RoundConfig（年份过滤），实现第1-3轮逻辑，新增 arXiv fetcher |
| 5 | LLM 摘要服务：从 abstract 生成 AI 中文摘要（复用 llm_providers.py，支持用户自选 LLM） |
| 6 | 反馈 API + profile_service（关键词偏好提取，暂无 embedding） |
| 7 | Vue 3 前端：认证页、Dashboard、ProjectCreate 向导、SearchRoundView + DocumentCard + 反馈控件 |
| 8 | 集成测试，生产 Docker Compose 配置，站内通知（WebSocket badge） |

**Phase 1 不含**：专利检索、万方/百度学术、PDF全文下载、embedding打分、邮件/Telegram通知

### Phase 2（第9-16周）— 中文生态 + 专利 + 监控

| 周 | 交付物 |
|---|---|
| 9-10 | 万方 Open API + 百度学术爬虫（`fetchers/chinese.py`） |
| 11-12 | USPTO PatentsView + CNIPA 专利检索（`fetchers/patents.py`） |
| 13-14 | PDF 全文流水线：Unpaywall + pdfplumber（`fulltext_pipeline.py` + `fulltext_tasks.py`） |
| 15 | pgvector embedding 计算 + hybrid scoring 上线（`relevance_engine.py` 升级） |
| 16 | Celery-beat 每日监控任务 + 邮件通知 + Monitoring 前端页面 |

### Phase 3（第17-24周）— 全球检索 + 高级功能

| 周 | 交付物 |
|---|---|
| 17-18 | 第5轮全球检索：EPO OPS + WIPO + LLM 翻译外文摘要为中文 |
| 19-20 | Telegram Bot + QQ Bot 通知（替代/补充邮件） |
| 21-22 | 多用户协作：项目共享、团队通知、角色权限（owner/viewer） |
| 23-24 | ECharts 分析看板（研究热点、关键词趋势、来源分布）+ Redis 缓存优化 |

---

## 十二、关键技术决策记录（ADR）

| 决策 | 选择 | 理由 |
|---|---|---|
| 数据库 | PostgreSQL 替代 SQLite | 多进程写安全、pgvector、多用户隔离 |
| 任务调度 | Celery+Redis 替代 BackgroundTasks | 持久化、cron 调度、重试、监控 |
| 向量方案 | pgvector 而非独立向量库 | 千级文档/用户的规模不需要 Qdrant/Pinecone，避免额外基础设施 |
| CNKI | 暂跳过，用万方+百度学术替代 | 无公开 API，机构账号成本高；Phase 3 再处理 |
| 摘要降级 | 无全文时从 abstract 生成，透明标注 | ~70% 文章无可获取全文，必须优雅降级 |
| 通知渠道 | Phase 1 站内消息，Phase 2+ 邮件+Telegram+QQ | 循序渐进，不阻塞核心功能上线 |
| 部署 | Linux 云服务器 + Docker Compose | Windows Docker Desktop 完全兼容（WSL2），开发生产同一套配置 |

---

## 十三、Docker Compose 服务清单

```yaml
services:
  postgres:    # pgvector/pgvector:pg16
  redis:       # redis:7-alpine
  backend:     # FastAPI + uvicorn workers
  worker:      # celery -A app.workers.celery_app worker -Q default,fulltext
  beat:        # celery -A app.workers.celery_app beat（定时监控调度）
  flower:      # celery flower（任务监控 UI，端口 5555）
  frontend:    # nginx serve Vue 3 build
  nginx:       # 反向代理（:80/:443 → backend:8000 / frontend:3000）
```

本地开发挂载卷：`./data/pdfs`（PDF存储）、`./data/exports`（导出文件）

---

## 十四、Phase 1 验收标准

1. `docker-compose up -d` 单命令启动全部服务
2. 注册用户 → 创建项目 → 描述研究方向 → 启动第1轮检索
3. 检索完成后看到10篇文档，每篇有 AI 生成的中文摘要（200-300字，非原文复制）
4. 对文档评分（相关/不相关/非常相关）后，自动触发第2轮（10年范围）
5. API 文档 `http://localhost:8000/docs` 可访问全部端点
6. Flower `http://localhost:5555` 可看到 Celery 任务执行记录
7. 支持切换 LLM 提供商（DeepSeek/Ollama/OpenAI 等）不影响其他功能
