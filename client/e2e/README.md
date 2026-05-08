# Client e2e tests (Playwright)

走 Vite dev server，不经过 Tauri runtime。所有 axios 请求被 `context.route` 拦截 mock，
所有 `@tauri-apps/api/core invoke` 通过 `__TAURI_INTERNALS__.invoke` 桩处理（secure_*/fs_*/log_*/plugin:sql|*）。

## 跑

```bash
cd client
npm run e2e            # headless
npm run e2e:headed     # 看浏览器
npm run e2e:debug      # 单步调试
npm run e2e:report     # 看 html report
```

首次跑需要安装 chromium：

```bash
npx playwright install chromium
```

playwright.config 已配 `webServer`：自动起 vite dev → 测完关。CI 环境也是同样行为。
本地 dev 时如果 5173 已在跑 vite，会 reuseExistingServer。

## 文件

| 文件 | LOC | 覆盖 |
|---|---|---|
| `fixtures/mockApi.ts` | 650 | Tauri invoke 桩 + axios route mock + 共享 state + `authedTest` fixture |
| `login.spec.ts` | 82 | 场景 1a：登录 / 注册 / 邀请码 / 校验 / 路由守卫 |
| `round.spec.ts` | 112 | 场景 1b：项目创建 / 对话页加载 / round 状态机 / 反馈 / 关键词计划 |
| `collaboration.spec.ts` | 65 | 场景 2：协作问答 + citations + 文献库 |
| `graph.spec.ts` | 70 | 场景 3：KG 数据形状 + ProjectView 路由 |
| `playwright.config.ts` | 61 | webServer / project / reporter / locale |

总测试数：**20 passed**

## 设计取舍（option B）

agent 选 option B（Vite dev server + mock）而不是真 Tauri，因为：

- Tauri `npm run tauri:dev` 首次 cargo 5-10 分钟，每次跑测试不现实
- 我们要测的是 Vue 视图 / 路由 / 状态机 / API 集成，不是 Tauri runtime（OS keychain / SQLite / IPC）
- Tauri 层的真实 e2e 应该是手测（M3 已有 58 个 vitest 单测覆盖 fs/sql/sync repo）

### Fixture 重要约定

**所有 test 必须 destructure `mockState`**（即使不用，加 `void mockState`）。否则
Playwright 不会激活 fixture，`__TAURI_INTERNALS__` 桩没注入 → 客户端 bootstrap
里 `Database.load`/`fs_*` 抛 "Cannot read properties of undefined (reading 'invoke')"
→ 整个 app 启动失败，body 被 catch 替换成"客户端启动失败：..."。

```ts
// 对：
test('xxx', async ({ page, mockState }) => { void mockState; ... })

// 错：
test('xxx', async ({ page }) => { ... })  // 没激活 mockState fixture，Tauri 桩没注入
```

`authedTest`（默认所有 spec 用的）会在 `mockState` 初始化时一并写入 fake token，
所以不用单独 preauth。

## 真 Tauri e2e 留给 user 手测的清单

- [ ] OS keychain：登录后 Win Credential Manager 看 `top.scholarpilot.client.access_token`
- [ ] SQLite migrations：注册后 `<AppData>/scholarpilot/scholarpilot.db` 11 表齐
- [ ] BYOK：Settings → 输 OpenAI key → 检索能用
- [ ] Logout 数据清除：`fs_remove projects/cache/exports`（CLAUDE.md M3 §10）
- [ ] PDF download：付费源 PatentHub 单轮 5 篇预算守门
- [ ] SSE：检索 round 真后端 status 推送（API mock 走 polling 状态机，不是真 SSE）
- [ ] Cytoscape 渲染：知识图谱节点真 SVG（vitest 已覆盖数据流，但渲染要真 DOM）
- [ ] 协作 ChatPanel 完整流：rich_type=collaboration_started → resumePlan → collaboration_answer

## Mock 状态

每个 test 独立的 `mockState`（fixture 提供），包括：

- 1 user：tester@scholarpilot.top
- 0 projects（按需 push）
- 3 documents：Transformer / BERT / GNN survey
- statusSequence：`fetching → scoring → summarizing → awaiting_feedback`（每次 GET status 推进）
- KG nodes/edges：4 节点 3 边（Transformer / BERT / Attention / NLP）

## 已知限制

- Vue Router 守卫依赖 `useAuthStore.ensureInit`，必须先 init secure_storage 才能跳 dashboard。
  `authedTest` 在 init script 阶段写假 token 解决。
- ChatPanel 的发送按钮用 paper-plane SVG 没文字，测试用 `Enter` 键触发更稳。
- KnowledgeGraph 路由 `/projects/:projectId/graph` 真有，但 KG 数据来源是
  客户端 GraphRepo（本地 SQLite），mock 不覆盖。e2e 验证数据 API + 容器可访问，
  渲染细节由 vitest `KnowledgeGraph.test.ts` 覆盖。
- ProjectView 拿数据走本地 `projectStore.fetchProject`（SQLite），不调 axios，
  所以 e2e 只验证页面骨架（`.project-view` 渲染）+ 路由可达，深层流程交给 vitest。
- `request.get/post`（playwright 自带 fetch）**不走 context.route**。如果要测
  API 形状，必须用 `fetchInPage(page, path, init)` helper（页面里 evaluate fetch
  → 经过 context.route）。

## 加新 spec

1. import：`import { authedTest as test, expect, fetchInPage } from './fixtures/mockApi'`
2. 测试签名：`async ({ page, mockState })`，没用到也加 `void mockState`
3. 网络验证：`fetchInPage(page, '/api/...', { method, body })` → 返回 `{ status, body }`
4. UI 验证：直接 `page.locator('...').click()` / `toBeVisible()`
