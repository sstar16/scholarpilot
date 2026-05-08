import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  libraryApi,
  type LibraryFile,
  type LibraryDetailResponse,
} from '../api/client'

export const useLibraryStore = defineStore('library', () => {
  const files = ref<LibraryFile[]>([])
  const total = ref(0)
  const byBucket = ref<Record<string, number>>({})
  const selectedSlug = ref<string | null>(null)
  const currentDetail = ref<LibraryDetailResponse | null>(null)
  const loading = ref(false)
  const detailLoading = ref(false)
  const rebuilding = ref(false)
  const filter = ref<{ bucket: string; search: string }>({
    bucket: 'all',
    search: '',
  })
  const detailCache = ref<Record<string, LibraryDetailResponse>>({})

  const filteredFiles = computed<LibraryFile[]>(() => {
    const { bucket, search } = filter.value
    return files.value.filter((f) => {
      if (bucket !== 'all' && (f.bucket || 'uncategorized') !== bucket) {
        return false
      }
      if (search) {
        const q = search.toLowerCase()
        const hit =
          f.title.toLowerCase().includes(q) ||
          (f.title_zh || '').toLowerCase().includes(q) ||
          f.authors_short.toLowerCase().includes(q)
        if (!hit) return false
      }
      return true
    })
  })

  const groupedFiles = computed<Record<string, LibraryFile[]>>(() => {
    const groups: Record<string, LibraryFile[]> = {
      very_relevant: [],
      relevant: [],
      uncertain: [],
      irrelevant: [],
      uncategorized: [],
    }
    for (const f of filteredFiles.value) {
      const b = f.bucket || 'uncategorized'
      if (!groups[b]) groups[b] = []
      groups[b].push(f)
    }
    return groups
  })

  async function loadFiles(projectId: string) {
    loading.value = true
    try {
      const res = await libraryApi.list(projectId)
      files.value = res.data.files
      total.value = res.data.total
      byBucket.value = res.data.by_bucket
    } finally {
      loading.value = false
    }
  }

  async function selectFile(projectId: string, slug: string) {
    selectedSlug.value = slug
    const cached = detailCache.value[slug]
    if (cached) {
      currentDetail.value = cached
      return
    }
    detailLoading.value = true
    try {
      const res = await libraryApi.detail(projectId, slug)
      currentDetail.value = res.data
      detailCache.value[slug] = res.data
    } finally {
      detailLoading.value = false
    }
  }

  function clearDetail() {
    selectedSlug.value = null
    currentDetail.value = null
  }

  async function triggerRebuild(projectId: string) {
    rebuilding.value = true
    try {
      await libraryApi.rebuild(projectId)
    } finally {
      setTimeout(() => {
        rebuilding.value = false
        loadFiles(projectId)
      }, 2000)
    }
  }

  function setFilter(partial: Partial<{ bucket: string; search: string }>) {
    filter.value = { ...filter.value, ...partial }
  }

  // P1: 多选 + 批量删除状态
  const selectedSlugs = ref<Set<string>>(new Set())
  const deleting = ref(false)

  function toggleSelect(slug: string) {
    const next = new Set(selectedSlugs.value)
    if (next.has(slug)) next.delete(slug)
    else next.add(slug)
    selectedSlugs.value = next
  }
  function selectAll(slugs: string[]) {
    selectedSlugs.value = new Set(slugs)
  }
  function clearSelection() {
    selectedSlugs.value = new Set()
  }

  async function deleteSelected(projectId: string): Promise<{ deleted: number; failed: string[] }> {
    const slugs = Array.from(selectedSlugs.value)
    if (!slugs.length) return { deleted: 0, failed: [] }
    deleting.value = true
    try {
      const res = await libraryApi.deleteBatch(projectId, slugs)
      // 本地乐观移除已成功的
      const ok = new Set(slugs.filter((s) => !res.data.failed.includes(s)))
      files.value = files.value.filter((f) => !ok.has(f.slug))
      total.value = res.data.remaining_total >= 0 ? res.data.remaining_total : files.value.length
      if (selectedSlug.value && ok.has(selectedSlug.value)) {
        selectedSlug.value = null
        currentDetail.value = null
      }
      clearSelection()
      return { deleted: res.data.deleted, failed: res.data.failed }
    } finally {
      deleting.value = false
    }
  }

  return {
    files,
    total,
    byBucket,
    selectedSlug,
    currentDetail,
    loading,
    detailLoading,
    rebuilding,
    filter,
    filteredFiles,
    groupedFiles,
    loadFiles,
    selectFile,
    clearDetail,
    triggerRebuild,
    setFilter,
    // P1 批量删除
    selectedSlugs,
    deleting,
    toggleSelect,
    selectAll,
    clearSelection,
    deleteSelected,
  }
})
