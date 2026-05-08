// @vitest-environment happy-dom
/**
 * KnowledgeGraph 单测 — Vue 组件 mount 需要 DOM env。
 *
 * 测试策略：cytoscape 整个 mock 掉，仅在 happy-dom 内 mount Vue 组件验证：
 *   1. CytoscapeCanvas onMounted 调一次 cytoscape() 工厂、destroy 在 unmount 时调用
 *   2. cytoscape 实例没有被 ref/reactive 包装（用 Vue Proxy 检测）
 *   3. useGraphRenderer 把 GraphRepo 的 nodes/edges 转成 cytoscape elements 正确
 *   4. KnowledgeGraph view 渲染节点 60+ 不崩
 *   5. LOD 阈值 500：超过自动设 filterType=['paper','method','technology']
 *   6. EventBus `graph_updated` 触发 reload
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { isProxy, isReactive, isRef, nextTick } from 'vue'

// ─────────────── cytoscape 工厂 mock ───────────────
// CytoscapeCanvas onMounted 时 import 'cytoscape' / 'cytoscape-fcose'，
// 在 Node 环境跑时 cytoscape 内部需要 DOM，所以全 mock 掉。
const _cytoscapeInstances: any[] = []

function _makeFakeCy(): any {
  const fakeCollection = {
    length: 0,
    remove: vi.fn(),
    addClass: vi.fn(() => fakeCollection),
    removeClass: vi.fn(() => fakeCollection),
    neighborhood: vi.fn(() => fakeCollection),
    forEach: vi.fn(),
  }
  const fakeNodesCollection = Object.assign(
    Object.create({
      [Symbol.iterator]: function* () {
        // empty default — 单测可覆盖
      },
    }),
    fakeCollection,
  )

  const cy = {
    on: vi.fn(),
    elements: vi.fn(() => fakeCollection),
    nodes: vi.fn(() => fakeNodesCollection),
    add: vi.fn(),
    getElementById: vi.fn(() => ({ length: 0, remove: vi.fn(), removeClass: vi.fn(), neighborhood: vi.fn(() => fakeCollection) })),
    layout: vi.fn(() => ({ run: vi.fn() })),
    fit: vi.fn(),
    center: vi.fn(),
    animate: vi.fn(),
    batch: vi.fn((fn: () => void) => fn()),
    destroy: vi.fn(),
  }
  _cytoscapeInstances.push(cy)
  return cy
}

vi.mock('cytoscape', () => {
  const factory = vi.fn(() => _makeFakeCy())
  // cytoscape.use() 注册扩展（fcose）— mock 成 no-op
  ;(factory as any).use = vi.fn()
  return {
    default: factory,
  }
})

vi.mock('cytoscape-fcose', () => ({
  default: function fcoseExt() {
    /* no-op extension stub */
  },
}))

// ─────────────── GraphRepo mock ───────────────
// 不打 Tauri fs；直接给 view 一组返回值。
let _mockNodes: any[] = []
let _mockEdges: any[] = []
let _mockLayoutText: string | null = null

vi.mock('@/data/graph/graphRepo', () => {
  return {
    GraphRepo: class {
      nodesPath = 'projects/proj-1/library/graph/nodes.json'
      edgesPath = 'projects/proj-1/library/graph/edges.json'
      layoutPath = 'projects/proj-1/library/graph/layout.json'
      snapshotsDir = 'projects/proj-1/library/graph/snapshots'
      async loadNodes() {
        return _mockNodes
      }
      async loadEdges() {
        return _mockEdges
      }
      async exportLayout(_data: unknown) {
        // no-op
      }
    },
  }
})

vi.mock('@/data/fs/files', () => ({
  readText: vi.fn(async (rel: string) => {
    if (rel.endsWith('layout.json')) return _mockLayoutText
    return null
  }),
  writeText: vi.fn(),
  fileExists: vi.fn(),
  removePath: vi.fn(),
  listDir: vi.fn(async () => []),
  PATHS: {} as any,
  assertSafeId: () => true,
}))

// ─────────────── vue-router mock（route.params） ───────────────
let _routeParams: Record<string, string> = { projectId: 'proj-1' }
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: _routeParams }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

// ─────────────── 通用 setup ───────────────

import { mount, flushPromises } from '@vue/test-utils'
import KnowledgeGraph from '../KnowledgeGraph.vue'
import CytoscapeCanvas from '@/components/graph/CytoscapeCanvas.vue'
import { _resetEventBusForTesting, getEventBus } from '@/data/orchestrator/eventBus'
import {
  buildElements,
  buildLayoutOptions,
  isCachedLayoutUsable,
  snapshotPositions,
} from '@/composables/useGraphRenderer'

beforeEach(() => {
  _mockNodes = []
  _mockEdges = []
  _mockLayoutText = null
  _routeParams = { projectId: 'proj-1' }
  _cytoscapeInstances.length = 0
  _resetEventBusForTesting()
  vi.clearAllMocks()
})

afterEach(() => {
  /* 清理已挂载组件由 vue-test-utils unmount 默认处理 */
})

// ──────────────────────── useGraphRenderer 纯函数 ────────────────────────

describe('useGraphRenderer.buildElements', () => {
  it('空 nodes/edges → 空 elements', () => {
    const out = buildElements([], [], null)
    expect(out.elements).toEqual([])
    expect(out.degreeMap).toEqual({})
    expect(out.missingPositions).toBe(0)
  })

  it('翻译 nodes/edges → group=nodes/edges + size + color', () => {
    const nodes = [
      { label: 'Transformer', type: 'method' as const, weight: 0.9, source_doc_ids: ['d1'] },
      { label: 'Attention', type: 'concept' as const, weight: 0.8, source_doc_ids: ['d1', 'd2'] },
    ]
    const edges = [
      { source: 'Transformer', target: 'Attention', relation: 'topic' as const, weight: 0.6 },
    ]
    const out = buildElements(nodes, edges, null)
    expect(out.elements).toHaveLength(3)
    const node0 = out.elements[0] as any
    expect(node0.group).toBe('nodes')
    expect(node0.data.id).toBe('Transformer')
    expect(node0.data.type).toBe('method')
    expect(typeof node0.data.size).toBe('number')
    const edge = out.elements[2] as any
    expect(edge.group).toBe('edges')
    expect(edge.data.source).toBe('Transformer')
    expect(edge.data.target).toBe('Attention')
  })

  it('跳过端点不存在的边', () => {
    const nodes = [{ label: 'A', type: 'concept' as const, weight: 0.5, source_doc_ids: [] }]
    const edges = [
      { source: 'A', target: 'B', relation: 'cites' as const, weight: 0.5 },
      { source: 'A', target: 'A', relation: 'cites' as const, weight: 0.5 },
    ]
    const out = buildElements(nodes, edges, null)
    // B 不存在，第一条跳；第二条 self-loop 端点存在 → 保留（cytoscape 自己处理 self-loop 渲染）
    expect(out.elements.filter((e: any) => e.group === 'edges')).toHaveLength(1)
  })

  it('cachedLayout 给定坐标 → element.position 注入', () => {
    const nodes = [
      { label: 'A', type: 'concept' as const, weight: 0.5, source_doc_ids: [] },
      { label: 'B', type: 'concept' as const, weight: 0.5, source_doc_ids: [] },
    ]
    const layout = {
      positions: { A: { x: 10, y: 20 } },
      generated_at: 1700000000000,
    }
    const out = buildElements(nodes, [], layout)
    const a = out.elements[0] as any
    const b = out.elements[1] as any
    expect(a.position).toEqual({ x: 10, y: 20 })
    expect(b.position).toBeUndefined()
    expect(out.missingPositions).toBe(1)
  })
})

describe('useGraphRenderer.isCachedLayoutUsable', () => {
  it('null layout → false', () => {
    expect(isCachedLayoutUsable([], null)).toBe(false)
  })
  it('覆盖率 ≥ 70% → true', () => {
    const nodes = Array.from({ length: 10 }, (_, i) => ({
      label: `n${i}`,
      type: 'concept' as const,
      weight: 0.5,
      source_doc_ids: [],
    }))
    const layout = {
      positions: Object.fromEntries(
        Array.from({ length: 8 }, (_, i) => [`n${i}`, { x: i, y: i }]),
      ),
      generated_at: 0,
    }
    expect(isCachedLayoutUsable(nodes, layout)).toBe(true)
  })
  it('覆盖率 < 70% → false', () => {
    const nodes = Array.from({ length: 10 }, (_, i) => ({
      label: `n${i}`,
      type: 'concept' as const,
      weight: 0.5,
      source_doc_ids: [],
    }))
    const layout = {
      positions: Object.fromEntries(
        Array.from({ length: 5 }, (_, i) => [`n${i}`, { x: i, y: i }]),
      ),
      generated_at: 0,
    }
    expect(isCachedLayoutUsable(nodes, layout)).toBe(false)
  })
})

describe('useGraphRenderer.buildLayoutOptions', () => {
  it('hasCachedPositions=true → preset', () => {
    const opts = buildLayoutOptions('fcose', true) as any
    expect(opts.name).toBe('preset')
  })
  it('fcose name → fcose options + animate=false', () => {
    const opts = buildLayoutOptions('fcose', false) as any
    expect(opts.name).toBe('fcose')
    expect(opts.animate).toBe(false)
    expect(opts.randomize).toBe(false)
  })
  it('其他 layout 透传 name', () => {
    expect((buildLayoutOptions('circle') as any).name).toBe('circle')
    expect((buildLayoutOptions('grid') as any).name).toBe('grid')
    expect((buildLayoutOptions('concentric') as any).name).toBe('concentric')
  })
})

describe('useGraphRenderer.snapshotPositions', () => {
  it('迭代 cy.nodes() iter → CachedLayout', () => {
    const fakeNodes = [
      { id: () => 'A', position: () => ({ x: 1, y: 2 }) },
      { id: () => 'B', position: () => ({ x: 3, y: 4 }) },
    ]
    const snap = snapshotPositions(fakeNodes)
    expect(snap.positions).toEqual({ A: { x: 1, y: 2 }, B: { x: 3, y: 4 } })
    expect(snap.generated_at).toBeGreaterThan(0)
  })
})

// ──────────────────────── CytoscapeCanvas 单测 ────────────────────────

describe('CytoscapeCanvas', () => {
  it('onMounted 调用 cytoscape 工厂一次', async () => {
    const cy = await import('cytoscape')
    const wrapper = mount(CytoscapeCanvas, {
      props: { nodes: [], edges: [], layout: null },
    })
    await flushPromises()
    expect(cy.default).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('onUnmount destroy cytoscape 实例', async () => {
    const wrapper = mount(CytoscapeCanvas, {
      props: { nodes: [], edges: [], layout: null },
    })
    await flushPromises()
    expect(_cytoscapeInstances).toHaveLength(1)
    const cy = _cytoscapeInstances[0]
    wrapper.unmount()
    expect(cy.destroy).toHaveBeenCalledTimes(1)
  })

  it('cytoscape 实例没有被 Vue ref/reactive 包装（避免 issue #2844 的 Proxy 拦截）', async () => {
    // _getCyForTesting 暴露给单测
    const wrapper = mount(CytoscapeCanvas, {
      props: { nodes: [], edges: [], layout: null },
    })
    await flushPromises()
    const cy = (wrapper.vm as any)._getCyForTesting()
    expect(cy).not.toBeNull()
    expect(isRef(cy)).toBe(false)
    expect(isReactive(cy)).toBe(false)
    expect(isProxy(cy)).toBe(false)
    wrapper.unmount()
  })

  it('addElements / removeElements API 直接调到 cy', async () => {
    const wrapper = mount(CytoscapeCanvas, {
      props: { nodes: [], edges: [], layout: null },
    })
    await flushPromises()
    const cy = _cytoscapeInstances[0]
    ;(wrapper.vm as any).addElements([{ data: { id: 'X' } } as any])
    expect(cy.add).toHaveBeenCalled()
    ;(wrapper.vm as any).removeElements(['X'])
    expect(cy.getElementById).toHaveBeenCalledWith('X')
    wrapper.unmount()
  })
})

// ──────────────────────── KnowledgeGraph view 单测 ────────────────────────

describe('KnowledgeGraph view', () => {
  it('60+ 节点渲染不崩', async () => {
    _mockNodes = Array.from({ length: 65 }, (_, i) => ({
      label: `node-${i}`,
      type: i % 3 === 0 ? 'paper' : i % 3 === 1 ? 'concept' : 'method',
      weight: 0.5,
      source_doc_ids: [`d${i}`],
    }))
    _mockEdges = Array.from({ length: 60 }, (_, i) => ({
      source: `node-${i}`,
      target: `node-${i + 1}`,
      relation: 'topic' as const,
      weight: 0.5,
    }))
    const wrapper = mount(KnowledgeGraph)
    await flushPromises()
    await nextTick()
    expect(wrapper.find('[data-testid="knowledge-graph-page"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="cytoscape-canvas"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('LOD 阈值 500：> 500 节点自动设 filterType=[paper, method, technology]', async () => {
    _mockNodes = Array.from({ length: 600 }, (_, i) => ({
      label: `n-${i}`,
      type: i % 3 === 0 ? 'paper' : i % 3 === 1 ? 'concept' : 'author',
      weight: 0.5,
      source_doc_ids: [],
    }))
    _mockEdges = []
    const wrapper = mount(KnowledgeGraph)
    await flushPromises()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.lodActive).toBe(true)
    expect(vm.filterType.sort()).toEqual(['method', 'paper', 'technology'])
    // concept/author 类型被过滤掉了
    const filteredTypes = new Set(vm.filteredNodes.map((n: any) => n.type))
    expect(filteredTypes.has('concept')).toBe(false)
    expect(filteredTypes.has('author')).toBe(false)
    expect(filteredTypes.has('paper')).toBe(true)
    wrapper.unmount()
  })

  it('LOD 阈值 500：≤ 500 节点不启用 LOD', async () => {
    _mockNodes = Array.from({ length: 100 }, (_, i) => ({
      label: `n-${i}`,
      type: i % 2 === 0 ? 'paper' : 'concept',
      weight: 0.5,
      source_doc_ids: [],
    }))
    _mockEdges = []
    const wrapper = mount(KnowledgeGraph)
    await flushPromises()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.lodActive).toBe(false)
    expect(vm.filterType).toEqual([])
    wrapper.unmount()
  })

  it('搜索过滤：只显示 label 包含查询字符串的节点', async () => {
    _mockNodes = [
      { label: 'Transformer', type: 'method', weight: 0.9, source_doc_ids: [] },
      { label: 'GraphNN', type: 'method', weight: 0.7, source_doc_ids: [] },
      { label: 'Attention', type: 'concept', weight: 0.8, source_doc_ids: [] },
    ]
    _mockEdges = []
    const wrapper = mount(KnowledgeGraph)
    await flushPromises()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.filteredNodes).toHaveLength(3)
    vm.search = 'graph'
    await nextTick()
    expect(vm.filteredNodes).toHaveLength(1)
    expect(vm.filteredNodes[0].label).toBe('GraphNN')
    wrapper.unmount()
  })

  it('EventBus graph_updated 事件 → 触发 reload', async () => {
    _mockNodes = [
      { label: 'A', type: 'concept', weight: 0.5, source_doc_ids: [] },
    ]
    _mockEdges = []
    const wrapper = mount(KnowledgeGraph)
    await flushPromises()
    await nextTick()
    expect((wrapper.vm as any).nodes).toHaveLength(1)

    // 改 mock 再 publish
    _mockNodes = [
      { label: 'A', type: 'concept', weight: 0.5, source_doc_ids: [] },
      { label: 'B', type: 'paper', weight: 0.7, source_doc_ids: [] },
    ]
    getEventBus().publish('graph:proj-1', 'graph_updated', { count: 2 })
    await flushPromises()
    await nextTick()
    expect((wrapper.vm as any).nodes).toHaveLength(2)
    wrapper.unmount()
  })

  it('节点点击 → selectedNode 更新 + 邻居计算', async () => {
    _mockNodes = [
      { label: 'A', type: 'concept', weight: 0.5, source_doc_ids: [] },
      { label: 'B', type: 'paper', weight: 0.7, source_doc_ids: [] },
      { label: 'C', type: 'method', weight: 0.6, source_doc_ids: [] },
    ]
    _mockEdges = [
      { source: 'A', target: 'B', relation: 'cites', weight: 0.5 },
      { source: 'A', target: 'C', relation: 'topic', weight: 0.4 },
    ]
    const wrapper = mount(KnowledgeGraph)
    await flushPromises()
    await nextTick()

    // 模拟子组件 emit node-click
    const canvas = wrapper.findComponent(CytoscapeCanvas)
    await canvas.vm.$emit('node-click', 'A', 'A', 'concept')
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.selectedNode).not.toBeNull()
    expect(vm.selectedNode.label).toBe('A')
    expect(vm.selectedNeighbors).toHaveLength(2)
    expect(vm.selectedNeighbors.map((n: any) => n.label).sort()).toEqual(['B', 'C'])

    wrapper.unmount()
  })

  it('layout.json 缓存命中 → cachedLayout 设置', async () => {
    _mockNodes = [
      { label: 'A', type: 'concept', weight: 0.5, source_doc_ids: [] },
    ]
    _mockEdges = []
    _mockLayoutText = JSON.stringify({
      positions: { A: { x: 1, y: 2 } },
      generated_at: 1700000000000,
    })
    const wrapper = mount(KnowledgeGraph)
    await flushPromises()
    await nextTick()
    expect((wrapper.vm as any).cachedLayout).not.toBeNull()
    expect((wrapper.vm as any).cachedLayout.positions.A).toEqual({ x: 1, y: 2 })
    wrapper.unmount()
  })
})
