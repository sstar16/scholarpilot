/**
 * LLM types — 客户端 TS 等价物，对齐 backend `services/core/llm_types.py`。
 *
 * 设计原则：
 * - 字段名严格匹配 backend dataclass，方便从 sp-api 反序列化结果（虽然 Phase B
 *   后 LLM 调用直接走客户端 provider，不再经 sp-api，但保持兼容性能减少跨阶段
 *   故障）
 * - `reasoning?` 字段保留：DeepSeek-reasoner 等推理模型的思维链
 */
import type { ByokProvider } from '@/api/byok_config'

/** Token usage for a single LLM call. */
export interface LLMUsage {
  input_tokens: number
  output_tokens: number
}

/** Full result of a non-streaming LLM call. */
export interface LLMResult {
  text: string
  usage: LLMUsage
  cost_usd: number
  latency_ms: number
  provider: string
  model: string
  finish_reason?: string | null
  /** 思维链文本（仅 deepseek-reasoner 等推理模型返回；非推理模型为 undefined）。 */
  reasoning?: string | null
}

/** Single chunk from a streaming LLM call. */
export interface LLMChunk {
  delta: string
  done: boolean
  usage?: LLMUsage
  cost_usd: number
  latency_ms: number
  provider: string
  model: string
  finish_reason?: string | null
}

/** Provider 构造配置（从 BYOK keychain 读出来组装）。 */
export interface ProviderConfig {
  provider: ByokProvider | 'ollama' | 'jiekou'
  api_key?: string | null
  base_url?: string | null
  model?: string | null
  /** Ollama 用 host 字段（与 base_url 等价，保留兼容）。 */
  host?: string | null
  max_tokens?: number | null
  /** 单次 LLM HTTP 调用最长秒数（默认按 provider 类型决定）。 */
  timeout?: number | null
  /** 显示用 provider name（用于 LLMResult.provider 字段，jiekou 等中转用）。 */
  provider_name?: string | null
}

/** Generate options（对齐 backend `generate_full` 参数）。 */
export interface GenerateOptions {
  temperature?: number
  max_tokens?: number | null
  response_format?: { type: 'json_object' | 'text' } | null
  frequency_penalty?: number | null
}

/** USD per 1M tokens — (input_price, output_price)
 *  Sources: official pricing pages as of 2026-04 (与 backend `llm_types.py:64-90` 对齐)。
 */
export const TOKEN_PRICING: Record<string, [number, number]> = {
  // Claude 4.x series
  'claude-opus-4-6': [15.0, 75.0],
  'claude-sonnet-4-6': [3.0, 15.0],
  'claude-sonnet-4-20250514': [3.0, 15.0],
  'claude-haiku-4-5-20251001': [1.0, 5.0],
  // OpenAI
  'gpt-4o': [2.5, 10.0],
  'gpt-4o-mini': [0.15, 0.6],
  'gpt-4-turbo': [10.0, 30.0],
  'gpt-5.4-mini': [0.25, 1.0], // jiekou alias
  // DeepSeek
  'deepseek-chat': [0.14, 0.28],
  'deepseek-reasoner': [0.55, 2.19],
  'deepseek/deepseek-v3.1': [0.27, 1.10],
  // Moonshot
  'moonshot-v1-8k': [0.17, 0.17],
  'moonshot-v1-32k': [0.34, 0.34],
  'moonshot-v1-128k': [0.84, 0.84],
  // Gemini via jiekou
  'gemini-3.1-pro-preview': [1.25, 5.0],
  // Ollama (local, free)
  'llama3.2': [0.0, 0.0],
  'llama3.2:70b': [0.0, 0.0],
  'qwen2.5': [0.0, 0.0],
  'deepseek-r1': [0.0, 0.0],
}

/** Compute USD cost for a given model + usage. Returns 0.0 for unknown models.
 *
 *  对齐 backend `compute_cost()`（含 partial-match fallback）。
 */
export function computeCost(model: string, usage: LLMUsage): number {
  let prices = TOKEN_PRICING[model]
  if (!prices) {
    // Fallback: partial matches（与 backend 一致）
    for (const [key, val] of Object.entries(TOKEN_PRICING)) {
      if (key.includes(model) || model.includes(key)) {
        prices = val
        break
      }
    }
  }
  if (!prices) return 0.0
  const [inputPerM, outputPerM] = prices
  const cost
    = (usage.input_tokens / 1_000_000) * inputPerM
    + (usage.output_tokens / 1_000_000) * outputPerM
  // round to 6 decimals
  return Math.round(cost * 1_000_000) / 1_000_000
}

/** Rough estimate for providers without usage reporting (Ollama sometimes).
 *
 *  Rule: ~3 chars per token (mixed CJK/Latin practical approximation).
 *  对齐 backend `estimate_tokens()`。
 */
export function estimateTokens(text: string): number {
  if (!text) return 0
  return Math.max(1, Math.floor(text.length / 3))
}

/** Default base URLs per provider — 从 backend `llm_request_resolver.py:26-30` 移植。 */
export const DEFAULT_BASE_URLS: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
  deepseek: 'https://api.deepseek.com/v1',
  moonshot: 'https://api.moonshot.cn/v1',
  jiekou: 'https://api.jiekou.ai/openai',
}
