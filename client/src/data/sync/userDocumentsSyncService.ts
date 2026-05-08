/**
 * 0028 client side: PDF 多设备 ownership 同步。
 *
 * 三个核心函数：
 * - syncOwnedDocuments(projectId?) : 拉云端 ownership list → 本地 doc 没文件的标记
 *   `fulltext_pdf_status='downloading'`，让 silentPdfReconciler（commit 3）感知触发下载
 * - markUploaded(pid, did, format, syncToCloud) : 用户上传 PDF 后调，告诉 backend
 *   "我自己留了一份"。syncToCloud=true 走 uploaded_synced（binary 也送 backend，
 *   commit 4 UI 给开关），syncToCloud=false 走 uploaded_local（不送 binary）
 * - markUnowned(pid, did, format) : 用户主动删本地副本时调，云端记 owned=false →
 *   多设备一致（spec Q5=A：B 删除则 A 也删）
 *
 * 设计约束：
 * - downloadDocumentPdf 路径**不**调 markOwn — backend 的 GET /file 已经在内部
 *   自动写 ownership（commit 1b 的 hook），客户端不要重复
 * - syncOwnedDocuments 不直接拉 binary，只是"标记意图"，binary 拉取由 reconciler
 *   按配额 / 重试 / 并发处理
 */

import { userDocsApi, type OwnedDocumentDto } from '@/api/client'
import { getDocument, updateDocumentLocalPaths } from '@/data/sqlite/repos/documentRepo'

export class OwnershipSyncError extends Error {
  constructor(message: string, public cause?: unknown) {
    super(message)
    this.name = 'OwnershipSyncError'
  }
}

export interface SyncOwnedResult {
  /** 云端返回多少 owned 记录 */
  pulled: number
  /** 其中本地无 PDF 文件、需要静默下载的篇数 */
  pendingDownload: number
  /** 跳过的篇数（已经在本地，或源是 uploaded_local 没法从 backend 拉） */
  skipped: number
  syncedAtMs: number
}

/**
 * 拉云端 ownership 列表 → 本地 documents 表打 `fulltext_pdf_status='downloading'` 信号。
 *
 * 不传 projectId = 拉用户所有项目的 ownership（首登用，谨慎，配额吞）。
 * 一般场景传当前 projectId（spec Q3=A：进项目时触发）。
 *
 * 不抓 binary — 那是 reconciler 的职责（commit 3）。
 */
export async function syncOwnedDocuments(projectId?: string): Promise<SyncOwnedResult> {
  let items: OwnedDocumentDto[]
  try {
    const r = await userDocsApi.listOwned(projectId, 'pdf')
    items = r.data.items
  } catch (err) {
    throw new OwnershipSyncError(
      'owned docs sync failed: ' + (err as Error).message,
      err,
    )
  }

  const now = Date.now()
  let pendingDownload = 0
  let skipped = 0

  for (const item of items) {
    // 本地还没 doc 元数据（可能跨项目尚未 sync round_documents）→ 跳过
    // reconciler 会在下次进 round 时再补
    const local = await getDocument(item.document_id)
    if (!local) {
      skipped++
      continue
    }

    // 已在本地 fs（pdf_local_path set）→ 跳过
    if (local.pdf_local_path) {
      skipped++
      continue
    }

    // uploaded_local 源 backend 没 binary，标记 downloading 也下不到，跳过
    // （用户在另一台设备的纯本地上传，本设备无法自动同步那份）
    if (item.source === 'uploaded_local') {
      skipped++
      continue
    }

    // downloaded / uploaded_synced：标记 downloading，让 reconciler 拉 binary
    await updateDocumentLocalPaths(item.document_id, {
      fulltext_pdf_status: 'downloading',
    })
    pendingDownload++
  }

  return {
    pulled: items.length,
    pendingDownload,
    skipped,
    syncedAtMs: now,
  }
}

/**
 * 用户上传 PDF 后调（uploadDocumentPdf 已写本地后）。
 *
 * @param syncToCloud true → uploaded_synced（binary 也送 backend，多设备能拉），
 *                    false → uploaded_local（仅本机 + 标记，最隐私）
 */
export async function markUploaded(
  projectId: string,
  documentId: string,
  format: 'pdf' | 'html' = 'pdf',
  syncToCloud = false,
): Promise<void> {
  await userDocsApi.markOwn(projectId, documentId, {
    source: syncToCloud ? 'uploaded_synced' : 'uploaded_local',
    format,
  })
}

/**
 * 用户主动删除本地副本时调，让云端 owned 记录 = removed → 多设备一致。
 */
export async function markUnowned(
  projectId: string,
  documentId: string,
  format: 'pdf' | 'html' = 'pdf',
): Promise<void> {
  await userDocsApi.markUnown(projectId, documentId, format)
}
