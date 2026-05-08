/**
 * Library store —— C5：文献库 list 来自本地 SQLite document_classifications + documents，
 * detail 来自 library/docs/<docId>.md。
 *
 * 之前：调 `libraryApi.list/detail/rebuild/deleteBatch` 全 backend.
 * 现在：
 *   - list / groupedFiles：listClassificationsByProject + getDocumentsByIds
 *   - detail (selectFile)：LiteratureWriter.readDoc(slug=docId)
 *   - rebuild：从本地数据重写 library/index.md
 *   - deleteBatch：删 classification + delete .md
 *
 * 兼容性：保留 `slug` 字段（== docId，不再 backend 那种 SEO slug）；view 里 `slug` 当 key 用。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { LiteratureWriter, type LibraryDoc } from '@/data/fs/literatureWriter'
import { fileExists, removePath } from '@/data/fs/files'
import { PATHS } from '@/data/fs/paths'
import {
  deleteClassification,
  listClassificationsByProject,
  type ClientBucket,
} from '@/data/sqlite/repos/bucketRepo'
import { getDocumentsByIds } from '@/data/sqlite/repos/documentRepo'
import { getProject } from '@/data/sqlite/repos/projectRepo'
import type { LocalDocument } from '@/types/local'

// View 端期望的 list / detail 形状（保 1:1 兼容旧 LibraryFile / LibraryDetailResponse）
export interface LibraryFile {
  slug: string                       // == docId
  title: string
  title_zh?: string | null
  authors_short: string
  year?: number | null
  bucket?: string | null
  quality_score?: number | null
  updated_at?: string | null
  extract_status?: string | null
  document_id?: string | null
  source?: string | null
  external_id?: string | null
  doi?: string | null
  url?: string | null
  pdf_url?: string | null
}

export interface LibraryDetailResponse {
  slug: string
  frontmatter: Record<string, unknown>
  body_md: string
  raw: string
}

function _yearFromPubDate(pubDate?: string | null): number | null {
  if (!pubDate) return null
  const m = /^(\d{4})/.exec(pubDate)
  return m ? parseInt(m[1], 10) : null
}

function _authorsShort(authors?: string | null): string {
  if (!authors) return '未知'
  const list = authors.split(/[,;]/).map((s) => s.trim()).filter(Boolean)
  if (list.length === 0) return '未知'
  if (list.length === 1) return list[0]
  return `${list[0]} 等`
}

function _docToLibFile(d: LocalDocument, bucket: ClientBucket | null): LibraryFile {
  return {
    slug: d.id,
    title: d.title,
    title_zh: d.title_zh ?? null,
    authors_short: _authorsShort(d.authors),
    year: _yearFromPubDate(d.publication_date),
    bucket,
    quality_score: d.quality_score ?? null,
    updated_at: d.last_synced_at ? new Date(d.last_synced_at).toISOString() : null,
    extract_status: d.fulltext_status,
    document_id: d.id,
    source: d.source,
    external_id: d.external_id,
    doi: d.doi,
    url: d.url,
    pdf_url: d.pdf_url,
  }
}

function _docToLibraryWriterDoc(d: LocalDocument, bucket: ClientBucket | null): LibraryDoc {
  return {
    docId: d.id,
    title: d.title,
    authors: d.authors ?? '',
    year: _yearFromPubDate(d.publication_date),
    source: d.source,
    doi: d.doi,
    oneLineSummary: d.one_line_summary_user ?? d.one_line_summary ?? null,
    summary: d.ai_summary_user ?? d.ai_summary ?? null,
    keyPoints: d.ai_key_points_user ?? d.ai_key_points ?? null,
    score: d.quality_score ?? null,
    bucket: bucket ?? 'uncategorized',
    tags: d.concept_tags ?? null,
    journal: d.journal ?? null,
    url: d.url ?? null,
  }
}

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
  const selectedSlugs = ref<Set<string>>(new Set())
  const deleting = ref(false)

  const filteredFiles = computed<LibraryFile[]>(() => {
    const { bucket, search } = filter.value
    return files.value.filter((f) => {
      if (bucket !== 'all' && (f.bucket || 'uncategorized') !== bucket) {
        return false
      }
      if (search) {
        const q = search.toLowerCase()
        const hit =
          f.title.toLowerCase().includes(q)
          || (f.title_zh || '').toLowerCase().includes(q)
          || f.authors_short.toLowerCase().includes(q)
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

  async function loadFiles(projectId: string): Promise<void> {
    loading.value = true
    try {
      const classifications = await listClassificationsByProject(projectId)
      const bucketByDoc = new Map<string, ClientBucket>()
      for (const c of classifications) bucketByDoc.set(c.document_id, c.bucket)
      const docIds = Array.from(bucketByDoc.keys())
      const docs = await getDocumentsByIds(docIds)
      files.value = docs.map((d) => _docToLibFile(d, bucketByDoc.get(d.id) ?? null))
      total.value = files.value.length
      const counts: Record<string, number> = {}
      for (const f of files.value) {
        const k = f.bucket || 'uncategorized'
        counts[k] = (counts[k] ?? 0) + 1
      }
      byBucket.value = counts
    } finally {
      loading.value = false
    }
  }

  async function selectFile(projectId: string, slug: string): Promise<void> {
    selectedSlug.value = slug
    const cached = detailCache.value[slug]
    if (cached) {
      currentDetail.value = cached
      return
    }
    detailLoading.value = true
    try {
      const project = await getProject(projectId)
      const writer = new LiteratureWriter(projectId, project?.title ?? null)
      const parsed = await writer.readDoc(slug)
      if (!parsed) {
        // 文件还没生成 → 用 SQLite 数据现场拼一份占位
        const docs = await getDocumentsByIds([slug])
        const d = docs[0]
        if (d) {
          const fallback: LibraryDetailResponse = {
            slug,
            frontmatter: {
              doc_id: d.id,
              title: d.title,
              authors: d.authors ?? '',
              year: _yearFromPubDate(d.publication_date) ?? '',
              source: d.source,
              doi: d.doi ?? '',
              bucket: '',
            },
            body_md: `# ${d.title}\n\n${d.ai_summary ?? d.abstract ?? ''}`,
            raw: '',
          }
          currentDetail.value = fallback
          detailCache.value[slug] = fallback
        } else {
          currentDetail.value = null
        }
        return
      }
      const detail: LibraryDetailResponse = {
        slug,
        frontmatter: parsed.frontmatter as Record<string, unknown>,
        body_md: parsed.body,
        raw: '',
      }
      currentDetail.value = detail
      detailCache.value[slug] = detail
    } finally {
      detailLoading.value = false
    }
  }

  function clearDetail() {
    selectedSlug.value = null
    currentDetail.value = null
  }

  async function triggerRebuild(projectId: string): Promise<void> {
    rebuilding.value = true
    try {
      const project = await getProject(projectId)
      const writer = new LiteratureWriter(projectId, project?.title ?? null)
      // 重写每篇 doc.md + 重写 index.md
      const classifications = await listClassificationsByProject(projectId)
      const bucketByDoc = new Map<string, ClientBucket>()
      for (const c of classifications) bucketByDoc.set(c.document_id, c.bucket)
      const docs = await getDocumentsByIds(Array.from(bucketByDoc.keys()))
      const writerDocs = docs.map((d) => _docToLibraryWriterDoc(d, bucketByDoc.get(d.id) ?? null))
      for (const wd of writerDocs) {
        try {
          await writer.writeDoc(wd)
        } catch (e) {
          console.warn('[library] rebuild writeDoc failed:', wd.docId, e)
        }
      }
      await writer.writeIndex(writerDocs)
      detailCache.value = {}
      await loadFiles(projectId)
    } finally {
      rebuilding.value = false
    }
  }

  function setFilter(partial: Partial<{ bucket: string; search: string }>) {
    filter.value = { ...filter.value, ...partial }
  }

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

  /**
   * 批量删除：仅从当前项目的 library 移除（删 classification + 删 .md），不删全局 documents 表。
   * 单条失败收集到 failed[]，整体不抛。
   */
  async function deleteSelected(projectId: string): Promise<{ deleted: number; failed: string[] }> {
    const slugs = Array.from(selectedSlugs.value)
    if (!slugs.length) return { deleted: 0, failed: [] }
    deleting.value = true
    const failed: string[] = []
    try {
      const project = await getProject(projectId)
      const projTitle = project?.title ?? null
      for (const slug of slugs) {
        try {
          await deleteClassification(projectId, slug)
          // 删 .md（不存在不算失败）—— 这里 slug == docId，命名同 LiteratureWriter
          const safe = slug.replace(/[^A-Za-z0-9._\-]/g, '-').replace(/-+/g, '-').replace(/^-+|-+$/g, '')
          const rel = `${PATHS.projectRoot(projectId, projTitle)}/library/docs/${safe}.md`
          if (await fileExists(rel)) {
            await removePath(rel)
          }
        } catch (e) {
          console.warn('[library] deleteSelected failed for slug:', slug, e)
          failed.push(slug)
        }
      }
      const ok = new Set(slugs.filter((s) => !failed.includes(s)))
      files.value = files.value.filter((f) => !ok.has(f.slug))
      total.value = files.value.length
      if (selectedSlug.value && ok.has(selectedSlug.value)) {
        selectedSlug.value = null
        currentDetail.value = null
      }
      clearSelection()
      return { deleted: ok.size, failed }
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
    selectedSlugs,
    deleting,
    toggleSelect,
    selectAll,
    clearSelection,
    deleteSelected,
  }
})
