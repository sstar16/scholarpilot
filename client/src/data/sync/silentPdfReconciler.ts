/**
 * 0028 silent PDF reconciler — 实际触发本地缺失 PDF 的批量下载。
 *
 * 工作流（spec docs/spec-pdf-ownership-sync.md §3.2）：
 * 1. 调 userDocsApi.listOwned(projectId, 'pdf') 拿当前用户在该 project 的 ownership list
 * 2. _filterPending 过滤：跳 uploaded_local（backend 没 binary）+ 跳已在本地的
 * 3. 应用每日配额（默认 100/天，settings 表持久化跨进程）
 * 4. 并发 N（默认 3）调 downloadDocumentPdf 拉 binary
 * 5. 单篇失败 → 指数退避重试 (10s / 30s / 90s)
 *
 * PRD §C8（2026-05-08）：原 syncOrchestrator.hydrateProject 已删；调用方现直接
 * `import { reconcileSilent } from '@/data/sync/silentPdfReconciler'` 自行 fire-and-forget。
 */

import { type OwnedDocumentDto } from '@/api/client'
import { downloadDocumentPdf } from './documentsSyncService'
import { getDocument, updateDocumentLocalPaths } from '@/data/sqlite/repos/documentRepo'
import { getSetting, setSetting } from '@/data/sqlite/repos/settingsRepo'
import { getDatabase } from '@/data/sqlite/connection'
import { invoke } from '@tauri-apps/api/core'

// 2026-05-08：sp-api 零本地 PDF 改造后三通道路由
//
//   A 类 OA 直链 (arxiv / openalex / europe_pmc / crossref / semantic_scholar)
//     → rust `pdf_fetch_direct` 自抓三层兜底，sp-api 不参与
//
//   B 类 landing-meta (pubmed / dblp / clinical_trials / openalex_zh)
//     → rust 先试 `pdf_fetch_direct`（万一 doc 已带 pdf_url 直接命中）
//     → 失败：rust `pdf_fetch_via_resolve_url` 调 sp-api resolve-url 拿 URL，
//       再客户端自抓 binary。sp-api 端不下载 binary。
//
//   C 类付费源 (patenthub / lens / epo_ops / bigquery_patents)
//     → rust `pdf_fetch_via_proxy` 调 sp-api stream proxy，
//       sp-api 用 token 调付费 API，httpx stream chunked 转发，**0 落盘**。
//       402 = 软超额；前端弹二次确认，用户确认后带 force=true 重发。
const PAID_SOURCES = new Set<string>([
  'patenthub',
  'lens',
  'lens_patent',
  'epo_ops',
  'bigquery_patents',
])

// B 类（landing 上有 citation_pdf_url meta，sp-api 服务端代解析）
const LANDING_META_SOURCES = new Set<string>([
  'pubmed',
  'dblp',
  'clinical_trials',
  'openalex_zh',
])

// 标记: '__SP_DISABLE_RUST_PDF__' 全局可由测试 / E2E 关掉 rust 通道。
const _isRustDisabled = (): boolean => {
  return typeof globalThis !== 'undefined'
    && (globalThis as any).__SP_DISABLE_RUST_PDF__ === true
}

const SETTING_KEY_DAILY_COUNT = 'silent_pdf_daily_count'
const SETTING_KEY_DAILY_DATE = 'silent_pdf_daily_date'

export const RECONCILER_DEFAULTS = {
  dailyCap: 100,
  concurrency: 3,
  retryDelaysMs: [10_000, 30_000, 90_000] as const,
}

export interface ReconcileOptions {
  dailyCap?: number
  concurrency?: number
  /** 注入 retry delays 给单测（默认 [10s, 30s, 90s]） */
  retryDelaysMs?: readonly number[]
  /** 注入 sleep 实现给单测（默认 setTimeout-based） */
  sleep?: (ms: number) => Promise<void>
}

export interface ReconcileResult {
  /** 实际启动下载的篇数 */
  attempted: number
  /** 下载成功 */
  succeeded: number
  /** 下载失败（重试用尽） */
  failed: number
  /** 因每日配额耗尽未下的 */
  capped: number
  /** filter 阶段跳过的（uploaded_local / 已在本地 / 元数据缺失） */
  skipped: number
}

// ── 进度事件机制（给 UI composable 订阅）──────────────────────────────

export type ReconcileEvent =
  | { kind: 'started'; projectId: string; total: number }
  | { kind: 'progress'; projectId: string; completed: number; total: number; lastDocId: string; lastSucceeded: boolean }
  | { kind: 'finished'; projectId: string; result: ReconcileResult }

type ReconcileListener = (e: ReconcileEvent) => void

const _listeners = new Set<ReconcileListener>()

export function onReconcileEvent(fn: ReconcileListener): () => void {
  _listeners.add(fn)
  return () => _listeners.delete(fn)
}

function _emit(e: ReconcileEvent): void {
  // 异步 emit (queueMicrotask) — 避免 reconciler worker 完成一篇时同步触发
  // listener (useSilentPdfSync 改 reactive ref / SilentSyncIndicator re-render)
  // 跟 Vue scheduler 在处理 ElDrawer transition 子树 patch 时撞上, 触发
  // 'instance.update is not a function' patch race。
  // 延后 1 个 microtask = 当前 JS 执行栈完 + Vue patch loop 完, 再分发事件。
  queueMicrotask(() => {
    for (const fn of _listeners) {
      try { fn(e) } catch { /* ignore listener errors */ }
    }
  })
}

function _todayKey(): string {
  return new Date().toISOString().slice(0, 10)  // YYYY-MM-DD UTC
}

/**
 * 读今日已消耗配额；如果跨日则重置为 0。
 */
export async function getDailyConsumed(): Promise<number> {
  const today = _todayKey()
  const storedDate = await getSetting(SETTING_KEY_DAILY_DATE)
  if (storedDate !== today) {
    await setSetting(SETTING_KEY_DAILY_DATE, today)
    await setSetting(SETTING_KEY_DAILY_COUNT, '0')
    return 0
  }
  const count = await getSetting(SETTING_KEY_DAILY_COUNT)
  return count ? parseInt(count, 10) : 0
}

async function _incrementDailyConsumed(by = 1): Promise<void> {
  const today = _todayKey()
  await setSetting(SETTING_KEY_DAILY_DATE, today)
  const current = await getDailyConsumed()
  await setSetting(SETTING_KEY_DAILY_COUNT, String(current + by))
}

/**
 * 过滤出"实际可下载"的子集：跳 uploaded_local（backend 无 binary）+ 跳本地已有 +
 * 跳本地缺元数据的（doc 还没被 round sync 写下来）。
 */
export async function filterPending(items: OwnedDocumentDto[]): Promise<OwnedDocumentDto[]> {
  const out: OwnedDocumentDto[] = []
  for (const item of items) {
    if (item.source === 'uploaded_local') continue
    const local = await getDocument(item.document_id)
    if (!local) continue
    if (local.pdf_local_path) continue
    out.push(item)
  }
  return out
}

function _defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * 三通道路由由 ``documentsSyncService.downloadDocumentPdf`` 统一负责，本函数
 * 只关心"该 doc 是否最终落到本地"。reconciler 跳过付费源（PAID_SOURCES）
 * 静默批量下载 — 那些有真金白银成本，只响应用户主动点击。
 *
 * 测试钩子 ``__SP_DISABLE_RUST_PDF__`` 早期是用来在 vitest 跳过 rust invoke，
 * 现在 downloadDocumentPdf 内部全部 invoke rust，禁用钩子已不影响 silent 路径
 * （vitest 的 mock 是 ``vi.mock('@/data/sync/documentsSyncService')``）。
 */
async function _downloadOnce(
  projectId: string,
  documentId: string,
): Promise<boolean> {
  const doc = await getDocument(documentId)
  if (!doc) return false

  const source = (doc.source || '').toLowerCase()

  // 付费源跳过 silent 批量（用户实际点击时由 documentsSyncService 走 _viaProxy）
  if (PAID_SOURCES.has(source)) {
    return false
  }

  try {
    const r = await downloadDocumentPdf(projectId, documentId)
    return r.status === 'available' || r.status === 'skipped'
  } catch {
    return false
  }
}

// 把测试钩子标为 used（防 TS6133，仍允许测试 spy 全局变量）
void _isRustDisabled
void invoke

async function _downloadWithRetry(
  projectId: string,
  documentId: string,
  _retryDelaysMs: readonly number[],
  _sleep: (ms: number) => Promise<void>,
): Promise<boolean> {
  // 单次尝试: rust 5s + sp-api 单次 = 单篇 < 30s, 100 篇 / 3 worker ≈ 17min 上限。
  // retry 早已被废 (上一版用户实测 99% 失败是源站 403 / backend 404, retry 没意义),
  // 现在双通道一次试两种通道, 仍 fail 就交给下次 reconciler。
  return _downloadOnce(projectId, documentId)
}

async function _processBatch(
  projectId: string,
  items: OwnedDocumentDto[],
  concurrency: number,
  retryDelaysMs: readonly number[],
  sleep: (ms: number) => Promise<void>,
): Promise<{ succeeded: number; failed: number }> {
  let succeeded = 0
  let failed = 0
  let cursor = 0
  let completed = 0

  async function worker() {
    while (true) {
      const idx = cursor++
      if (idx >= items.length) return
      const item = items[idx]
      const ok = await _downloadWithRetry(
        projectId,
        item.document_id,
        retryDelaysMs,
        sleep,
      )
      if (ok) succeeded++
      else failed++
      completed++
      _emit({
        kind: 'progress',
        projectId,
        completed,
        total: items.length,
        lastDocId: item.document_id,
        lastSucceeded: ok,
      })
      // 配额累计放到批次结束后一次性写 — 并发 worker 同时 read-modify-write
      // 会丢失更新（两个 worker 都拿 0 都写 1，应该是 2）
    }
  }

  const workers = Array.from(
    { length: Math.min(concurrency, items.length) },
    () => worker(),
  )
  await Promise.all(workers)

  return { succeeded, failed }
}

/**
 * 主入口：拉云端 ownership → 过滤 → 配额 → 并发下载。
 *
 * 失败不抛错（fire-and-forget 模式），返回 stats 给 UI 展示。
 */
export async function reconcileSilent(
  projectId: string,
  options: ReconcileOptions = {},
): Promise<ReconcileResult> {
  const dailyCap = options.dailyCap ?? RECONCILER_DEFAULTS.dailyCap
  const concurrency = options.concurrency ?? RECONCILER_DEFAULTS.concurrency
  const retryDelaysMs = options.retryDelaysMs ?? RECONCILER_DEFAULTS.retryDelaysMs
  const sleep = options.sleep ?? _defaultSleep

  // 用户期望: "进项目把 backend 该项目下所有 PDF 都下到本地"。
  //
  // ⚠️ 之前用 fulltext_pdf_status='available' 过滤, 但发现 SQLite 这字段不可信:
  //   - hydrateRoundResults 写 SQLite 时 backend 返的 status 经常是 'not_attempted'
  //   - documentsSyncService.downloadDocumentPdf 写文件后调 updateDocumentLocalPaths
  //     标 'available', 但下一次 hydrateRoundResults 又被 backend 'not_attempted' 覆盖
  //   - 用户实测 462 doc 中 0 个 status='available' 但 fs 有 11 个 PDF -> 数据不一致
  //
  // 改成: SELECT 该项目**所有有下载源**的 doc (pdf_url / doi / patenthub external_id
  // 任一非空), 不依赖 status 字段。每个 doc 调 downloadDocumentPdf:
  //   - 内部 fileExists(slug 路径 / legacy 路径) -> 本地有就 skip + 顺便修 SQLite
  //   - 本地没 -> GET /file 拿 binary 写本地 (backend 已有 PDF) 或 POST /download-fulltext
  //     trigger Celery (backend 也没 PDF)
  // 单一 source of truth = fs 实际有没有, 不看 backend status。
  let items: OwnedDocumentDto[]
  try {
    const db = getDatabase()
    const rows = await db.select<{ document_id: string }>(
      `SELECT DISTINCT d.id AS document_id
       FROM documents d
       JOIN round_documents rd ON rd.document_id = d.id
       JOIN search_rounds sr ON sr.id = rd.round_id
       WHERE sr.project_id = ?
         AND (
           (d.pdf_url IS NOT NULL AND d.pdf_url != '')
           OR (d.doi IS NOT NULL AND d.doi != '')
           OR d.source = 'patenthub'
         )`,
      [projectId],
    )
    // 构造 OwnedDocumentDto 兼容形 (filterPending 只用 source !== 'uploaded_local' 判断)
    items = rows.map((r) => ({
      document_id: r.document_id,
      project_id: projectId,
      source: 'downloaded' as const,
      format: 'pdf' as const,
      owned_at: new Date().toISOString(),
      last_seen_at: new Date().toISOString(),
    })) as unknown as OwnedDocumentDto[]
  } catch (e) {
    console.warn('[reconcileSilent] SQLite query failed:', e)
    return { attempted: 0, succeeded: 0, failed: 0, capped: 0, skipped: 0 }
  }

  const pending = await filterPending(items)
  const skipped = items.length - pending.length

  if (pending.length === 0) {
    return { attempted: 0, succeeded: 0, failed: 0, capped: 0, skipped }
  }

  const consumed = await getDailyConsumed()
  const remaining = Math.max(0, dailyCap - consumed)
  const willAttempt = pending.slice(0, remaining)
  const capped = pending.length - willAttempt.length

  if (willAttempt.length === 0) {
    const r: ReconcileResult = { attempted: 0, succeeded: 0, failed: 0, capped, skipped }
    _emit({ kind: 'finished', projectId, result: r })
    return r
  }

  _emit({ kind: 'started', projectId, total: willAttempt.length })

  const { succeeded, failed } = await _processBatch(
    projectId,
    willAttempt,
    concurrency,
    retryDelaysMs,
    sleep,
  )

  // 批次结束一次性扣配额（成功篇数）— 避免并发 worker race
  if (succeeded > 0) {
    const today = _todayKey()
    await setSetting(SETTING_KEY_DAILY_DATE, today)
    const after = (await getDailyConsumed()) + succeeded
    await setSetting(SETTING_KEY_DAILY_COUNT, String(after))
  }

  const result: ReconcileResult = {
    attempted: willAttempt.length,
    succeeded,
    failed,
    capped,
    skipped,
  }
  _emit({ kind: 'finished', projectId, result })
  return result
}
