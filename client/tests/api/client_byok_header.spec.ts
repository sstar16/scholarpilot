import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('@/api/secure_storage', () => ({
  SECURE_KEYS: {
    ACCESS_TOKEN: 'access_token',
    REFRESH_TOKEN: 'refresh_token',
    USER_ID: 'user_id',
    BYOK_CONFIG: 'byok_config',
  },
  secureGet: vi.fn(async () => null),
  secureSet: vi.fn(),
  secureDelete: vi.fn(),
}))
vi.mock('element-plus', () => ({ ElMessage: { warning: vi.fn() } }))

import api, {
  setAccessTokenCache,
  setByokActiveCache,
  setByokConfigCache,
  _resetApiCacheForTesting,
} from '@/api/client'

function _runInterceptor(): Record<string, any> {
  const fakeConfig: any = { headers: {}, url: '/api/test', method: 'get' }
  const handler = (api.interceptors.request as any).handlers[0].fulfilled
  // A1 后拦截器是 sync — 直接返回 config，不需要 await
  return handler(fakeConfig) as Record<string, any>
}

describe('ApiClient request interceptor (A1: module-level sync cache)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    _resetApiCacheForTesting()
  })

  it('access token cache 为 null → 不注入 Authorization', () => {
    setAccessTokenCache(null)
    const result = _runInterceptor()
    expect(result.headers.Authorization).toBeUndefined()
    expect(result.headers['X-Client-Type']).toBeDefined()
    expect(result.headers['X-Client-Version']).toBeDefined()
  })

  it('access token cache 已设 → 注入 Bearer header', () => {
    setAccessTokenCache('fake-access-token')
    const result = _runInterceptor()
    expect(result.headers.Authorization).toBe('Bearer fake-access-token')
  })

  it('byok_active=false → 不注入 BYOK header（即使 config 已 cache）', () => {
    setAccessTokenCache('tok')
    setByokActiveCache(false)
    setByokConfigCache({
      provider: 'openai',
      api_key: 'sk-x',
      model: 'gpt-4o',
      base_url: null,
      configured_at: 1,
    })
    const result = _runInterceptor()
    expect(result.headers['X-User-LLM-Key']).toBeUndefined()
    expect(result.headers['X-User-LLM-Provider']).toBeUndefined()
    expect(result.headers['X-Client-Type']).toBeDefined()
  })

  it('byok_active=true + 完整 config → 注入全部 4 个 BYOK header', () => {
    setAccessTokenCache('tok')
    setByokActiveCache(true)
    setByokConfigCache({
      provider: 'openai',
      api_key: 'sk-x',
      model: 'gpt-4o',
      base_url: 'https://x.example.com',
      configured_at: 1,
    })
    const result = _runInterceptor()
    expect(result.headers['X-User-LLM-Provider']).toBe('openai')
    expect(result.headers['X-User-LLM-Key']).toBe('sk-x')
    expect(result.headers['X-User-LLM-Model']).toBe('gpt-4o')
    expect(result.headers['X-User-LLM-Base-Url']).toBe('https://x.example.com')
  })

  it('byok_active=true 但 config cache 为 null → 不注入（防御）', () => {
    setAccessTokenCache('tok')
    setByokActiveCache(true)
    setByokConfigCache(null)
    const result = _runInterceptor()
    expect(result.headers['X-User-LLM-Key']).toBeUndefined()
  })
})
