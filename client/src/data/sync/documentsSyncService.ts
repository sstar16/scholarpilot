/**
 * 客户端 PDF 下载 / 上传（per-user / per-project 本地维护）。
 *
 * **2026-05-08 sp-api 零本地 PDF 改造后**：客户端 100% 拥有 PDF I/O。
 * sp-api 只做两件事：
 *   - B 类：解析 landing 上的 citation_pdf_url meta，**只返 URL 字符串**
 *   - C 类：付费源 token stream proxy，httpx chunked 转发**不落盘**
 * A 类（OA 直链）由客户端 Rust 自抓三层兜底，sp-api 完全不参与。
 *
 * 三类源路由（参考 silentPdfReconciler.ts 同名常量保持一致）：
 *   A 类: pdf_fetch_direct（rust 内 5 层 stealth headers + L1/L2/L3 兜底）
 *   B 类: pdf_fetch_direct → 失败回退 pdf_fetch_via_resolve_url（sp-api 解析 URL → rust 自抓）
 *   C 类: pdf_fetch_via_proxy（sp-api stream → rust 边收边写）
 *
 * 用户主动选本地 PDF 文件上传 → uploadDocumentPdf 直接写客户端 fs + SQLite。
 */

import { invoke } from '@tauri-apps/api/core'
import { writeBytes, fileExists, PATHS, assertSafeId } from '@/data/fs/files'
import { getDocument, updateDocumentLocalPaths } from '@/data/sqlite/repos/documentRepo'
import { getProject } from '@/data/sqlite/repos/projectRepo'
import { secureGet, SECURE_KEYS } from '@/api/secure_storage'

export interface DownloadDocResult {
  documentId: string
  status: 'available' | 'skipped' | 'queued' | 'failed'
  reason?: string
  size?: number
  /** rust 报告的层级：direct/unpaywall/doi-meta/resolve-url/paid-stream/failed/budget */
  layer?: string
  /** patenthub 软超额时的 used/max（前端弹二次确认） */
  budgetExceeded?: { used: number; max: number; costPerPdf: number; clientRunId: string }
}

/** 与 silentPdfReconciler.ts 保持一致的源分类（单一真相在 reconciler）。 */
const PAID_SOURCES = new Set<string>([
  'patenthub', 'lens', 'lens_patent', 'epo_ops', 'bigquery_patents',
])
const LANDING_META_SOURCES = new Set<string>([
  'pubmed', 'dblp', 'clinical_trials', 'openalex_zh',
])

interface RustPdfResult {
  success: boolean
  local_path?: string | null
  size_bytes?: number | null
  error?: string | null
  layer_used?: string | null
}

function _spApiBase(): string {
  return (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://localhost:8000'
}

async function _authToken(): Promise<string> {
  const tok = await secureGet(SECURE_KEYS.ACCESS_TOKEN)
  return tok || ''
}

/**
 * 主动下载单篇 PDF 到客户端本地（三通道路由）。
 *
 * 失败不抛错，状态 + 原因写到 documents.fulltext_pdf_status。
 *
 * 返回 status：
 *   'skipped'   本地已有
 *   'available' 刚下完写本地成功
 *   'queued'    付费源软超额（402）→ 调用方需提示用户二次确认后带 force=true 重发
 *               (实现细节：文档约定保留 'queued' 语义，结合 budgetExceeded 字段)
 *   'failed'    所有通道都失败
 */
export async function downloadDocumentPdf(
  projectId: string,
  documentId: string,
  options: { force?: boolean; clientRunId?: string } = {},
): Promise<DownloadDocResult> {
  assertSafeId(projectId, 'projectId')
  assertSafeId(documentId, 'documentId')

  const doc = await getDocument(documentId)
  if (!doc) {
    return { documentId, status: 'failed', reason: 'document not found in local DB' }
  }

  const proj = await getProject(projectId)
  const projTitle = proj?.title || null
  const slugPath = PATHS.pdfFile(projectId, documentId, doc.title, projTitle)
  const legacyPath = PATHS.pdfFileLegacy(projectId, documentId)

  // Step 0: 本地已有？
  if (await fileExists(slugPath)) {
    await updateDocumentLocalPaths(documentId, {
      pdf_local_path: slugPath,
      fulltext_pdf_status: 'available',
      fulltext_status: 'available',
    })
    return { documentId, status: 'skipped', reason: 'already on disk (slug)' }
  }
  if (await fileExists(legacyPath)) {
    await updateDocumentLocalPaths(documentId, {
      pdf_local_path: legacyPath,
      fulltext_pdf_status: 'available',
      fulltext_status: 'available',
    })
    return { documentId, status: 'skipped', reason: 'already on disk (legacy UUID)' }
  }

  const source = (doc.source || '').toLowerCase()
  const isPaid = PAID_SOURCES.has(source)
  const isLandingMeta = LANDING_META_SOURCES.has(source)

  // Step 1: 路由到对应 rust 通道
  if (isPaid) {
    return _viaProxy(projectId, documentId, doc, options)
  }

  // A 类 + B 类先尝试 rust 直抓（doc.pdf_url 已知 / unpaywall / DOI-meta）
  const directResult = await _viaDirect(projectId, documentId, doc)
  if (directResult.status === 'available' || directResult.status === 'skipped') {
    return directResult
  }

  // B 类直抓失败 → 走 sp-api resolve-url 拿 URL 再 rust 抓
  if (isLandingMeta) {
    return _viaResolveUrl(projectId, documentId, doc)
  }

  // A 类直抓失败 — 没有进一步通道；统一持久化失败状态。
  await updateDocumentLocalPaths(documentId, { fulltext_pdf_status: 'failed' })
  return directResult
}

async function _viaDirect(
  projectId: string,
  documentId: string,
  doc: any,
): Promise<DownloadDocResult> {
  try {
    const r = await invoke<RustPdfResult>('pdf_fetch_direct', {
      req: {
        doc_id: documentId,
        source: doc.source || '',
        external_id: doc.external_id || null,
        doi: doc.doi || null,
        pdf_url: doc.pdf_url || null,
        landing_url: doc.url || null,
        project_id: projectId,
        timeout_secs: 5,
      },
    })
    if (r.success && r.local_path) {
      await updateDocumentLocalPaths(documentId, {
        pdf_local_path: `projects/${projectId}/pdfs/${documentId}.pdf`,
        fulltext_pdf_status: 'available',
        fulltext_status: 'available',
      })
      return {
        documentId,
        status: 'available',
        size: r.size_bytes ?? undefined,
        layer: r.layer_used ?? undefined,
      }
    }
    return {
      documentId,
      status: 'failed',
      reason: r.error || 'rust direct: unknown',
      layer: r.layer_used ?? 'failed',
    }
  } catch (e) {
    return { documentId, status: 'failed', reason: 'invoke direct failed: ' + (e as Error).message }
  }
}

async function _viaResolveUrl(
  projectId: string,
  documentId: string,
  doc: any,
): Promise<DownloadDocResult> {
  try {
    const r = await invoke<RustPdfResult>('pdf_fetch_via_resolve_url', {
      req: {
        doc_id: documentId,
        source: doc.source || '',
        external_id: doc.external_id || null,
        doi: doc.doi || null,
        pdf_url: doc.pdf_url || null,
        landing_url: doc.url || null,
        project_id: projectId,
        sp_api_base: _spApiBase(),
        auth_token: await _authToken(),
        timeout_secs: 25,
      },
    })
    if (r.success && r.local_path) {
      await updateDocumentLocalPaths(documentId, {
        pdf_local_path: `projects/${projectId}/pdfs/${documentId}.pdf`,
        fulltext_pdf_status: 'available',
        fulltext_status: 'available',
      })
      return {
        documentId,
        status: 'available',
        size: r.size_bytes ?? undefined,
        layer: r.layer_used ?? 'resolve-url',
      }
    }
    await updateDocumentLocalPaths(documentId, { fulltext_pdf_status: 'failed' })
    return {
      documentId,
      status: 'failed',
      reason: r.error || 'resolve-url failed',
      layer: r.layer_used ?? 'failed',
    }
  } catch (e) {
    await updateDocumentLocalPaths(documentId, { fulltext_pdf_status: 'failed' })
    return {
      documentId,
      status: 'failed',
      reason: 'invoke resolve-url failed: ' + (e as Error).message,
    }
  }
}

async function _viaProxy(
  projectId: string,
  documentId: string,
  doc: any,
  options: { force?: boolean; clientRunId?: string },
): Promise<DownloadDocResult> {
  const clientRunId = options.clientRunId || `${projectId}:${documentId}`
  if (!doc.external_id) {
    return {
      documentId,
      status: 'failed',
      reason: 'paid source missing external_id',
    }
  }
  try {
    const r = await invoke<RustPdfResult>('pdf_fetch_via_proxy', {
      req: {
        doc_id: documentId,
        source: doc.source || '',
        external_id: doc.external_id,
        doi: doc.doi || null,
        pdf_url: doc.pdf_url || null,
        project_id: projectId,
        client_run_id: clientRunId,
        force: !!options.force,
        sp_api_base: _spApiBase(),
        auth_token: await _authToken(),
        timeout_secs: 120,
      },
    })
    if (r.success && r.local_path) {
      await updateDocumentLocalPaths(documentId, {
        pdf_local_path: `projects/${projectId}/pdfs/${documentId}.pdf`,
        fulltext_pdf_status: 'available',
        fulltext_status: 'available',
      })
      return {
        documentId,
        status: 'available',
        size: r.size_bytes ?? undefined,
        layer: r.layer_used ?? 'paid-stream',
      }
    }
    // 软超额（402） — rust 把 detail JSON 塞 error 字段，prefix=BUDGET_EXCEEDED:
    if (r.error && r.error.startsWith('BUDGET_EXCEEDED:')) {
      const raw = r.error.slice('BUDGET_EXCEEDED:'.length)
      let parsed: any = null
      try { parsed = JSON.parse(raw) } catch { /* ignore */ }
      const detail = parsed?.detail ?? parsed ?? {}
      return {
        documentId,
        status: 'queued',  // 复用 queued 语义：等用户二次确认
        reason: detail.message || 'patenthub budget exceeded',
        layer: 'budget',
        budgetExceeded: {
          used: detail.used ?? 0,
          max: detail.max ?? 0,
          costPerPdf: detail.cost_per_pdf ?? 1.1,
          clientRunId: detail.client_run_id ?? clientRunId,
        },
      }
    }
    await updateDocumentLocalPaths(documentId, { fulltext_pdf_status: 'failed' })
    return {
      documentId,
      status: 'failed',
      reason: r.error || 'proxy failed',
      layer: r.layer_used ?? 'failed',
    }
  } catch (e) {
    await updateDocumentLocalPaths(documentId, { fulltext_pdf_status: 'failed' })
    return {
      documentId,
      status: 'failed',
      reason: 'invoke proxy failed: ' + (e as Error).message,
    }
  }
}

/**
 * 用户从本地选 PDF 文件上传到客户端 — 直接写本地 fs + SQLite，不 push 服务端。
 */
export async function uploadDocumentPdf(
  projectId: string,
  documentId: string,
  bytes: Uint8Array,
): Promise<{ relPath: string; size: number }> {
  assertSafeId(projectId, 'projectId')
  assertSafeId(documentId, 'documentId')

  const relPath = PATHS.pdfFile(projectId, documentId)
  await writeBytes(relPath, bytes)
  await updateDocumentLocalPaths(documentId, {
    pdf_local_path: relPath,
    fulltext_pdf_status: 'available',
    fulltext_status: 'available',
  })
  return { relPath, size: bytes.byteLength }
}

/**
 * 删除某篇 PDF 的本地副本（保留 SQLite document 记录但清掉 pdf_local_path）。
 */
export async function removeDocumentPdf(
  projectId: string,
  documentId: string,
): Promise<void> {
  assertSafeId(projectId, 'projectId')
  assertSafeId(documentId, 'documentId')
  const relPath = PATHS.pdfFile(projectId, documentId)
  const { removePath } = await import('@/data/fs/files')
  if (await fileExists(relPath)) {
    await removePath(relPath)
  }
  await updateDocumentLocalPaths(documentId, {
    pdf_local_path: null,
    fulltext_pdf_status: 'not_attempted',
  })
}
