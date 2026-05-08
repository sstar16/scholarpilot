import { ref, computed, watch, type Ref } from 'vue'
import { featuresApi } from '@/api/client'

export interface FeatureResult {
  allowed: boolean
  scene: string
  feature: string
  reason?: string | null
  suggested_action?: { trigger: string; label: string } | null
}

export type FeatureMap = {
  new_round: FeatureResult
  collaboration: FeatureResult
  schedule: FeatureResult
  pdf_import: FeatureResult
}

export function useFeatureGate(projectId: Ref<string | null>) {
  const results = ref<FeatureMap | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh() {
    if (!projectId.value) {
      results.value = null
      return
    }
    loading.value = true
    error.value = null
    try {
      const resp = await featuresApi.checkAll(projectId.value)
      results.value = resp.data as FeatureMap
    } catch (e: any) {
      error.value = e?.message ?? 'fetch failed'
    } finally {
      loading.value = false
    }
  }

  watch(projectId, () => { refresh() }, { immediate: true })

  const canNewRound = computed(() => results.value?.new_round.allowed ?? false)
  const canCollaborate = computed(() => results.value?.collaboration.allowed ?? false)
  const canSchedule = computed(() => results.value?.schedule.allowed ?? false)
  const canPdfImport = computed(() => results.value?.pdf_import.allowed ?? false)

  return {
    results,
    loading,
    error,
    refresh,
    canNewRound,
    canCollaborate,
    canSchedule,
    canPdfImport,
  }
}
