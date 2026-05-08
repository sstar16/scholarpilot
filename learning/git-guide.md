# ScholarPilot 团队开发指南

> 适用人员：2-3人本科生团队，使用 Git + Claude Code 协作开发
> 最后更新：2026-03-24

---

## 目录

1. [第一天：仓库初始化](#1-第一天仓库初始化)
2. [分支策略](#2-分支策略)
3. [Commit 规范](#3-commit-规范)
4. [项目文件结构](#4-项目文件结构)
5. [三个必须有的文件](#5-三个必须有的文件)
6. [共享文档：Notion 使用方式](#6-共享文档notion-使用方式)
7. [分工与防冲突原则](#7-分工与防冲突原则)
8. [Claude Code 使用指南](#8-claude-code-使用指南)
9. [每日工作流（完整版）](#9-每日工作流完整版)
10. [常见问题处理](#10-常见问题处理)
11. [第一天操作清单](#11-第一天操作清单)

---

## 1. 第一天：仓库初始化

**由一个人操作，其他人等邀请链接。**

### 1.1 本地初始化

```bash
mkdir scholarpilot && cd scholarpilot
git init
```

### 1.2 创建 `.gitignore`

在项目根目录创建 `.gitignore`，内容如下：

```
# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/
*.egg-info/
dist/
build/

# 环境变量（API Key 绝对不能提交！）
.env
.env.local
*.env

# 数据库文件
*.db
*.sqlite
data/

# IDE
.vscode/
.idea/
*.swp
*.swo

# 系统文件
.DS_Store
Thumbs.db

# 日志
logs/
*.log

# Claude Code 缓存
.claude/
```

### 1.3 推送到 GitHub

```bash
git add .gitignore
git commit -m "init: project scaffold"

# 去 GitHub 网页新建仓库（选 Private），然后执行：
git remote add origin https://github.com/你的用户名/scholarpilot.git
git branch -M main
git push -u origin main
```

### 1.4 邀请队友

GitHub 仓库页面 → Settings → Collaborators → Add people
把队友的 GitHub 用户名加进来，权限选 **Write**。

---

## 2. 分支策略

### 2.1 三层分支结构

```
main    ──●─────────────────●──────────────●──
           ↑                ↑              ↑
           v0.1          v0.2           v0.3
           （每周五 PR 合并一次，永远可运行）

dev     ──●──●──●──────────●──●──●────────●──
              ↑            ↑
         （每天下班前合并各自分支到这里）

feat/*  ──────●──●──●──↗        （个人开发分支）
```

- `main`：永远可以运行，只接受从 dev 来的 Pull Request，**不直接提交**
- `dev`：日常集成，每天下班前把自己的 feat 分支合进来
- `feat/xxx`：每个功能/模块一个分支，个人工作区

### 2.2 分支命名规范

```
feat/pipeline-fetcher      新功能
feat/llm-summarizer
fix/pubmed-timeout         修 bug
fix/sse-disconnect
refactor/relevance-scorer  重构
```

### 2.3 每日标准操作

```bash
# ── 早上开始工作 ──────────────────────────────────
git checkout dev
git pull origin dev                    # 先拉最新，防止冲突

git checkout -b feat/你的功能名         # 从 dev 切出自己的分支

# ── 写代码过程中，阶段性提交 ──────────────────────
git add .
git commit -m "feat: PubMed fetcher 基础搜索完成"
git push origin feat/你的功能名        # 推到远端，防止本地丢失

# ── 晚上下班前，合并到 dev ────────────────────────
git checkout dev
git pull origin dev                    # 再拉一次
git merge feat/你的功能名
git push origin dev

# ── 遇到冲突时（按提示解决后）────────────────────
git add .
git commit -m "merge: 解决与人B的 database.py 冲突"
git push origin dev
```

### 2.4 每周五：dev → main

不要直接 merge，在 **GitHub 网页**发 Pull Request：
1. 点击 Pull requests → New pull request
2. base: `main` ← compare: `dev`
3. 写本周完成了什么（3句话就够）
4. 至少一个队友点 Approve
5. Merge

---

## 3. Commit 规范

### 3.1 格式

```
类型: 简短描述（不超过 50 个字）
```

### 3.2 类型说明

| 类型 | 含义 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat: PubMed fetcher 支持时间范围过滤` |
| `fix` | 修 bug | `fix: Semantic Scholar API 超时从 10s 改为 30s` |
| `refactor` | 重构 | `refactor: LLMQueryParser 提取 _safe_parse_json` |
| `test` | 加测试 | `test: 补充 parse 方法的边界用例` |
| `docs` | 改文档 | `docs: 更新 README 添加环境配置说明` |
| `chore` | 杂事 | `chore: 添加 pymupdf 到 requirements.txt` |

### 3.3 禁止写的 commit 信息

```bash
# ❌ 这些没有任何意义
git commit -m "fix"
git commit -m "update"
git commit -m "修改了一些东西"
git commit -m "aaa"

# ✅ 应该写成这样
git commit -m "fix: PubMed XML 解析空摘要时 KeyError"
git commit -m "feat: 查询解析新增 en_boolean_query 字段"
```

---

## 4. 项目文件结构

```
scholarpilot/
├── .env.example              ← API Key 模板（提交，不提交 .env）
├── .gitignore
├── README.md
├── requirements.txt
├── CLAUDE.md                 ← 给 Claude Code 的项目背景（重要！）
│
├── docs/
│   ├── setup.md              ← 环境配置步骤
│   ├── api.md                ← 接口文档
│   └── decisions.md          ← 技术决策记录
│
├── services/                 ← 后端核心逻辑
│   ├── __init__.py
│   ├── llm_parser.py
│   ├── llm_providers.py
│   ├── database.py
│   ├── task_manager.py
│   ├── relevance_scorer.py
│   └── fetchers/
│       ├── __init__.py
│       ├── pubmed.py
│       ├── semantic_scholar.py
│       └── arxiv.py
│
├── api/
│   ├── __init__.py
│   └── routes.py
│
├── frontend/
│   └── src/
│
└── tests/
    ├── test_parser.py
    ├── test_fetchers.py
    └── test_pipeline.py
```

立刻创建目录结构：

```bash
mkdir -p docs services/fetchers api frontend/src tests
touch docs/api.md docs/setup.md docs/decisions.md
touch services/fetchers/__init__.py
touch api/__init__.py api/routes.py
touch tests/test_parser.py tests/test_fetchers.py
touch .env.example CLAUDE.md README.md
```

---

## 5. 三个必须有的文件

### 5.1 `.env.example`

```bash
# 复制此文件为 .env，填入真实值
# 真实的 .env 绝对不要提交到 git！

# LLM
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here

# 数据源
SEMANTIC_SCHOLAR_API_KEY=your_key_here

# 数据库
DB_PATH=./data/scholarpilot.db

# 日志
LOG_LEVEL=INFO
```

### 5.2 `docs/setup.md`

```markdown
# 环境配置

## 要求
- Python 3.11+
- Node.js 18+（前端）
- Claude Code（见下方安装）

## 后端配置

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入你的 API Key
python -m pytest tests/        # 跑通说明环境 OK
```

## 需要申请的 API Key

| 服务 | 地址 | 费用 |
|------|------|------|
| Anthropic | https://console.anthropic.com | 按量付费 |
| OpenAI（embedding 用）| https://platform.openai.com | 按量付费 |
| Semantic Scholar | https://www.semanticscholar.org/product/api | 免费 |

## 常见问题

- **import 报错**：确认 `.venv` 已激活（命令行前有 `(.venv)` 标志）
- **API 报 401**：检查 `.env` 文件是否存在且 Key 正确
- **数据库报错**：确认 `data/` 目录存在，`mkdir -p data`
```

### 5.3 `docs/decisions.md`

每次做重要技术选择就在这里记一条，格式如下：

```markdown
# 技术决策记录

## 2025-03-24 | 向量数据库选 ChromaDB
**决定**：MVP 阶段用 ChromaDB
**原因**：纯 Python，无需独立进程，pip 一行安装
**代价**：超过 10 万条文献后可能需要迁移到 Qdrant
**负责人**：XXX

## 2025-03-24 | LLM 摘要用 claude-haiku
**决定**：摘要生成用 haiku，查询解析用 sonnet
**原因**：haiku 摘要质量够用，成本是 sonnet 的 1/5
**负责人**：XXX
```

---

## 6. 共享文档：Notion 使用方式

GitHub 管代码，Notion 管一切非代码内容。免费版完全够用。

### 6.1 Notion 页面结构

```
ScholarPilot/
├── 每周站会记录
├── 任务看板（Database）
├── API 接口草稿
├── 用户反馈记录
└── 遇到的坑与解决方案
```

### 6.2 任务看板字段

每张卡片只需要 4 个字段：

| 字段 | 说明 |
|------|------|
| 任务名 | 一句话描述，如「实现 PubMed 时间范围过滤」 |
| 负责人 | 谁来做 |
| 截止日 | 具体到天 |
| 状态 | 待做 / 进行中 / 完成 / 卡住了 |

### 6.3 每周站会（10 分钟，每周一）

每人说 3 件事：
1. 上周完成了什么
2. 本周计划做什么
3. 有什么卡住了，需要帮助

记录在 Notion 的「每周站会记录」页面。

---

## 7. 分工与防冲突原则

### 7.1 按模块分工

| 人员 | 主要负责文件 | 说明 |
|------|------------|------|
| 人 A（后端/数据） | `services/fetchers/` `services/relevance_scorer.py` | 数据抓取和初筛 |
| 人 B（后端/AI） | `services/llm_parser.py` `services/llm_providers.py` | LLM 调用和摘要 |
| 人 C（前端/串联） | `frontend/` `api/routes.py` `services/database.py` | 界面和接口 |

### 7.2 共用文件的规则

以下文件多人会碰到，改之前在微信群说一声：

- `requirements.txt`：加新依赖前说一句，改完立刻 push
- `services/__init__.py`：只有加新模块时才改
- `api/routes.py`：前后端对接时协商后再改
- `CLAUDE.md`：任何人发现信息过时都可以更新，更新后通知大家

---

## 8. Claude Code 使用指南

### 8.1 安装

```bash
npm install -g @anthropic-ai/claude-code
```

在项目根目录运行：

```bash
claude
```

### 8.2 最重要的文件：`CLAUDE.md`

这是 Claude Code 的「项目说明书」。每次 Claude Code 启动都会读这个文件。
写得越清楚，生成的代码越符合你的项目风格。

以下是 ScholarPilot 的 `CLAUDE.md` 模板，直接复制使用：

```markdown
# ScholarPilot 项目背景

## 产品定位
AI 驱动的科研情报追踪平台。核心流程：
用户输入研究描述 → LLM 解析为检索参数 → 并发检索多个学术数据库
→ 相关性排序 → 全文获取 → LLM 生成摘要 → SSE 流式推送前端

## 技术栈
- 后端：Python 3.11, FastAPI, asyncio, httpx, aiosqlite
- 向量：ChromaDB, text-embedding-3-small
- 前端：React 18, Tailwind CSS
- LLM：Anthropic Claude API（通过 LLMProviderManager 统一调用）

## 已有代码（不要改动这些文件的对外接口）
- `services/task_manager.py`：异步任务队列，TaskManager 和 TaskStatus，可直接用
- `services/database.py`：DatabaseManager，基于 aiosqlite，可加新表但不改现有表
- `services/relevance_scorer.py`：关键词相关性评分，RelevanceScorer，可直接用
- `services/llm_providers.py`：LLM 调用封装，LLMProviderManager，不要改

## 代码风格（严格遵守）
- 所有 IO 操作必须是 async/await，不用同步阻塞调用
- 数据源请求失败时用 return_exceptions=True 降级，不能让整条管道崩溃
- 所有函数返回的 paper 对象统一格式：
  {"title": str, "abstract": str, "url": str, "source": str,
   "year": int, "authors": str, "doi": str | None}
- 不用 print 调试，用 logging.getLogger(__name__)
- 函数要有 docstring，说明参数和返回值

## 目录约定
- 数据源抓取代码放 services/fetchers/
- FastAPI 路由放 api/routes.py
- 测试放 tests/，文件名 test_模块名.py

## 当前 Sprint 目标（Week 1）
实现从关键词输入到拿到文献元数据列表的完整管道：
PubMed + Semantic Scholar + arXiv 三个数据源并发检索并返回统一格式
```

### 8.3 高效使用 Claude Code 的提示词模板

**开始一个新功能时：**

```
请帮我实现 services/fetchers/pubmed.py 中的 PubMedFetcher 类。

要求：
- search(keywords: list[str], years: int) -> list[dict] 方法
- 返回格式参考 CLAUDE.md 中的 paper 统一格式
- 使用 NCBI E-utilities API（esearch + efetch）
- 失败时返回空列表，不抛异常
- 加上简单的测试用例放在 tests/test_fetchers.py
```

**调试报错时：**

```
这个函数报错了，错误信息如下：
[粘贴完整报错]

相关代码：
[粘贴出错的函数]

请帮我找出原因并修复，同时说明为什么会出现这个问题。
```

**代码审查时：**

```
请 review 这段代码，重点检查：
1. 有没有可能抛出未处理的异常
2. async/await 用法是否正确
3. 有没有明显的性能问题

[粘贴代码]
```

**写完一个模块后让 Claude 生成测试：**

```
请为 services/fetchers/pubmed.py 中的 PubMedFetcher 写单元测试。
使用 pytest + pytest-asyncio。
用 httpx.MockTransport 模拟 API 响应，不要真实发请求。
```

### 8.4 Claude Code 的工作模式

Claude Code 有两种使用方式，根据任务选择：

**交互模式**（日常使用）：直接在终端输入需求，Claude Code 会修改文件、运行命令。适合：实现新功能、调试 bug、重构代码。

```bash
cd scholarpilot
claude
# 然后直接输入：「帮我实现 PubMed fetcher」
```

**文件模式**（复杂任务）：先把需求写成 markdown 文件，再让 Claude Code 读取执行。适合：实现一整个模块、多文件联动的修改。

```bash
# 先写好 task.md 描述清楚要做什么
claude "请读取 task.md 并按照要求实现代码"
```

### 8.5 Claude Code 使用的关键原则

**原则一：给上下文，不给猜测空间**

```
# ❌ 差的提示
「帮我写一个 fetcher」

# ✅ 好的提示
「帮我在 services/fetchers/semantic_scholar.py 里实现
SemanticScholarFetcher 类，参考 services/fetchers/pubmed.py
的结构，使用 https://api.semanticscholar.org/graph/v1/paper/search 接口，
返回格式和 PubMedFetcher 一致」
```

**原则二：一次只做一件事**

```
# ❌ 一次要求太多
「帮我实现三个 fetcher，加上排序逻辑，再写测试，再接到路由里」

# ✅ 分步来
第一步：「实现 SemanticScholarFetcher」→ 确认没问题
第二步：「现在给它写测试」→ 确认没问题
第三步：「把它接入 pipeline.py」
```

**原则三：生成后立刻验证**

Claude Code 生成代码后，立刻运行它：

```bash
# 跑测试
python -m pytest tests/test_fetchers.py -v

# 快速验证单个函数
python -c "
import asyncio
from services.fetchers.pubmed import PubMedFetcher
async def test():
    f = PubMedFetcher()
    results = await f.search(['stem cell', 'dental pulp'], years=3)
    print(f'拿到 {len(results)} 条，第一条：{results[0][\"title\"] if results else \"空\"}')
asyncio.run(test())
"
```

**原则四：让 Claude Code 解释它写的代码**

```
「刚才写的 _parse_xml 方法我看不太懂，请逐行解释一下」
```

不理解的代码不要提交，出了 bug 自己也没法改。

**原则五：用 `/clear` 管理上下文**

Claude Code 的对话窗口有 token 上限。写完一个功能模块后，输入 `/clear` 清空上下文，再开始下一个模块。不清除的话后面的输出质量会变差。

```bash
# 完成一个模块后
/clear
# 重新开始，Claude Code 会重新读 CLAUDE.md
```

### 8.6 每周的 Claude Code 使用节奏

```
周一：用 Claude Code 搭本周要实现模块的骨架（类定义、函数签名）
周二-周四：逐个函数实现，边写边测
周五：用 Claude Code 帮忙写本周新增代码的测试，准备 PR
```

### 8.7 哪些事不要交给 Claude Code

| 不要交给 Claude Code | 原因 |
|---------------------|------|
| 决定用哪个技术方案 | 它会给出答案，但不承担后果，你需要自己想清楚 |
| 直接把生成的代码推到 main | 必须人工 review + 跑测试 |
| 让它修改 `.env` 文件 | API Key 安全问题 |
| 实现你完全看不懂的算法 | 出 bug 自己改不了 |

---

## 9. 每日工作流（完整版）

```bash
# ── 早上（10 分钟）────────────────────────────────────
git checkout dev
git pull origin dev

# 看看昨天队友提交了什么
git log origin/dev --oneline -10

# 切到自己的分支开始工作
git checkout feat/你的功能名
# 或者开始新功能
git checkout -b feat/新功能名

# ── 开发中（随时）────────────────────────────────────
# 打开 Claude Code
claude

# 阶段性提交（功能点完成就提交，别等到晚上一次提交）
git add .
git commit -m "feat: 完成 PubMed XML 解析"
git push origin feat/你的功能名    # 推到远端备份

# ── 晚上下班前（15 分钟）─────────────────────────────
# 跑一遍测试，确保没有破坏现有功能
python -m pytest tests/ -v

# 合并到 dev
git checkout dev
git pull origin dev
git merge feat/你的功能名

# 如果有冲突：
# 1. 打开冲突文件，找到 <<<<<<< 标记
# 2. 手动决定保留哪段代码
# 3. git add . && git commit -m "merge: 解决冲突"

git push origin dev

# 在微信群里说一句：「今天的代码推好了，完成了 xxx」
```

---

## 10. 常见问题处理

### 不小心提交了 `.env` 文件

```bash
# 立刻执行：
git rm --cached .env
git commit -m "fix: 从版本控制中移除 .env"
git push

# 然后：去 Anthropic/OpenAI 控制台把泄露的 Key 撤销，重新生成一个
# 这一步必须做！已经推送的 Key 要假设已经泄露
```

### 合并冲突解决流程

```bash
git merge feat/别人的分支
# 报 CONFLICT 时：

# 1. 查看哪些文件冲突
git status

# 2. 打开冲突文件，长这样：
# <<<<<<< HEAD（你的代码）
# your code
# =======
# their code
# >>>>>>> feat/别人的分支（对方的代码）

# 3. 手动编辑，保留正确的版本，删掉标记符号

# 4. 解决完后
git add .
git commit -m "merge: 解决 database.py 中的冲突"
```

### 搞坏了代码想撤回

```bash
# 撤回最近一次 commit（代码改动保留，只撤 commit）
git reset --soft HEAD~1

# 彻底丢弃最近一次 commit 的所有改动（谨慎！）
git reset --hard HEAD~1

# 只撤回某个文件到上次 commit 的状态
git checkout HEAD -- services/database.py
```

### 误删了文件

```bash
git checkout HEAD -- 文件路径
```

---

## 11. 第一天操作清单

按顺序执行，每项完成后打勾：

```
□ 1. 建 GitHub 仓库，推送 .gitignore
□ 2. 把现有代码放入 services/ 目录并提交
□ 3. 创建 .env.example、docs/setup.md、CLAUDE.md
□ 4. 邀请队友为 Collaborator
□ 5. 每人 clone 仓库，按 setup.md 配好环境
□ 6. 每人运行 python -m pytest tests/ 确认环境 OK
□ 7. 安装 Claude Code：npm install -g @anthropic-ai/claude-code
□ 8. 在项目目录运行 claude，确认能正常启动
□ 9. 建 Notion workspace，建任务看板，分配 Week 1 任务
□ 10. 每人建自己的 feat/ 分支，开始写第一行代码
```

第 5-6 步是验收门槛：队友能独立按文档把环境跑起来，后续才不会卡在低级问题上。

---

*本文档随项目迭代更新。发现内容过时请直接修改并提交 `docs: 更新 gitteach.md`。*
