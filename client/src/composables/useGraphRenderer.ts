/**
 * useGraphRenderer — cytoscape 元素转换 + 样式 + layout 配置复用 composable。
 *
 * 把 GraphRepo 的 nodes/edges JSON 翻译成 cytoscape `ElementDefinition[]`，并提供：
 *  - NODE_STYLE / EDGE_STYLE：按 entity type / relation 着色
 *  - LAYOUT_PRESETS：fcose / circle / grid / concentric 复用配置
 *  - applyCachedPositions：layout.json 缓存的坐标 → 直接 preset
 *
 * 不持有 cytoscape 实例引用（实例由 CytoscapeCanvas 管理 + markRaw），
 * 这里全是纯函数，单测友好。
 */
import type { ElementDefinition } from 'cytoscape'

import type { GraphEdge, GraphNode } from '@/data/graph/graphRepo'

// ──────────────────────── 节点 / 边视觉常量 ────────────────────────

/** Entity type → fill color（V1 6 类对齐 graphAgent.ENTITY_TYPES）。 */
export const ENTITY_TYPE_COLORS: Record<string, string> = {
  paper: '#4E79A7', // 蓝
  concept: '#59A14F', // 绿
  author: '#F28E2B', // 橙
  organization: '#E15759', // 红
  method: '#76B7B2', // 青
  technology: '#B07AA1', // 紫
  // legacy 兜底（旧版可能有 document / topic / journal）
  document: '#4E79A7',
  topic: '#E15759',
  journal: '#76B7B2',
}

/** 节点描边色（深一档，用于选中/默认 border）。 */
export const ENTITY_TYPE_BORDERS: Record<string, string> = {
  paper: '#2e5a85',
  concept: '#3d7a34',
  author: '#c06b10',
  organization: '#a73e3f',
  method: '#4a8e8b',
  technology: '#7a4f70',
  document: '#2e5a85',
  topic: '#a73e3f',
  journal: '#4a8e8b',
}

/** Relation type → edge color（V1 6 类对齐 graphAgent.RELATION_TYPES）。 */
export const RELATION_TYPE_COLORS: Record<string, string> = {
  cites: '#2563eb', // 蓝（引用）
  extends: '#f97316', // 橙（延伸）
  contradicts: '#dc2626', // 红（矛盾）
  coauthor: '#cbd5e1', // 灰（共同作者）
  topic: '#a855f7', // 紫（主题归属）
  method_of: '#0d9488', // 青（方法属于）
}

/** 默认 cytoscape style（基于 type 着色 + 度量映射 size）。 */
export const DEFAULT_NODE_STYLE: cytoscape.StylesheetStyle[] = [
  {
    selector: 'node',
    style: {
      'background-color': 'data(color)',
      'border-color': 'data(border)',
      'border-width': 1.5,
      'label': 'data(label)',
      'color': '#1e293b',
      'text-outline-color': '#ffffff',
      'text-outline-width': 2,
      'font-size': 11,
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 4,
      'width': 'data(size)',
      'height': 'data(size)',
    },
  },
  {
    selector: 'node:selected',
    style: {
      'border-width': 3,
      'border-color': '#1e293b',
    },
  },
  {
    selector: 'edge',
    style: {
      'width': 'data(width)',
      'line-color': 'data(color)',
      'target-arrow-color': 'data(color)',
      'target-arrow-shape': 'data(arrow)' as 'triangle',
      'curve-style': 'bezier',
      'opacity': 0.7,
    },
  },
  {
    selector: 'edge:selected',
    style: {
      'opacity': 1,
      'width': 4,
    },
  },
  {
    selector: '.dimmed',
    style: {
      'opacity': 0.15,
    },
  },
]

// ──────────────────────── Layout 预设 ────────────────────────

export type LayoutName = 'fcose' | 'circle' | 'grid' | 'concentric' | 'preset'

/** Layout 默认参数（fcose 走 quality=default + 不动画，避免大图卡）。 */
export function buildLayoutOptions(name: LayoutName, hasCachedPositions = false): cytoscape.LayoutOptions {
  if (hasCachedPositions || name === 'preset') {
    return { name: 'preset', fit: true, padding: 30 }
  }
  if (name === 'fcose') {
    return {
      name: 'fcose',
      // @ts-expect-error fcose extension options not in @types/cytoscape
      quality: 'default',
      randomize: false,
      animate: false,
      fit: true,
      padding: 30,
      nodeRepulsion: 4500,
      idealEdgeLength: 70,
      edgeElasticity: 0.45,
      gravity: 0.25,
      gravityRangeCompound: 1.5,
      numIter: 2500,
    }
  }
  if (name === 'circle') {
    return { name: 'circle', fit: true, padding: 30 }
  }
  if (name === 'grid') {
    return { name: 'grid', fit: true, padding: 30 }
  }
  if (name === 'concentric') {
    return {
      name: 'concentric',
      fit: true,
      padding: 30,
      minNodeSpacing: 30,
    }
  }
  // fallback
  return { name: 'fcose', fit: true, padding: 30 } as cytoscape.LayoutOptions
}

// ──────────────────────── 缓存的坐标格式 ────────────────────────

/** layout.json 持久化结构。 */
export interface CachedLayout {
  positions: Record<string, { x: number; y: number }>
  generated_at: number
}

// ──────────────────────── nodes/edges → cytoscape elements ────────────────────────

/** 节点 size 映射：基础 14 + 度数 / maxDegree * 26（最大 ≈ 40）。 */
function _sizeForDegree(degree: number, maxDegree: number): number {
  if (maxDegree <= 0) return 18
  return 14 + Math.round((degree / maxDegree) * 26)
}

/** label 截断 — 太长会盖到邻居，统一截 22 字符。 */
function _truncateLabel(label: string): string {
  return label.length > 22 ? `${label.slice(0, 20)}…` : label
}

/**
 * 把 GraphRepo 输出的 nodes/edges 转成 cytoscape ElementDefinition[]。
 *
 * - 节点 id = label（同 mergeIntoLists 主键的 label 部分；同 label 不同 type 是两个节点 → id 用 `<label>__<type>` 避碰）
 * - 边的 source/target 与 mergeFragment 一致：纯 label 字符串。但如果存在 type 后缀，要去找对应；
 *   实际 mergeFragment 写的是纯 label，所以 cytoscape 这边 id 也用纯 label，碰撞不在数据层面解决。
 * - 跳过端点不存在的边（防御性，避免 cytoscape 报错）。
 *
 * 通过 cachedLayout 直接给 position（cytoscape 配 preset layout 用）。
 */
export function buildElements(
  nodes: GraphNode[],
  edges: GraphEdge[],
  cachedLayout?: CachedLayout | null,
): { elements: ElementDefinition[]; degreeMap: Record<string, number>; missingPositions: number } {
  // degree map
  const degreeMap: Record<string, number> = {}
  for (const n of nodes) degreeMap[n.label] = 0
  for (const e of edges) {
    if (degreeMap[e.source] !== undefined) degreeMap[e.source]++
    if (degreeMap[e.target] !== undefined) degreeMap[e.target]++
  }
  const maxDegree = Math.max(1, ...Object.values(degreeMap))

  let missingPositions = 0
  const positions = cachedLayout?.positions ?? {}

  const nodeElements: ElementDefinition[] = nodes.map((n) => {
    const degree = degreeMap[n.label] ?? 0
    const color = ENTITY_TYPE_COLORS[n.type] ?? '#64748b'
    const border = ENTITY_TYPE_BORDERS[n.type] ?? '#444'
    const cached = positions[n.label]
    if (cachedLayout && !cached) missingPositions++
    return {
      group: 'nodes' as const,
      data: {
        id: n.label,
        label: _truncateLabel(n.label),
        rawLabel: n.label,
        type: n.type,
        weight: n.weight,
        size: _sizeForDegree(degree, maxDegree),
        color,
        border,
        sourceDocCount: n.source_doc_ids?.length ?? 0,
      },
      ...(cached ? { position: { x: cached.x, y: cached.y } } : {}),
    }
  })

  // valid edges only
  const nodeIdSet = new Set(nodes.map((n) => n.label))
  const edgeElements: ElementDefinition[] = []
  let edgeCounter = 0
  for (const e of edges) {
    if (!nodeIdSet.has(e.source) || !nodeIdSet.has(e.target)) continue
    edgeCounter++
    const color = RELATION_TYPE_COLORS[e.relation] ?? '#94a3b8'
    const arrow = e.relation === 'cites' || e.relation === 'extends' || e.relation === 'contradicts' ? 'triangle' : 'none'
    edgeElements.push({
      group: 'edges' as const,
      data: {
        id: `e:${e.source}|${e.target}|${e.relation}|${edgeCounter}`,
        source: e.source,
        target: e.target,
        relation: e.relation,
        weight: e.weight,
        color,
        width: 1.2 + e.weight * 2.5,
        arrow,
      },
    })
  }

  return {
    elements: [...nodeElements, ...edgeElements],
    degreeMap,
    missingPositions,
  }
}

/**
 * 检查缓存的 layout 是否覆盖了当前 nodes 集合的大部分（≥ 70%）。
 * 不够 → 丢弃缓存重跑 fcose；够 → 沿用 preset。
 */
export function isCachedLayoutUsable(
  nodes: GraphNode[],
  cachedLayout: CachedLayout | null | undefined,
  minCoverage = 0.7,
): boolean {
  if (!cachedLayout || !cachedLayout.positions) return false
  if (nodes.length === 0) return false
  let covered = 0
  for (const n of nodes) {
    if (cachedLayout.positions[n.label]) covered++
  }
  return covered / nodes.length >= minCoverage
}

/**
 * 给定 cytoscape 实例的 nodes() iterable（duck-typed），把每个 node 的 (id, position) 抽取成
 * CachedLayout 形式（写盘前调用）。
 *
 * 抽出来纯函数化，方便单测；CytoscapeCanvas.saveLayout 直接喂 cy.nodes() 进来。
 */
export interface CyPositionedNode {
  id(): string
  position(): { x: number; y: number }
}

export function snapshotPositions(iter: Iterable<CyPositionedNode>): CachedLayout {
  const positions: Record<string, { x: number; y: number }> = {}
  for (const n of iter) {
    const p = n.position()
    positions[n.id()] = { x: p.x, y: p.y }
  }
  return {
    positions,
    generated_at: Date.now(),
  }
}
