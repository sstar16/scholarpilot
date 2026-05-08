# 04 · Agent 角色与协作关系

> **核心问题**：项目里 10 个 agent 各做什么？谁调谁？为什么不是"主 agent + 子 agent"模式？

---

## 1. 10 个 agent 一览

```mermaid
graph LR
    subgraph "对话决策层"
        RDA["ResearchDecisionAgent"]
        IA["IntentAnalysisAgent"]
        IR["IntentRouter<br/>(prompt 文件，不是 class)"]
    end
    
    subgraph "检索流水线"
        QPA["QueryPlanAgent"]
        SA["ScoringAgent"]
        MA["MemoryAgent"]
    end
    
    subgraph "深度分析"
        RA["ResearchAgent"]
        PA["ProbeAgent"]
    end
    
    subgraph "辅助"
        MMA["MemoryMarkdownAgent"]
        DIA["DocImportAgent"]
    end
    
    style RDA fill:#fef3c7,stroke:#d97706
    style IA fill:#fee2e2,stroke:#dc2626
    style RA fill:#dbeafe,stroke:#2563eb
```

---

## 2. 详细规格表

| Agent | 文件 | 调用方 | 输入 | 输出 | 失败降级 |
|---|---|---|---|---|---|
| **ResearchDecisionAgent** | `harness/agents/research_decision_agent.py` | `api/conversation.py:143` 创建项目时一次性调用 | `user_input`, `supplementary_context` | `{is_research_request, title, description, domains, query_plan?}` | → IntentAnalysisAgent |
| **IntentAnalysisAgent** | `harness/agents/intent_agent.py` | RDA 失败时降级 / `manual_live_json_mode.py` 测试 | 同上 | `{is_research_request, title, description, ...}`（不含 query_plan） | 无（最后兜底）|
| **QueryPlanAgent** | `harness/agents/query_plan_agent.py` | `phases/plan_query.py:48` 每轮检索 | `project_description`, `memory_text`, `round_number`, `tool_reliability` | `QueryPlan(base_query, sources, year_from/to, exclude_terms)` | `build_query()` 规则函数 |
| **ScoringAgent** | `harness/agents/scoring_agent.py` | `phases/score.py:56` 每轮检索 | `docs[]`, `project_description`, `cutoff`, `user_memory` | `{above_cutoff: [{doc, score, reasoning}], below_cutoff: [...]}` | `relevance_engine` 传统分数 |
| **ResearchAgent** | `harness/agents/research_agent.py` | `api/conversation.py:799` & `api/collaboration.py` 协作问答 | `question`, `papers`, `project_description`, `conversation_history` | `{answer, citations: [{doc_id, snippet}]}` | "暂不可用"消息 |
| **ProbeAgent** | `harness/agents/probe_agent.py` | `api/collaboration.py:940` 协作前的 section 级精读探针 | doc + question | `[{section_label, excerpt_quote, relevance, insight}]` | 跳过探针，退化 full_text[:8000] |
| **MemoryAgent** | `harness/agents/memory_agent.py` | `api/feedback.py:154` & `api/search.py:793` 用户分类后 | `project_description`, `current_memory`, `feedback_buckets` | `updated_memory_text` (markdown) | 保留旧 memory_text |
| **MemoryMarkdownAgent** | `harness/agents/memory_markdown_agent.py` | `api/memory.py:97/222` /memory 页"🪄 从对话提炼"按钮 | conversation_messages, current_md | refined_md | 保留旧 md |
| **DocImportAgent** | `harness/agents/doc_import_agent.py` | `workers/import_tasks.py:19` 用户上传 PDF | parsed PDF text + project | `{title, authors, abstract, ai_summary}` | 失败标记，让用户手动填 |

---

## 3. Agent 之间的调用关系

```mermaid
flowchart TD
    User(["用户消息"])
    User --> ConvAPI["api/conversation.py"]
    ConvAPI -->|创建项目| RDA["ResearchDecisionAgent"]
    RDA -.失败降级.-> IA["IntentAnalysisAgent"]
    
    User2(["确认关键词"])
    User2 --> SearchAPI["api/search.py"]
    SearchAPI --> Worker["Celery Worker"]
    Worker --> PR["PhaseRunner"]
    PR -->|PlanQueryPhase| QPA["QueryPlanAgent"]
    QPA -.失败降级.-> BQ["build_query()<br/>规则函数"]
    PR -->|ScorePhase| SA["ScoringAgent"]
    SA -.失败降级.-> RE["relevance_engine"]
    
    User3(["分类反馈"])
    User3 --> FBApi["api/feedback.py"]
    FBApi -->|hook POST_FEEDBACK| MA["MemoryAgent"]
    
    User4(["协作问答"])
    User4 --> CollabAPI["api/collaboration.py"]
    CollabAPI --> RA["ResearchAgent"]
    CollabAPI -->|协作前探针| PA["ProbeAgent"]
    
    User5(["上传 PDF"])
    User5 --> ImportAPI["api/document_import.py"]
    ImportAPI --> ImpWorker["Celery worker"]
    ImpWorker --> DIA["DocImportAgent"]
    
    User7(["/memory 页 🪄"])
    User7 --> MemAPI["api/memory.py"]
    MemAPI --> MMA["MemoryMarkdownAgent"]
    
    classDef agent fill:#dbeafe,stroke:#2563eb,stroke-width:2px
    classDef fallback fill:#fee2e2,stroke:#dc2626
    
    class RDA,IA,QPA,SA,RA,PA,MA,MMA,DIA agent
    class BQ,RE fallback
```

**关键观察**：
- 所有 agent 调用方**只有 4 类**：FastAPI router / Celery worker / PhaseRunner / Hook handler
- **agent 之间没有相互调用**——这是有意为之的解耦设计
- 每个 agent 只负责自己那一锤子活，不知道下游谁会用结果

---

## 4. 为什么不是 supervisor 范式？

业界（LangGraph / OpenAI Swarm / Anthropic）目前流行"主 agent 路由 + 子 agent 工作"的 supervisor pattern。**ScholarPilot 没用这个**，理由：

```mermaid
flowchart LR
    subgraph "supervisor 范式（如 LangGraph）"
        S1["主 LLM Agent<br/>(理解+决策+调度)"]
        S1 -->|tool call| W1[Worker A]
        S1 -->|tool call| W2[Worker B]
        S1 -->|tool call| W3[Worker C]
        W1 --> S1
        W2 --> S1
        W3 --> S1
    end
    
    subgraph "ScholarPilot 现行（workflow + agent）"
        SM["状态机<br/>(Python 代码)"]
        SM --> P1["Phase A → Agent A"]
        P1 --> P2["Phase B → Agent B"]
        P2 --> P3["Phase C → Agent C"]
    end
```

| 维度 | supervisor | ScholarPilot |
|---|---|---|
| 路由决策 | LLM 推理（每条消息都过一次主 LLM） | Python `current_state` switch（固定确定）|
| 决策成本 | $$$（每轮 N 次 LLM）| 零（代码）|
| 决策延迟 | 1-3s | 微秒 |
| 输出可预测性 | LLM 可能跑偏到不该走的路径 | 固定路径，非常可预测 |
| 灵活度 | 极高（适合开放对话）| 中（需先定义 state）|
| 适用场景 | 开放助手 / 编码代理 / 多领域问答 | **强结构 workflow**（如科研检索）|

**Anthropic 自己的 "Building effective agents" 一文也强调**："Don't use agents when workflows suffice"。ScholarPilot 的核心流程（项目→关键词→检索→反馈）正是 workflow，所以选这个范式是对的。

---

## 5. 何时该用 LLM？何时不该？

项目里 LLM 调用集中在这几个场景：

```mermaid
flowchart TD
    Q{"做的事"}
    Q -->|"理解用户自然语言<br/>(意图、问答)"| Y1["✅ LLM<br/>(RDA, ResearchAgent)"]
    Q -->|"对开放文本输出结构化判断<br/>(评分、关键词生成)"| Y2["✅ LLM<br/>(ScoringAgent, QueryPlanAgent)"]
    Q -->|"路由到具体动作<br/>(state switch)"| N1["❌ 用代码<br/>(conversation.py)"]
    Q -->|"格式化数据<br/>(去重、排序)"| N2["❌ 用代码<br/>(build_dedup, rerank)"]
    Q -->|"调用外部 API<br/>(数据源)"| N3["❌ 用代码<br/>(fetchers/*.py)"]
    Q -->|"持久化"| N4["❌ 用代码<br/>(save_round)"]
    
    style Y1 fill:#dbeafe
    style Y2 fill:#dbeafe
    style N1 fill:#d1fae5
    style N2 fill:#d1fae5
    style N3 fill:#d1fae5
    style N4 fill:#d1fae5
```

**红线**：能用代码确定性解决的，**绝不让 LLM 兜**。代码错可调试，LLM 错难复现。

---

## 6. ResearchDecisionAgent 的特殊地位

它是项目里**最像主 agent**的角色，但只在创建项目时跑一次：

```mermaid
sequenceDiagram
    Note over RDA: 一次 LLM 调用，做 3 件事
    RDA->>RDA: 1. 是不是研究请求？(布尔)
    RDA->>RDA: 2. 提取项目元数据 (title, desc, domains)
    RDA->>RDA: 3. 预生成 query_plan（base_query, sources, year）
    RDA->>Project: 把 query_plan 存到<br/>project.search_config["precomputed_plan"]
    Note over RDA: 第 1 轮检索时，<br/>QueryPlanAgent 看到 precomputed_plan 就跳过自己<br/>(节省一次 LLM 调用)
```

**为什么 RDA 把 3 件事打包**：
- 节省 LLM 调用（创建项目 → 第一轮检索原本要 2 次，合一次）
- 第 1 轮的 query_plan 与意图判断是高度相关的（一句话讲清楚研究方向就能产生关键词）

**潜在问题**：
- precomputed_plan 没有"用一次后失效"的机制，可能被复用导致后续轮不更新（CLAUDE.md 没明示）
- 第 1 轮和后续轮走两条不同代码路径，维护成本高

详见 [03-search-pipeline.md](./03-search-pipeline.md#7-失败降级矩阵) 关于 PlanQueryPhase 的说明。

---

## 7. Hook 系统：横切关注点

10 个 agent 不直接互相依赖，但**很多副作用通过 Hook 触发**：

```mermaid
flowchart LR
    subgraph "Hook 触发点"
        H1["ROUND_START"]
        H2["POST_SEARCH"]
        H3["POST_SCORING"]
        H4["ROUND_COMPLETE"]
        H5["POST_FEEDBACK"]
        H6["PROJECT_CREATE"]
    end
    
    subgraph "Hook handlers (harness/hooks/)"
        HH1["metrics_hook.py<br/>计时统计"]
        HH2["logging_hook.py"]
        HH3["workbench_hook.py<br/>缓存源统计供前端"]
        HH4["summary_metrics_hook.py"]
        HH5["kg_refresh_hook.py<br/>更新知识图谱"]
        HH6["skill_recommender_hook.py<br/>推 skill_suggestion 富消息"]
    end
    
    H1 --> HH1
    H1 --> HH2
    H2 --> HH3
    H3 --> HH4
    H4 --> HH5
    H4 --> HH2
    H5 --> HH5
    H5 --> HH6
    H6 --> HH5
    
    classDef hook fill:#fce7f3
    class H1,H2,H3,H4,H5,H6 hook
```

**Hook 系统的核心价值**：
- 加新功能不用改主流程代码（KG / 推荐 / 指标都是后挂的）
- 失败可隔离（hook 抛异常只 log，不影响主流程）
- 可单测（hook 与 phase 解耦）

代码：`backend/app/harness/hook_engine.py` + `harness/hooks/*.py`

---

## 8. 给 agent 加个新成员的清单

要加一个 `LiteratureGapAgent`（找文献空白）？

1. 在 `backend/app/harness/agents/` 加 `literature_gap_agent.py`
2. 在 `harness/prompts/` 加对应 prompt（参考 `query_plan.py`）
3. **决定调用方**：
   - 如果是检索的一部分 → 加新 phase（见 [03-search-pipeline.md#8-给开发者怎么加一个-phase](./03-search-pipeline.md#8-给开发者怎么加一个-phase)）
   - 如果是用户主动触发 → 加 API endpoint
   - 如果是反馈后自动 → 注册到某个 hook
4. **降级策略**：明确"LLM 失败时返回什么"
5. 写测试：`tests/harness/test_literature_gap_agent.py`

**不要做的事**：
- ❌ 让新 agent 调其他 agent（保持 agent 之间无依赖）
- ❌ 让 agent 自己写 DB（让调用方写）
- ❌ 让 agent 跨 round 持有状态（agent 是函数式的，每次调用独立）

---

## 9. 调试一个失灵的 agent

```mermaid
flowchart TD
    Issue["agent 输出有问题"]
    Issue --> Q1{"LLM 调用本身？"}
    Q1 -->|看 LLM 日志| Devtools["devtools :3001<br/>LLM 调用历史 + token + 耗时"]
    Q1 -->|prompt 改了？| Prompts["backend/app/harness/prompts/<br/>看实际拼出来的 system prompt"]
    
    Issue --> Q2{"agent 收到的输入？"}
    Q2 -->|检查调用方| Caller["grep agent.method 找调用方<br/>看传进来的参数"]
    
    Issue --> Q3{"降级触发了？"}
    Q3 -->|grep '降级' 或 'fallback'| Logs["docker compose logs backend worker"]
    
    Issue --> Q4{"hook 干扰？"}
    Q4 -->|disable hook 试试| Hookoff["注释掉 harness/bootstrap.py<br/>对应 hook 注册"]
```

---

## 下一步

- 看数据流向（DB / Redis / SSE 全链）→ [05-data-flow.md](./05-data-flow.md)
