# ScholarPilot — Claude Code 项目约定

## 项目简介
面向科研人员的全领域情报检索平台。核心功能：渐进式多轮检索、AI中文摘要、用户反馈驱动画像。

## 技术栈
- 后端：FastAPI + PostgreSQL(pgvector) + Redis + Celery
- 前端：Vue 3 + Vite + Pinia + Element Plus
- 部署：Docker Compose（`docker-compose up -d` 启动全部服务）

## 开发约定

### 后端
- 所有 async 函数必须用 `asyncio`，禁止在 async 上下文中调用 sync 阻塞函数
- LLM 调用统一走 `app.services.core.llm_providers.LLMProviderManager`，不要直接调用 LLM SDK
- 数据库迁移：**不要修改** `alembic/versions/0001_initial.py`，新字段请创建新迁移文件
- Celery 任务中运行 async：使用 `_run_async()` helper（见 search_tasks.py）
- 错误处理：Fetcher 层只 `print` + `return []`，不抛异常；API 层抛 HTTPException

### 前端
- 状态管理：用 Pinia store，不要在组件里直接调用 API
- API 调用：统一走 `frontend/src/api/client.ts` 的具名导出
- 图标：Element Plus 图标全局注册，直接 `<el-icon><Setting /></el-icon>` 即可

### Git 工作流
- 分支：`feat/<功能名>` 从 `dev` 切出，完成后 PR 到 `dev`
- Commit 格式：`feat: 描述` / `fix: 描述` / `refactor: 描述`
- 不要直接推到 `main`，`main` 只接受来自 `dev` 的 PR

### 关键文件速查
```
backend/app/services/core/llm_providers.py   # LLM管理器（勿改接口）
backend/app/services/search_engine.py        # 检索引擎（协调fetchers）
backend/app/workers/search_tasks.py          # Celery主任务链
backend/app/workers/monitor_tasks.py         # 每日监控任务
backend/alembic/versions/0001_initial.py     # 初始迁移（勿改）
frontend/src/api/client.ts                   # API客户端（类型化）
frontend/src/stores/search.ts               # 搜索状态（含轮询逻辑）
```

### 验证命令
```bash
# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f backend
docker-compose logs -f worker

# API文档
open http://localhost:8000/docs

# 任务监控
open http://localhost:5555
```

## Phase 1 验收标准（当前目标）
1. `docker-compose up -d` 无报错
2. 注册→创建项目→启动第1轮检索
3. 看到10篇文档 + AI生成的中文摘要
4. 评分后自动触发第2轮
5. `/docs` 可访问所有 API 端点
