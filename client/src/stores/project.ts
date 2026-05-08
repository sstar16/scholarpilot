/**
 * Project store —— C5：list/get/upsert/delete 走本地 SQLite repo。
 *
 * 之前：fetchProject 调 backend `projectApi.get(id)` 把 backend ProjectOut 直接灌进 current.
 * 现在：直接读本地 sqlite（projectRepo），云端同步由后台 syncOrchestrator 负责。
 *
 * 兼容字段映射：view 里读 `project.search_config` / `project.title` / `project.domain` /
 * `project.domains` / `project.status` / `project.id` —— 全部都在 LocalProject 里有，
 * 多 0 transform。view 不用改。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  deleteProject,
  getProject,
  listProjects,
  type ListProjectsOptions,
  upsertProject,
} from '@/data/sqlite/repos/projectRepo'
import type { LocalProject } from '@/types/local'

export const useProjectStore = defineStore('project', () => {
  const current = ref<LocalProject | null>(null)
  const list = ref<LocalProject[]>([])
  const loading = ref(false)

  async function fetchProject(id: string): Promise<LocalProject | null> {
    loading.value = true
    try {
      const p = await getProject(id)
      current.value = p
      return p
    } finally {
      loading.value = false
    }
  }

  async function fetchList(opts: ListProjectsOptions = {}): Promise<LocalProject[]> {
    loading.value = true
    try {
      const items = await listProjects(opts)
      list.value = items
      return items
    } finally {
      loading.value = false
    }
  }

  async function upsert(p: LocalProject): Promise<void> {
    await upsertProject(p)
    if (current.value?.id === p.id) current.value = p
    const idx = list.value.findIndex((x) => x.id === p.id)
    if (idx >= 0) list.value[idx] = p
    else list.value = [p, ...list.value]
  }

  async function remove(id: string): Promise<void> {
    await deleteProject(id)
    if (current.value?.id === id) current.value = null
    list.value = list.value.filter((x) => x.id !== id)
  }

  function clear() {
    current.value = null
  }

  return {
    current,
    list,
    loading,
    fetchProject,
    fetchList,
    upsert,
    remove,
    clear,
  }
})
