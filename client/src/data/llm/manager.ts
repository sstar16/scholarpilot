/**
 * LLM Manager — 客户端单例，负责：
 * 1. 启动从 keychain 读 BYOK config（`api/byok_config.ts`）→ 构造 active provider
 * 2. 暴露 `generate(prompt, options)` / `generateStream(prompt, options)`
 * 3. 提供 `reload()` 让 settings 改 BYOK 后立即生效
 *
 * 与 backend `LLMProviderManager` 差异：
 * - 客户端只配一个 BYOK provider，**无 fallback 池**（active 失败直接报错）
 * - 不需要 Redis TTL 缓存（keychain 直读 + 内存单例）
 * - 不需要 hook engine fire / Celery worker 兼容
 * - 不需要 ContextVar BYOK 透传（client 没有多用户隔离）
 */
import { loadByokConfig, type ByokConfig } from '@/api/byok_config'

import {
  buildProvider,
  type BaseLLMProvider,
} from './providers'
import {
  DEFAULT_BASE_URLS,
  type GenerateOptions,
  type LLMChunk,
  type LLMResult,
  type ProviderConfig,
} from './types'

// ── 内部状态 ────────────────────────────────────────────────────────────

let _activeProvider: BaseLLMProvider | null = null
let _initialized = false

// ── BYOK → ProviderConfig ────────────────────────────────────────────────

/** 把 ByokConfig（keychain 读出）翻译成构造 provider 用的 ProviderConfig。 */
function _byokToProviderConfig(byok: ByokConfig): ProviderConfig {
  const baseUrl = byok.base_url || DEFAULT_BASE_URLS[byok.provider] || null
  return {
    provider: byok.provider,
    api_key: byok.api_key,
    base_url: baseUrl,
    model: byok.model,
    provider_name: byok.provider,
  }
}

// ── 公共 API ────────────────────────────────────────────────────────────

/** 单例初始化（app bootstrap 调一次）。 */
export async function init(): Promise<void> {
  if (_initialized) return
  _initialized = true
  await reload()
}

/** 重新读 keychain 重建 active provider。settings 改 BYOK 后调用。 */
export async function reload(): Promise<void> {
  const byok = await loadByokConfig()
  if (!byok) {
    _activeProvider = null
    return
  }
  try {
    _activeProvider = buildProvider(_byokToProviderConfig(byok))
  } catch (e) {
    console.warn('[LLMManager] buildProvider failed:', e)
    _activeProvider = null
  }
}

/** 获取当前 active provider。 */
export function getActiveProvider(): BaseLLMProvider | null {
  return _activeProvider
}

/** 主入口：非流式生成。无 active provider 时返回 null。 */
export async function generate(
  prompt: string,
  options: GenerateOptions = {},
): Promise<LLMResult | null> {
  if (!_activeProvider) {
    console.warn('[LLMManager] generate called but no active provider (BYOK 未配置?)')
    return null
  }
  return _activeProvider.generateFull(prompt, options)
}

/** 主入口：流式生成。无 active provider 时返回空迭代器。 */
export async function* generateStream(
  prompt: string,
  options: GenerateOptions = {},
): AsyncIterable<LLMChunk> {
  if (!_activeProvider) {
    console.warn('[LLMManager] generateStream called but no active provider (BYOK 未配置?)')
    return
  }
  yield* _activeProvider.generateStream(prompt, options)
}

/** 检查 active provider 连接。 */
export async function checkConnection() {
  if (!_activeProvider) {
    return {
      connected: false,
      provider: 'none',
      error: '未配置 BYOK provider',
    }
  }
  return _activeProvider.checkConnection()
}

// ── 测试用 ──────────────────────────────────────────────────────────────

/** 测试用：强制重置内部状态（不动 keychain）。 */
export function _resetForTesting(): void {
  _activeProvider = null
  _initialized = false
}

/** 测试用：直接注入 provider（绕过 keychain）。 */
export function _setProviderForTesting(provider: BaseLLMProvider | null): void {
  _activeProvider = provider
  _initialized = true
}

// ── 默认 export 单例 ────────────────────────────────────────────────────

/** 单例命名空间，方便调用方一行 `import llm from '...'; llm.generate(...)`。 */
export const llmManager = {
  init,
  reload,
  generate,
  generateStream,
  getActiveProvider,
  checkConnection,
}
