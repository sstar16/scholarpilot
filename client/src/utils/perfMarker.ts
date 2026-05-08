/**
 * Dev-only performance marker helpers.
 *
 * 生产构建（import.meta.env.DEV === false）所有函数等价 noop —— 0 运行时开销。
 *
 * 设计动机
 * ─────────
 * PERFORMANCE.md 的 B1（webview SQLite WASM）/ B2（Worker sync）deferred 决策依赖
 * 实测数据（IPC < 1ms / sync < 50ms）。但缺工具让用户/开发者能自己验证 — 现在补上。
 *
 * 用法
 * ───
 *   import { withMarker } from '@/utils/perfMarker'
 *
 *   const docs = await withMarker('repo.documents.list', () =>
 *     documentRepo.listByProject(pid),
 *   )
 *
 * 1. DevTools Performance 录制：marker 显示为 user-timing entry，跟 React/Vue 内部 entry 同 lane
 * 2. console 即时查看：`__sp_perf.dump()` 输出 p50/p95/max 表（filter 可过滤前缀）
 *
 * 触发 PERFORMANCE.md 决策门槛
 * ───────────────────────────
 *   B1（迁 SQLite 到 webview WASM）: hot path query p95 > 5ms 或 IPC 频率 > 100/sec
 *   B2（sync 移到 Web Worker）: sync 单次 p95 > 200ms
 *
 * 录一遍主要操作（创建项目 / 完成检索 / 切换项目 / 协作研究答问）后输入：
 *   __sp_perf.dump('sync:')   // sync 耗时
 *   __sp_perf.dump('repo.')   // SQLite query 耗时
 */

const DEV = import.meta.env.DEV === true
const MAX_SAMPLES = 500

interface Sample {
  name: string
  durationMs: number
  ts: number
}

const _samples: Sample[] = []

function _record(name: string, durationMs: number): void {
  if (!DEV) return
  if (_samples.length >= MAX_SAMPLES) _samples.shift()
  _samples.push({ name, durationMs, ts: Date.now() })
}

/**
 * 把异步/同步函数包一层 perf marker。dev 模式记录 user-timing + 内存样本，prod 直接 fn()。
 *
 * 不重命名 / 不重排参数 / 不吞错 — fn() throw 后仍 record 耗时再 rethrow。
 */
export async function withMarker<T>(
  name: string,
  fn: () => Promise<T> | T,
): Promise<T> {
  if (!DEV) return fn() as Promise<T>

  const startMark = `${name}:start`
  const endMark = `${name}:end`
  performance.mark(startMark)
  const t0 = performance.now()
  try {
    return await fn()
  } finally {
    const dur = performance.now() - t0
    performance.mark(endMark)
    try {
      performance.measure(name, startMark, endMark)
    } catch {
      /* startMark 已被 clear / 不存在 — 忽略 */
    }
    performance.clearMarks(startMark)
    performance.clearMarks(endMark)
    _record(name, dur)
  }
}

interface Stat {
  name: string
  count: number
  p50: number
  p95: number
  max: number
  totalMs: number
}

function _percentile(sorted: number[], p: number): number {
  if (!sorted.length) return 0
  const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * p))
  return sorted[idx]
}

export function getStats(filter?: string): Stat[] {
  const groups = new Map<string, number[]>()
  for (const s of _samples) {
    if (filter && !s.name.includes(filter)) continue
    let g = groups.get(s.name)
    if (!g) {
      g = []
      groups.set(s.name, g)
    }
    g.push(s.durationMs)
  }
  return Array.from(groups.entries())
    .map(([name, durs]): Stat => {
      const sorted = durs.slice().sort((a, b) => a - b)
      return {
        name,
        count: sorted.length,
        p50: _percentile(sorted, 0.5),
        p95: _percentile(sorted, 0.95),
        max: sorted[sorted.length - 1] ?? 0,
        totalMs: sorted.reduce((s, d) => s + d, 0),
      }
    })
    .sort((a, b) => b.totalMs - a.totalMs)
}

export function dumpMarkers(filter?: string): void {
  if (!DEV) {
    console.warn('[perfMarker] dump disabled in production build')
    return
  }
  const stats = getStats(filter)
  if (!stats.length) {
    console.info(
      '[perfMarker] no samples yet — operate the app first (e.g. open project / send message), then dump again',
    )
    return
  }
  console.table(
    stats.map((s) => ({
      name: s.name,
      count: s.count,
      p50_ms: +s.p50.toFixed(2),
      p95_ms: +s.p95.toFixed(2),
      max_ms: +s.max.toFixed(2),
      total_ms: +s.totalMs.toFixed(0),
    })),
  )
}

export function clearMarkers(): void {
  if (!DEV) return
  _samples.length = 0
  performance.clearMeasures()
}

if (DEV && typeof window !== 'undefined') {
  ;(window as unknown as { __sp_perf: object }).__sp_perf = {
    dump: dumpMarkers,
    getStats,
    clear: clearMarkers,
    samples: (): readonly Sample[] => _samples.slice(),
  }
}
