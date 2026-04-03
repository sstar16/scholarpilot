# ScholarPilot 版本更新说明

## dev0 → 最新版本 (v1.9) 变更总览

> **dev0** (2026-03-29): MVP 首版发布
> **v1.9** (2026-04-04): 完整 AI Agent 驱动版本

**核心数据**: 30 次提交 | 136 个文件变更 | +18,054 行代码

---

## 一、架构级变更

| 维度 | dev0 | 最新版本 |
|------|------|----------|
| 检索流程 | 固定 5 轮渐进式检索 | 开放式轮次，用户自主控制 |
| 反馈系统 | 每轮独立反馈表 | 4 桶分类系统（跨轮次） |
| 文档评分 | 传统规则（关键词+引用+时效） | LLM Agent 全文智能评分 |
| 关键词优化 | 单次批量 LLM 调用 | 按数据源并行 LLM 优化 |
| 前端交互 | 静态时间线 + 批量反馈 | 实时流式推送 + 桶侧边栏 |
| Agent 框架 | 无 | 完整编排（工具注册/Hook/技能/Agent） |
| LLM 管理 | 分散实例化 | 统一单例 + Redis 60s 缓存 |
| 数据源 | 11 个 | 15 个（新增 SooPat/EPO/DBLP/百度学术） |

---

## 二、新增功能详解

### 2.1 AI Agent 框架 (Phase 1.5 - 1.7)

全新的 Agent 驱动架构，让检索更智能：

- **QueryPlanAgent** — LLM 驱动的搜索策略规划，自动生成按数据源优化的关键词
- **ScoringAgent** — 全文 LLM 评分，结合用户分类历史作为正例参考
- **MemoryAgent** — 用户画像学习，根据反馈持续优化后续检索
- **DeepDiveAgent** — 对感兴趣的文献进行深度探索

**新增技能 (Skills)**:
- `deep_dive` — 深入研究特定发现
- `gap_finder` — 识别研究空白
- `trend_spotter` — 发现研究趋势

### 2.2 四桶分类系统 (Phase 1.8)

取代旧的每轮反馈机制，提供更灵活的文献管理：

| 桶 | 含义 | 作用 |
|----|------|------|
| very_relevant | 非常相关 | 核心参考文献 |
| relevant | 相关 | 值得关注 |
| uncertain | 不确定 | 待进一步判断 |
| irrelevant | 不相关 | 排除噪音 |

- 支持拖拽分类
- 跨轮次管理，文献分类结果累积
- 分类结果反馈到 Memory Agent，持续优化检索精度

### 2.3 开放式轮次

- 不再限制固定 5 轮，用户可自由发起任意数量的检索轮次
- 每轮检索前可预览和编辑各数据源关键词
- 两阶段流程：`prepare → confirm-keywords → execute`

### 2.4 实时流式推送 (SSE)

- 检索过程实时可见：逐篇文献流式推送到前端
- 粒子搜索动画，提升等待体验
- 按数据源显示独立进度条

### 2.5 新增数据源

| 数据源 | 类型 | 说明 |
|--------|------|------|
| SooPat | 中国专利 | 自动登录 + 专利检索 |
| EPO OPS | 欧洲专利 | 欧洲专利局官方 API |
| DBLP | 计算机文献 | 计算机科学文献库 |
| 百度学术 | 中文学术 | 中文学术搜索增强 |

### 2.6 LLM 统一管理 (Phase 1.9)

- 全局单例 `get_llm_manager()`，消除 12 处分散实例化
- Redis 缓存配置（60s TTL），减少重复加载
- 支持 6 个提供商：Ollama / OpenAI / Anthropic / DeepSeek / Moonshot / jiekou.ai

---

## 三、前端 UI 重大改进

### 新增组件
- **BucketSidebar** — 四桶侧边栏，支持拖拽分类
- **KeywordConfirmPanel** — 按数据源确认/编辑关键词
- **DocumentStream** — 实时文献流式展示
- **SearchingAnimation** — 粒子搜索动画
- **SourceProgressBar** — 数据源进度可视化
- **MonitoringPanel** — 监控任务管理面板
- **RoundHistory** — 动态轮次历史
- **AgentPlanView** — Agent 规划可视化
- **CutoffSlider** — 相关度斩杀线配置

### 核心页面重写
- **ProjectView** — 全面重构（500 → 1163 行），集成桶系统和流式推送
- **DocumentCard** — 增强交互，支持评分展示和桶分类操作
- **Dashboard** — 新增高级筛选功能

---

## 四、性能与稳定性优化

- 消除 N+1 查询问题（反馈查询 O(3N) → O(3)）
- 修复长时间 LLM 调用后 ORM 对象脱离 session 的崩溃
- 各数据源并行检索，整体速度提升
- 错误分层处理：Fetcher 静默降级 / API 抛异常 / Celery 更新状态

---

## 五、数据库迁移

从 dev0 升级需要执行以下迁移：

| 迁移文件 | 内容 |
|----------|------|
| `0004_add_source_stats.py` | 数据源统计表 |
| `0005_scoring_agent_columns.py` | Agent 评分相关字段 |
| `0006_open_loop_buckets.py` | 四桶分类表 + 旧反馈数据迁移 |

---

## 六、升级注意事项

1. **数据库迁移必须执行** — 新增了 3 个迁移文件
2. **环境变量更新** — 检查 `.env.example` 获取新增配置项
3. **前端必须 rebuild** — `docker-compose build frontend`
4. **后端需要 rebuild** — 新增了依赖包，需 `docker-compose build backend worker beat`
5. **旧反馈数据自动迁移** — `0006` 迁移会将旧 feedback 表数据转换为桶分类

```bash
# 推荐升级步骤
git pull origin main
cp .env.example .env.new   # 对比新增配置项并合并到 .env
docker-compose build
docker-compose up -d
docker-compose logs -f backend  # 确认迁移成功
```
