import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import {
  saveByokConfig,
  loadByokConfig,
  clearByokConfig,
  getByokActive,
  setByokActive,
  clearByokCache,
  type ByokConfig,
} from '@/api/byok_config'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))
vi.mock('@/data/sqlite/repos/settingsRepo', () => ({
  setSetting: vi.fn(),
  getSetting: vi.fn(),
  deleteSetting: vi.fn(),
}))

import { invoke } from '@tauri-apps/api/core'
import { setSetting, getSetting, deleteSetting } from '@/data/sqlite/repos/settingsRepo'

const sample: ByokConfig = {
  provider: 'openai',
  api_key: 'sk-test',
  model: 'gpt-4o',
  base_url: null,
  configured_at: 1714400000000,
}

describe('byok_config', () => {
  beforeEach(() => {
    clearByokCache()
    vi.clearAllMocks()
  })
  afterEach(() => {
    clearByokCache()
  })

  it('saveByokConfig 同步写 keychain + 设 byok_active=true', async () => {
    await saveByokConfig(sample)
    expect(invoke).toHaveBeenCalledWith('secure_set', {
      key: 'byok_config',
      value: JSON.stringify(sample),
    })
    expect(setSetting).toHaveBeenCalledWith('byok_active', 'true')
  })

  it('loadByokConfig 命中 cache 第二次不读 keychain', async () => {
    ;(invoke as any).mockResolvedValue(JSON.stringify(sample))
    const first = await loadByokConfig()
    const second = await loadByokConfig()
    expect(first).toEqual(sample)
    expect(second).toEqual(sample)
    expect(invoke).toHaveBeenCalledTimes(1)  // 第二次走 cache
  })

  it('clearByokConfig 删 keychain + 清 byok_active + invalidate cache', async () => {
    ;(invoke as any).mockResolvedValue(JSON.stringify(sample))
    await loadByokConfig()  // 先 cache
    await clearByokConfig()
    expect(invoke).toHaveBeenCalledWith('secure_delete', { key: 'byok_config' })
    expect(deleteSetting).toHaveBeenCalledWith('byok_active')
    // 清 cache 后再 loadByokConfig 读 keychain
    ;(invoke as any).mockResolvedValueOnce(null)
    const reloaded = await loadByokConfig()
    expect(reloaded).toBeNull()
  })

  it('getByokActive 读 settings; setByokActive 写 settings', async () => {
    ;(getSetting as any).mockResolvedValue('true')
    expect(await getByokActive()).toBe(true)

    await setByokActive(false)
    expect(setSetting).toHaveBeenCalledWith('byok_active', 'false')
  })
})
