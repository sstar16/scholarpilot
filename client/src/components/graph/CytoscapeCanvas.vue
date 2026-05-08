<template>
  <div ref="containerRef" class="cy-container" data-testid="cytoscape-canvas"></div>
</template>

<script setup lang="ts">
/**
 * CytoscapeCanvas — 封装 cytoscape 实例 + Vue 3 reactive 陷阱处理。
 *
 * Vue 3 + cytoscape 集成 gotcha (issue #2844)：
 *   - 不能把 cytoscape Core 放到 ref / reactive。Vue 的 Proxy 会拦截 cytoscape 内部
 *     对 nodes/edges 集合的可枚举属性访问，导致渲染错位 / 性能退化 / 偶发崩溃。
 *   - 解决：用 module-scope 变量 / `markRaw` 包装；本组件用 module-scope `let cy: Core | null`，
 *     不放进 ref 也不放 reactive。父组件想拿 cy 通过 `defineExpose` 出去的方法操作。
 *
 * 增量更新 API（defineExpose）：
 *   - addElements / removeElements：父监听 EventBus `graph_updated` 后调，避免全量重建
 *   - saveLayout：抽 cy.nodes() 当前坐标 → CachedLayout 给父写盘
 *   - applyLayout：换 layout (fcose / circle / grid / concentric)
 *   - rerunLayout：触发 fcose 一次完整重排
 *   - fit / center：viewport 操作
 *
 * 不监听 props.nodes/edges 的全量替换（父用增量 API），但 onMounted 时一次性建图。
 */
import { onMounted, onUnmounted, ref, markRaw, watch } from 'vue'
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import fcose from 'cytoscape-fcose'

import {
  DEFAULT_NODE_STYLE,
  buildElements,
  buildLayoutOptions,
  isCachedLayoutUsable,
  snapshotPositions,
  type CachedLayout,
  type LayoutName,
} from '@/composables/useGraphRenderer'
import type { GraphEdge, GraphNode } from '@/data/graph/graphRepo'

// fcose 注册一次（cytoscape.use 幂等：重复 use 同一 ext 无害，但避免热重载残留）
let _fcoseRegistered = false
if (!_fcoseRegistered) {
  try {
    cytoscape.use(fcose as unknown as cytoscape.Ext)
    _fcoseRegistered = true
  } catch (e) {
    // 重复注册抛是无害的，cytoscape 不允许同一 ext 双注册
    _fcoseRegistered = true
  }
}

const props = defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
  layout?: CachedLayout | null
  /** 初始 layout 名称（无缓存时使用），默认 fcose。 */
  initialLayout?: LayoutName
}>()

const emit = defineEmits<{
  'node-click': [nodeId: string, rawLabel: string, type: string]
  'edge-click': [edgeId: string]
  'background-click': []
  'layout-saved': [layout: CachedLayout]
  'ready': [cy: Core]
}>()

const containerRef = ref<HTMLDivElement | null>(null)

// 关键：不要 ref / reactive 包装 cy（Vue 3 Proxy 拦截 cytoscape 内部 collection 访问）
let cy: Core | null = null

// ─────────────── lifecycle ───────────────

onMounted(() => {
  if (!containerRef.value) return

  const { elements } = buildElements(props.nodes, props.edges, props.layout)
  const cacheUsable = isCachedLayoutUsable(props.nodes, props.layout)
  const layoutOpts = buildLayoutOptions(
    cacheUsable ? 'preset' : (props.initialLayout ?? 'fcose'),
    cacheUsable,
  )

  // markRaw 兜底：防止任何 ref/reactive 把它给 proxy 化（双保险，主要保护 future refactor）
  cy = markRaw(
    cytoscape({
      container: containerRef.value,
      elements,
      style: DEFAULT_NODE_STYLE,
      layout: layoutOpts,
      // 视觉 / 交互配置
      wheelSensitivity: 0.2,
      minZoom: 0.2,
      maxZoom: 3,
      boxSelectionEnabled: false,
      autounselectify: false,
    }),
  )

  cy.on('tap', 'node', (evt) => {
    const n = evt.target
    emit('node-click', n.id(), n.data('rawLabel') ?? n.id(), n.data('type') ?? 'unknown')
  })
  cy.on('tap', 'edge', (evt) => {
    emit('edge-click', evt.target.id())
  })
  cy.on('tap', (evt) => {
    if (evt.target === cy) emit('background-click')
  })

  emit('ready', cy)
})

// nodes/edges 完全替换（filter 切换、loadGraph 完成）→ 全量重建
// 增量更新走 defineExpose 的 addElements/removeElements，不走 watch
watch(
  () => [props.nodes.length, props.edges.length],
  ([newNodeCount, newEdgeCount], [oldNodeCount, oldEdgeCount]) => {
    if (!cy) return
    // 数量没变就不动（性能：不每次 prop 变化重建）
    if (newNodeCount === oldNodeCount && newEdgeCount === oldEdgeCount) return
    rebuildAll()
  },
)

onUnmounted(() => {
  if (cy) {
    try {
      cy.destroy()
    } catch {
      /* cytoscape destroy 偶尔抛 — 忽略 */
    }
    cy = null
  }
})

// ─────────────── 内部辅助 ───────────────

function rebuildAll() {
  if (!cy) return
  const cacheUsable = isCachedLayoutUsable(props.nodes, props.layout)
  const { elements } = buildElements(props.nodes, props.edges, props.layout)
  cy.batch(() => {
    cy!.elements().remove()
    cy!.add(elements)
  })
  cy.layout(buildLayoutOptions(
    cacheUsable ? 'preset' : (props.initialLayout ?? 'fcose'),
    cacheUsable,
  )).run()
}

// ─────────────── defineExpose（增量更新 / layout 控制） ───────────────

defineExpose({
  /** 增量加：父监听 graph_updated 事件后调。 */
  addElements: (els: ElementDefinition[]) => {
    if (!cy) return
    cy.add(els)
  },
  /** 增量删：按 id 列表移除。 */
  removeElements: (ids: string[]) => {
    if (!cy) return
    cy.batch(() => {
      for (const id of ids) {
        const el = cy!.getElementById(id)
        if (el && el.length > 0) el.remove()
      }
    })
  },
  /** 抽快照当前 nodes 坐标（写盘前调）。 */
  saveLayout: (): CachedLayout | null => {
    if (!cy) return null
    const nodes = cy.nodes() as unknown as Iterable<{ id(): string; position(): { x: number; y: number } }>
    const snap = snapshotPositions(nodes)
    emit('layout-saved', snap)
    return snap
  },
  /** 切 layout 算法。 */
  applyLayout: (name: LayoutName) => {
    if (!cy) return
    cy.layout(buildLayoutOptions(name, false)).run()
  },
  /** 重排（fcose）。 */
  rerunLayout: () => {
    if (!cy) return
    cy.layout(buildLayoutOptions('fcose', false)).run()
  },
  fit: () => cy?.fit(undefined, 30),
  center: () => cy?.center(),
  /** 高亮一个 node 及其邻居（搜索用）。 */
  focusNode: (id: string) => {
    if (!cy) return
    const n = cy.getElementById(id)
    if (!n || n.length === 0) return
    cy.elements().addClass('dimmed')
    n.removeClass('dimmed')
    n.neighborhood().removeClass('dimmed')
    cy.animate({ center: { eles: n }, zoom: 1.5 }, { duration: 300 })
  },
  /** 清除高亮。 */
  clearFocus: () => {
    if (!cy) return
    cy.elements().removeClass('dimmed')
  },
  /** 测试用 — 暴露 cy（生产代码不要用，只给 Vue DevTools / 单测）。 */
  _getCyForTesting: () => cy,
})
</script>

<style scoped>
.cy-container {
  width: 100%;
  height: 100%;
  min-height: 600px;
  background: #fafafa;
  background-image:
    linear-gradient(rgba(120, 100, 80, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120, 100, 80, 0.03) 1px, transparent 1px);
  background-size: 32px 32px;
  border-radius: 8px;
}
</style>
