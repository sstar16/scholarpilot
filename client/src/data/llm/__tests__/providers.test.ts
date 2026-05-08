/**
 * Providers 单测 — mock axios 验证三个 provider 的 happy path + 错误兜底。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('axios')
import axios from 'axios'

import {
  AnthropicProvider,
  OllamaProvider,
  OpenAICompatibleProvider,
  buildProvider,
} from '../providers'
import { computeCost, estimateTokens, TOKEN_PRICING } from '../types'

const _axios = axios as unknown as { post: ReturnType<typeof vi.fn>; get: ReturnType<typeof vi.fn> }

beforeEach(() => {
  vi.clearAllMocks()
  ;(axios as any).post = vi.fn()
  ;(axios as any).get = vi.fn()
})

// ── compute_cost / estimate_tokens ──────────────────────────────────────

describe('compute_cost', () => {
  it('对 gpt-4o-mini 算出对的价格（0.15 + 0.6 USD per 1M）', () => {
    const cost = computeCost('gpt-4o-mini', { input_tokens: 1_000_000, output_tokens: 1_000_000 })
    expect(cost).toBeCloseTo(0.75, 5)
  })

  it('对 deepseek-chat 算出对的价格', () => {
    const cost = computeCost('deepseek-chat', { input_tokens: 100_000, output_tokens: 50_000 })
    // (0.1 * 0.14) + (0.05 * 0.28) = 0.014 + 0.014 = 0.028
    expect(cost).toBeCloseTo(0.028, 5)
  })

  it('对未知 model 返回 0', () => {
    expect(computeCost('totally-unknown-model-xyz', { input_tokens: 100, output_tokens: 100 }))
      .toBe(0)
  })

  it('partial match：含 "gpt-4o" 的别名命中 gpt-4o 价格', () => {
    const cost = computeCost('gpt-4o-2024-08-06', { input_tokens: 1_000_000, output_tokens: 0 })
    // partial match 找到 gpt-4o，input price 2.5 USD/1M
    expect(cost).toBeCloseTo(2.5, 5)
  })

  it('全部 TOKEN_PRICING 项都是 (number, number) 二元组', () => {
    for (const [model, price] of Object.entries(TOKEN_PRICING)) {
      expect(Array.isArray(price), `${model} should be tuple`).toBe(true)
      expect(price).toHaveLength(2)
      expect(typeof price[0]).toBe('number')
      expect(typeof price[1]).toBe('number')
    }
  })
})

describe('estimate_tokens', () => {
  it('空字符串返回 0', () => {
    expect(estimateTokens('')).toBe(0)
  })

  it('短文本至少返回 1', () => {
    expect(estimateTokens('a')).toBe(1)
  })

  it('长文本按 len/3 估算', () => {
    expect(estimateTokens('a'.repeat(30))).toBe(10)
  })
})

// ── OllamaProvider ──────────────────────────────────────────────────────

describe('OllamaProvider', () => {
  it('generate_full happy path：返回 LLMResult 含 text + usage + cost', async () => {
    _axios.post.mockResolvedValueOnce({
      status: 200,
      data: {
        response: 'hello world',
        prompt_eval_count: 10,
        eval_count: 5,
        done: true,
        done_reason: 'stop',
      },
    })
    const p = new OllamaProvider({ provider: 'ollama', host: 'http://localhost:11434', model: 'llama3.2' })
    const result = await p.generateFull('test prompt')
    expect(result).not.toBeNull()
    expect(result!.text).toBe('hello world')
    expect(result!.usage.input_tokens).toBe(10)
    expect(result!.usage.output_tokens).toBe(5)
    expect(result!.provider).toBe('ollama')
    expect(result!.model).toBe('llama3.2')
    expect(result!.finish_reason).toBe('stop')
    expect(result!.cost_usd).toBe(0)  // llama3.2 free
    expect(_axios.post).toHaveBeenCalledTimes(1)
    const [url, payload] = _axios.post.mock.calls[0]
    expect(url).toBe('http://localhost:11434/api/generate')
    expect((payload as any).stream).toBe(false)
  })

  it('JSON mode：response_format=json_object 时设 format=json', async () => {
    _axios.post.mockResolvedValueOnce({
      status: 200,
      data: { response: '{"k":1}', prompt_eval_count: 5, eval_count: 3, done: true, done_reason: 'stop' },
    })
    const p = new OllamaProvider({ provider: 'ollama' })
    await p.generateFull('plz json', { response_format: { type: 'json_object' } })
    const [, payload] = _axios.post.mock.calls[0]
    expect((payload as any).format).toBe('json')
  })

  it('网络异常：返回 null + 不抛', async () => {
    _axios.post.mockRejectedValueOnce(new Error('ECONNREFUSED'))
    const p = new OllamaProvider({ provider: 'ollama' })
    const result = await p.generateFull('x')
    expect(result).toBeNull()
  })

  it('checkConnection happy path 返回 connected=true + 模型列表', async () => {
    _axios.get.mockResolvedValueOnce({
      status: 200,
      data: { models: [{ name: 'llama3.2' }, { name: 'qwen2.5' }] },
    })
    const p = new OllamaProvider({ provider: 'ollama', model: 'llama3.2' })
    const status = await p.checkConnection()
    expect(status.connected).toBe(true)
    expect(status.available_models).toEqual(['llama3.2', 'qwen2.5'])
    expect(status.current_model).toBe('llama3.2')
  })
})

// ── OpenAICompatibleProvider ────────────────────────────────────────────

describe('OpenAICompatibleProvider', () => {
  it('未配 api_key 直接返回 null', async () => {
    const p = new OpenAICompatibleProvider({ provider: 'openai', api_key: '' })
    const result = await p.generateFull('x')
    expect(result).toBeNull()
    expect(_axios.post).not.toHaveBeenCalled()
  })

  it('happy path：解析 choices[0].message.content + usage + reasoning', async () => {
    _axios.post.mockResolvedValueOnce({
      status: 200,
      data: {
        choices: [{
          message: { content: 'hello', reasoning_content: 'because reasons' },
          finish_reason: 'stop',
        }],
        usage: { prompt_tokens: 100, completion_tokens: 50 },
      },
    })
    const p = new OpenAICompatibleProvider({
      provider: 'deepseek',
      api_key: 'sk-test',
      base_url: 'https://api.deepseek.com/v1',
      model: 'deepseek-reasoner',
      provider_name: 'deepseek',
    })
    const result = await p.generateFull('test')
    expect(result).not.toBeNull()
    expect(result!.text).toBe('hello')
    expect(result!.reasoning).toBe('because reasons')
    expect(result!.usage.input_tokens).toBe(100)
    expect(result!.usage.output_tokens).toBe(50)
    expect(result!.provider).toBe('deepseek')
    expect(result!.cost_usd).toBeGreaterThan(0)  // deepseek-reasoner 有价
    // 验证 Authorization header
    const [, , config] = _axios.post.mock.calls[0]
    expect((config as any).headers.Authorization).toBe('Bearer sk-test')
  })

  it('JSON mode + prompt 不含 "json"：自动加兜底提示', async () => {
    _axios.post.mockResolvedValueOnce({
      status: 200,
      data: {
        choices: [{ message: { content: '{}' }, finish_reason: 'stop' }],
        usage: { prompt_tokens: 5, completion_tokens: 1 },
      },
    })
    const p = new OpenAICompatibleProvider({
      provider: 'openai',
      api_key: 'sk-x',
      model: 'gpt-4o-mini',
    })
    await p.generateFull('plz return some data', { response_format: { type: 'json_object' } })
    const [, body] = _axios.post.mock.calls[0]
    expect((body as any).response_format).toEqual({ type: 'json_object' })
    // 因为原 prompt 不含 "json"，messages 应被替换成加了兜底提示的版本
    expect((body as any).messages[0].content).toContain('Response must be valid JSON')
  })

  it('JSON mode + prompt 已含 "json"：不重复加兜底', async () => {
    _axios.post.mockResolvedValueOnce({
      status: 200,
      data: {
        choices: [{ message: { content: '{}' }, finish_reason: 'stop' }],
        usage: { prompt_tokens: 5, completion_tokens: 1 },
      },
    })
    const p = new OpenAICompatibleProvider({
      provider: 'openai',
      api_key: 'sk-x',
      model: 'gpt-4o-mini',
    })
    await p.generateFull('please return JSON', { response_format: { type: 'json_object' } })
    const [, body] = _axios.post.mock.calls[0]
    expect((body as any).messages[0].content).toBe('please return JSON')
  })

  it('frequency_penalty 透传到 body', async () => {
    _axios.post.mockResolvedValueOnce({
      status: 200,
      data: {
        choices: [{ message: { content: 'x' }, finish_reason: 'stop' }],
        usage: { prompt_tokens: 5, completion_tokens: 1 },
      },
    })
    const p = new OpenAICompatibleProvider({
      provider: 'openai',
      api_key: 'sk-x',
      model: 'gpt-4o-mini',
    })
    await p.generateFull('test', { frequency_penalty: 0.5 })
    const [, body] = _axios.post.mock.calls[0]
    expect((body as any).frequency_penalty).toBe(0.5)
  })

  it('DeepSeek base_url：max_tokens 自动 clamp 到 8192', () => {
    const p = new OpenAICompatibleProvider({
      provider: 'deepseek',
      api_key: 'sk',
      base_url: 'https://api.deepseek.com/v1',
      model: 'deepseek-chat',
      max_tokens: 16000,
    })
    expect(p.max_tokens).toBe(8192)
  })

  it('401 错误返回 null（不抛）', async () => {
    _axios.post.mockRejectedValueOnce(Object.assign(new Error('401 Unauthorized'), {
      isAxiosError: true,
      response: { status: 401, data: { error: 'invalid key' } },
    }))
    const p = new OpenAICompatibleProvider({
      provider: 'openai',
      api_key: 'sk-bad',
      model: 'gpt-4o-mini',
    })
    const result = await p.generateFull('x')
    expect(result).toBeNull()
  })

  it('JSON parse 错误（response.data 不是预期 shape）：返回 null', async () => {
    _axios.post.mockResolvedValueOnce({
      status: 200,
      data: { unexpected: 'shape' },  // 没 choices 字段
    })
    const p = new OpenAICompatibleProvider({
      provider: 'openai',
      api_key: 'sk',
      model: 'gpt-4o-mini',
    })
    const result = await p.generateFull('x')
    expect(result).toBeNull()
  })
})

// ── AnthropicProvider ────────────────────────────────────────────────────

describe('AnthropicProvider', () => {
  it('未配 api_key 返回 null', async () => {
    const p = new AnthropicProvider({ provider: 'anthropic', api_key: '' })
    const result = await p.generateFull('x')
    expect(result).toBeNull()
  })

  it('happy path：解析 content[0].text + usage + stop_reason', async () => {
    _axios.post.mockResolvedValueOnce({
      status: 200,
      data: {
        content: [{ type: 'text', text: 'hello from claude' }],
        usage: { input_tokens: 50, output_tokens: 30 },
        stop_reason: 'end_turn',
      },
    })
    const p = new AnthropicProvider({
      provider: 'anthropic',
      api_key: 'sk-ant',
      model: 'claude-sonnet-4-20250514',
    })
    const result = await p.generateFull('test')
    expect(result).not.toBeNull()
    expect(result!.text).toBe('hello from claude')
    expect(result!.usage.input_tokens).toBe(50)
    expect(result!.usage.output_tokens).toBe(30)
    expect(result!.finish_reason).toBe('end_turn')
    expect(result!.provider).toBe('anthropic')
    // 验证 x-api-key + anthropic-version headers
    const [, , config] = _axios.post.mock.calls[0]
    expect((config as any).headers['x-api-key']).toBe('sk-ant')
    expect((config as any).headers['anthropic-version']).toBe('2023-06-01')
  })

  it('JSON mode 不支持 response_format 但加 prompt 提示', async () => {
    _axios.post.mockResolvedValueOnce({
      status: 200,
      data: {
        content: [{ type: 'text', text: '{}' }],
        usage: { input_tokens: 5, output_tokens: 1 },
        stop_reason: 'end_turn',
      },
    })
    const p = new AnthropicProvider({
      provider: 'anthropic',
      api_key: 'sk-ant',
      model: 'claude-sonnet-4-20250514',
    })
    await p.generateFull('regular prompt', { response_format: { type: 'json_object' } })
    const [, body] = _axios.post.mock.calls[0]
    // 不传 response_format 给 Anthropic
    expect((body as any).response_format).toBeUndefined()
    // prompt 末尾加了 "Response must be valid JSON"
    expect((body as any).messages[0].content).toContain('Response must be valid JSON')
  })

  it('网络错误返回 null', async () => {
    _axios.post.mockRejectedValueOnce(new Error('connect ETIMEDOUT'))
    const p = new AnthropicProvider({
      provider: 'anthropic',
      api_key: 'sk',
      model: 'claude-sonnet-4-20250514',
    })
    const result = await p.generateFull('x')
    expect(result).toBeNull()
  })
})

// ── buildProvider 工厂 ───────────────────────────────────────────────────

describe('buildProvider 工厂', () => {
  it('provider=anthropic → AnthropicProvider', () => {
    const p = buildProvider({ provider: 'anthropic', api_key: 'sk' })
    expect(p).toBeInstanceOf(AnthropicProvider)
    expect(p.providerName).toBe('anthropic')
  })

  it('provider=openai → OpenAICompatibleProvider', () => {
    const p = buildProvider({ provider: 'openai', api_key: 'sk', model: 'gpt-4o-mini' })
    expect(p).toBeInstanceOf(OpenAICompatibleProvider)
    expect(p.providerName).toBe('openai')
  })

  it('provider=deepseek → OpenAICompatibleProvider', () => {
    const p = buildProvider({
      provider: 'deepseek',
      api_key: 'sk',
      base_url: 'https://api.deepseek.com/v1',
      model: 'deepseek-chat',
    })
    expect(p).toBeInstanceOf(OpenAICompatibleProvider)
    expect(p.providerName).toBe('deepseek')
  })

  it('provider=moonshot → OpenAICompatibleProvider', () => {
    const p = buildProvider({
      provider: 'moonshot',
      api_key: 'sk',
      base_url: 'https://api.moonshot.cn/v1',
      model: 'moonshot-v1-8k',
    })
    expect(p).toBeInstanceOf(OpenAICompatibleProvider)
    expect(p.providerName).toBe('moonshot')
  })

  it('provider=ollama → OllamaProvider', () => {
    const p = buildProvider({
      provider: 'ollama',
      host: 'http://localhost:11434',
      model: 'llama3.2',
    })
    expect(p).toBeInstanceOf(OllamaProvider)
    expect(p.providerName).toBe('ollama')
  })

  it('provider=custom → OpenAICompatibleProvider 用传入 base_url', () => {
    const p = buildProvider({
      provider: 'custom',
      api_key: 'sk',
      base_url: 'https://my.api/v1',
      model: 'my-model',
    })
    expect(p).toBeInstanceOf(OpenAICompatibleProvider)
    expect((p as OpenAICompatibleProvider).base_url).toBe('https://my.api/v1')
  })
})
