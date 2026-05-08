/**
 * LLM providers — 客户端 TS 等价物，从 backend `services/core/llm_providers.py` 1:1 移植。
 *
 * 三个 provider class：
 * - OllamaProvider：本地 Ollama（无需 API key）
 * - OpenAICompatibleProvider：覆盖 OpenAI / DeepSeek / Moonshot / jiekou.ai 等 OpenAI 兼容端点
 * - AnthropicProvider：Anthropic Claude API
 *
 * 与 backend 差异：
 * - httpx → axios（client 已有依赖，避免引入 fetch + AbortController 自管 timeout）
 * - **删除** BYOK ContextVar / `_byok_provider` 分支（client 没有多用户隔离需求，BYOK
 *   直接在构造时注入 ProviderConfig）
 * - **删除** Hook engine fire 调用（hook engine 是 backend DevTools 用的，client 不需要）
 * - **保留** DeepSeek max_tokens 8192 clamp、JSON mode prompt 兜底、frequency_penalty 透传、
 *   stream_options.include_usage 解析、Anthropic SSE 多事件类型解析
 */
import axios, { AxiosError, type AxiosResponse } from 'axios'

import {
  computeCost,
  estimateTokens,
  type LLMChunk,
  type LLMResult,
  type LLMUsage,
  type GenerateOptions,
  type ProviderConfig,
} from './types'

// ── 内部工具 ─────────────────────────────────────────────────────────────

/** monotonic-ish ms timestamp（对齐 backend `time.monotonic() * 1000`）。 */
function _nowMs(): number {
  // performance.now 在 Node/JSDOM/Tauri webview 都有；不可用时退化到 Date.now
  return typeof performance !== 'undefined' ? performance.now() : Date.now()
}

function _redactErr(e: unknown): string {
  if (e instanceof AxiosError) {
    const code = e.code ?? '?'
    const status = e.response?.status ?? '?'
    return `[axios code=${code} status=${status}] ${e.message}`
  }
  if (e instanceof Error) return `${e.name}: ${e.message}`
  return String(e)
}

// ── Base ────────────────────────────────────────────────────────────────

export abstract class BaseLLMProvider {
  protected config: ProviderConfig
  protected timeout: number  // ms

  constructor(config: ProviderConfig) {
    this.config = config
    // backend 默认 25s（generate_full 短调用），子类可在 ctor 拉长
    this.timeout = (config.timeout ?? 25.0) * 1000
  }

  abstract get providerName(): string

  abstract generateFull(prompt: string, options?: GenerateOptions): Promise<LLMResult | null>

  /** 流式生成（async generator）。 */
  abstract generateStream(prompt: string, options?: GenerateOptions): AsyncIterable<LLMChunk>

  /** Backward-compat：返回纯文本或 null。 */
  async generate(prompt: string, options?: GenerateOptions): Promise<string | null> {
    const result = await this.generateFull(prompt, options)
    return result ? result.text : null
  }

  /** 检查连接状态。 */
  abstract checkConnection(): Promise<{
    connected: boolean
    provider: string
    available_models?: string[]
    current_model?: string | null
    error?: string
  }>
}

// ── Ollama ──────────────────────────────────────────────────────────────

export class OllamaProvider extends BaseLLMProvider {
  private host: string
  public model: string

  constructor(config: ProviderConfig) {
    super(config)
    this.host = config.host ?? config.base_url ?? 'http://localhost:11434'
    this.model = config.model ?? 'llama3.2'
  }

  get providerName() { return 'ollama' }

  async generateFull(prompt: string, options: GenerateOptions = {}): Promise<LLMResult | null> {
    const { temperature = 0.1, max_tokens, response_format } = options
    // Ollama 的 repeat_penalty 语义和 OpenAI frequency_penalty 不同（1~2 vs -2~2），
    // 不做映射以免误导；参数接收但 no-op（与 backend 一致）。
    const start = _nowMs()
    const payload: Record<string, unknown> = {
      model: this.model,
      prompt,
      stream: false,
      options: {
        temperature,
        num_predict: max_tokens ?? 500,
      },
    }
    // Ollama 用顶层 "format": "json" 启用 JSON mode（不是 response_format）
    if (response_format?.type === 'json_object') {
      payload.format = 'json'
    }
    try {
      const response = await axios.post(`${this.host}/api/generate`, payload, {
        timeout: this.timeout,
      })
      if (response.status === 200) {
        const data = response.data as Record<string, any>
        const text = String(data.response ?? '')
        const usage: LLMUsage = {
          input_tokens: data.prompt_eval_count || estimateTokens(prompt),
          output_tokens: data.eval_count || estimateTokens(text),
        }
        return {
          text,
          usage,
          cost_usd: computeCost(this.model, usage),
          latency_ms: Math.round(_nowMs() - start),
          provider: 'ollama',
          model: this.model,
          finish_reason: data.done_reason ?? null,
        }
      }
    } catch (e) {
      console.warn('[Ollama] 生成错误:', _redactErr(e))
    }
    return null
  }

  async *generateStream(prompt: string, options: GenerateOptions = {}): AsyncIterable<LLMChunk> {
    const { temperature = 0.1 } = options
    const start = _nowMs()
    let accumulated = ''
    try {
      const response = await axios.post<AsyncIterable<Uint8Array>>(
        `${this.host}/api/generate`,
        {
          model: this.model,
          prompt,
          stream: true,
          options: { temperature, num_predict: 500 },
        },
        { responseType: 'stream', timeout: this.timeout },
      )
      // axios stream — 逐行 ndjson
      for await (const lineRaw of _streamLines(response.data)) {
        const line = lineRaw.trim()
        if (!line) continue
        let data: Record<string, any>
        try {
          data = JSON.parse(line)
        } catch {
          continue
        }
        const delta = String(data.response ?? '')
        accumulated += delta
        if (delta) {
          yield {
            delta,
            done: false,
            cost_usd: 0,
            latency_ms: 0,
            provider: 'ollama',
            model: this.model,
          }
        }
        if (data.done) {
          const usage: LLMUsage = {
            input_tokens: data.prompt_eval_count || estimateTokens(prompt),
            output_tokens: data.eval_count || estimateTokens(accumulated),
          }
          yield {
            delta: '',
            done: true,
            usage,
            cost_usd: computeCost(this.model, usage),
            latency_ms: Math.round(_nowMs() - start),
            provider: 'ollama',
            model: this.model,
            finish_reason: data.done_reason ?? null,
          }
          return
        }
      }
    } catch (e) {
      console.warn('[Ollama] 流式错误:', _redactErr(e))
      yield {
        delta: '',
        done: true,
        usage: {
          input_tokens: estimateTokens(prompt),
          output_tokens: estimateTokens(accumulated),
        },
        cost_usd: 0,
        latency_ms: Math.round(_nowMs() - start),
        provider: 'ollama',
        model: this.model,
        finish_reason: 'error',
      }
    }
  }

  async checkConnection() {
    try {
      const response = await axios.get(`${this.host}/api/tags`, { timeout: 5000 })
      if (response.status === 200) {
        const data = response.data as Record<string, any>
        const models = (data.models ?? []).map((m: { name: string }) => m.name)
        return {
          connected: true,
          provider: 'ollama',
          available_models: models,
          current_model: this.model,
        }
      }
    } catch (e) {
      console.warn('[Ollama] 连接检查失败:', _redactErr(e))
    }
    return {
      connected: false,
      provider: 'ollama',
      error: '无法连接到 Ollama 服务',
    }
  }
}

// ── OpenAI 兼容（OpenAI / DeepSeek / Moonshot / jiekou.ai） ────────────────

export class OpenAICompatibleProvider extends BaseLLMProvider {
  public api_key: string
  public base_url: string
  public model: string
  public max_tokens: number
  public _provider_name: string

  constructor(config: ProviderConfig) {
    super(config)
    this.api_key = config.api_key ?? ''
    this.base_url = config.base_url ?? 'https://api.openai.com/v1'
    this.model = config.model ?? 'gpt-4o-mini'
    this._provider_name = config.provider_name ?? 'openai'
    this.max_tokens = config.max_tokens ?? 4096
    // DeepSeek max_tokens 上限 8192（与 backend `llm_providers.py:242-243` 一致）
    if (this.base_url.toLowerCase().includes('deepseek') && this.max_tokens > 8192) {
      this.max_tokens = 8192
    }
    // 长 prompt（带全文+KG+笔记）回答常 > 25s；给 OpenAI-compat 宽限到 120s
    if (this.timeout < 120_000) {
      this.timeout = 120_000
    }
  }

  get providerName() { return this._provider_name }

  async generateFull(prompt: string, options: GenerateOptions = {}): Promise<LLMResult | null> {
    if (!this.api_key) {
      console.warn(`[${this._provider_name}] 未配置 API 密钥`)
      return null
    }
    const { temperature = 0.1, max_tokens, response_format, frequency_penalty } = options
    const start = _nowMs()
    const body: Record<string, any> = {
      model: this.model,
      messages: [{ role: 'user', content: prompt }],
      temperature,
      max_tokens: max_tokens ?? this.max_tokens,
    }
    // JSON mode：OpenAI/DeepSeek/Moonshot 强制要求 prompt 里提到 "json"，否则 API 400。
    // caller 没写的话自动补一句兜底（与 backend `llm_providers.py:269-277` 一致）。
    if (response_format) {
      body.response_format = response_format
      if (
        response_format.type === 'json_object'
        && !prompt.toLowerCase().includes('json')
      ) {
        body.messages = [{
          role: 'user',
          content: prompt + '\n\n(Response must be valid JSON.)',
        }]
      }
    }
    if (frequency_penalty !== undefined && frequency_penalty !== null) {
      body.frequency_penalty = frequency_penalty
    }
    try {
      const response = await axios.post(
        `${this.base_url}/chat/completions`,
        body,
        {
          headers: {
            'Authorization': `Bearer ${this.api_key}`,
            'Content-Type': 'application/json',
          },
          timeout: this.timeout,
        },
      )
      if (response.status === 200) {
        const data = response.data as Record<string, any>
        const msg = data.choices[0].message
        const text = String(msg.content ?? '')
        // DeepSeek reasoner 等推理模型把思维链放 reasoning_content；普通 chat 模型无此字段
        const reasoning = msg.reasoning_content || null
        const usageRaw = data.usage ?? {}
        const usage: LLMUsage = {
          input_tokens: usageRaw.prompt_tokens || estimateTokens(prompt),
          output_tokens: usageRaw.completion_tokens || estimateTokens(text),
        }
        return {
          text,
          usage,
          cost_usd: computeCost(this.model, usage),
          latency_ms: Math.round(_nowMs() - start),
          provider: this._provider_name,
          model: this.model,
          finish_reason: data.choices[0].finish_reason ?? null,
          reasoning,
        }
      }
      console.warn(
        `[${this._provider_name}] API 错误 status=${response.status} url=${this.base_url}/chat/completions`,
      )
    } catch (e) {
      console.warn(`[${this._provider_name}] 生成错误:`, _redactErr(e))
    }
    return null
  }

  async *generateStream(prompt: string, options: GenerateOptions = {}): AsyncIterable<LLMChunk> {
    if (!this.api_key) {
      console.warn(`[${this._provider_name}] 未配置 API 密钥`)
      return
    }
    const { temperature = 0.1 } = options
    const start = _nowMs()
    let accumulated = ''
    let finalUsage: LLMUsage | null = null
    let finish: string | null = null
    try {
      const response = await axios.post<AsyncIterable<Uint8Array>>(
        `${this.base_url}/chat/completions`,
        {
          model: this.model,
          messages: [{ role: 'user', content: prompt }],
          temperature,
          max_tokens: this.max_tokens,
          stream: true,
          stream_options: { include_usage: true },
        },
        {
          headers: {
            'Authorization': `Bearer ${this.api_key}`,
            'Content-Type': 'application/json',
          },
          responseType: 'stream',
          timeout: this.timeout,
        },
      )
      for await (const lineRaw of _streamLines(response.data)) {
        const line = lineRaw.trim()
        if (!line || !line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (payload === '[DONE]') break
        let data: Record<string, any>
        try {
          data = JSON.parse(payload)
        } catch {
          continue
        }
        const choices = data.choices ?? []
        if (choices.length) {
          const deltaObj = choices[0].delta ?? {}
          const deltaText = String(deltaObj.content ?? '')
          if (deltaText) {
            accumulated += deltaText
            yield {
              delta: deltaText,
              done: false,
              cost_usd: 0,
              latency_ms: 0,
              provider: this._provider_name,
              model: this.model,
            }
          }
          if (choices[0].finish_reason) {
            finish = choices[0].finish_reason
          }
        }
        // usage is on final chunk when stream_options.include_usage
        if (data.usage) {
          finalUsage = {
            input_tokens: data.usage.prompt_tokens || 0,
            output_tokens: data.usage.completion_tokens || 0,
          }
        }
      }
      if (!finalUsage) {
        finalUsage = {
          input_tokens: estimateTokens(prompt),
          output_tokens: estimateTokens(accumulated),
        }
      }
      yield {
        delta: '',
        done: true,
        usage: finalUsage,
        cost_usd: computeCost(this.model, finalUsage),
        latency_ms: Math.round(_nowMs() - start),
        provider: this._provider_name,
        model: this.model,
        finish_reason: finish,
      }
    } catch (e) {
      console.warn(`[${this._provider_name}] 流式错误:`, _redactErr(e))
      yield {
        delta: '',
        done: true,
        usage: {
          input_tokens: estimateTokens(prompt),
          output_tokens: estimateTokens(accumulated),
        },
        cost_usd: 0,
        latency_ms: Math.round(_nowMs() - start),
        provider: this._provider_name,
        model: this.model,
        finish_reason: 'error',
      }
    }
  }

  async checkConnection() {
    if (!this.api_key) {
      return {
        connected: false,
        provider: this._provider_name,
        error: '未配置 API 密钥',
      }
    }
    try {
      const response = await axios.get(
        `${this.base_url}/models`,
        {
          headers: { 'Authorization': `Bearer ${this.api_key}` },
          timeout: 10_000,
        },
      )
      if (response.status === 200) {
        const data = response.data as Record<string, any>
        const models = (data.data ?? []).slice(0, 20).map((m: { id: string }) => m.id)
        return {
          connected: true,
          provider: this._provider_name,
          available_models: models,
          current_model: this.model,
        }
      }
    } catch (e) {
      console.warn(`[${this._provider_name}] 连接检查失败:`, _redactErr(e))
    }
    return {
      connected: false,
      provider: this._provider_name,
      error: `无法连接到 ${this._provider_name} 服务`,
    }
  }
}

// ── Anthropic ────────────────────────────────────────────────────────────

export class AnthropicProvider extends BaseLLMProvider {
  public api_key: string
  public base_url: string
  public model: string
  public max_tokens: number

  constructor(config: ProviderConfig) {
    super(config)
    this.api_key = config.api_key ?? ''
    this.base_url = config.base_url ?? 'https://api.anthropic.com'
    this.model = config.model ?? 'claude-sonnet-4-20250514'
    this.max_tokens = config.max_tokens ?? 4096
  }

  get providerName() { return 'anthropic' }

  async generateFull(prompt: string, options: GenerateOptions = {}): Promise<LLMResult | null> {
    if (!this.api_key) {
      console.warn('[Anthropic] 未配置 API 密钥')
      return null
    }
    let { temperature = 0.1, max_tokens, response_format } = options
    // Anthropic 不支持 OpenAI 风格 response_format。仅在 caller 启 JSON mode 时追加提示
    // （与 backend `llm_providers.py:486-487` 一致）。
    let usePrompt = prompt
    if (
      response_format?.type === 'json_object'
      && !prompt.toLowerCase().includes('json')
    ) {
      usePrompt = prompt + '\n\n(Response must be valid JSON.)'
    }
    const start = _nowMs()
    try {
      const response = await axios.post(
        `${this.base_url}/v1/messages`,
        {
          model: this.model,
          max_tokens: max_tokens ?? this.max_tokens,
          messages: [{ role: 'user', content: usePrompt }],
          temperature,
        },
        {
          headers: {
            'x-api-key': this.api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
          },
          timeout: this.timeout,
        },
      )
      if (response.status === 200) {
        const data = response.data as Record<string, any>
        let text = ''
        for (const block of data.content ?? []) {
          if (block.type === 'text') {
            text = block.text
            break
          }
        }
        const u = data.usage ?? {}
        const usage: LLMUsage = {
          input_tokens: u.input_tokens || estimateTokens(prompt),
          output_tokens: u.output_tokens || estimateTokens(text),
        }
        return {
          text,
          usage,
          cost_usd: computeCost(this.model, usage),
          latency_ms: Math.round(_nowMs() - start),
          provider: 'anthropic',
          model: this.model,
          finish_reason: data.stop_reason ?? null,
        }
      }
      console.warn(`[Anthropic] API 错误 ${response.status}`)
    } catch (e) {
      console.warn('[Anthropic] 生成错误:', _redactErr(e))
    }
    return null
  }

  async *generateStream(prompt: string, options: GenerateOptions = {}): AsyncIterable<LLMChunk> {
    if (!this.api_key) return
    const { temperature = 0.1 } = options
    const start = _nowMs()
    let accumulated = ''
    let inputTokens = 0
    let outputTokens = 0
    let finish: string | null = null
    try {
      const response = await axios.post<AsyncIterable<Uint8Array>>(
        `${this.base_url}/v1/messages`,
        {
          model: this.model,
          max_tokens: this.max_tokens,
          messages: [{ role: 'user', content: prompt }],
          temperature,
          stream: true,
        },
        {
          headers: {
            'x-api-key': this.api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
          },
          responseType: 'stream',
          timeout: this.timeout,
        },
      )
      // Anthropic SSE format: "event: {type}\ndata: {json}\n\n"
      for await (const lineRaw of _streamLines(response.data)) {
        const line = lineRaw.trim()
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        let data: Record<string, any>
        try {
          data = JSON.parse(payload)
        } catch {
          continue
        }
        const eventType = data.type
        if (eventType === 'message_start') {
          const u = (data.message ?? {}).usage ?? {}
          inputTokens = u.input_tokens || 0
          outputTokens = u.output_tokens || 0
        } else if (eventType === 'content_block_delta') {
          const delta = data.delta ?? {}
          if (delta.type === 'text_delta') {
            const text = String(delta.text ?? '')
            if (text) {
              accumulated += text
              yield {
                delta: text,
                done: false,
                cost_usd: 0,
                latency_ms: 0,
                provider: 'anthropic',
                model: this.model,
              }
            }
          }
        } else if (eventType === 'message_delta') {
          const u = data.usage ?? {}
          if (u.output_tokens) outputTokens = u.output_tokens
          if (data.delta?.stop_reason) finish = data.delta.stop_reason
        } else if (eventType === 'message_stop') {
          break
        }
      }
      const usage: LLMUsage = {
        input_tokens: inputTokens || estimateTokens(prompt),
        output_tokens: outputTokens || estimateTokens(accumulated),
      }
      yield {
        delta: '',
        done: true,
        usage,
        cost_usd: computeCost(this.model, usage),
        latency_ms: Math.round(_nowMs() - start),
        provider: 'anthropic',
        model: this.model,
        finish_reason: finish,
      }
    } catch (e) {
      console.warn('[Anthropic] 流式错误:', _redactErr(e))
      const usage: LLMUsage = {
        input_tokens: inputTokens || estimateTokens(prompt),
        output_tokens: outputTokens || estimateTokens(accumulated),
      }
      yield {
        delta: '',
        done: true,
        usage,
        cost_usd: computeCost(this.model, usage),
        latency_ms: Math.round(_nowMs() - start),
        provider: 'anthropic',
        model: this.model,
        finish_reason: 'error',
      }
    }
  }

  async checkConnection() {
    if (!this.api_key) {
      return {
        connected: false,
        provider: 'anthropic',
        error: '未配置 API 密钥',
      }
    }
    // Anthropic 没有 list models 端点，做一个轻量 messages 测试
    try {
      const response = await axios.post(
        `${this.base_url}/v1/messages`,
        {
          model: this.model,
          max_tokens: 10,
          messages: [{ role: 'user', content: 'Hi' }],
        },
        {
          headers: {
            'x-api-key': this.api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
          },
          timeout: 10_000,
        },
      )
      if (response.status === 200) {
        return {
          connected: true,
          provider: 'anthropic',
          available_models: [
            'claude-sonnet-4-20250514',
            'claude-haiku-4-5-20251001',
            'claude-opus-4-6',
          ],
          current_model: this.model,
        }
      }
    } catch (e) {
      console.warn('[Anthropic] 连接检查失败:', _redactErr(e))
    }
    return {
      connected: false,
      provider: 'anthropic',
      error: '无法连接到 Anthropic 服务',
    }
  }
}

// ── 流分行工具 ──────────────────────────────────────────────────────────

/** 把 async-iterable 字节流（Node Readable / fetch ReadableStream）按 \n 切行。
 *
 *  Phase B B1 的流式实现走 axios stream 适配：
 *  - Node 环境（vitest 跑测试）：axios `responseType: 'stream'` 返回 Node Readable，
 *    天然实现 Symbol.asyncIterator。
 *  - Tauri webview（生产）：axios 在浏览器 adapter 下 stream 不可用；流式调用
 *    后续会切到 `fetch(...).body` ReadableStream（B5 KnowledgeAgent / 共同研究
 *    才会真正用流式，B1 仅 generate_full 路径在用），届时这里改 reader.read() 即可。
 *
 *  所以本函数只覆盖一条 Node Readable 路径，不做多 adapter 兼容。
 */
async function* _streamLines(stream: AsyncIterable<Uint8Array | string>): AsyncIterable<string> {
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  for await (const chunk of stream) {
    buffer += typeof chunk === 'string' ? chunk : decoder.decode(chunk, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 1)
      yield line
    }
  }
  // flush decoder tail
  buffer += decoder.decode()
  if (buffer) yield buffer
}

// ── 工厂 ─────────────────────────────────────────────────────────────────

/** 根据 BYOK config 构造对应 provider。
 *
 *  对齐 backend `llm_request_resolver.py:_build_temp_provider` + `LLMProviderManager.PROVIDER_TEMPLATES`。
 */
export function buildProvider(config: ProviderConfig): BaseLLMProvider {
  const provider = config.provider
  if (provider === 'anthropic') {
    return new AnthropicProvider(config)
  }
  if (provider === 'ollama') {
    return new OllamaProvider(config)
  }
  // openai / deepseek / moonshot / jiekou / custom 全部走 OpenAI 兼容
  // 仅 jiekou 历史上用 AnthropicProvider — 但实际它的 base_url `/openai` 是 OpenAI 格式
  // （见 backend 模板 line 750），新代码统一走 OpenAICompatibleProvider
  const cfgWithName: ProviderConfig = {
    ...config,
    provider_name: config.provider_name ?? provider,
  }
  return new OpenAICompatibleProvider(cfgWithName)
}
