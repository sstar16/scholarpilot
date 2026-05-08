import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'

import {
  SECURE_KEYS,
  secureDelete,
  secureGet,
  secureSet,
} from '../api/secure_storage'
import { authApi, setAccessTokenCache } from '../api/client'
import { initDatabase, getDatabase } from '../data/sqlite/connection'

/**
 * Auth store：token 持有内存 ref（同步访问给 router/SSE/components 用），
 * 持久化层走 OS keychain（启动时 hydrate；login/logout 写 keyring）。
 *
 * router beforeEach 先 await ensureInit() 再判 auth.token，避免首次启动时
 * keyring 还没 hydrate 就被路由判断为未登录。
 */
export const useAuthStore = defineStore('auth', () => {
  const token = ref('')
  const user = ref<any>(null)
  let _initPromise: Promise<void> | null = null

  const isLoggedIn = computed(() => !!token.value)

  async function ensureInit(): Promise<void> {
    if (_initPromise) return _initPromise
    _initPromise = (async () => {
      const stored = await secureGet(SECURE_KEYS.ACCESS_TOKEN)
      if (stored) {
        token.value = stored
        setAccessTokenCache(stored)  // A1: 同步 ApiClient module cache
        try {
          await fetchMe()
        } catch {
          // 失败不打断 init，可能是 backend 还没起或 token 过期
          await logout()
        }
      }
    })()
    return _initPromise
  }

  async function login(email: string, password: string) {
    invoke('log_webview_error', {
      level: 'warn',
      message: `login attempt: email=${email}`,
      source: 'auth.login',
    }).catch(() => {})
    let res
    try {
      res = await authApi.login({ email, password })
    } catch (err: any) {
      const status = err?.response?.status
      const data = JSON.stringify(err?.response?.data || {}).slice(0, 500)
      const msg = err?.message || String(err)
      invoke('log_webview_error', {
        level: 'error',
        message: `login HTTP error: status=${status} msg=${msg} data=${data}`,
        source: 'auth.login',
      }).catch(() => {})
      throw err  // re-throw 让 UI 显示错误
    }
    const { access_token, refresh_token } = res.data
    token.value = access_token
    setAccessTokenCache(access_token)
    await secureSet(SECURE_KEYS.ACCESS_TOKEN, access_token)
    await secureSet(SECURE_KEYS.REFRESH_TOKEN, refresh_token)
    invoke('log_webview_error', {
      level: 'warn',
      message: `login token saved, calling fetchMe`,
      source: 'auth.login',
    }).catch(() => {})
    await fetchMe()
    // accounts.json: 记住这个账号 + 设为 active (登录页"最近账号"用)
    try {
      await invoke('accounts_remember_user', {
        email,
        displayName: user.value?.name ?? null,
        userId: user.value?.id ? String(user.value.id) : null,
      })
      invoke('log_webview_error', {
        level: 'warn',
        message: `login complete: user=${user.value?.name} id=${user.value?.id}`,
        source: 'auth.login',
      }).catch(() => {})
    } catch (e) {
      console.warn('[login] accounts_remember_user failed:', e)
    }
  }

  async function register(
    email: string,
    name: string,
    password: string,
    invitationCode?: string,
  ) {
    // 2026-05-08：客户端 desktop 注册无需邀请码（后端按 X-Client-Type=desktop 跳过校验），
    // invitationCode 改为可选参数；如果调用方传了仍透传给后端（兼容旧路径）。
    const payload: {
      email: string
      name: string
      password: string
      invitation_code?: string
    } = { email, name, password }
    if (invitationCode && invitationCode.trim()) {
      payload.invitation_code = invitationCode.trim().toLowerCase()
    }
    const res = await authApi.register(payload)
    const { access_token, refresh_token } = res.data
    token.value = access_token
    setAccessTokenCache(access_token)  // A1: 同步 ApiClient module cache
    await secureSet(SECURE_KEYS.ACCESS_TOKEN, access_token)
    await secureSet(SECURE_KEYS.REFRESH_TOKEN, refresh_token)
    await fetchMe()
  }

  async function fetchMe() {
    try {
      const res = await authApi.me()
      user.value = res.data
    } catch {
      await logout()
    }
  }

  async function logout() {
    // 先尝试通知后端撤销 refresh（失败不阻断本地清理）
    const refresh = await secureGet(SECURE_KEYS.REFRESH_TOKEN)
    if (refresh && token.value) {
      try {
        await authApi.logout(refresh)
      } catch {
        /* ignore: 本地清理才是主目标 */
      }
    }
    token.value = ''
    user.value = null
    setAccessTokenCache(null)  // A1: 同步 ApiClient module cache
    await secureDelete(SECURE_KEYS.ACCESS_TOKEN)
    await secureDelete(SECURE_KEYS.REFRESH_TOKEN)

    // ── 多账号 P0 (agent 调研 §6, Figma/Standard Notes 模式): 清账号本地数据 ──
    //
    // ⚠️ 关键改动 (2026-05-04): 不再 fs_remove scholarpilot.db, 改用 SQL DELETE
    // 清表保留 schema。原因: tauri-plugin-sql 在 plugin 注册时定义 migrations,
    // Database.load 多次调用**不重跑 migrations**。如果 fs_remove 删了 .db 文件
    // 再 reinit -> 创建空 DB 文件 -> migrations 不再跑 -> 没 documents 等表 ->
    // 后续所有 SQL "no such table" 报错 -> silentPdfReconciler 全挂。
    //
    // 改用 SQL DELETE: 保留 11 张表的 schema, 仅清数据。配合 fs_remove
    // projects/cache/exports 子目录, 实现"账号数据物理隔离"。
    // 失败仅 warn, 不阻塞 logout 流程。
    try {
      const db = getDatabase()
      const tables = [
        'round_documents', 'document_classifications',  // 先删 FK 子表
        'messages', 'research_note_pages', 'sync_state',
        'documents', 'search_rounds', 'projects',  // 再删父表
        'conversation_sessions', 'settings', 'meta_kv',
      ]
      for (const t of tables) {
        try { await db.execute(`DELETE FROM "${t}"`) } catch (e) {
          console.warn(`[logout] clear ${t}:`, e)
        }
      }
    } catch (e) {
      console.warn('[logout] DB clear failed:', e)
    }

    for (const rel of [
      'projects', 'cache', 'exports',
      // memory/ 不删: 留给跨账号引用 (后续 M1+ 多账号子目录改造时拆)
      // logs/ 不删: 跨账号 debug 仍想看
    ]) {
      try {
        const exists = await invoke<boolean>('fs_exists', { relPath: rel })
        if (exists) await invoke('fs_remove', { relPath: rel })
      } catch (e) {
        console.warn(`[logout] fs_remove ${rel} failed:`, e)
      }
    }
    // accounts.json: 清 active_user_email (users[] 注册表保留, 给"最近账号" UI 用)
    try {
      await invoke('accounts_clear_active')
    } catch (e) { console.warn('[logout] accounts_clear_active failed:', e) }
    // 重建子目录骨架 (projects/cache/exports 被 fs_remove 删了, 这里主动重建
    // 让 silent reconciler / fs_write_bytes_b64 后续不用 lazy mkdir, 用户
    // ls AppData 也能一眼看到结构)
    try {
      await invoke('fs_ensure_app_dirs')
    } catch (e) { console.warn('[logout] fs_ensure_app_dirs failed:', e) }
  }

  return {
    token,
    user,
    isLoggedIn,
    ensureInit,
    login,
    register,
    fetchMe,
    logout,
  }
})
