/**
 * Notebook store —— C5：pages 走本地 SQLite。
 *
 * 之前：调 `notebookApi.listPages/createPage/updatePage/deletePage` 全 backend.
 * 现在：调 notebookRepo（research_note_pages 表）。
 *
 * applyAiUpdate 由 AI 后台 hook 触发；本地 page 替换由 collaboration store 走 notebookRepo
 * upsert，再调 fetchPages 刷新视图。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  deleteNotebookPage,
  getNotebookPage,
  listPagesByProject,
  upsertNotebookPage,
} from '@/data/sqlite/repos/notebookRepo'
import type { LocalNotebookPage } from '@/types/local'

export type NotebookPage = LocalNotebookPage

export interface AiNoteUpdate {
  mode: 'create_page' | 'update_page' | 'append_to_page'
  page_id: string
  title: string
  reason: string
  prev_len: number
  new_len: number
  preview: string
  at: string  // client-side ISO
}

function _genId(): string {
  return `local-${crypto.randomUUID()}`
}

export const useNotebookStore = defineStore('notebook', () => {
  const projectId = ref<string | null>(null)
  const pages = ref<NotebookPage[]>([])
  const currentPageId = ref<string | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const panelOpen = ref(false)
  const lastAiUpdate = ref<AiNoteUpdate | null>(null)

  const currentPage = computed<NotebookPage | null>(
    () => pages.value.find((p) => p.id === currentPageId.value) || null,
  )

  async function fetchPages(pid: string): Promise<void> {
    projectId.value = pid
    loading.value = true
    try {
      pages.value = await listPagesByProject(pid)
      if (!currentPageId.value || !pages.value.find((p) => p.id === currentPageId.value)) {
        currentPageId.value = pages.value[0]?.id || null
      }
    } finally {
      loading.value = false
    }
  }

  function selectPage(id: string) {
    currentPageId.value = id
  }

  async function createPage(title?: string, bodyMd?: string): Promise<NotebookPage | null> {
    if (!projectId.value) return null
    const now = Date.now()
    const sortOrder = pages.value.length
      ? Math.max(...pages.value.map((p) => p.sort_order)) + 1
      : 0
    const page: NotebookPage = {
      id: _genId(),
      project_id: projectId.value,
      title: title || '未命名页',
      body_md: bodyMd || '',
      sort_order: sortOrder,
      updated_at: now,
      updated_by: 'user',
      created_at: now,
      last_synced_at: null,
    }
    await upsertNotebookPage(page)
    await fetchPages(projectId.value)
    currentPageId.value = page.id
    return page
  }

  async function updateCurrentPage(patch: { title?: string; body_md?: string }): Promise<NotebookPage | null> {
    if (!projectId.value || !currentPageId.value) return null
    saving.value = true
    try {
      const existing = await getNotebookPage(currentPageId.value)
      if (!existing) return null
      const updated: NotebookPage = {
        ...existing,
        title: patch.title ?? existing.title,
        body_md: patch.body_md ?? existing.body_md,
        updated_at: Date.now(),
        updated_by: 'user',
      }
      await upsertNotebookPage(updated)
      const idx = pages.value.findIndex((p) => p.id === updated.id)
      if (idx >= 0) pages.value[idx] = updated
      return updated
    } finally {
      saving.value = false
    }
  }

  async function deletePage(pageId: string): Promise<void> {
    if (!projectId.value) return
    await deleteNotebookPage(pageId)
    await fetchPages(projectId.value)
  }

  function openPanel(pid?: string) {
    panelOpen.value = true
    const target = pid || projectId.value
    if (target) {
      projectId.value = target
      fetchPages(target).catch(() => { /* ignore */ })
    }
  }

  function closePanel() {
    panelOpen.value = false
  }

  /**
   * AI 在 collaboration respond 后若触发了 note_update，由 collaboration store 调用此方法：
   * - 更新 lastAiUpdate（触发 toast）
   * - 拉最新 pages
   * - 切换到被 AI 写入的页面
   *
   * AI 的 page 写入由 collaboration store 内部直接 upsertNotebookPage —— 这里只负责
   * 视图侧通知 + 刷新。
   */
  function applyAiUpdate(update: {
    mode: string
    page_id: string
    title: string
    reason: string
    prev_len: number
    new_len: number
    preview?: string
  }) {
    lastAiUpdate.value = {
      mode: update.mode as AiNoteUpdate['mode'],
      page_id: update.page_id,
      title: update.title,
      reason: update.reason || '',
      prev_len: update.prev_len || 0,
      new_len: update.new_len || 0,
      preview: update.preview || '',
      at: new Date().toISOString(),
    }
    if (projectId.value) {
      fetchPages(projectId.value)
        .then(() => {
          if (update.page_id) currentPageId.value = update.page_id
        })
        .catch(() => { /* ignore */ })
    }
  }

  function dismissAiUpdate() {
    lastAiUpdate.value = null
  }

  function reset() {
    projectId.value = null
    pages.value = []
    currentPageId.value = null
    loading.value = false
    saving.value = false
    panelOpen.value = false
    lastAiUpdate.value = null
  }

  return {
    projectId,
    pages,
    currentPageId,
    loading,
    saving,
    panelOpen,
    lastAiUpdate,
    currentPage,
    fetchPages,
    selectPage,
    createPage,
    updateCurrentPage,
    deletePage,
    openPanel,
    closePanel,
    applyAiUpdate,
    dismissAiUpdate,
    reset,
  }
})
