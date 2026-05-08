# sp-api · ScholarPilot HK client-only backend

[![CI](https://github.com/sstar16/scholarpilot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sstar16/scholarpilot/actions/workflows/ci.yml)

物理隔离的客户端后端，专门给 Tauri 客户端走。CN web 仍用 `backend/`，互不感知。

## 职责（最小子集）

- 数据源 fetcher 调度（14 源 OpenAlex / arXiv / PubMed / patenthub / ...）
- PDF 下载兜底（chromium 已删；客户端自己解析 binary）
- 用户 / 邀请码 / refresh token / 站点反馈 / 遥测
- SSE run_id 流（`/api/stream/runs/{run_id}`）
- 客户端版本拦截（< MIN_CLIENT_VERSION 返 426）

## 不做的

- LLM 调用（全部在客户端 BYOK）
- 检索 round / scoring / summary 编排（客户端 ScorePhase / SummaryPhase）
- harness / hooks / skills / knowledge graph
- 浏览器 fallback PDF（playwright 已删，资源紧张的 4G HK 机不背）
- PDF 解析（PyMuPDF 已删，客户端 PyMuPDF 解析 binary）

## 部署 SOP（HK，2026-05-08+）

### 自动化（推荐）

```bash
# 本机 D:/AI/scholarpilot-dev 跑（已配 SSH 免密）
bash scripts/deploy-sp-api-hk.sh             # 部署
bash scripts/deploy-sp-api-hk.sh --dry-run   # 演练
bash scripts/deploy-sp-api-hk.sh --rollback  # 回滚到 sp-api-pinned-tag

# Windows PowerShell 版
pwsh scripts/deploy-sp-api-hk.ps1
```

脚本会：rsync 推 sp-api/ + compose + scripts → docker compose up --build → 等 healthy → alembic upgrade head → 烟测 /health + /api/fetcher/sources → 本地打 deploy tag。

### 手工 SOP（首次或 debug）

```bash
# 1. 上传代码
ssh admin@HK
cd /opt/scholarpilot && git fetch && git pull origin main

# 2. 配 env（首次）
cp sp-api/.env.example .env.sp-api
# 编辑：POSTGRES_PASSWORD / SECRET_KEY（新生成）/ CLOUDFLARE_TUNNEL_TOKEN
# 共享：LENS_API_TOKEN / EPO_CONSUMER_KEY/SECRET / PATENTHUB_API_TOKEN / TELEGRAM_*

# 3. 起容器
docker compose -f docker-compose.sp-api.yml --env-file .env.sp-api up -d

# 4. 验证
docker exec sp-api-postgres-1 psql -U urip urip -c '\dt'   # 期 7 张表
docker exec sp-api-backend-1 curl -s localhost:8000/health  # 期 200，无 llm 字段
docker exec sp-api-backend-1 pytest tests/ -q              # 期全绿

# 5. admin 引导
docker exec -it sp-api-backend-1 python scripts/create_admin.py admin@scholarpilot.top
# 登录后到 /api/admin/invitations 生成首批邀请码

# 6. CF Tunnel 切 hostname
# CF Dashboard → tunnel sp-api-v2 → Published application routes →
# 加 api.scholarpilot.top → http://sp-api-backend:8000
# 同步删除旧 tunnel sp-api 的同名 route
```

## 本地 dev

```bash
cd sp-api
python -m venv venv
.\venv\Scripts\Activate.ps1     # Windows
pip install -r requirements.txt

# 启动需要 postgres + redis；可临时连本地 docker
alembic upgrade head            # 跑 migration
uvicorn app.main:app --reload   # 本地 :8000
pytest -q                        # 单测
```

## 文件树速览

```
sp-api/
├── app/
│   ├── main.py              # FastAPI 入口（含 ClientMetaMiddleware 426 拦截）
│   ├── config.py            # Settings — 删了所有 LLM 字段
│   ├── database.py
│   ├── dependencies.py
│   ├── api/                 # auth / admin / fetcher / fulltext / stream / ...
│   ├── models/              # 7 张表 ORM
│   ├── schemas/
│   ├── middleware/
│   ├── services/
│   │   ├── fetchers/        # 14 个 fetcher（不含 LLM 依赖）
│   │   ├── fulltext_service.py  # 删 chromium fallback + extract_text stub
│   │   └── patenthub_budget.py  # derive_budget_key（无 round 表）
│   └── workers/
│       ├── celery_app.py    # 仅 fulltext / import / devtools 三 queue
│       ├── fulltext_tasks.py
│       ├── import_tasks.py  # 接客户端预解析的元数据
│       └── devtools_tasks.py
├── alembic/
│   └── versions/
│       └── 0001_sp_api_initial.py  # 7 张表全新 schema
├── tests/                    # ≥16 测试
├── data/pdfs/                # PDF 临时归档
├── Dockerfile               # 不装 chromium，~700MB 镜像
├── requirements.txt
├── .env.example
└── pyproject.toml
```
