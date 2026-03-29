# ScholarPilot

**面向科研人员的全领域智能情报检索平台**

ScholarPilot 帮助科研人员从海量学术文献、专利、临床试验中快速定位最相关的研究情报。用户只需用自然语言描述研究方向，系统通过 **渐进式多轮检索** 从多个数据源并行抓取，AI 生成中文摘要，用户反馈驱动画像持续优化，最终转入每日自动监控模式。

> **当前版本：dev0**（2026-03-29）— MVP 功能完整，适合小规模内测

---

## 功能概览

### 核心能力

- **渐进式多轮检索**：每轮时间范围逐步扩展（近5年→10年→20年→全时间），避免信息过载
- **多数据源并行**：同时搜索学术论文、专利、临床试验，结果实时合并
- **AI 中文摘要**：对每篇文献生成中文摘要、关键要点、与项目的关联理由
- **用户反馈学习**：对文献标注相关度后，系统自动优化下一轮检索关键词
- **每日监控模式**：5轮结束后自动切换，每天推送最新相关文献
- **综合智能评分**：关键词相关性（60%）+ 引用影响力（25%）+ 发表时效性（15%）

### 高级配置

- **每轮独立配置**：为每轮单独设置年份范围、语言优先级（中文/英文/双语）、返回数量
- **多领域选择**：支持同时选择多个研究领域
- **数据源开关**：可单独启用/禁用专利库、临床试验库
- **评分权重调整**：可自定义三个评分维度的权重

---

## 系统架构

```
用户浏览器
  └─ nginx:80
      ├─ /api/*  → FastAPI backend:8000   (HTTP + WebSocket)
      └─ /*      → Vue3 frontend:80
```

### 核心数据流

```
POST /api/projects/{id}/rounds/start
  → create_next_round()       写入 search_rounds 表
  → execute_round.delay()     Celery 异步任务
      → build_query()         构建检索计划（关键词+年份+数据源）
      → execute_search()      asyncio.gather 并行调用所有 fetcher
      → save_round_documents() 写入 documents + round_documents 表
      → chord(generate_summary × N)(finalize_round)  并行生成摘要
  → round.status = "awaiting_feedback"

POST /api/projects/{id}/rounds/{rid}/feedback
  → update_profile_from_feedbacks()   更新用户画像关键词偏好
  → create_next_round() + execute_round.delay()   启动下一轮
  → 第 N 轮结束: activate_monitoring() → 写入 monitor_jobs 表

Celery Beat 每天早6点:
  → run_daily_monitors() → 检索近7天新文献 → 评分 → 保存
```

### 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + TypeScript + Element Plus + Vite |
| 后端 | FastAPI + SQLAlchemy (async) + Alembic |
| 任务队列 | Celery + Redis |
| 数据库 | PostgreSQL 16 + pgvector |
| AI | 支持 Ollama / OpenAI兼容 / Anthropic / DeepSeek / Moonshot |
| 部署 | Docker Compose（单机一键启动） |

---

## 目录结构

```
scholarpilot/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI 路由（projects / search / feedback / auth / llm）
│   │   ├── models/           # SQLAlchemy ORM 模型
│   │   ├── schemas/          # Pydantic 请求/响应 Schema
│   │   ├── services/
│   │   │   ├── fetchers/     # 数据源 Fetcher（每个文件一个数据源）
│   │   │   │   ├── base.py           AbstractFetcher 基类 + FetcherRegistry
│   │   │   │   ├── international.py  学术论文来源（OpenAlex / EuropePMC / ...）
│   │   │   │   ├── patents.py        USPTO 美国专利
│   │   │   │   ├── lens.py           Lens.org 全球专利（CN/US/EP/WO）
│   │   │   │   ├── clinical.py       ClinicalTrials.gov 临床试验
│   │   │   │   └── crossref.py       Crossref 学术元数据
│   │   │   ├── core/
│   │   │   │   ├── llm_providers.py  LLM 多后端统一管理
│   │   │   │   └── llm_config_store.py  Redis 持久化 LLM 配置
│   │   │   ├── query_builder.py      检索计划构建（关键词翻译+来源选择）
│   │   │   ├── search_engine.py      并行检索执行 + 综合评分 + 去重
│   │   │   ├── relevance_engine.py   文献评分（关键词+引用+时效）
│   │   │   ├── progressive_search.py 轮次状态机管理
│   │   │   ├── llm_summarizer.py     AI 摘要生成
│   │   │   └── profile_service.py    用户画像更新
│   │   ├── workers/
│   │   │   ├── celery_app.py         Celery 应用配置
│   │   │   └── search_tasks.py       检索/摘要/监控 Celery 任务
│   │   ├── config.py                 环境变量配置（pydantic-settings）
│   │   └── main.py                   FastAPI 应用入口
│   ├── alembic/versions/             数据库迁移文件
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── ProjectCreate.vue     创建项目（含高级搜索配置）
│   │   │   ├── ProjectView.vue       项目主页（检索进度+文献卡片+反馈）
│   │   │   └── Dashboard.vue         项目列表
│   │   ├── components/
│   │   │   ├── DocumentCard.vue      文献卡片（摘要+关键点+相关度评分）
│   │   │   └── RoundTimeline.vue     轮次进度时间轴
│   │   ├── stores/search.ts          Pinia 状态管理（轮次轮询）
│   │   └── api/client.ts             API 调用封装
│   └── Dockerfile
├── nginx/nginx.conf
├── docker-compose.yml
├── .env.example
└── docs/
    ├── dev-notes/                    每日开发日志
    └── ENGINEERING_PLAN.md           工程规划文档
```

---

## 数据源

### 学术论文

| 数据源 | 覆盖 | 国内可访问 | 说明 |
|--------|------|-----------|------|
| OpenAlex | 2.5亿+ 文献 | ✅ | 主力来源，开放数据 |
| EuropePMC | PubMed全量 | ✅ | PubMed 欧洲镜像，有完整摘要 |
| Crossref | 1.3亿+ | ✅ | 引用数据丰富 |
| Semantic Scholar | 2亿+ | ⚠️ 限速 | 默认禁用，需 API Key |
| arXiv | CS/物理预印本 | ❌ | 国内封锁，默认禁用 |
| PubMed | 生物医学 | ❌ | 国内封锁，用 EuropePMC 替代 |

### 专利

| 数据源 | 覆盖 | 说明 |
|--------|------|------|
| Lens.org | CN/US/EP/WO/JP/KR 等 90+ 国，1.6亿+ | 需配置 `LENS_API_TOKEN`（免费） |
| USPTO | 美国专利 | 免费，PatentsView API |

### 临床试验

| 数据源 | 覆盖 | 说明 |
|--------|------|------|
| ClinicalTrials.gov | 全球临床试验 | 免费，官方 API v2 |

> 通过 `.env` 的 `DISABLED_SOURCES` 变量控制禁用列表，无需改代码。

---

## 快速开始

### 前置要求

- Docker + Docker Compose
- 至少 4GB 可用内存

### 1. 克隆并配置

```bash
git clone <repo-url>
cd scholarpilot
cp .env.example .env
```

编辑 `.env`，至少填写：

```env
POSTGRES_PASSWORD=你的数据库密码
SECRET_KEY=一个长随机字符串
```

可选配置：

```env
# Lens.org 全球专利（强烈建议配置）
# 免费申请：https://www.lens.org/lens/user/subscriptions
LENS_API_TOKEN=your_token_here

# 禁用在国内无法访问的数据源
DISABLED_SOURCES=pubmed,arxiv,biorxiv,medrxiv,semantic_scholar
```

### 2. 启动服务

```bash
docker-compose up -d
```

首次启动约需 3-5 分钟（拉取镜像、构建前端）。

### 3. 配置 AI 模型

打开 `http://localhost` → 右上角设置 → 配置 LLM 提供商。

支持：
- **DeepSeek**（推荐，国内可访问，性价比高）：填入 API Key
- **Moonshot / 通义 / 等 OpenAI 兼容接口**：填入 Base URL + API Key
- **Ollama**（本地模型）：填入 `http://host.docker.internal:11434`
- **Anthropic Claude / OpenAI**：填入 API Key

### 4. 开始使用

1. 注册账号 → 新建项目
2. 填写研究方向描述（越详细越好）
3. 选择领域（可多选）
4. 可选：展开"高级搜索配置"自定义每轮参数
5. 点击创建 → 等待第1轮检索完成（约 30-60 秒）
6. 对文献评分，系统自动启动下一轮
7. 5轮结束后进入每日监控模式

---

## 常用运维命令

```bash
# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f backend    # 后端 / API 日志
docker-compose logs -f worker     # Celery 任务日志

# 后端代码改动后（有 volume 挂载，无需 rebuild）
docker-compose restart backend worker

# 前端代码改动后（无 volume 挂载，必须 rebuild）
docker-compose build frontend && docker-compose up -d frontend && docker-compose restart nginx

# 改了 .env 后（需重建+重启 nginx）
docker-compose up -d backend worker && docker-compose restart nginx

# 任务监控面板
open http://localhost:5555    # Flower（Celery 任务监控）

# ⚠️ 停服（保留数据）
docker-compose down           # 安全
docker-compose down -v        # 危险！删除所有数据库数据
```

---

## 对外共享（临时）

开发/演示期间，用 Cloudflare Quick Tunnel 快速获得公网 URL：

```bash
# 安装（Windows）
winget install cloudflare.cloudflared

# 启动隧道（保持终端窗口开着）
cloudflared tunnel --url http://localhost
# 输出：https://xxx.trycloudflare.com  ← 发给对方即可
```

> 注意：每次重启 URL 会变；关闭终端窗口服务断开。适合临时演示。

---

## 开发路线图

### dev0（当前，2026-03-29）
- ✅ 5轮渐进式检索 + AI 中文摘要
- ✅ 多数据源并行（OpenAlex / EuropePMC / Crossref / Lens.org 专利 / ClinicalTrials）
- ✅ 用户反馈驱动画像学习
- ✅ 综合评分（关键词 + 引用 + 时效）
- ✅ 每轮独立可配置（年份/语言/Top K）
- ✅ 多领域选择、跨轮去重
- ✅ Docker 一键部署

### dev1（计划）
- 万方 / 百度学术 中文数据源
- PDF 全文抓取 + 向量检索（pgvector embedding）
- 邮件通知（每日监控结果推送）
- 完善测试覆盖（Round 2–5 端到端）

### dev2（规划）
- EPO / WIPO / CNIPA 专利深度接入
- 文献关系图（引用网络可视化）
- 多用户协作 / 团队共享项目
- 多语言检索（中文直接查询）

---

## 许可证

内部研发项目，暂未开源。
