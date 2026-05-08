/**
 * OS keychain 包装：Win Credential Manager / macOS Keychain / Linux Secret Service。
 * 比 localStorage 安全，token 不会被网页注入读取。
 */
import { invoke } from '@tauri-apps/api/core'

export const SECURE_KEYS = {
  ACCESS_TOKEN: 'access_token',
  REFRESH_TOKEN: 'refresh_token',
  USER_ID: 'user_id',
  BYOK_CONFIG: 'byok_config',  // M3: BYOK provider 配置（API key + model + base_url）JSON-encoded
} as const

export type SecureKey = (typeof SECURE_KEYS)[keyof typeof SECURE_KEYS]

export async function secureSet(key: SecureKey, value: string): Promise<void> {
  await invoke('secure_set', { key, value })
}

export async function secureGet(key: SecureKey): Promise<string | null> {
  const v = await invoke<string | null>('secure_get', { key })
  return v ?? null
}

export async function secureDelete(key: SecureKey): Promise<void> {
  await invoke('secure_delete', { key })
}
