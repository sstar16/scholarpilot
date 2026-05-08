/**
 * M3: BYOK（Bring Your Own Key）配置管理。
 *
 * 数据流：
 * - keychain (`SECURE_KEYS.BYOK_CONFIG`)：完整配置 JSON（含 api_key 明文）
 * - settings 表 (`byok_active`)：开关；为 'true' 时 ApiClient 拦截器才注入 X-User-LLM-* header
 * - in-memory cache：避免每次请求都跨 Tauri IPC 读 keychain
 *
 * 调用约定：
 * - saveByokConfig 自动设 byok_active='true' + invalidate cache
 * - clearByokConfig 删 keychain + 删 byok_active + invalidate cache
 * - setByokActive 仅切开关，不动 keychain（用户暂时禁用但保留配置）
 */
import { invoke } from '@tauri-apps/api/core'

import { SECURE_KEYS } from './secure_storage'
import { setSetting, getSetting, deleteSetting } from '@/data/sqlite/repos/settingsRepo'
import { setByokActiveCache, setByokConfigCache } from './client'

export type ByokProvider = 'openai' | 'anthropic' | 'deepseek' | 'moonshot' | 'custom'

export interface ByokConfig {
  provider: ByokProvider
  api_key: string
  model: string | null
  base_url: string | null
  configured_at: number
}

let _cache: ByokConfig | null = null
let _cached = false

/** 单测专用 — 强制清 cache。生产代码应通过 save/clear 自动 invalidate。 */
export function clearByokCache(): void {
  _cache = null
  _cached = false
}

export async function saveByokConfig(cfg: ByokConfig): Promise<void> {
  await invoke('secure_set', {
    key: SECURE_KEYS.BYOK_CONFIG,
    value: JSON.stringify(cfg),
  })
  await setSetting('byok_active', 'true')
  _cache = cfg
  _cached = true
  // A1: 同步刷 ApiClient module cache，请求拦截器立即用新配置
  setByokConfigCache(cfg)
  setByokActiveCache(true)
}

export async function loadByokConfig(): Promise<ByokConfig | null> {
  if (_cached) return _cache
  const raw = await invoke<string | null>('secure_get', { key: SECURE_KEYS.BYOK_CONFIG })
  if (!raw) {
    _cache = null
  } else {
    try {
      _cache = JSON.parse(raw) as ByokConfig
    } catch {
      _cache = null
    }
  }
  _cached = true
  return _cache
}

export async function clearByokConfig(): Promise<void> {
  await invoke('secure_delete', { key: SECURE_KEYS.BYOK_CONFIG })
  await deleteSetting('byok_active')
  _cache = null
  _cached = false
  // A1: 同步刷 ApiClient module cache
  setByokConfigCache(null)
  setByokActiveCache(false)
}

export async function getByokActive(): Promise<boolean> {
  const v = await getSetting('byok_active')
  return v === 'true'
}

export async function setByokActive(active: boolean): Promise<void> {
  await setSetting('byok_active', active ? 'true' : 'false')
  // active flag 跟 cache 解耦 — 不动 _cache
  // A1: 同步刷 ApiClient module cache
  setByokActiveCache(active)
}
