# 02 · 对话流程与状态机

> **核心问题**：用户在 ChatPanel 里发一句话，系统怎么决定下一步是分析意图、确认关键词，还是路由到协作模式？

---

## 1. 状态机：7 个状态

`ConversationSession.current_state` 决定**当前可以做什么**，CLAUDE.md「对话状态机原则」是顶层锚点。

```mermaid
stateDiagram-v2
    [*] --> idle: 创建 session
    
    idle --> intent_analysis: 用户描述研究方向
    intent_analysis --> intent_confirmation: ResearchDecisionAgent 出意图
    intent_analysis --> idle: 不是研究请求 (闲聊/问答)
    intent_confirmation --> search_mode_selection: 用户点确认
    intent_confirmation --> idle: 用户取消
    
    search_mode_selection --> keyword_confirmation: 选 static_db/api/hybrid
    search_mode_selection --> idle: 用户退出
    
    keyword_confirmation --> [*]: dispatch Celery (state 转交给 SearchRound)
    keyword_confirmation --> idle: ExitButton 退出
    
    idle --> collaboration_selecting: 用户点 🤝 协作（文献库非空时）
    collaboration_selecting --> collaboration_active: 选完文献确认
    collaboration_selecting --> idle: 取消选择
    
    collaboration_active --> idle: 退出协作
    
    note right of idle: 自由聊天<br/>三大入口可用
    note right of keyword_confirmation: 只能编辑/确认 source_plans<br/>禁其他互动
    note left of collaboration_active: 只能问协作问题<br/>不触发新检索
```

**状态规则**：
- 默认 `idle`：自由聊天 + 三大功能入口（检索 / 协作 / 定时推送）
- 一旦进流程**必须走完或显式退出**，中途不能切流程
- 非 `idle` 状态下输入只路由给当前流程的 handler
- 前端按钮根据 state 联动启用/禁用（FunctionDock + FeatureGate）

---

## 2. send_message 路由分派

每次用户发消息（`POST /api/conversation/{sid}/message`），`backend/app/api/conversation.py:287` 根据 state 决定路径：

```mermaid
flowchart TD
    In["用户消息<br/>POST /message"]
    In --> S{"session.current_state?"}
    
    S -->|idle + 没绑项目| RDA["_run_intent_analysis()<br/>(conversation.py:287)"]
    S -->|idle + 已绑项目| Router["_run_intent_router()<br/>(conversation.py:677)"]
    S -->|intent_confirmation| BlockA["返回 'please confirm above'<br/>等用户点确认卡片"]
    S -->|search_mode_selection| BlockB["返回 'please pick mode'<br/>等用户选 dialog"]
    S -->|keyword_confirmation| BlockC["返回 'editing keywords'<br/>等用户确认气泡"]
    S -->|collaboration_selecting| BlockD["等用户选文献"]
    S -->|collaboration_active| Collab["_handle_collaboration_message()<br/>→ ResearchAgent"]
    
    RDA --> RDAOut["1 次 LLM 调用<br/>同时出 intent + query_plan"]
    RDAOut -->|失败| INA["IntentAnalysisAgent.analyze()<br/>(降级，只出 intent)"]
    RDAOut --> CreateProj["创建 Project<br/>+ PROJECT_CREATE hook"]
    
    Router --> Classify{"intent_type?"}
    Classify -->|search_request| Prepare["新一轮检索"]
    Classify -->|analyze_documents| Scope["suggest_scope()<br/>弹文献选择气泡"]
    Classify -->|research_qa| RA["ResearchAgent.answer()<br/>(基于已有文献回答)"]
    Classify -->|upload| UI["回复'请用上传按钮'"]
    Classify -->|general_chat| Chat["普通对话回复"]
    
    style RDA fill:#dbeafe,stroke:#2563eb
    style Router fill:#dbeafe,stroke:#2563eb
    style RDAOut fill:#fef3c7,stroke:#d97706
    style INA fill:#fee2e2,stroke:#dc2626
```

---

## 3. 三大场景的端到端调用链

### 场景 A · 创建项目

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant FE as ChatPanel.vue
    participant API as conversation.py
    participant RDA as ResearchDecisionAgent
    participant LLM as LLM Manager
    participant DB as Postgres
    participant Hook as HookEngine
    
    U->>FE: "我想研究 Transformer 推理加速"
    FE->>API: POST /{sid}/message
    Note over API: state == 'idle' & 没绑项目
    API->>API: _run_intent_analysis()
    API->>RDA: decide(user_input, supplementary)
    RDA->>LLM: 1 次调用<br/>(prompt: 项目识别 + query_plan)
    LLM-->>RDA: {is_research, title, desc, domains, query_plan}
    
    alt LLM 成功
        RDA-->>API: 完整 intent (含 precomputed_plan)
    else LLM 失败
        API->>API: 降级 IntentAnalysisAgent.analyze()
        Note over API: 只出 intent，不带 query_plan
    end
    
    API->>DB: 写 Project (status=draft)<br/>search_config.precomputed_plan = ...
    API->>Hook: PROJECT_CREATE
    Hook-->>Hook: kg_refresh / logging
    API->>DB: session.current_state = 'intent_confirmation'
    API-->>FE: MessageOut(<br/>  envelope: 项目草稿确认卡<br/>)
    FE-->>U: 显示意图确认气泡
    
    U->>FE: 点"确认"
    FE->>API: POST /{sid}/confirm action=confirm
    API->>DB: project.status = 'active'<br/>state = 'search_mode_selection'
    API-->>FE: MessageOut(<br/>  envelope: 模式选择卡<br/>)
```

### 场景 B · 执行一轮检索（高层）

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant FE as ChatPanel
    participant API as search.py
    participant CQ as Celery Redis
    participant W as Worker
    participant PR as PhaseRunner
    participant SSE as EventBus
    
    Note over U,FE: 已经在 keyword_confirmation 状态<br/>(KeywordConfirmPanel 显示)
    U->>FE: 点"确认本轮"<br/>(可能编辑了关键词)
    FE->>API: POST /confirm-keywords payload
    API->>API: 把 source_plans 写入 SearchRound
    API->>CQ: dispatch execute_round(round_id)
    API-->>FE: 200 (轮次开始)
    
    CQ->>W: deliver task
    W->>PR: PhaseRunner.run(ctx)
    
    loop 11 个 phase 顺序执行
        PR->>PR: phase.skip_if(ctx)?
        alt 不跳过
            PR->>SSE: round_status (progress 0.x)
            PR->>PR: pre_hook fire
            PR->>PR: phase.execute(ctx)
            PR->>PR: post_hook fire
            PR->>SSE: round_status (progress 0.y)
        end
    end
    
    PR->>SSE: round_complete
    SSE-->>FE: SSE 事件
    FE-->>U: 显示完成 + 文献卡
```

详细 phase 见 [03-search-pipeline.md](./03-search-pipeline.md)。

### 场景 C · 协作研究

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant FE as ChatPanel
    participant API as conversation.py
    participant IR as IntentRouter
    participant CO as collaboration.py
    participant RA as ResearchAgent
    participant DB as Postgres
    
    Note over U: state=idle，文献库已有分类文献
    U->>FE: "帮我分析下这些文献的核心矛盾"
    FE->>API: POST /{sid}/message
    Note over API: 已绑项目
    API->>IR: 路由分类
    IR-->>API: intent_type='analyze_documents'
    API->>CO: suggest_scope(session_id)
    CO->>DB: 读 very_relevant 桶
    CO->>API: collaboration_scope rich message
    API-->>FE: 富消息：选择文献气泡
    Note over API: state='collaboration_selecting'
    
    U->>FE: 勾选 5 篇 → 确认
    FE->>API: POST /collaboration/start (doc_ids)
    API->>DB: state='collaboration_active'<br/>构建 snapshot (papers + memory)
    API-->>FE: collaboration_started
    
    loop 协作问答
        U->>FE: 提问
        FE->>API: POST /message
        API->>RA: answer(question, papers, memory, history)
        RA->>RA: LLM 推理 (引用编号)
        RA-->>API: {answer, citations}
        API->>DB: 写 collaboration_answer rich message
        API-->>FE: 富消息：答案 + citation 跳转
    end
    
    U->>FE: 点退出
    FE->>API: POST /collaboration/exit
    API->>DB: state='idle'
    API-->>FE: flow_exited
```

---

## 4. 关键代码位置

| 关注点 | 文件:行号 |
|---|---|
| send_message 路由 | `backend/app/api/conversation.py:287` |
| _run_intent_analysis | `backend/app/api/conversation.py:143` |
| _run_intent_router (项目内分类) | `backend/app/api/conversation.py:677` |
| _create_project_from_intent | `backend/app/api/conversation.py:166` |
| confirm 路径（项目→模式选择→关键词）| `backend/app/api/conversation.py:572-650` |
| state 枚举 + 转换守卫 | `backend/app/services/session_state_registry.py` |
| FeatureGate（前端按钮启用矩阵）| `backend/app/services/feature_gate.py` + `frontend/src/composables/useFeatureGate.ts` |
| ExitButton（退出当前流程）| `frontend/src/components/conversation/ExitButton.vue` + `backend/app/api/session_exit.py` |

---

## 5. 异常路径设计

### 流程被中途打断

```mermaid
flowchart LR
    A["用户在 keyword_confirmation 状态"] --> B{"做了什么？"}
    B -->|按 ExitButton| C["session_exit.py<br/>清理本轮 + 回 idle"]
    B -->|关浏览器再开| D["前端 GET /session<br/>恢复 state"]
    B -->|换 mode 按钮| E["弹 ElMessageBox 确认<br/>清掉草稿再选模式"]
    
    style C fill:#fee2e2
    style D fill:#d1fae5
    style E fill:#fef3c7
```

### LLM 失败的统一降级

| 场景 | 主路径 | 降级 |
|---|---|---|
| 创建项目 | ResearchDecisionAgent (1 次 LLM 出 intent + query_plan) | IntentAnalysisAgent (只出 intent，query_plan 留空让 QueryPlanAgent 后补) |
| 检索 | QueryPlanAgent.agentic_plan() | build_query() 确定性函数 |
| 评分 | ScoringAgent.score_all() | relevance_engine 传统分数 |
| 协作回答 | ResearchAgent.answer() | 通用"分析暂不可用"消息 |

每次降级都会写日志 + 不抛给用户，UI 仍能继续走。

---

## 6. 跟代码同步的小技巧

- **找路由**：`backend/app/main.py:101-125` 注册了 24 个 router，全在 `app/api/`
- **找 state 转换的入口**：grep `current_state =` 在 `app/api/conversation.py` 看所有显式赋值
- **找发往前端的 rich message**：grep `rich_type=` 看产生方；前端消费方在 `frontend/src/components/conversation/RichMessageDispatcher.vue`
- **找异步事件**：`event_bus.py` 的 `publish_sync` / `publish_async` 调用方就是 SSE 推送源

---

## 下一步

- 看检索 phase 内部怎么编排 → [03-search-pipeline.md](./03-search-pipeline.md)
- 看 10 个 agent 各自做什么 → [04-agent-roles.md](./04-agent-roles.md)
