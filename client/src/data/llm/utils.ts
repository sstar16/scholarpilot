/**
 * LLM 模块工具函数（哈希、jobId 生成）。
 *
 * 设计要点：
 * - 浏览器/Tauri WebView 都有 `crypto.subtle`，无需 polyfill
 * - sha256 输出 hex（64 char），用于 prompt_hash 与 cache key
 * - vitest 默认跑在 jsdom，jsdom 没有 SubtleCrypto；测试侧通过
 *   `vitest.config.ts` 注入或者直接用 `globalThis.crypto = require('node:crypto').webcrypto`
 *   兜底（见各 test 文件 setup）
 */

/** 计算字符串 sha256，返回 hex 字符串。 */
export async function sha256(input: string): Promise<string> {
  const data = new TextEncoder().encode(input)
  const hashBuf = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(hashBuf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

/** 生成 LLM cache key：prompt + model + temperature → sha256 截断 32 char。 */
export async function makeCacheKey(
  prompt: string,
  model: string,
  temperature: number,
): Promise<string> {
  const composite = `${model}|${temperature.toFixed(3)}|${prompt}`
  const full = await sha256(composite)
  return full.slice(0, 32)
}

/** 简易 UUID v4（不引入 uuid 包）。 */
export function uuidv4(): string {
  // 优先用 crypto.randomUUID（modern WebView 都有）
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  // 兜底实现
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

/** 当前 unix-ms（与 SQLite schema INTEGER 时间戳约定一致）。 */
export function nowMs(): number {
  return Date.now()
}
