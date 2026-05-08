# 05 · 数据流向（DB · Redis · SSE · Memory）

> **核心问题**：用户的一句话，如何变成 DB 行、Redis 缓存、SSE 推送、最终回到前端？双层 Markdown memory 什么时候读、什么时候写？

---

## 1. 全链数据流总图

```mermaid
flowchart LR
    U["👤 用户"] -->|HTTP| FE["ChatPanel"]
    FE -->|POST /message| API["FastAPI conversation.py"]
    
    API -->|sync| LLM[("LLM Manager<br/>(单例 + Redis 60s 缓存)")]
    API -->|sync| PG1[("postgres<br/>session.messages, project, ...")]
    API -.dispatch.-> CQ[("redis: celery queue")]
    
    CQ -->|deliver| W["Worker"]
    W -->|read/write| PG2[("postgres<br/>round, document, classification")]
    W -->|publish| SSE_PUB[("redis: pub/sub<br/>round_status, agent_plan, ...")]
    W -->|set/get| AN[("redis: interrupt flag<br/>(Answer Now)")]
    
    SSE_PUB -->|subscribe| API
    API -->|HTTP SSE| FE
    
    PG1 -.读.-> ME["双层 Memory<br/>(user_memory + project_memory)"]
    W -.读.-> ME
    PG2 -.写.-> ME
    
    style API fill:#dbeafe,stroke:#2563eb
    style W fill:#d1fae5,stroke:#059669
    style PG1 fill:#fce7f3,stroke:#db2777
    style PG2 fill:#fce7f3,stroke:#db2777
    style ME fill:#fef3c7,stroke:#d97706
```

---

## 2. PostgreSQL 关键表

```mermaid
erDiagram
    USER ||--o{ PROJECT : owns
    USER ||--|| USER_PROFILE : has
    USER ||--o{ USER_MEMORY : has
    USER ||--o{ INVITATION_CODE : redeemed
    PROJECT ||--o{ PROJECT_MEMORY : has
    PROJECT ||--o{ SEARCH_ROUND : runs
    PROJECT ||--o{ DOCUMENT : "owns refs"
    PROJECT ||--o{ MONITOR_JOB : monitors
    PROJECT ||--o{ DOCUMENT_CLASSIFICATION : classified
    PROJECT ||--o{ CONVERSATION_SESSION : "1+ sessions"
    SEARCH_ROUND ||--o{ ROUND_DOCUMENT : produces
    DOCUMENT ||--o{ ROUND_DOCUMENT : "linked"
    DOCUMENT ||--o{ DOCUMENT_CLASSIFICATION : classified
    CONVERSATION_SESSION ||--o{ MESSAGE : contains
    MONITOR_JOB ||--o{ MONITORING_PUSH : sends
    PROJECT ||--o{ DOCUMENT_IMPORT_JOB : "PDF imports"
    PROJECT ||--o{ RESEARCH_NOTE_PAGE : notebook
    USER ||--o{ USER_FEEDBACK : "site feedback"

    USER {
        uuid id PK
        string email
        string hashed_password
        bool is_admin
        text invitation_code_id
    }
    PROJECT {
        uuid id PK
        uuid user_id FK
        string title
        text description
        json search_config
        int current_round
        string status
    }
    SEARCH_ROUND {
        uuid id PK
        uuid project_id FK
        int round_number
        string status
        json source_stats
        json search_queries
    }
    DOCUMENT {
        uuid id PK
        uuid project_id FK
        string title
        text abstract
        text ai_summary
        json ai_key_points
        float relevance_score
    }
    CONVERSATION_SESSION {
        uuid id PK
        uuid user_id FK
        uuid project_id FK NULL
        string current_state
        json messages
        json pending_confirmation
    }
    USER_MEMORY {
        uuid id PK
        uuid user_id FK
        text markdown
        int version
    }
    PROJECT_MEMORY {
        uuid id PK
        uuid project_id FK
        text markdown
        int version
    }
```

注：实际 schema 由 `backend/app/models/*.py` 定义，alembic 0001→0022 累计迁移。本图突出主关系，省略时间戳和不重要字段。

---

## 3. Redis 用途

| Key 模式 | 内容 | TTL | 谁读谁写 |
|---|---|---|---|
| Celery default queue | 任务列表（execute_round / generate_summary / 等）| — | API 写、worker 读 |
| `llm:config` | 当前活跃 LLM 提供商 + token/参数 | 60s | LLMManager 单例读写 |
| `keyword_plan:{round_id}` | per-source 查询词草稿（用户编辑前后）| ~1h | conversation.py & search.py 读写 |
| `interrupt_flag:{round_id}` | "用户点了 Answer Now" 标志 | 60s | API 写、PhaseRunner 读 |
| `recipe:lock:{project_id}` | 项目食谱再生成 SET-NX-EX dedup | 60s | recipe_tasks |
| `stale_hint:{project_id}` | 距上次检索 N 天的去重 + 用户 dismiss | 7d | telemetry & staleness |
| `dev_log:*` | DevTools 日志缓冲 | rolling | log_writer & devtools UI |
| pub/sub channel `round:{round_id}` | SSE 事件流 | 一次性 | EventBus |

代码：`backend/app/services/event_bus.py` + 各 service。

---

## 4. SSE 推送链

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户浏览器
    participant FE as 前端 useSessionSSE
    participant API as FastAPI /api/stream
    participant Redis
    participant W as Worker
    
    Note over U,FE: 进入项目页或对话页
    FE->>API: GET /api/stream/session/{sid}<br/>(SSE 长连)
    API->>Redis: SUBSCRIBE round:* + session:*
    
    Note over W: 跑 PhaseRunner
    W->>Redis: PUBLISH round:{rid} {round_status, progress}
    Redis-->>API: message
    API-->>FE: data: {...}\n\n
    FE->>FE: 更新进度条
    
    W->>Redis: PUBLISH session:{sid}<br/>{type: 'session_message_appended', msg}
    Redis-->>API: message
    API-->>FE: data: {...}\n\n
    FE->>FE: appendIncomingMessage 到对话
    
    Note over W: ScoringAgent.score_all 内部
    W->>Redis: PUBLISH llm_call_start
    Redis-->>API: message
    API-->>FE: data: {...}
    FE->>FE: useChatTokenTracker:<br/>turnStartTime = Date.now()<br/>启计时器
    
    W->>Redis: PUBLISH llm_usage_delta {input,output}
    Redis-->>API: message
    API-->>FE: data: {...}
    FE->>FE: turnInputTokens += ...<br/>turnOutputTokens += ...<br/>turnModel = ...
    
    Note over U: AI 回复完成
    FE->>FE: isAgentThinking false<br/>onTurnEnd 持久化 token 到消息 metadata
```

**前端订阅（commit 1d7918f 之后）**：
- `composables/useSessionSSE.ts` — 通用 SSE 连接管理
- `composables/useChatTokenTracker.ts` — 专门处理 token 实时追踪（这次重构抽出来的）
- `composables/useSSE.ts` — collaboration store 用

---

## 5. 双层 Markdown Memory 系统

### 5.1 概念

| 层 | 表 | 范围 | 谁能改 |
|---|---|---|---|
| **用户级** | `user_memory` | 跨项目共享（"我是 CS 学生，关注 LLM 推理"）| 用户在 /memory 页编辑 + MemoryAgent 自动追加 |
| **项目级** | `project_memory` | 仅当前项目（"本项目研究 KV cache 量化"）| 同上 |
| **(legacy)** | `user_profile.memory_text` | 老的 markdown 字段，跟 user_memory 部分功能重叠 | MemoryAgent 自动改写 |

CLAUDE.md 标注的 "双层 Markdown 记忆" 指的是**用户级 + 项目级**，CLAUDE.md memory「embedding 已彻底放弃」指 commit a34b48a 删除了向量字段。

### 5.2 何时读

```mermaid
flowchart LR
    P3["LoadMemoryPhase<br/>(每轮检索开头)"]
    P3 -->|读| UM["user_memory.markdown"]
    P3 -->|读| PM["project_memory.markdown"]
    P3 -->|读| LP["user_profile.memory_text<br/>(legacy)"]
    UM --> Combine["build_combined_memory_for_agents()"]
    PM --> Combine
    LP --> Combine
    Combine --> Out["combined_md 文本"]
    Out -->|prompt 注入| QPA["QueryPlanAgent"]
    Out -->|prompt 注入| SA["ScoringAgent"]
    Out -->|prompt 注入| RA["ResearchAgent"]
    
    style Combine fill:#fef3c7,stroke:#d97706
```

代码：
- `backend/app/services/markdown_memory.py: build_combined_memory_for_agents()`
- 调用方 `harness/pipeline/phases/load_memory.py:28-34`

### 5.3 何时写

```mermaid
flowchart LR
    User["用户分类反馈"] -->|POST /api/feedback| FB["feedback.py"]
    FB -->|hook fire| H["POST_FEEDBACK"]
    H -->|trigger| MA["MemoryAgent.update_memory()"]
    MA -->|读| Cur["current_memory_text"]
    MA -->|读| Buckets["feedback_buckets<br/>(very_relevant/relevant/uncertain/irrelevant)"]
    MA -->|LLM 改写| New["updated_md"]
    New -->|写回| UM2["user_memory.markdown<br/>(version+1)"]
    
    User2["/memory 页 🪄 按钮"] -->|POST /api/memory/refine| MEM["memory.py"]
    MEM --> MMA["MemoryMarkdownAgent"]
    MMA -->|读| Conv["最近 N 条对话"]
    MMA -->|LLM 提炼| Refined["refined_md"]
    Refined -->|写回| UM2
    
    style MA fill:#dbeafe
    style MMA fill:#dbeafe
    style UM2 fill:#fce7f3
```

### 5.4 版本机制

`user_memory.version` 单调递增，每次 MemoryAgent 改写 +1。前端在 /memory 页可以看到历史版本（如有）。

---

## 6. 一次完整的"创建项目→检索→反馈"数据流

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant FE as ChatPanel
    participant API as FastAPI
    participant LLM as LLM Manager
    participant DB as Postgres
    participant RD as Redis
    participant W as Worker
    
    Note over U,W: ====== 创建项目 ======
    U->>FE: "研究 Transformer 推理加速"
    FE->>API: POST /message
    API->>DB: 读 ConversationSession (state=idle)
    API->>LLM: ResearchDecisionAgent (1 次)
    LLM-->>API: intent + query_plan
    API->>DB: 写 Project (state=draft)<br/>+ search_config.precomputed_plan
    API->>DB: session.messages.append + state='intent_confirmation'
    API-->>FE: rich message: 意图确认卡
    
    U->>FE: 点确认
    FE->>API: POST /confirm action=confirm
    API->>DB: project.status='active'<br/>session.state='search_mode_selection'
    API-->>FE: 模式选择卡
    
    U->>FE: 选 hybrid 模式
    FE->>API: POST /confirm
    API->>DB: 创建 SearchRound (status=preparing)
    API->>LLM: QueryPlanAgent (用 precomputed_plan 时跳过)
    API->>DB: 写 round.search_queries
    API->>RD: SET keyword_plan:{rid}
    API->>DB: state='keyword_confirmation'
    API-->>FE: KeywordConfirmPanel 富消息
    
    Note over U,W: ====== 检索一轮 ======
    U->>FE: 编辑/确认关键词
    FE->>API: POST /confirm-keywords
    API->>DB: round.status='searching'
    API->>RD: dispatch execute_round
    API-->>FE: 200
    
    RD->>W: deliver task
    W->>DB: load round + project + scoring_weights
    W->>DB: 读 user_memory + project_memory
    W->>W: PhaseRunner 跑 11 phase
    
    loop 每个 phase
        W->>RD: SUBSCRIBE 检查 interrupt_flag
        W->>W: phase.execute()
        W->>RD: PUBLISH round_status (progress)
        RD->>API: message → SSE
        API-->>FE: progress 0.55
    end
    
    Note over W: 14 源 fetch (并行 httpx)
    W->>DB: 写 RoundDocument + Document
    W->>RD: dispatch summary chord (× N 篇)
    
    par 并行摘要
        RD->>W: deliver generate_summary_for_doc
        W->>LLM: 单篇摘要
        LLM-->>W: ai_summary + key_points
        W->>DB: 写 doc.ai_summary
    end
    
    W->>DB: round.status='awaiting_feedback'<br/>+ avg_score
    W->>RD: PUBLISH round_complete
    RD->>API: message
    API-->>FE: SSE 完成
    
    Note over U,W: ====== 用户反馈 → Memory 更新 ======
    U->>FE: 拖某文献到 very_relevant 桶
    FE->>API: POST /api/feedback
    API->>DB: 写 DocumentClassification
    API->>API: HookEngine.fire(POST_FEEDBACK)
    API->>LLM: MemoryAgent.update_memory()
    LLM-->>API: new_memory_text
    API->>DB: user_memory.markdown = new<br/>version += 1
    API-->>FE: 反馈成功
    
    Note over U: 下一轮检索时,<br/>新 memory_text 会自动作为 prompt 输入
```

---

## 7. 文件存储

```mermaid
flowchart LR
    User --> FE
    FE -->|上传 PDF| API
    API --> WK["Celery worker"]
    WK -->|文本提取| MD["markitdown / PyMuPDF"]
    WK -->|存原文件| FS1["data/pdfs/<br/>(host volume)"]
    WK -->|存解析文本| FS2["data/exports/"]
    WK --> DIA["DocImportAgent<br/>(LLM 出元数据)"]
    DIA --> DB[(Document)]
    
    User2["反爬下载文献全文"] --> FT["fulltext_service"]
    FT -->|多策略| HX["httpx + stealth"]
    FT -->|兜底| PW["Playwright headless Chrome"]
    FT --> FS1
    FT -->|metadata| DB
    
    User3["导出文献库"] --> Exp["export endpoint"]
    Exp --> FS2
    Exp --> Zip["zip / bibtex"]
    Zip --> User3
```

`data/` 在 host 上是 `D:\AI\scholarpilot-dev\data\`，docker volume 挂载到容器 `/app/data`，详见 [01-system-overview.md](./01-system-overview.md#5-数据持久化)。

---

## 8. 给开发者：怎么排查"数据没到前端"

```mermaid
flowchart TD
    Issue["前端显示错 / 没刷新"]
    Issue --> S1{"DB 里有吗？"}
    S1 -->|没有| W1["看 worker 日志<br/>docker logs -f worker"]
    S1 -->|有| S2{"API 能查到吗？"}
    S2 -->|不能| W2["FastAPI 路由调通？<br/>swagger /docs 试试"]
    S2 -->|能| S3{"SSE 推了吗？"}
    S3 -->|没推| W3["EventBus.publish 调用方<br/>grep 'publish_sync'"]
    S3 -->|推了| S4{"前端订阅了吗？"}
    S4 -->|没订阅| W4["useSessionSSE 在组件<br/>onMounted 里 connect 了？"]
    S4 -->|订阅了但没渲染| W5["Pinia store 收到 event 后<br/>有触发 reactive 更新吗？"]
    
    style W1 fill:#fee2e2
    style W3 fill:#fee2e2
    style W4 fill:#fee2e2
```

---

## 9. 总结

ScholarPilot 数据流的设计哲学：

1. **DB 是 source of truth**——任何 agent 输出最终都要落地，临时态只在 RoundContext.artifacts（内存）
2. **Redis 是高速通道**——队列 / 缓存 / pub-sub 三件套，但**不存业务数据**
3. **SSE 是单向通知**——前端不通过 SSE 写后端，只接收事件
4. **Memory 是跨轮持久化**——user/project 两层 markdown，用户级跨项目，项目级仅本项目，下游 agent 通过 prompt 注入消费
5. **失败不阻塞**——hook 抛错只 log，agent 失败有降级，单源失败收 partial_errors[]

---

## 完结

至此你已经看完 ScholarPilot 架构的 5 个维度：
1. ✅ 系统全景（容器架构）
2. ✅ 对话流程（状态机 + 路由）
3. ✅ 检索流水线（PhaseRunner DAG）
4. ✅ Agent 角色（10 个 agent）
5. ✅ 数据流向（DB / Redis / SSE / Memory）

回到 [README](./README.md) 查看其它路径。
