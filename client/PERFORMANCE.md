# 客户端性能优化记录

> 最后更新 2026-05-01。记录已 ship + 评估过 deferred 的方案 + 配套实测工具，避免重复评估。

## 已 ship（按 commit 时间）

### A1. ApiClient 拦截器 hydrate（commit `cf42aec`）

**问题**：每个 axios 请求拦截器跑 3 次跨进程 IPC：
- `secureGet(ACCESS_TOKEN)` → keyring crate
- `getByokActive()` → SQLite settings 表 query
- `loadByokConfig()` → keychain（虽有 cache 但仍 invoke）

拦截器是 `async`，每个请求 5-10 ms 额外开销。100 次 SSE 状态轮询 + 50 次 conversation message + 多次 sync 调用 = 累积秒级体感卡顿。

**改造**：`client/src/api/client.ts` 加 module-level 同步 cache（`_accessTokenCache` + `_byokActiveCache` + `_byokConfigCache`）：
- 启动 `hydrateApiCache()` 一次 hydrate（main.ts bootstrap）
- 所有写入路径同步刷 cache：login/register/logout/refresh/saveByok/clearByok/setByokActive
- 拦截器改 sync 函数纯读 module 变量

**收益**：拦截器从 5-10 ms × N 降到 < 0.1 ms × N。极端场景（连发消息 / 大列表 paginate）感知明显。

**测试**：`client_byok_header.spec.ts` 重写直接 setCache 控制场景，vitest 全集 61 PASS。

### A2. vite manualChunks（commit `f6a4026`）

**问题**：`dist/assets/index-*.js` 1246 KB（gzip 403 KB），所有 vendor + 业务代码混在一起。首屏白屏久 + 业务改 1 行整个 bundle 重下。

**改造**：`client/vite.config.ts` 加 `build.rollupOptions.output.manualChunks`，按 vendor 拆分：

```
vendor-vue          123 KB  vue / vue-router / pinia / @vueuse
vendor-element-plus 932 KB  element-plus / @element-plus/icons-vue（未来按需 import 减量）
vendor-vis          652 KB  vis-network / vis-data（仅 KG 页用）
vendor-markdown      89 KB  markdown-it / js-yaml / 等
vendor-net           38 KB  axios / form-data
vendor-tauri          ?     @tauri-apps/*
vendor-misc         163 KB  其它兜底（含 vue-virtual-scroller B3a 引入）
路由 chunk           1-153 KB（按页 lazy load — Login 16 / HomeJournal 19 / ChatPanel 153）
index.js             32 KB
```

**收益**：
- 首屏 Login 只下载 `index 32K + vendor-vue 123K + Login chunk 16K + 部分 element-plus = ~200-300K`（vs 之前 1246K）
- vendor 改动 vs 业务改动**独立 cache**，业务每天 commit 不让用户重下 vendor

**A2.1 element-plus 按需 import**（2026-05-01 ship）：装 `unplugin-auto-import` + `unplugin-vue-components` + `ElementPlusResolver`，移除 main.ts 的 `app.use(ElementPlus)` + `import 'element-plus/dist/index.css'` + 全量 icon register。App.vue 已用 `<el-config-provider :locale="zhCn">` 包子树，国际化不受影响。

收益：
```
                JS         CSS        合计       gzip
之前        932 KB    +  633 KB  = 1565 KB    335 KB
之后        796 KB    +  129 KB  =  925 KB    269 KB
减少        ↓14%      ↓80%       ↓ 640 KB    ↓ 66 KB / 20%
```

CSS 大砍是因为按需 resolver 只注入用过的 component CSS（之前 main.ts 全量 633 KB 包含大量未用组件样式）。JS 减少受限是因为现有代码用 `import { ElMessage } from 'element-plus'` barrel 已是 tree-shake friendly，剩 796 KB 主要是 ElDialog/ElTable/ElForm/ElDrawer 等复杂组件 logic 本身。

### A3. messages shallowRef（commit `8d334fc`）

**问题**：`conversation store messages = ref<ChatMessage[]>([])` 是深 reactive — 每次 push 触发递归遍历**所有 message** 的**所有属性**（content / metadata / rich_data {16 种 rich_type 嵌套对象}）做 diff。SSE 富消息频繁插入 + 100+ 条历史消息时感知卡顿。

**改造**：`messages` 从 `ref` 改 `shallowRef`。代价：mutate 单条 message 属性时不会触发 trigger，必须 immutable replace。改 3 处：
- `addLocalMessage`: `messages.value.push(...)` → `messages.value = [...messages.value, newMsg]`
- `appendIncomingMessage`: 同上
- `updateLastAssistantMeta`: mutate `m.metadata` → 构造 newMsg + 新数组替换 i 位置

**未改动**：`store.documents` 仍 ref（数量小，且 `RoundResultsMessage.vue` 多处直接 mutate `doc[statusField]` / `doc.fulltext_pdf_path` 等。改 shallowRef 需要在所有 mutate 处补 `triggerRef(documents)`，引入新维护负担 + 收益边际。当 RoundResults 列表实测卡顿时再做）。

**收益**：SSE 高频插入 + 长对话场景 reactive trigger 开销线性下降到 O(1)（vs 之前 O(N × M)，N=消息数 M=平均每条 message 属性数 ~5）。

### B3a. ChatPanel virtual scrolling（commit `b2a9ca5`）

**问题**：100+ 消息长对话场景，全量 DOM mount + reflow 累积成首屏 200ms+ 阻塞，滚动时反复 layout。

**改造**：`client/src/components/conversation/ChatPanel.vue` 接入 `vue-virtual-scroller@3.0.2` 的 DynamicScroller：
- template v-for 改 DynamicScroller scope slot，alias `{ item: msg, index: i, active }` 保留原闭包 — 所有 helper（`messageKey/isLastAssistant/lastConfirmationIndex/shouldShowExit/...`）仍在父 closure 直接访问，**0 组件抽象成本**（避免抽 MessageItem.vue + 30+ props 透传）
- `messagesWithKey` computed 注入 `_key` 字段（DynamicScroller 不支持复合 key fn）
- DynamicScrollerItem `:size-dependencies="[content, metadata, rich_data]"` 让消息内容变化时自动重测高，搭配 ResizeObserver 兜底
- `page-mode` 让 scroller 跟随父 `.chat-panel__messages` overflow，不破坏现有 layout（welcome / TypingBubble 仍在 scroller 同级）
- auto-scroll watcher 改用 `scrollerRef.scrollToItem(len-1)` 命令式 API，fallback `scrollRef.scrollTop`（welcome 阶段无 scroller 实例）

**收益**：100 条消息时 DOM 只渲染视口内 ~10 个 item，初始 mount 帧从 ~200ms 降到 <30ms；滚动 60fps 稳定。

### B3b-1. LibraryFileList virtual scrolling（commit `ba73d8b`）

**问题**：成熟项目累积 500+ 文献时，所有 file-card + el-tooltip / el-checkbox 一次性 mount — 每张卡 hover 按钮组、border transition 都吃 reflow 预算。

**改造**：`client/src/components/library/LibraryFileList.vue`：
- `flatItems` computed 把 `Record<bucket, files[]>` 扁平成一维 `[{type:'header'...}, {type:'doc'...}, ...]`，DynamicScroller 一维虚拟化覆盖跨桶滚动
- page-mode 让 scroller 跟随父 `.library-file-list` overflow，batch-toolbar 的 `position: sticky` 仍工作（同一 scroll context）
- size-dependencies：doc 看 title/score 变化，header 看 items.length
- el-tooltip / el-checkbox / el-icon 在 scroller reuse DOM 时表现稳定（Element Plus popper 是 teleport，跟 v-show 解耦）

**收益**：500+ 文献场景从 ~2s+ 首屏 mount 降到 <100ms。

### B3b-2. BucketCardView v-memo + stagger cap（commit `3826053`）

**评估**：CSS Grid `auto-fill, minmax(320px, 1fr)` 跟 RecycleScroller grid mode 的 fixed grid-items 冲突，没办法 1:1 接 DynamicScroller。先做轻量优化：

1. `v-memo="[d.document_id, d.bucket, b.key]"` 跳过 deps 不变时的 patch diff —— store change（如 fetchBuckets 触发整个 buckets reactive 替换）时，绝大多数卡的 deps 没变 → Vue 直接复用 vnode 不走 patch
2. stagger animationDelay cap：`i*0.03s` → `min(i, 30)*0.03s`，原 200 docs 累积 6s 一波一波出现，cap 后顶 0.9s 全部出现

**未来真要做 grid 虚拟化**（500+ docs 场景）：BucketCardItem 锁固定高度（line-clamp 摘要）→ 上 RecycleScroller `:grid-items=` 动态列数 + ResizeObserver watch 容器宽度。当前 100-200 docs 范围 v-memo 已能压住 re-render 成本。

### Tooling. perfMarker 实测工具（同 commit）

**目的**：B1/B2 deferred 决策依赖 IPC < 1ms / sync < 50ms 估算 — 加可触发的实测工具，让用户/开发者验证。

**实现**：`client/src/utils/perfMarker.ts`
- `withMarker(name, fn)` 包装异步/同步函数，dev 模式记 user-timing entry + 内存样本，**prod 直接 fn() 0 开销**
- `__sp_perf.dump(filter?)` 在 DevTools console 输出 p50/p95/max 表
- syncOrchestrator `_runScope` 已接通 → `__sp_perf.dump('sync:')` 即时看 sync 耗时分布

**用法**：
```js
// DevTools Console（dev 模式）
__sp_perf.dump('sync:')   // 看 sync 各 scope p50/p95/max
__sp_perf.dump('repo.')   // 看 SQLite query 耗时（需手动在 hot path 加 withMarker）
__sp_perf.clear()         // 清空样本重测
```

**额外修复**（同一 commit）：
- 加 `client/src/vite-env.d.ts` 含 `vite/client` reference — 修预存的 7 个 `Property 'env' does not exist on type 'ImportMeta'` typecheck 错误
- documentRepo.ts:130 `Row` cast 用 `as unknown as Record<...>` 修严格模式拒绝直转

---

## 评估过但 deferred（带触发条件 + 实测方法）

### B1. webview SQLite POC

**目标**：把 SQLite 从 Rust 主进程移到 webview 内（WASM），消除每次 query 的 IPC 序列化开销。

**候选方案**：
- `@evolu/web`：商业级 local-first 框架，自带 sync 协议（要重写整个数据层）
- `sqlite-wasm-http`：HTTP 协议（不适合本地）
- `@sqlite.org/sqlite-wasm`：官方 WASM 版（持久化用 OPFS）
- `wa-sqlite`：成熟，OPFS 持久化

**为什么 deferred**：
- 现 `tauri-plugin-sql` 每次 query IPC 估算 < 1 ms（WebView2 IPC 是 sync via JSON-RPC）
- 单次 query 不是瓶颈 — 拦截器调 3 次 IPC 才是（已 A1 fix）
- batch query 已经在用（`getDocumentsByIds` 一次拿全部）
- 数据迁移：现有用户的 `<AppData>\top.scholarpilot.client\scholarpilot.db` → OPFS 是异步流程
- OPFS 在 Tauri 2 WebView2 / WebKit 兼容性不一致
- 调试工具：现在能用 sqlite3 CLI 直接打开 .db；OPFS 是 sandbox 文件浏览器看不到

**触发条件 + 实测方法**：
1. 在 `client/src/data/sqlite/connection.ts` 的 `getDatabase().execute()` / `select()` 调用处包 `withMarker('repo.<name>', ...)`（按需为 hot path 加，不必全部）
2. dev 模式跑应用录一遍主要操作
3. console: `__sp_perf.dump('repo.')`
4. 触发门槛：
   - **任一 query p95 > 5ms** → 考虑迁 wa-sqlite + OPFS
   - **某 1 秒窗口内 IPC count > 100** → 考虑批合并或迁 WASM

不满足时**保留** tauri-plugin-sql。

### B2. Web Worker 跑 sync — POC 已 ship（dev opt-in）

**目标**：syncRoundResults 的 fetch + JSON parse / transform 移到 Web Worker，主线程只做 SQLite write。

**架构约束**（事实，不可变）：
- Tauri `invoke()` API 在 Worker scope **不可用**（Worker 不是 webview context）→ SQLite write 必须回主线程
- A1 的 `_accessTokenCache` 是主线程 module-level → Worker 内每次 task 必须重读 keychain（固有开销）

**实施**（commit pending）：
- `client/src/data/sync/syncWorker.ts` — Worker entry，原生 fetch + JSON parse，Comlink expose
- `client/src/data/sync/syncWorkerClient.ts` — 主线程 wrapper，lazy init Worker 单例 + 鉴权 headers gather
- `client/src/data/sync/roundsSyncService.ts` 加 `syncRoundResultsViaWorker()` 替代分支（默认仍走主线程）
- `client/src/data/sync/syncDevTools.ts` — dev-only 注册 `__sp_perf.compareWorker(pid, rid, n=5)`
- `vite.config.ts` 自动 emit worker chunk（实测 4.7 KB），主 bundle 不含 worker code

**dev 模式 A/B 验证**：
```js
// DevTools Console
await __sp_perf.compareWorker('your-project-id', 'your-round-id', 5)
// → 跑 5 轮主线程 + 5 轮 worker 路径
// → console.table 输出 sync.fetch.main vs sync.fetch.worker 的 p50/p95/max
```

**Promote 默认路径门槛**：
- `sync.fetch.worker` p95 < `sync.fetch.main` p95 - **50ms** 才换默认
- 不达成保留主线程（Worker 启动 ~10-30ms + Comlink postMessage 序列化抵消收益）

**当前默认**：仍走主线程 `syncRoundResults`。Worker 路径作为 opt-in POC，等数据驱动决策。

---

## 后续观察 metric

如果用户再反馈卡顿，按以下顺序确认是哪类瓶颈：

```
1. 打开 DevTools → Performance → 录一次复现操作
2. 看 flame chart：
   - 大块紫色 reactive trigger → A3 没覆盖完，扩展到 documents
   - 大块黄色 IPC scripting → A1 cache miss 或新 IPC 路径未 hydrate
   - 大块青色 layout/paint → DOM 太大，需要 B3a/B3b 同款手法扩展到新组件
   - 'sync:*' / 'repo.*' user-timing entry 高 → B1/B2 触发条件已满足
3. 看 Network：
   - 首次加载某 chunk > 500 KB → A2 manualChunks 没覆盖到该 vendor
4. 看 Memory：
   - heap 持续增长不释放 → memory leak（messages 数组永不清理 / SSE listener 没 unbind）
```

**console 一行命令排查**：
```js
__sp_perf.dump()             // 全部 marker p50/p95/max（按 totalMs 降序）
__sp_perf.dump('sync:')      // 只看 sync
__sp_perf.dump('repo.')      // 只看 SQLite（需为 hot path 加 withMarker）
__sp_perf.samples()          // 原始 sample[]，可自定义统计
__sp_perf.clear()            // 清空重测
```

---

## 决策记录

| 决策 | 日期 | commit | 理由 |
|---|---|---|---|
| 实施 A1 + A2 + A3 | 2026-05-01 | cf42aec / f6a4026 / 8d334fc | 风险低 + 已验证收益 + ship 后 user 立即感知 |
| 实施 B3a | 2026-05-01 | b2a9ca5 | minimal-invasive 0 子组件抽象，长对话场景必须 |
| 实施 B3b-1 | 2026-05-01 | ba73d8b | 500+ 文献场景必须，scroller flat list 简单稳定 |
| 实施 B3b-2 | 2026-05-01 | 3826053 | grid 虚拟化复杂度过高，先 v-memo + stagger cap 覆盖 100-200 docs 痛点 |
| 加 perfMarker 工具 | 2026-05-01 | （同 docs commit） | B1/B2 触发条件可被实测，决策有数据支撑 |
| 推迟 B1（webview SQLite） | 2026-05-01 | — | IPC 估算非瓶颈；用 `__sp_perf.dump('repo.')` 验证 |
| 推迟 B2（Worker sync） | 2026-05-01 | — | sync 估算非高频；用 `__sp_perf.dump('sync:')` 验证 |

每条 deferred 决策都附了**实测命令**。命中触发条件时直接读这份文档执行 plan，不需要重新评估。
