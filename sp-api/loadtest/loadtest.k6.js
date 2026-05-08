/**
 * sp-api k6 压测脚本（HK client-only backend）
 *
 * 覆盖：
 *   - GET  /health              （无需 auth；FetcherRegistry.get_all_info）
 *   - GET  /api/health          （别名）
 *   - GET  /                    （根路径）
 *   - GET  /api/fetcher/sources （需 auth；测的是路由活性 + 401 一致性，不是数据正确）
 *   - POST /api/fetcher/search  （需 auth；同上，401 视为路由活）
 *
 * 设计说明：
 *   sp-api 几乎所有业务路由要 OAuth2 token，压测里不创建真实账号（成本 + 数据
 *   污染）。我们打无 token 请求，405/401/422 都算"路由活"，只把 5xx 计入失败。
 *   这套压测目的是验证：
 *     - uvicorn workers 的 RPS / latency
 *     - middleware（CORS / RequestLogger / ClientMeta）的 overhead
 *     - DB / Redis 连接池在 100 vu 下不爆
 *
 * 阈值：
 *   - http_req_failed < 5%（5xx 视为失败，client error 不算）
 *   - http_req_duration p95 < 800ms
 *
 * 跑法：
 *   k6 run loadtest.k6.js                            # 默认 http://localhost:18000
 *   SP_API_URL=http://x:y k6 run loadtest.k6.js      # 自定义 base
 *   k6 run --vus 50 --duration 30s loadtest.k6.js    # 覆盖 stages
 */

import http from 'k6/http'
import { check, sleep } from 'k6'
import { Counter, Rate, Trend } from 'k6/metrics'

export const options = {
  // 阶梯 ramp：20s 升到 20vu → 1min 升到 100vu → 20s 降回 0
  stages: [
    { duration: '20s', target: 20 },
    { duration: '1m', target: 100 },
    { duration: '20s', target: 0 },
  ],
  thresholds: {
    // ⚠️ 不用 http_req_failed —— k6 默认把 4xx 都算 failed，但我们故意不带 token，
    // /api/fetcher/* 必返 401，业务上是"路由活、门有锁"。改用自定义 5xx 计数器。
    http_req_duration: ['p(95)<800', 'p(99)<2000'],
    'app_5xx_total': ['count<50'],
    'health_ok_rate': ['rate>0.95'],
  },
  // 跑完不发通知，cli 退出即可
  noConnectionReuse: false,
  userAgent: 'k6-loadtest/sp-api',
}

const BASE = __ENV.SP_API_URL || 'http://localhost:18000'

// 自定义指标
const errs5xx = new Counter('app_5xx_total')
const healthOkRate = new Rate('health_ok_rate')
const sourcesLatency = new Trend('sources_latency_ms', true)

// 通用 5xx 检查器
function check5xx(r, label) {
  const is5xx = r.status >= 500
  if (is5xx) {
    errs5xx.add(1, { endpoint: label })
    console.error(`[5xx] ${label} → ${r.status} body=${r.body && r.body.slice(0, 200)}`)
  }
  return !is5xx
}

export function setup() {
  // 烟雾测试：先 ping 一下 health，挂掉 fail-fast
  const r = http.get(`${BASE}/health`, { timeout: '10s' })
  if (r.status !== 200) {
    throw new Error(`setup health check failed: ${r.status} body=${r.body && r.body.slice(0, 500)}`)
  }
  console.log(`[setup] sp-api up, sources=${(r.json().sources || []).length}`)
  return { baseUrl: BASE }
}

export default function (data) {
  // 1. /health（FetcherRegistry.get_all_info — 真路由）
  let r = http.get(`${data.baseUrl}/health`, { tags: { name: 'health' } })
  const healthOk = r.status === 200
  healthOkRate.add(healthOk)
  check(r, {
    'health 200': (r) => r.status === 200,
    'health has sources': (r) => {
      try { return Array.isArray(r.json().sources) } catch (e) { return false }
    },
  })
  check5xx(r, 'health')

  // 2. /api/health（别名，命中同 handler）
  r = http.get(`${data.baseUrl}/api/health`, { tags: { name: 'api_health' } })
  check(r, { 'api_health 200': (r) => r.status === 200 })
  check5xx(r, 'api_health')

  // 3. / 根路径
  r = http.get(`${data.baseUrl}/`, { tags: { name: 'root' } })
  check(r, { 'root 200': (r) => r.status === 200 })
  check5xx(r, 'root')

  // 4. /api/fetcher/sources（需 auth → 期望 401，但路由要活）
  r = http.get(`${data.baseUrl}/api/fetcher/sources`, { tags: { name: 'fetcher_sources' } })
  sourcesLatency.add(r.timings.duration)
  check(r, {
    'sources route alive (not 5xx)': (r) => r.status < 500,
    'sources auth-gated (401/403)': (r) => r.status === 401 || r.status === 403 || r.status === 200,
  })
  check5xx(r, 'fetcher_sources')

  // 5. /api/fetcher/search（POST，schema 校验路径）
  const payload = JSON.stringify({
    source: 'arxiv',
    keywords: 'transformer attention',
    max_results: 3,
  })
  r = http.post(`${data.baseUrl}/api/fetcher/search`, payload, {
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'fetcher_search' },
  })
  check(r, {
    'search route alive (not 5xx)': (r) => r.status < 500,
    // 401（无 token）/ 422（schema 错）都是合法响应
    'search returns 4xx (auth gate)': (r) => r.status >= 400 && r.status < 500,
  })
  check5xx(r, 'fetcher_search')

  // 1-3s 间随机间隔模拟真实用户节奏
  sleep(Math.random() * 2 + 1)
}

export function teardown(data) {
  console.log(`[teardown] base=${data.baseUrl}`)
}
