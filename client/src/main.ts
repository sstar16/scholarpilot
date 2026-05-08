import { createApp } from 'vue'
import { createPinia } from 'pinia'
// Element Plus 组件按需 import 由 unplugin-vue-components 自动接管（vite.config.ts）
// CSS 也是按需注入，App.vue 用 <el-config-provider :locale="zhCn"> 处理国际化
// 但 icons 必须保留全量 register —— 模板里 <Folder/> <Setting/> <ArrowLeft/> <Edit/> 等用法
// 散落在很多组件，没在文件内 import；按需改 39 个文件成本极高，icons-vue 整包 gzip ~50KB
// 全量 register 是性价比最高方案（A2.1 移除 register 引入回归 bug，2026-05-01 fix）
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import './assets/design-system.css'
import App from './App.vue'
import { router } from './router'
import { invoke } from '@tauri-apps/api/core'
import { initDatabase } from '@/data/sqlite/connection'
import { hydrateApiCache } from '@/api/client'
import { llmManager } from '@/data/llm/manager'

// ── 全局 webview 错误捕获 → Rust log ──────────────────────────────────────
// 之前 webview JS 报错只能 F12 看, 关掉窗口就丢。打包后 .msi 用户连 F12
// 都不一定开, 排查无门。这里把 window.error / unhandledrejection /
// console.error 三类全转发到 Rust 端写 logs/ScholarPilot.log, 用户给我
// 一份 log 文件就能定位。
function _logToRust(level: 'error' | 'warn', message: string, source?: string) {
  // 截断避免单条 log 过大 (Rust log 同步写文件)
  const msg = message.length > 4000 ? message.slice(0, 4000) + '...[trunc]' : message
  invoke('log_webview_error', { level, message: msg, source }).catch(() => {})
}

window.addEventListener('error', (e) => {
  const stack = (e.error?.stack ?? '').slice(0, 3000)
  _logToRust(
    'error',
    `${e.message}\n  at ${e.filename}:${e.lineno}:${e.colno}\n${stack}`,
    'window.error',
  )
})

window.addEventListener('unhandledrejection', (e) => {
  const reason = (e.reason?.stack || String(e.reason)).slice(0, 3000)
  _logToRust('error', `unhandledrejection: ${reason}`, 'window.unhandledrejection')
})

const _origConsoleError = console.error.bind(console)
console.error = (...args: unknown[]) => {
  _origConsoleError(...args)
  try {
    const text = args
      .map((a) => (a as Error)?.stack || (typeof a === 'object' ? JSON.stringify(a) : String(a)))
      .join(' ')
    _logToRust('error', text, 'console.error')
  } catch { /* ignore */ }
}

async function bootstrap() {
  // 必须先 init DB 再 mount 组件，否则组件 onMounted 调 repo 时单例还没有
  await initDatabase()

  // 启动时 ensure 必要目录骨架（projects/cache/thumbnails/logs/exports/memory）—
  // 让 ls AppData/.../top.scholarpilot.client/ 一眼能看到客户端在做什么
  // 失败不阻塞启动（fs_* commands 仍会 lazy mkdir 自己用的子路径）
  try {
    await invoke('fs_ensure_app_dirs')
  } catch (e) {
    console.warn('[startup] fs_ensure_app_dirs failed:', e)
  }

  // A1: hydrate ApiClient module-level cache（access_token + byok_active + byok_config）
  // 拦截器之后纯同步读 cache，避免每个请求 3 次 IPC
  await hydrateApiCache()

  // 100% BYOK：从 keychain 读 BYOK 配置，构造 active LLM provider 单例
  // 不阻塞启动 — 没配 BYOK 时 _activeProvider 为 null，调用方各自 fallback
  try {
    await llmManager.init()
  } catch (e) {
    console.warn('[startup] llmManager.init failed:', e)
  }

  const app = createApp(App)
  const pinia = createPinia()

  // Icons 全量 register
  for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component)
  }

  app.use(pinia)
  app.use(router)

  app.mount('#app')

  // PRD §C8: 删除旧 sync orchestrator —— 客户端走本地 SQLite 直读，写本地后通过 sp-api
  // event 推到 server。startupHydrate / hydrateProject / hydrateRoundResults 全部不再需要。
  // TODO(C5): 如有需要，重新接 sp-api WebSocket 拉云端单向变更。
}

bootstrap().catch((err) => {
  console.error('App bootstrap failed:', err)
  document.body.innerHTML =
    `<div style="padding:2rem;font-family:system-ui">客户端启动失败：${(err as Error).message}</div>`
})
