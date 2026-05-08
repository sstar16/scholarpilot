import { ref } from 'vue'
import pLimit from 'p-limit'
import { uploadApi } from '@/api/client'

export interface ImportProgressItem {
  filename: string
  percent: number
  status: 'queued' | 'uploading' | 'parsing' | 'done' | 'failed' | 'cancelled'
  jobId?: string
  documentId?: string
  errorMsg?: string
}

export function usePdfImport(
  projectId: () => string | undefined,
  sessionId: () => string | undefined,
) {
  const items = ref<ImportProgressItem[]>([])
  const limit = pLimit(3)

  async function uploadFiles(files: File[]) {
    const baseIdx = items.value.length
    const newItems: ImportProgressItem[] = files.map((f) => ({
      filename: f.name,
      percent: 0,
      status: 'queued',
    }))
    items.value.push(...newItems)

    await Promise.all(
      files.map((file, i) =>
        limit(async () => {
          const item = items.value[baseIdx + i]
          const pid = projectId()
          const sid = sessionId()
          if (!pid || !sid) {
            item.status = 'failed'
            item.errorMsg = '项目或会话未就绪'
            return
          }
          item.status = 'uploading'
          try {
            const resp = await uploadApi.importPdf(
              pid, sid, file,
              (pct) => { item.percent = pct },
            )
            item.jobId = resp.data.job_id
            item.documentId = resp.data.document_id
            item.status = 'parsing'
          } catch (e: any) {
            item.status = 'failed'
            item.errorMsg = e?.response?.data?.detail || '上传失败'
          }
        }),
      ),
    )
  }

  function reset() {
    items.value = []
  }

  return { items, uploadFiles, reset }
}
