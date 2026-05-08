/**
 * GraphRepo 单测 — 用 in-memory FS mock 验证：
 *  1. loadNodes / loadEdges 空目录 → 返 []
 *  2. mergeFragment 增量合并：同主键 weight 累加 cap 1.0；source_doc_ids union
 *  3. mergeFragment 同 source/target/relation 边合并
 *  4. writeSnapshot 写盘 + 路径正确
 *  5. gcSnapshots 保留最近 N 份
 *  6. 事务式写：tmp 失败不污染正式文件
 *
 * 不打 Tauri：vi.mock('@/data/fs/files', ...) 用 Map 模拟整个 FS。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ──────────────────────── In-memory FS mock ────────────────────────

interface FsEntry {
  content: string
  modified_ms: number
  size: number
}

const _fsStore: Map<string, FsEntry> = new Map()
let _now = 1_700_000_000_000 // 起始 mock 时间（ms）
let _writeFailFor: string | RegExp | null = null

function _matches(path: string, pattern: string | RegExp): boolean {
  return typeof pattern === 'string' ? path === pattern : pattern.test(path)
}

vi.mock('@/data/fs/files', () => ({
  readText: vi.fn(async (rel: string) => {
    const e = _fsStore.get(rel)
    return e ? e.content : null
  }),
  writeText: vi.fn(async (rel: string, content: string) => {
    if (_writeFailFor && _matches(rel, _writeFailFor)) {
      throw new Error(`mock write fail for ${rel}`)
    }
    _now += 10
    _fsStore.set(rel, {
      content,
      modified_ms: _now,
      size: content.length,
    })
  }),
  writeBytes: vi.fn(),
  readBytes: vi.fn(),
  fileExists: vi.fn(async (rel: string) => _fsStore.has(rel)),
  fileSize: vi.fn(async (rel: string) => _fsStore.get(rel)?.size ?? null),
  removePath: vi.fn(async (rel: string) => {
    _fsStore.delete(rel)
  }),
  listDir: vi.fn(async (rel: string) => {
    const out: Array<{ name: string; is_dir: boolean; size: number; modified_ms: number }> = []
    const prefix = rel.endsWith('/') ? rel : rel + '/'
    const seenChildren = new Set<string>()
    for (const [path, e] of _fsStore.entries()) {
      if (!path.startsWith(prefix)) continue
      const remainder = path.slice(prefix.length)
      if (remainder.includes('/')) {
        const dirName = remainder.slice(0, remainder.indexOf('/'))
        if (!seenChildren.has(dirName)) {
          seenChildren.add(dirName)
          out.push({ name: dirName, is_dir: true, size: 0, modified_ms: e.modified_ms })
        }
        continue
      }
      if (seenChildren.has(remainder)) continue
      seenChildren.add(remainder)
      out.push({ name: remainder, is_dir: false, size: e.size, modified_ms: e.modified_ms })
    }
    return out
  }),
  downloadToFile: vi.fn(),
  PATHS: undefined as any, // re-export 走 paths.ts
  assertSafeId: undefined as any,
}))

import { GraphRepo, GraphRepoError, mergeIntoLists, type GraphEdge, type GraphNode } from '../graphRepo'
import type { GraphFragment } from '@/data/agents/graphAgent'

// ──────────────────────── reset ────────────────────────

beforeEach(() => {
  _fsStore.clear()
  _now = 1_700_000_000_000
  _writeFailFor = null
  vi.clearAllMocks()
})

// ──────────────────────── mergeIntoLists 纯函数 ────────────────────────

describe('mergeIntoLists', () => {
  it('空 existing + 空 fragment → 空结果', () => {
    const out = mergeIntoLists([], [], { entities: [], relations: [] })
    expect(out.nodes).toEqual([])
    expect(out.edges).toEqual([])
  })

  it('空 existing + 有 fragment → 直接装载', () => {
    const fragment: GraphFragment = {
      entities: [
        { label: 'A', type: 'concept', weight: 0.5, source_doc_ids: ['d1'] },
        { label: 'B', type: 'paper', weight: 0.7, source_doc_ids: ['d1'] },
      ],
      relations: [{ source: 'A', target: 'B', relation: 'topic', weight: 0.6 }],
    }
    const out = mergeIntoLists([], [], fragment)
    expect(out.nodes).toHaveLength(2)
    expect(out.edges).toHaveLength(1)
    expect(out.nodes[0].label).toBe('A')
  })

  it('同 (label, type) 节点 → weight 累加 cap 1.0', () => {
    const existing: GraphNode[] = [
      { label: 'A', type: 'concept', weight: 0.6, source_doc_ids: ['d1'] },
    ]
    const fragment: GraphFragment = {
      entities: [{ label: 'A', type: 'concept', weight: 0.5, source_doc_ids: ['d2'] }],
      relations: [],
    }
    const out = mergeIntoLists(existing, [], fragment)
    expect(out.nodes).toHaveLength(1)
    // 0.6 + 0.5 = 1.1, cap 到 1.0
    expect(out.nodes[0].weight).toBe(1.0)
    // source_doc_ids union
    expect(out.nodes[0].source_doc_ids.sort()).toEqual(['d1', 'd2'])
  })

  it('同 label 不同 type → 不同节点（type 是主键一部分）', () => {
    const fragment: GraphFragment = {
      entities: [
        { label: 'X', type: 'concept', weight: 0.5, source_doc_ids: ['d1'] },
        { label: 'X', type: 'method', weight: 0.5, source_doc_ids: ['d1'] },
      ],
      relations: [],
    }
    const out = mergeIntoLists([], [], fragment)
    expect(out.nodes).toHaveLength(2)
  })

  it('label 大小写 / 空白不影响主键', () => {
    const existing: GraphNode[] = [
      { label: 'GraphNN', type: 'concept', weight: 0.4, source_doc_ids: ['d1'] },
    ]
    const fragment: GraphFragment = {
      entities: [{ label: '  graphnn  ', type: 'concept', weight: 0.3, source_doc_ids: ['d2'] }],
      relations: [],
    }
    const out = mergeIntoLists(existing, [], fragment)
    expect(out.nodes).toHaveLength(1)
    expect(out.nodes[0].weight).toBeCloseTo(0.7)
    expect(out.nodes[0].source_doc_ids.sort()).toEqual(['d1', 'd2'])
  })

  it('source_doc_ids union 不重复', () => {
    const existing: GraphNode[] = [
      { label: 'A', type: 'concept', weight: 0.3, source_doc_ids: ['d1', 'd2'] },
    ]
    const fragment: GraphFragment = {
      entities: [{ label: 'A', type: 'concept', weight: 0.2, source_doc_ids: ['d2', 'd3'] }],
      relations: [],
    }
    const out = mergeIntoLists(existing, [], fragment)
    expect(out.nodes[0].source_doc_ids.sort()).toEqual(['d1', 'd2', 'd3'])
  })

  it('同 (source, target, relation) 边 → weight 累加', () => {
    const existing: GraphEdge[] = [
      { source: 'A', target: 'B', relation: 'cites', weight: 0.5 },
    ]
    const fragment: GraphFragment = {
      entities: [
        { label: 'A', type: 'concept', weight: 0.5, source_doc_ids: ['d1'] },
        { label: 'B', type: 'concept', weight: 0.5, source_doc_ids: ['d1'] },
      ],
      relations: [{ source: 'A', target: 'B', relation: 'cites', weight: 0.3 }],
    }
    const out = mergeIntoLists([], existing, fragment)
    expect(out.edges).toHaveLength(1)
    expect(out.edges[0].weight).toBeCloseTo(0.8)
  })

  it('同 source/target 不同 relation → 不同边', () => {
    const fragment: GraphFragment = {
      entities: [
        { label: 'A', type: 'concept', weight: 0.5, source_doc_ids: ['d1'] },
        { label: 'B', type: 'concept', weight: 0.5, source_doc_ids: ['d1'] },
      ],
      relations: [
        { source: 'A', target: 'B', relation: 'cites', weight: 0.5 },
        { source: 'A', target: 'B', relation: 'extends', weight: 0.4 },
      ],
    }
    const out = mergeIntoLists([], [], fragment)
    expect(out.edges).toHaveLength(2)
  })
})

// ──────────────────────── GraphRepo basic IO ────────────────────────

describe('GraphRepo: load 空目录', () => {
  it('loadNodes 文件不存在 → 返 []', async () => {
    const repo = new GraphRepo('proj-1')
    expect(await repo.loadNodes()).toEqual([])
  })

  it('loadEdges 文件不存在 → 返 []', async () => {
    const repo = new GraphRepo('proj-1')
    expect(await repo.loadEdges()).toEqual([])
  })

  it('loadNodes 文件损坏 → 返 [] 不抛', async () => {
    const repo = new GraphRepo('proj-1')
    _fsStore.set(repo.nodesPath, { content: 'not json', modified_ms: _now, size: 8 })
    expect(await repo.loadNodes()).toEqual([])
  })

  it('exists() 文件不存在 → false', async () => {
    const repo = new GraphRepo('proj-1')
    expect(await repo.exists()).toBe(false)
  })

  it('projectId 路径符号 → 抛错', () => {
    expect(() => new GraphRepo('../evil')).toThrow(/Unsafe/)
  })
})

// ──────────────────────── mergeFragment ────────────────────────

describe('GraphRepo.mergeFragment', () => {
  it('空 graph + fragment → 写出 nodes.json + edges.json', async () => {
    const repo = new GraphRepo('proj-2', { projectTitle: null })
    const fragment: GraphFragment = {
      entities: [
        { label: 'Transformer', type: 'method', weight: 0.9, source_doc_ids: ['d1'] },
        { label: 'Attention', type: 'concept', weight: 0.8, source_doc_ids: ['d1'] },
      ],
      relations: [{ source: 'Transformer', target: 'Attention', relation: 'topic', weight: 0.85 }],
    }
    await repo.mergeFragment(fragment)

    const nodes = await repo.loadNodes()
    const edges = await repo.loadEdges()
    expect(nodes).toHaveLength(2)
    expect(edges).toHaveLength(1)
    expect(nodes[0].label).toBe('Transformer')
    // 文件实际写到 fsStore
    expect(_fsStore.has(repo.nodesPath)).toBe(true)
    expect(_fsStore.has(repo.edgesPath)).toBe(true)
  })

  it('两次 merge：同标签 weight 累加 → load 可见合并结果', async () => {
    const repo = new GraphRepo('proj-3')
    await repo.mergeFragment({
      entities: [{ label: 'A', type: 'concept', weight: 0.4, source_doc_ids: ['d1'] }],
      relations: [],
    })
    await repo.mergeFragment({
      entities: [{ label: 'A', type: 'concept', weight: 0.3, source_doc_ids: ['d2'] }],
      relations: [],
    })
    const nodes = await repo.loadNodes()
    expect(nodes).toHaveLength(1)
    expect(nodes[0].weight).toBeCloseTo(0.7)
    expect(nodes[0].source_doc_ids.sort()).toEqual(['d1', 'd2'])
  })

  it('mergeFragment 抛 nullable 时不污染数据', async () => {
    const repo = new GraphRepo('proj-4')
    await expect(repo.mergeFragment(null as any)).rejects.toBeInstanceOf(GraphRepoError)
  })

  it('事务式写：tmp 写失败 → 正式文件保持原样', async () => {
    const repo = new GraphRepo('proj-5')
    // 先成功写一次
    await repo.mergeFragment({
      entities: [{ label: 'Init', type: 'paper', weight: 0.5, source_doc_ids: ['d1'] }],
      relations: [],
    })
    const beforeNodes = await repo.loadNodes()
    expect(beforeNodes).toHaveLength(1)

    // 模拟下一次写 tmp 文件失败
    _writeFailFor = /\.tmp$/
    await expect(
      repo.mergeFragment({
        entities: [{ label: 'New', type: 'paper', weight: 0.5, source_doc_ids: ['d2'] }],
        relations: [],
      }),
    ).rejects.toThrow()
    // 正式文件还是原样（仍只有 Init）
    const afterNodes = await repo.loadNodes()
    expect(afterNodes).toHaveLength(1)
    expect(afterNodes[0].label).toBe('Init')
  })
})

// ──────────────────────── writeSnapshot + GC ────────────────────────

describe('GraphRepo.writeSnapshot + GC', () => {
  it('写一份快照 → 列出可见', async () => {
    const repo = new GraphRepo('proj-6')
    await repo.mergeFragment({
      entities: [{ label: 'X', type: 'concept', weight: 0.5, source_doc_ids: ['d1'] }],
      relations: [],
    })
    await repo.writeSnapshot('round-1')
    const list = await repo.listSnapshots()
    expect(list).toHaveLength(1)
    expect(list[0].round_id).toBe('round-1')
    // 路径正确
    expect(_fsStore.has(`${repo.snapshotsDir}/round-1.json`)).toBe(true)

    // 内容可解析回 GraphSnapshot
    const raw = _fsStore.get(`${repo.snapshotsDir}/round-1.json`)!.content
    const snap = JSON.parse(raw)
    expect(snap.round_id).toBe('round-1')
    expect(snap.nodes).toHaveLength(1)
    expect(snap.created_at).toBeGreaterThan(0)
  })

  it('roundId 路径符号 → 抛错', async () => {
    const repo = new GraphRepo('proj-7')
    await expect(repo.writeSnapshot('../evil')).rejects.toThrow(/Unsafe/)
  })

  it('GC：保留最近 20 份，第 21 份起最旧的删', async () => {
    const repo = new GraphRepo('proj-8', { snapshotKeepCount: 20 })
    // 先写 25 份快照（每份 mtime 递增）
    for (let i = 1; i <= 25; i++) {
      await repo.writeSnapshot(`round-${i}`)
    }
    const list = await repo.listSnapshots()
    expect(list.length).toBe(20)
    // 最早的 round-1..round-5 应该被删除
    const names = list.map((l) => l.round_id).sort()
    expect(names).not.toContain('round-1')
    expect(names).not.toContain('round-5')
    expect(names).toContain('round-25')
    expect(names).toContain('round-6')
  })

  it('GC：自定义 keep=3', async () => {
    const repo = new GraphRepo('proj-9', { snapshotKeepCount: 3 })
    for (let i = 1; i <= 5; i++) {
      await repo.writeSnapshot(`r-${i}`)
    }
    const list = await repo.listSnapshots()
    expect(list.length).toBe(3)
    const names = list.map((l) => l.round_id).sort()
    expect(names).toEqual(['r-3', 'r-4', 'r-5'])
  })

  it('listSnapshots 目录不存在 → []', async () => {
    const repo = new GraphRepo('proj-10')
    expect(await repo.listSnapshots()).toEqual([])
  })
})

// ──────────────────────── exportLayout ────────────────────────

describe('GraphRepo.exportLayout', () => {
  it('写 layout.json 占位（C11 后续填充）', async () => {
    const repo = new GraphRepo('proj-11')
    await repo.exportLayout({ positions: { A: { x: 1, y: 2 } } })
    expect(_fsStore.has(repo.layoutPath)).toBe(true)
    const raw = _fsStore.get(repo.layoutPath)!.content
    const data = JSON.parse(raw)
    expect(data.positions.A).toEqual({ x: 1, y: 2 })
  })

  it('不传 layoutData → 写默认 stub', async () => {
    const repo = new GraphRepo('proj-12')
    await repo.exportLayout()
    const raw = _fsStore.get(repo.layoutPath)!.content
    const data = JSON.parse(raw)
    expect(data.positions).toEqual({})
    expect(data.generated_at).toBeGreaterThan(0)
  })
})

// ──────────────────────── path 正确性 ────────────────────────

describe('GraphRepo: path 命名', () => {
  it('UUID 项目（无 title）→ projects/<id>/library/graph/...', () => {
    const repo = new GraphRepo('proj-x')
    expect(repo.nodesPath).toBe('projects/proj-x/library/graph/nodes.json')
    expect(repo.edgesPath).toBe('projects/proj-x/library/graph/edges.json')
    expect(repo.layoutPath).toBe('projects/proj-x/library/graph/layout.json')
    expect(repo.snapshotsDir).toBe('projects/proj-x/library/graph/snapshots')
  })

  it('有 projectTitle → 路径走 slug', () => {
    // 客户端 slug 规则我们不强假设格式，只验包含 graph 路径片段
    const repo = new GraphRepo('proj-x', { projectTitle: 'My Research' })
    expect(repo.nodesPath).toContain('library/graph/nodes.json')
  })
})
