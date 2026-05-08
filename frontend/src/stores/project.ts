import { defineStore } from 'pinia'
import { ref } from 'vue'
import { projectApi } from '../api/client'

export const useProjectStore = defineStore('project', () => {
  const current = ref<any>(null)
  const loading = ref(false)

  async function fetchProject(id: string) {
    loading.value = true
    try {
      const res = await projectApi.get(id)
      current.value = res.data
    } finally {
      loading.value = false
    }
  }

  function clear() {
    current.value = null
  }

  return { current, loading, fetchProject, clear }
})
