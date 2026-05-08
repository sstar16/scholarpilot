import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { notebookApi, type NotebookPage } from '../api/client'

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

  async function fetchPages(pid: string) {
    projectId.value = pid
    loading.value = true
    try {
      const r = await notebookApi.listPages(pid)
      pages.value = r.data.pages || []
      // 选页面：若当前页被删或未选 → 选第一个
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
    const r = await notebookApi.createPage(projectId.value, {
      title,
      body_md: bodyMd,
    })
    await fetchPages(projectId.value)
    currentPageId.value = r.data.id
    return r.data
  }

  async function updateCurrentPage(patch: { title?: string; body_md?: string }) {
    if (!projectId.value || !currentPageId.value) return null
    saving.value = true
    try {
      const r = await notebookApi.updatePage(projectId.value, currentPageId.value, patch)
      const idx = pages.value.findIndex((p) => p.id === currentPageId.value)
      if (idx >= 0) pages.value[idx] = r.data
      return r.data
    } finally {
      saving.value = false
    }
  }

  async function deletePage(pageId: string) {
    if (!projectId.value) return
    await notebookApi.deletePage(projectId.value, pageId)
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
