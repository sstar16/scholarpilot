# ScholarPilot 团队开发指南
# Git + Claude Code 完整手册

> 适用人员：2-3 人本科生团队，使用 Git + Claude Code 协作开发  
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
8. [Claude Code 完整使用指南](#8-claude-code-完整使用指南)
   - 8.1 安装与启动
   - 8.2 最重要的文件：CLAUDE.md
   - 8.3 三种工作模式
   - 8.4 提示词模板库
   - 8.5 五条核心原则
   - 8.6 上下文管理：/clear 的正确用法
   - 8.7 每周节奏
   - 8.8 三人团队协作节奏
   - 8.9 哪些事不要交给 Claude Code
   - 8.10 实战经验：最容易犯的错
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
3. 写本周完成了什么（3 句话就够）
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
├── CLAUDE.md                 ← 给 Claude Code 的项目背景（核心！每人都要读）
│
├── docs/
│   ├── setup.md              ← 环境配置步骤
│   ├── api.md                ← 接口文档
│   ├── decisions.md          ← 技术决策记录
│   └── claudeteach.md        ← 本文件
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

​```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入你的 API Key
python -m pytest tests/        # 跑通说明环境 OK
​```

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

每次做重要技术选择就在这里记一条：

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

以下文件多人会碰到，**改之前在微信群说一声**：

- `requirements.txt`：加新依赖前说一句，改完立刻 push
- `services/__init__.py`：只有加新模块时才改
- `api/routes.py`：前后端对接时协商后再改
- `CLAUDE.md`：任何人发现信息过时都可以更新，更新后通知大家

### 7.3 串行优于并行的原则

三人同时开发最容易出的问题：三个人各自让 Claude Code 生成同一类代码（比如都在写 database 操作），结果写法完全不一样，合并时乱成一团。

**正确做法**：人 A 先让 Claude Code 生成 `DatabaseManager` 扩展，合入 dev 之后，其他人再基于这份代码继续写自己的部分。**共用基础设施要等第一个人写完再接**。

---

## 8. Claude Code 完整使用指南

### 8.1 安装与启动

```bash
# 安装（全局，只需装一次）
npm install -g @anthropic-ai/claude-code

# 在项目根目录启动
cd scholarpilot
claude
```

首次启动会要求登录 Anthropic 账号，按提示操作即可。

**确认能用**：启动后输入「你好，请列出当前目录下的文件」，它能列出文件说明安装成功。

---

### 8.2 最重要的文件：`CLAUDE.md`

这是 Claude Code 的「项目说明书」。**每次 Claude Code 启动时都会自动读取这个文件**，不需要你每次重新解释项目背景。写得越清楚，生成的代码越符合你的项目风格。

**投入产出比**：写 `CLAUDE.md` 花 1 小时，能省掉之后 20 次重复解释背景的时间。每次 Claude Code 生成的代码风格不对（比如用了同步 `requests` 而不是 `async httpx`），第一反应不是重新提问，而是去 `CLAUDE.md` 里补充这条约束。

以下是 ScholarPilot 的 `CLAUDE.md` 完整模板，直接复制到项目根目录：

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
- 所有 IO 操作必须是 async/await，禁止同步阻塞调用
- 数据源请求失败时用 return_exceptions=True 降级，不能让整条管道崩溃
- 所有函数返回的 paper 对象统一格式：
  {"title": str, "abstract": str, "url": str, "source": str,
   "year": int, "authors": str, "doi": str | None}
- 禁止用 print 调试，用 logging.getLogger(__name__)
- 每个函数必须有 docstring，说明参数类型和返回值
- 异常要用具体类型捕获，禁止裸 except:

## 目录约定
- 数据源抓取代码放 services/fetchers/
- FastAPI 路由放 api/routes.py
- 测试放 tests/，文件名 test_模块名.py

## 当前 Sprint 目标（每周一更新）
Week 1：PubMed + Semantic Scholar + arXiv 三源并发检索，返回统一格式
Week 2：全文获取 + LLM 摘要生成 + SSE 推送
```

**`CLAUDE.md` 需要随项目进度更新的字段**：每周一站会后，把「当前 Sprint 目标」更新成本周目标，Claude Code 会自动聚焦在当前任务上。

---

### 8.3 三种工作模式

根据任务类型选择不同的使用方式：

#### 模式一：交互模式（日常主力）

直接在终端输入需求，Claude Code 会读取文件、写代码、运行命令、报告结果。

```bash
cd scholarpilot
claude
# 然后直接打字：「帮我实现 PubMed fetcher 的时间范围过滤」
```

**适合**：实现新功能、调试 bug、重构代码、问技术问题。

#### 模式二：任务文件模式（复杂任务）

先把需求写成 markdown 文件，再让 Claude Code 读取执行。适合一次性要修改多个文件的大任务。

```bash
# 先写 task.md，描述清楚要做什么、涉及哪些文件
cat > task.md << EOF
## 任务：实现完整的数据抓取管道

### 要创建的文件
1. services/fetchers/pubmed.py - PubMedFetcher 类
2. services/fetchers/semantic_scholar.py - SemanticScholarFetcher 类
3. services/fetchers/arxiv.py - ArXivFetcher 类
4. services/pipeline.py - 三源并发调用入口

### 统一返回格式
见 CLAUDE.md 中的 paper 对象格式

### 注意事项
- 每个 fetcher 失败时返回空列表，不抛异常
- 用 asyncio.gather(return_exceptions=True) 并发调用
EOF

claude "请读取 task.md 并按照要求实现代码"
```

#### 模式三：单次命令模式（快速任务）

不进入交互，直接执行一条指令。

```bash
# 快速生成测试文件
claude "为 services/fetchers/pubmed.py 生成 pytest 单元测试，
保存到 tests/test_pubmed.py，用 httpx.MockTransport 模拟响应"

# 快速解释某段代码
claude "解释 services/relevance_scorer.py 中 _text_match_score 的算法逻辑"

# 快速检查某个文件的问题
claude "检查 services/llm_parser.py 有没有未处理的异常或潜在 bug"
```

---

### 8.4 提示词模板库

把这些模板存下来，遇到对应场景直接复制修改。

#### 开始实现新功能

```
请帮我实现 services/fetchers/pubmed.py 中的 PubMedFetcher 类。

具体要求：
- search(keywords: list[str], years: int = 5) -> list[dict] 方法
- 返回格式严格遵守 CLAUDE.md 中的 paper 统一格式
- 使用 NCBI E-utilities API（先 esearch 拿 ID 列表，再 efetch 拿详情）
- 任何网络错误或解析错误都返回空列表，不抛异常
- 请同时在 tests/test_fetchers.py 写一个验证函数签名和返回格式的测试
```

#### 调试报错

```
这个函数报错了，请帮我找出原因并修复。

报错信息：
[粘贴完整的 Traceback，从 Traceback (most recent call last) 开始]

出错的代码：
[粘贴出错的函数，包括函数签名]

我的理解是 [你觉得哪里有问题]，但不确定。
请解释为什么会出现这个错误，并给出修复方案。
```

#### 请求代码审查

```
请 review 这段代码，我是新手，重点帮我检查：
1. 有没有可能在某些输入下抛出未处理的异常
2. async/await 的用法有没有问题（有没有在 async 函数里用了同步阻塞调用）
3. 返回值类型和 CLAUDE.md 里规定的格式是否一致
4. 有没有明显的性能问题

[粘贴代码]
```

#### 生成测试

```
请为 services/fetchers/pubmed.py 中的 PubMedFetcher 写完整单元测试。

要求：
- 使用 pytest + pytest-asyncio
- 用 respx 或 httpx.MockTransport 模拟 HTTP 响应，不发真实请求
- 覆盖以下场景：
  1. 正常返回 3 条结果
  2. API 返回空列表
  3. 网络超时
  4. API 返回格式异常（缺少字段）
- 每个测试函数写注释说明测试什么场景
```

#### 重构已有代码

```
请重构这个函数，目标是让它更好维护，不要改变它的对外行为。

当前代码：
[粘贴代码]

主要问题（我自己发现的）：
- [描述你觉得哪里写得不好]

重构后请说明改了什么，为什么这样改更好。
```

#### 让 Claude Code 解释它生成的代码

```
你刚才写的 _parse_xml 方法我看不太懂，请逐行解释：
1. 每行代码在做什么
2. 为什么要这样写，有没有其他写法
3. 如果 XML 里某个字段不存在会怎样

[粘贴那段代码]
```

#### 接口对齐（前后端联调）

```
我是前端（人C），需要对接后端的 /api/search/stream 接口。

请根据 api/routes.py 中的实现，告诉我：
1. 请求格式是什么（method、path、body 字段）
2. SSE 推送的每条消息格式是什么（type 字段有哪些值，各自的数据结构）
3. 错误情况下返回什么

然后帮我写一个 React hook：usePaperSearch(query, projectDesc)
处理 SSE 连接、数据累积和错误状态。
```

---

### 8.5 五条核心原则

#### 原则一：给上下文，不给猜测空间

```
# ❌ 差的提示——Claude Code 只能猜
「帮我写一个 fetcher」

# ✅ 好的提示——文件路径、类名、接口地址、返回格式全说清楚
「帮我在 services/fetchers/semantic_scholar.py 里实现
SemanticScholarFetcher 类，参考 services/fetchers/pubmed.py
的结构，使用 https://api.semanticscholar.org/graph/v1/paper/search 接口，
返回格式和 PubMedFetcher 一致（见 CLAUDE.md）」
```

#### 原则二：一次只做一件事

```
# ❌ 一次要求太多——生成的代码质量会下降，而且出错了不知道哪出的
「帮我实现三个 fetcher，加上排序逻辑，再写测试，再接到路由里」

# ✅ 分步来——每步确认没问题再进行下一步
第一步：「实现 SemanticScholarFetcher 的 search 方法」
    → 跑测试，确认通过
第二步：「给它写单元测试」
    → 确认测试通过
第三步：「把它接入 services/pipeline.py 的 fetch_all_sources 函数」
```

#### 原则三：生成后立刻验证，不跳过

Claude Code 生成的代码通常能跑，但它不知道你的具体业务逻辑。比如它可能在 API 返回空结果时返回 `None` 而不是 `[]`，下游排序时就会直接报 `TypeError`。

```bash
# 每次生成后，至少跑一遍测试
python -m pytest tests/test_fetchers.py -v

# 或者写一个快速验证脚本
python -c "
import asyncio
from services.fetchers.pubmed import PubMedFetcher

async def smoke_test():
    f = PubMedFetcher()
    results = await f.search(['stem cell', 'dental pulp'], years=2)
    # 验证返回格式
    assert isinstance(results, list), '必须返回列表'
    if results:
        r = results[0]
        for key in ['title', 'abstract', 'url', 'source', 'year']:
            assert key in r, f'缺少字段: {key}'
    print(f'通过：拿到 {len(results)} 条，格式正确')

asyncio.run(smoke_test())
"
```

#### 原则四：不理解的代码不提交

出了 bug 自己没法改，review 时也说不清楚。遇到看不懂的地方：

```
「刚才写的 _parse_xml 方法，第 23-28 行我看不懂，
请逐行解释在做什么，以及为什么要这样处理 None 的情况」
```

理解之后再提交。这个习惯能让你在 5 周内真正学到东西，而不是只是「让 AI 写了一堆代码」。

#### 原则五：让 Claude Code 帮你 review，不只是帮你写

Claude Code 的代码审查能力很强，写完一个模块后：

```
「请 review services/fetchers/pubmed.py，
重点检查异常处理是否完整、async 用法是否正确、
有没有可能在生产环境出现的潜在问题」
```

这比自己 review 效率高，也比等队友 review 快。

---

### 8.6 上下文管理：`/clear` 的正确用法

Claude Code 的对话窗口有 token 上限。**对话越长，后面输出质量越差**——它会开始「忘记」前面约定的代码风格和接口格式。

**正确节奏**：完成一个独立模块就 `/clear`，让它重新读 `CLAUDE.md` 开始下一个。

```bash
# 场景示例：
# 1. 实现 PubMedFetcher（一个完整对话）
#    → 完成后 /clear

# 2. 实现 SemanticScholarFetcher（新对话）
#    → Claude Code 自动读 CLAUDE.md，知道你的项目背景
#    → 完成后 /clear

# 3. 写测试（新对话）
#    → /clear
```

**什么时候不用 `/clear`**：调试同一个 bug 的过程中不要清，上下文对排查问题有帮助。

**如果忘了 `/clear` 导致代码质量下降**：重新开一个对话，把出问题的代码粘贴进去，说「这段代码是上个会话生成的，请帮我检查质量，重点看是否符合 CLAUDE.md 的规范」。

---

### 8.7 每周节奏

把 Claude Code 的使用和每周开发节奏结合起来：

```
周一（上午1小时）：
  → 站会确定本周任务
  → 用 Claude Code 搭本周各模块的骨架（类定义、函数签名、docstring）
  → 骨架提交到各自的 feat 分支，让队友知道你在做什么

周二-周四：
  → 逐个函数实现，边写边用 Claude Code 验证
  → 每完成一个函数就跑测试，不积累到最后

周五（下午1小时）：
  → 用 Claude Code 帮忙补全本周代码的测试
  → 检查有没有遗漏的异常处理
  → 准备 PR：dev → main
  → 更新 CLAUDE.md 的「当前 Sprint 目标」为下周内容
```

---

### 8.8 三人团队的 Claude Code 协作节奏

**避免三人同时问同一类问题**

三个人同时让 Claude Code 生成 database 操作代码 → 写法不一样 → 合并冲突。

建议分工：
- 每周一各自在 Notion 里写清楚「本周我要让 Claude Code 帮我做什么」
- 如果两人要生成有依赖关系的代码（比如人A写 fetcher，人C写调用 fetcher 的路由），人A先写，推到 dev 后人C再开始

**共享有效的提示词**

发现某个提示词特别好用，把它加到本文档的 8.4 节，或者发到微信群。好的提示词是团队共同资产。

**不同模块的 CLAUDE.md 补充**

每人可以在自己负责的模块目录下放一个 `CLAUDE.md` 补充说明：

```bash
# 例如：services/fetchers/CLAUDE.md
# 专门说明 fetchers 目录的约定，细化根目录 CLAUDE.md 的规则
```

Claude Code 会读取当前目录和所有父目录的 `CLAUDE.md`，越具体的目录级 `CLAUDE.md` 优先级越高。

---

### 8.9 哪些事不要交给 Claude Code

| 不要交给 Claude Code | 为什么 | 应该怎么做 |
|---------------------|--------|-----------|
| 决定用哪个技术方案 | 它会给答案但不承担后果，且倾向于给「看起来合理」的答案而不是「适合你团队」的答案 | 自己权衡，记录在 decisions.md |
| 直接把生成的代码推到 main | 没有人工验证 | 必须跑测试 + 至少一人 review |
| 修改 `.env` 文件 | API Key 安全风险 | 手动编辑 |
| 实现你完全看不懂的算法 | 出 bug 自己改不了，code review 时说不清楚 | 先让它解释清楚，理解后再让它实现 |
| 设计数据库 schema | 改 schema 成本很高，后期迁移麻烦 | 团队一起讨论，记录在 decisions.md |
| 解决团队分歧 | 它会给出一个「客观」答案，但团队问题要靠沟通 | 开会或微信群讨论 |

---

### 8.10 实战经验：最容易犯的错

这些是根据实际开发经验总结的坑，提前知道能省很多时间：

**坑一：生成完就跑，不读代码**

Claude Code 生成的代码通常能运行，但细节可能不符合你的需求。比如它处理 None 的方式、日志级别的选择、错误信息的格式，都可能需要微调。每次生成后花 3 分钟读一遍，有问题当场改，不要等到出了 bug 再回头找。

**坑二：上下文积累太长不清理**

一个对话里写了 2 小时代码，后面生成的内容开始忽略 CLAUDE.md 里的规范（比如开始用同步 requests 而不是 async httpx）。这时候不是 Claude Code「变笨了」，是上下文太长它开始遗忘早期约定。发现质量下降就立刻 `/clear`。

**坑三：让它一次做太多事**

「帮我实现三个 fetcher 并写测试并接入路由」——生成的代码量大、互相耦合，出了问题很难定位。一次一个模块，验证通过再继续。

**坑四：不更新 CLAUDE.md**

项目进行到第三周，CLAUDE.md 里的「当前 Sprint 目标」还是 Week 1 的内容，代码里已经加了 ChromaDB 但 CLAUDE.md 里没有说。Claude Code 就会生成不一致的代码。**每周一站会后更新 CLAUDE.md**，这是团队的共同责任。

**坑五：三人各自问重复问题**

三个人分别让 Claude Code 解释同一个 API 的用法，浪费时间。谁先搞清楚一个问题，就把结论写进 `docs/decisions.md` 或者 Notion 的「遇到的坑」页面，其他人直接看文档。

---

## 9. 每日工作流（完整版）

```bash
# ── 早上（10 分钟）────────────────────────────────────
git checkout dev
git pull origin dev

# 看看昨天队友提交了什么
git log origin/dev --oneline -10

# 切到自己的分支
git checkout feat/你的功能名
# 或新建
git checkout -b feat/新功能名

# ── 开发中（随时）────────────────────────────────────
# 打开 Claude Code
claude

# 功能点完成就提交（不要等到晚上一次性提交）
git add .
git commit -m "feat: 完成 PubMed XML 解析"
git push origin feat/你的功能名    # 推到远端备份

# ── 晚上下班前（15 分钟）─────────────────────────────
# 跑一遍全部测试，确保没有破坏现有功能
python -m pytest tests/ -v

# 有报错先修，修完再合并
git checkout dev
git pull origin dev
git merge feat/你的功能名

# 如果有冲突：
# 1. git status 看冲突文件
# 2. 打开文件，找 <<<<<<< 标记，手动决定保留哪段
# 3. git add . && git commit -m "merge: 解决 database.py 冲突"

git push origin dev

# 微信群里说一句：「今天推好了，完成了 xxx，明天做 xxx」
```

---

## 10. 常见问题处理

### 不小心提交了 `.env` 文件

```bash
# 立刻执行（不要拖）：
git rm --cached .env
git commit -m "fix: 从版本控制中移除 .env"
git push

# ！！必须做：去控制台撤销泄露的 Key，重新生成
# Anthropic: https://console.anthropic.com → API Keys
# OpenAI: https://platform.openai.com → API Keys
# 已经 push 的 Key 要假设已经泄露，即使仓库是 Private
```

### 合并冲突解决流程

```bash
git merge feat/别人的分支
# 报 CONFLICT 时：

# 1. 查看哪些文件冲突
git status

# 2. 打开冲突文件，找到这样的标记：
# <<<<<<< HEAD          ← 你的代码
# your code here
# =======
# their code here
# >>>>>>> feat/别人的分支  ← 对方的代码

# 3. 手动编辑，保留正确的版本，删掉 <<<<< ===== >>>>> 这三行

# 4. 如果看不懂冲突怎么解，可以：
# claude "帮我解决这个 git 冲突，这是冲突文件内容：[粘贴内容]，
#          我的版本在做 xxx，队友的版本在做 yyy，应该保留哪个"

# 5. 解决完后
git add .
git commit -m "merge: 解决 database.py 中的冲突"
```

### 搞坏了代码想撤回

```bash
# 撤回最近一次 commit（代码改动保留，只撤 commit 记录）
git reset --soft HEAD~1

# 彻底丢弃最近一次 commit 的所有改动（谨慎！不可逆）
git reset --hard HEAD~1

# 只把某个文件恢复到上次 commit 的状态
git checkout HEAD -- services/database.py
```

### 误删了文件

```bash
git checkout HEAD -- 被删文件的路径
```

### Claude Code 生成的代码风格和项目不一致

```
# 不要重新提问，先去 CLAUDE.md 补充约束，然后：
「请根据 CLAUDE.md 中的代码风格规范，review 并修正你刚才生成的代码，
 重点检查：async/await 用法、日志方式、异常处理风格」
```

### 不知道某个库怎么用

```bash
# 不用查文档，直接问
claude "我需要用 httpx 发一个带 timeout 和 retry 的异步 GET 请求，
        请给我一个可以直接用的示例，并解释每个参数的含义"
```

---

## 11. 第一天操作清单

按顺序执行，每项完成后打勾：

```
□ 1.  建 GitHub 仓库（Private），推送 .gitignore
□ 2.  创建完整目录结构（mkdir -p 那条命令）
□ 3.  把现有代码放入 services/ 目录并提交
□ 4.  创建 .env.example、docs/setup.md、docs/decisions.md
□ 5.  复制本文档 8.2 节的 CLAUDE.md 模板到项目根目录
□ 6.  邀请队友为 Collaborator（GitHub Settings → Collaborators）
□ 7.  每人 clone 仓库，按 docs/setup.md 独立配好环境
□ 8.  每人运行 python -m pytest tests/ 确认环境 OK（这是验收门槛）
□ 9.  安装 Claude Code：npm install -g @anthropic-ai/claude-code
□ 10. 每人在项目目录运行 claude，确认能正常启动并读取 CLAUDE.md
□ 11. 建 Notion workspace，建任务看板，分配 Week 1 的具体任务到人
□ 12. 每人建自己的 feat/ 分支，开始写第一行代码
```

**第 7-8 步是真正的验收门槛**：队友能独立按文档把环境跑起来，说明文档写清楚了，后续不会卡在「我这里跑不起来」这种低级问题上。如果跑不起来，先修文档再继续。

---

*本文档随项目迭代更新。发现内容过时，直接修改并提交：*  
`git commit -m "docs: 更新 claudeteach.md 补充 xxx 经验"`
