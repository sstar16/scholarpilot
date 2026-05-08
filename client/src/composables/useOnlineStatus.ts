import { ref, onMounted, onUnmounted, computed } from 'vue'

/**
 * 网络在线状态。**仅** navigator.onLine —— 客户端 100% 本地数据
 * （PRD §C8 改造后无云同步业务），所以不再有 sync 状态机 / lastSyncAt 等。
 *
 * UI 用法：仅在 `online === false` 时显示 indicator（在线状态不打扰用户）。
 */
export function useOnlineStatus() {
  const online = ref<boolean>(navigator.onLine)

  function _setOnline() { online.value = true }
  function _setOffline() { online.value = false }

  onMounted(() => {
    window.addEventListener('online', _setOnline)
    window.addEventListener('offline', _setOffline)
  })

  onUnmounted(() => {
    window.removeEventListener('online', _setOnline)
    window.removeEventListener('offline', _setOffline)
  })

  const label = computed<string>(() => online.value ? '在线' : '离线')
  const tone = computed<'ok' | 'err'>(() => online.value ? 'ok' : 'err')

  return { online, label, tone }
}
