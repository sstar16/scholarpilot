<template>
  <el-dialog
    v-model="visible"
    :title="`知识图谱 — ${currentLabel}`"
    width="85%"
    top="5vh"
    destroy-on-close
  >
    <div class="kg-container">
      <!-- Bucket switcher -->
      <div class="kg-switcher">
        <el-radio-group v-model="bucketModel" size="small">
          <el-radio-button
            v-for="opt in BUCKET_OPTIONS"
            :key="opt.key"
            :value="opt.key"
          >
            <span class="dot" :style="{ background: opt.color }"></span>
            {{ opt.label }}
          </el-radio-button>
        </el-radio-group>
      </div>

      <!-- Stats bar -->
      <div class="kg-stats" v-if="stats">
        <el-tag size="small">{{ stats.node_count }} 节点</el-tag>
        <el-tag size="small" type="info">{{ stats.edge_count }} 关系</el-tag>
        <el-tag v-for="(count, type) in stats.nodes_by_type" :key="type" size="small" type="warning">
          {{ type }}: {{ count }}
        </el-tag>
      </div>

      <!-- Edge legend -->
      <div class="kg-legend">
        <span class="lg-item"><i class="lg-bar lg-concept"></i>概念关系（AI）</span>
        <span class="lg-item"><i class="lg-bar lg-doc"></i>文献关系（AI）</span>
        <span class="lg-item"><i class="lg-bar lg-cite"></i>引用（Crossref）</span>
        <span class="lg-item"><i class="lg-bar lg-discuss"></i>讨论 / 作者</span>
      </div>

      <!-- vis-network container (overlay + clean network div separated to avoid DOM conflicts) -->
      <div class="kg-canvas-wrap">
        <div v-if="loading || rebuilding" class="kg-loading-card">
          <div class="kg-loading-card__eyebrow">
            — {{ rebuilding ? 'AI · DEEP REBUILD' : 'AI · LOADING GRAPH' }} —
          </div>
          <div class="kg-loading-card__title">
            {{ rebuilding ? '深度重建知识图谱' : '正在分析知识图谱' }}
          </div>
          <div class="kg-loading-card__stage">
            <el-icon class="kg-loading-card__spin is-loading" :size="18"><Loading /></el-icon>
            <span class="kg-loading-card__stage-text">{{ currentStageText }}</span>
          </div>
          <div class="kg-loading-card__bar">
            <div class="kg-loading-card__bar-fill" />
          </div>
          <div class="kg-loading-card__hint">
            {{
              rebuilding
                ? 'LLM 正在抽取实体、推理语义关联并重写图谱索引。通常 30 秒至 3 分钟（视文献量和 LLM 速度）。'
                : 'AI 在后台聚合节点、社区、hubs 与缺口分析。文献越多耗时越长，一般 3–15 秒。'
            }}
          </div>
        </div>
        <div v-if="!loading && nodes.length === 0" class="kg-empty">
          <template v-if="(stats?.node_count || 0) === 0">
            <p>知识图谱尚未构建</p>
            <p class="sub">点击下方按钮从现有文献自动生成</p>
            <el-button
              type="primary"
              :loading="rebuilding"
              @click="triggerRebuild"
              style="margin-top: 12px"
            >
              <el-icon><Refresh /></el-icon>
              立即构建
            </el-button>
          </template>
          <template v-else>
            <p>当前桶（{{ currentLabel }}）暂无图谱数据</p>
            <p class="sub">请切换到「全部」或其他有数据的桶</p>
          </template>
        </div>
        <div v-show="!loading && nodes.length > 0" ref="networkContainer" class="kg-network"></div>
      </div>

      <!-- Node info panel -->
      <div v-if="selectedNode" class="kg-info-panel">
        <div class="kg-info-header">
          <span class="kg-info-label">{{ selectedNode.label }}</span>
          <el-tag size="small" :color="TYPE_COLORS[selectedNode.node_type] || '#64748b'" effect="dark">
            {{ selectedNode.node_type }}
          </el-tag>
        </div>
        <div class="kg-info-body">
          <span v-if="selectedNode.community != null" class="kg-info-item">
            社区: {{ selectedNode.community }}
          </span>
          <span class="kg-info-item">度: {{ selectedNode.degree }}</span>
          <span v-if="selectedNode.neighbors?.length" class="kg-info-item">
            邻居: {{ selectedNode.neighbors.slice(0, 5).join(', ') }}{{ selectedNode.neighbors.length > 5 ? '…' : '' }}
          </span>
        </div>
        <!-- 讨论该实体的文献列表（点击非 document 节点自动加载）-->
        <div v-if="!String(selectedNode.node_id || '').startsWith('doc:')" class="kg-entity-docs">
          <div class="kg-entity-docs-head">
            <strong>讨论该实体的文献</strong>
            <el-tag v-if="!loadingEntityDocs" size="small" type="info" effect="plain">
              {{ entityDocs.length }} 篇
            </el-tag>
          </div>
          <div v-if="loadingEntityDocs" class="kg-entity-docs-loading">
            <el-icon class="is-loading"><Loading /></el-icon> 加载中...
          </div>
          <div v-else-if="!entityDocs.length" class="kg-entity-docs-empty">
            KG 里没有文献关联到这个实体
          </div>
          <ul v-else class="kg-entity-docs-list">
            <li v-for="d in entityDocs" :key="d.id" class="kg-entity-doc-item">
              <div class="ed-title">
                <a v-if="d.url" :href="d.url" target="_blank" rel="noopener">{{ d.title }}</a>
                <span v-else>{{ d.title }}</span>
                <el-tag size="small" effect="plain" type="success" class="ed-edge">
                  {{ d.edge_type }}
                </el-tag>
              </div>
              <div v-if="d.one_line_summary" class="ed-oneline">
                {{ d.one_line_summary }}
              </div>
              <div class="ed-meta">
                <span v-if="d.source">{{ d.source }}</span>
                <span v-if="d.publication_date">· {{ d.publication_date.slice(0, 7) }}</span>
                <span v-if="d.journal">· {{ d.journal }}</span>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Footer with hubs -->
    <template #footer>
      <div class="kg-footer">
        <div v-if="hubs.length" class="kg-section">
          <strong>Hub 节点:</strong>
          <el-tag v-for="h in hubs.slice(0, 5)" :key="h.node_id" size="small" style="margin: 2px">
            {{ h.label }} ({{ h.degree }})
          </el-tag>
        </div>
        <div v-if="gaps.length" class="kg-section">
          <strong>研究空白:</strong>
          <span v-for="g in gaps.slice(0, 3)" :key="g.concept" class="gap-item">
            {{ g.suggestion }}
          </span>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onUnmounted, computed } from 'vue'
import { Refresh, Loading } from '@element-plus/icons-vue'
import { Network, DataSet } from 'vis-network/standalone'
import api from '../../api/client'

const props = defineProps<{
  projectId: string
}>()

const visible = defineModel<boolean>('visible', { default: false })
const bucketModel = defineModel<string>('bucket', { default: 'very_relevant' })

const BUCKET_OPTIONS = [
  { key: 'all', label: '全部', color: '#7c3aed' },
  { key: 'very_relevant', label: '核心', color: '#0d9488' },
  { key: 'relevant', label: '相关', color: '#2563eb' },
  { key: 'uncertain', label: '待定', color: '#64748b' },
  { key: 'irrelevant', label: '排除', color: '#dc2626' },
]
const BUCKET_LABEL_MAP: Record<string, string> = Object.fromEntries(
  BUCKET_OPTIONS.map((o) => [o.key, o.label])
)
const currentLabel = computed(() => BUCKET_LABEL_MAP[bucketModel.value] || bucketModel.value)

// Color map by node type
const TYPE_COLORS: Record<string, string> = {
  document: '#4E79A7',
  author: '#F28E2B',
  concept: '#59A14F',
  topic: '#E15759',
  journal: '#76B7B2',
}

// Darker border shades for each type
const TYPE_BORDER_COLORS: Record<string, string> = {
  document: '#2e5a85',
  author: '#c06b10',
  concept: '#3d7a34',
  topic: '#b53537',
  journal: '#4a8e8b',
}

const loading = ref(false)
const rebuilding = ref(false)

// ── Loading 阶段轮播（期刊风 loading 卡片使用） ──
const LOAD_STAGES = [
  '正在读取图谱结构…',
  'AI 聚合实体与社区分块…',
  '计算节点重要性（hubs）…',
  '识别语义关联缺口…',
  '布局力学优化中…',
]
const REBUILD_STAGES = [
  'LLM 扫描文献并抽取实体…',
  'AI 推理实体间语义关联…',
  '构建社区检测与聚类…',
  '写入图谱索引…',
  '收尾 · 统计度中心性…',
]
const loadStageIdx = ref(0)
let stageTimer: ReturnType<typeof setInterval> | null = null
const currentStageText = computed(() => {
  const pool = rebuilding.value ? REBUILD_STAGES : LOAD_STAGES
  return pool[loadStageIdx.value % pool.length]
})
watch([loading, rebuilding], ([l, r]) => {
  if (l || r) {
    loadStageIdx.value = 0
    if (stageTimer) clearInterval(stageTimer)
    // rebuild 更慢 → 文字切换更慢
    stageTimer = setInterval(() => {
      loadStageIdx.value += 1
    }, r ? 4500 : 2200)
  } else if (stageTimer) {
    clearInterval(stageTimer)
    stageTimer = null
  }
}, { immediate: true })
onUnmounted(() => {
  if (stageTimer) clearInterval(stageTimer)
})

const nodes = ref<any[]>([])
const edges = ref<any[]>([])
const stats = ref<any>(null)
const hubs = ref<any[]>([])
const gaps = ref<any[]>([])
const selectedNode = ref<any>(null)

const networkContainer = ref<HTMLElement>()
let network: Network | null = null

// Reload on visibility or bucket change; wait 300ms for dialog animation
watch([visible, bucketModel], async ([v]) => {
  if (!v) {
    destroyNetwork()
    return
  }
  await loadGraph()
  setTimeout(() => initNetwork(), 300)
})

onUnmounted(() => destroyNetwork())

function destroyNetwork() {
  if (network) {
    network.destroy()
    network = null
  }
}

async function loadGraph() {
  loading.value = true
  nodes.value = []
  edges.value = []
  selectedNode.value = null
  try {
    const bucketParam = bucketModel.value === 'all' ? '' : `?bucket=${bucketModel.value}`
    const graphUrl = `/api/projects/${props.projectId}/graph${bucketParam}`

    const [graphRes, hubsRes, gapsRes] = await Promise.all([
      api.get(graphUrl),
      api.get(`/api/projects/${props.projectId}/graph/hubs?top_k=8`),
      api.get(`/api/projects/${props.projectId}/graph/gaps`),
    ])
    nodes.value = graphRes.data.nodes || []
    edges.value = graphRes.data.edges || []
    stats.value = graphRes.data.stats
    hubs.value = hubsRes.data.hubs || []
    gaps.value = gapsRes.data.gaps || []
  } catch (e) {
    console.error('Failed to load graph', e)
  } finally {
    loading.value = false
  }
}

async function triggerRebuild() {
  rebuilding.value = true
  try {
    await api.post(`/api/projects/${props.projectId}/graph/rebuild`)
    const start = Date.now()
    while (Date.now() - start < 30000) {
      await new Promise((r) => setTimeout(r, 2000))
      await loadGraph()
      if (nodes.value.length > 0) break
    }
    await nextTick()
    initNetwork()
  } catch (e) {
    console.error('Rebuild failed', e)
  } finally {
    rebuilding.value = false
  }
}

// 概念 → 概念 语义关系（LLM 推断）
const CONCEPT_RELATION_TYPES = new Set([
  'sub_concept', 'parent_concept', 'same_as',
  'causes', 'precedes', 'contrasts', 'related_method',
])
// 文献 → 文献 语义关系（LLM 推断）
const DOC_RELATION_TYPES = new Set([
  'extends', 'refutes', 'parallel', 'surveys', 'replicates', 'applies',
])

function edgeStyleFor(e: any): {
  color: string
  width: number
  dashes: boolean | number[]
  hasArrow: boolean
} {
  const et = e.edge_type || ''
  if (et === 'cites') {
    return { color: '#2563eb', width: 2.4, dashes: false, hasArrow: true }
  }
  if (CONCEPT_RELATION_TYPES.has(et)) {
    return { color: '#a855f7', width: 2, dashes: [4, 4], hasArrow: true }
  }
  if (DOC_RELATION_TYPES.has(et)) {
    // LLM 推断的文献关系：橙色实线带箭头（比 cites 柔和，区别明显）
    return { color: '#f97316', width: 2.2, dashes: [6, 3], hasArrow: true }
  }
  if (et === 'discusses') {
    return { color: '#94a3b8', width: 1.5, dashes: false, hasArrow: false }
  }
  if (et === 'authored_by' || et === 'co_authored') {
    return { color: '#cbd5e1', width: 1, dashes: false, hasArrow: false }
  }
  if (et === 'published_in') {
    return { color: '#fbbf24', width: 1, dashes: false, hasArrow: false }
  }
  return { color: '#94a3b8', width: 1, dashes: true, hasArrow: false }
}

function edgeTooltipFor(e: any): string {
  const et = e.edge_type || 'unknown'
  let head = et
  if (e.edge_type === 'cites') {
    head = 'cites · Crossref'
  } else if (e.llm_inferred) {
    const pct = typeof e.llm_confidence === 'number'
      ? ` (${Math.round(e.llm_confidence * 100)}%)`
      : ''
    const tag = DOC_RELATION_TYPES.has(et) ? '文献关系' : '概念关系'
    head = `${et} · AI ${tag}${pct}`
  } else if (e.confidence) {
    head = `${et} · ${e.confidence}`
  }
  const reason = typeof e.reason === 'string' && e.reason
    ? `\n${e.reason}`
    : ''
  return `${head}${reason}`
}

function buildVisData() {
  // Compute degree map
  const degreeMap: Record<string, number> = {}
  for (const n of nodes.value) degreeMap[n.id] = 0
  for (const e of edges.value) {
    if (degreeMap[e.source] !== undefined) degreeMap[e.source]++
    if (degreeMap[e.target] !== undefined) degreeMap[e.target]++
  }
  const maxDegree = Math.max(1, ...Object.values(degreeMap))

  // Build adjacency for neighbor lookup
  const neighborMap: Record<string, string[]> = {}
  for (const n of nodes.value) neighborMap[n.id] = []
  for (const e of edges.value) {
    neighborMap[e.source]?.push(e.target)
    neighborMap[e.target]?.push(e.source)
  }
  // Store degree/neighbor on node objects for info panel
  const nodeIdToRaw: Record<string, any> = {}
  for (const n of nodes.value) {
    n._degree = degreeMap[n.id] || 0
    n._neighbors = neighborMap[n.id] || []
    nodeIdToRaw[n.id] = n
  }

  const labelThreshold = maxDegree * 0.15

  const visNodes = nodes.value.map((n) => {
    const degree = degreeMap[n.id] || 0
    const size = 10 + 30 * (degree / maxDegree)
    const color = TYPE_COLORS[n.node_type] || '#64748b'
    const border = TYPE_BORDER_COLORS[n.node_type] || '#444'
    const showLabel = degree >= labelThreshold
    return {
      id: n.id,
      label: showLabel ? (n.label.length > 20 ? n.label.slice(0, 18) + '…' : n.label) : '',
      title: `${n.label}\n类型: ${n.node_type}${n.properties?.summary ? '\n' + n.properties.summary : ''}`,
      size,
      color: {
        background: color,
        border,
        highlight: { background: color, border: '#fff' },
        hover: { background: color, border: '#fff' },
      },
      font: { size: 12, color: '#333' },
      borderWidth: 1.5,
      shape: 'dot',
    }
  })

  // Only keep edges where both endpoints exist in the node set
  const nodeIdSet = new Set(nodes.value.map((n) => n.id))
  const validEdges = edges.value.filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
  console.log(`[KG] edges: ${edges.value.length} total, ${validEdges.length} with valid endpoints`)

  // Deduplicate edges (keep one per unique from-to pair)
  const edgeSet = new Set<string>()
  const dedupedEdges: typeof validEdges = []
  for (const e of validEdges) {
    const key = `${e.source}|${e.target}`
    if (!edgeSet.has(key)) {
      edgeSet.add(key)
      dedupedEdges.push(e)
    }
  }
  console.log(`[KG] deduped: ${validEdges.length} → ${dedupedEdges.length} unique edges`)
  console.log('[KG] node ids:', visNodes.slice(0, 5).map((n: any) => n.id))
  console.log('[KG] edge from→to:', dedupedEdges.slice(0, 5).map(e => `${e.source} → ${e.target}`))

  const visEdges = dedupedEdges.map((e) => {
    const style = edgeStyleFor(e)
    return {
      from: e.source,
      to: e.target,
      width: style.width,
      dashes: style.dashes,
      color: { color: style.color, inherit: false },
      arrows: style.hasArrow
        ? { to: { enabled: true, scaleFactor: 0.6 } }
        : undefined,
      title: edgeTooltipFor(e),
    }
  })

  return { visNodes, visEdges, nodeIdToRaw }
}

function initNetwork() {
  console.log('[KG] initNetwork called, container:', !!networkContainer.value, 'nodes:', nodes.value.length, 'edges:', edges.value.length)
  if (!networkContainer.value || nodes.value.length === 0) return

  // clientWidth guard — retry if container not yet rendered
  const cw = networkContainer.value.clientWidth
  const ch = networkContainer.value.clientHeight
  console.log('[KG] container size:', cw, 'x', ch)
  if (cw < 50) {
    requestAnimationFrame(() => initNetwork())
    return
  }

  destroyNetwork()

  const { visNodes, visEdges, nodeIdToRaw } = buildVisData()
  console.log('[KG] visNodes:', visNodes.length, 'visEdges:', visEdges.length)

  // 2026-04-18 KG 视觉美化:
  //  - ≤ 10 节点：圆形初始布局 + 轻物理（避免挤成一坨）
  //  - 10-30 节点：标准 forceAtlas2 + 较强向心力
  //  - > 30 节点：强斥力大范围铺开
  //  - 标签统一白描边提高对比度
  const n = visNodes.length
  const isSmall = n <= 10
  const isMid = n > 10 && n <= 30

  // 小节点集：给初始圆形坐标（让物理从好起点稳定）
  if (isSmall && n > 0) {
    const R = 130
    visNodes.forEach((node: any, i: number) => {
      const theta = (2 * Math.PI * i) / n
      node.x = R * Math.cos(theta)
      node.y = R * Math.sin(theta)
    })
  }

  const nodeDataSet = new DataSet(visNodes)
  const edgeDataSet = new DataSet(visEdges)

  const options = {
    physics: {
      enabled: true,
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: isSmall ? -25 : (isMid ? -60 : -100),
        centralGravity: isSmall ? 0.04 : (isMid ? 0.02 : 0.01),
        springLength: isSmall ? 90 : (isMid ? 130 : 180),
        springConstant: 0.08,
        damping: 0.45,
        avoidOverlap: 1.0, // 最强防叠
      },
      stabilization: { iterations: isSmall ? 120 : 220, fit: true },
    },
    nodes: {
      shape: 'dot',
      borderWidth: 1.5,
      // 白色描边让标签在任何颜色节点上都清晰
      font: { size: 12, color: '#1e293b', strokeWidth: 3, strokeColor: '#ffffff' },
    },
    edges: {
      color: { color: '#94a3b8', inherit: false },
      smooth: { type: 'continuous', roundness: 0.2 },
      selectionWidth: 3,
      arrows: { to: { enabled: true, scaleFactor: 0.5 } },
    },
    interaction: {
      hover: true,
      tooltipDelay: 100,
      hideEdgesOnDrag: true,
      navigationButtons: false,
      keyboard: false,
    },
  }

  network = new Network(
    networkContainer.value,
    { nodes: nodeDataSet, edges: edgeDataSet },
    options
  )

  // Disable physics after stabilization, fit graph to viewport
  network.once('stabilizationIterationsDone', () => {
    network?.setOptions({ physics: { enabled: false } })
    network?.fit({ animation: { duration: 300 } })
  })

  // Click node → show info panel
  network.on('click', (params) => {
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0]
      const raw = nodeIdToRaw[nodeId]
      if (raw) {
        selectedNode.value = {
          node_id: nodeId,
          label: raw.label,
          node_type: raw.node_type,
          community: raw.community,
          degree: raw._degree,
          neighbors: raw._neighbors.map((nid: string) => nodeIdToRaw[nid]?.label || nid),
        }
        // 若点的是非 document 节点，自动拉讨论它的文献
        if (!String(nodeId).startsWith('doc:')) {
          fetchEntityDocs(String(nodeId))
        } else {
          entityDocs.value = []
        }
      }
    } else {
      selectedNode.value = null
      entityDocs.value = []
    }
  })
}

const entityDocs = ref<Array<any>>([])
const loadingEntityDocs = ref(false)
async function fetchEntityDocs(entityId: string) {
  entityDocs.value = []
  loadingEntityDocs.value = true
  try {
    const res = await api.get(
      `/api/projects/${props.projectId}/graph/entity/${encodeURIComponent(entityId)}/documents`,
    )
    entityDocs.value = res.data?.documents || []
  } catch (e) {
    entityDocs.value = []
  } finally {
    loadingEntityDocs.value = false
  }
}
</script>

<style scoped>
.kg-container { position: relative; }
.kg-switcher {
  display: flex;
  justify-content: center;
  margin-bottom: var(--space-3);
}
.kg-switcher .dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 5px;
  vertical-align: 1px;
}
.kg-stats { display: flex; gap: var(--space-2); flex-wrap: wrap; margin-bottom: var(--space-3); }
.kg-canvas-wrap {
  position: relative;
  width: 100%;
  height: 500px;
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-md);
  overflow: hidden;
  /* 金色软光 + 纸纹底，与期刊风对齐 */
  background:
    radial-gradient(ellipse at 30% 30%, rgba(198, 172, 87, 0.08) 0%, transparent 55%),
    radial-gradient(ellipse at 70% 70%, rgba(13, 148, 136, 0.06) 0%, transparent 55%),
    var(--paper-warm);
  animation: kg-canvas-in 0.6s var(--ease-spring) both;
  box-shadow: inset 0 0 60px rgba(20, 20, 20, 0.04);
}
.kg-canvas-wrap::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(120, 100, 80, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120, 100, 80, 0.03) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
}
@keyframes kg-canvas-in {
  from { opacity: 0; transform: scale(0.98); }
  to { opacity: 1; transform: scale(1); }
}
.kg-network {
  width: 100%;
  height: 100%;
}
.kg-loading, .kg-empty {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: var(--ink-400);
}
.kg-loading { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); }

/* AI 加载期刊风卡片（loading + rebuilding 共用） */
.kg-loading-card {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: min(440px, 90%);
  padding: 26px 30px 22px;
  background: rgba(253, 252, 248, 0.97);
  border: 1px solid rgba(198, 172, 87, 0.35);
  border-radius: var(--radius-lg);
  backdrop-filter: blur(14px);
  box-shadow:
    0 20px 48px rgba(20, 20, 20, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.6);
  text-align: center;
  animation: richStamp 500ms var(--ease-spring) both;
  z-index: 5;
}
.kg-loading-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(198, 172, 87, 0.8), transparent);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  pointer-events: none;
}
.kg-loading-card__eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.35em;
  color: #c6ac57;
  margin-bottom: 10px;
}
.kg-loading-card__title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--ink-900);
  letter-spacing: -0.3px;
  margin-bottom: 18px;
}
.kg-loading-card__stage {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: rgba(198, 172, 87, 0.08);
  border: 1px solid rgba(198, 172, 87, 0.25);
  border-radius: 999px;
  color: var(--ink-700);
  font-size: 13px;
  margin-bottom: 16px;
}
.kg-loading-card__stage-text {
  min-height: 1em;
  transition: opacity 0.3s;
}
.kg-loading-card__spin { color: #c6ac57; }
.kg-loading-card__bar {
  height: 3px;
  background: rgba(198, 172, 87, 0.15);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 14px;
  position: relative;
}
.kg-loading-card__bar-fill {
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg,
    transparent,
    rgba(198, 172, 87, 0.8),
    transparent
  );
  background-size: 50% 100%;
  background-repeat: no-repeat;
  animation: kg-loading-shimmer 1.6s ease-in-out infinite;
}
@keyframes kg-loading-shimmer {
  0%   { background-position: -50% 0; }
  100% { background-position: 150% 0; }
}
.kg-loading-card__hint {
  font-size: 11.5px;
  color: var(--ink-500);
  font-style: italic;
  line-height: 1.6;
}
.kg-empty .sub { font-size: var(--type-sub-size); color: var(--ink-300); }
.kg-info-panel {
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-md);
  background: var(--paper);
  font-size: var(--type-sub-size);
  animation: kg-panel-in var(--duration-normal) var(--ease-spring) both;
  box-shadow: 0 8px 24px -14px rgba(20, 20, 20, 0.12);
}
@keyframes kg-panel-in {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.kg-info-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.kg-info-label {
  font-weight: 600;
  color: var(--ink-900);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kg-info-body {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  color: var(--ink-600);
}
.kg-info-item { font-size: var(--type-meta-size); }
.kg-footer { text-align: left; }
.kg-section { margin-bottom: var(--space-2); font-size: var(--type-sub-size); }
.gap-item {
  display: block;
  font-size: var(--type-meta-size);
  color: var(--signal-amber);
  margin-top: var(--space-1);
}
.kg-legend {
  display: flex;
  gap: var(--space-4);
  flex-wrap: wrap;
  padding: var(--space-2) 2px;
  font-size: var(--type-meta-size);
  color: var(--ink-400);
}
.kg-legend .lg-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.kg-legend .lg-bar {
  display: inline-block;
  width: 22px;
  height: 3px;
  border-radius: 2px;
}
.kg-legend .lg-concept {
  background: repeating-linear-gradient(
    90deg, var(--signal-purple) 0 4px, transparent 4px 8px
  );
}
.kg-legend .lg-doc {
  background: repeating-linear-gradient(
    90deg, var(--signal-amber) 0 6px, transparent 6px 9px
  );
}
.kg-legend .lg-cite { background: var(--signal-blue); }
.kg-legend .lg-discuss { background: var(--ink-300); }

/* 讨论某实体的文献列表 */
.kg-entity-docs {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--ink-100);
}
.kg-entity-docs-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--type-meta-size);
  color: var(--signal-blue);
  margin-bottom: var(--space-2);
}
.kg-entity-docs-loading,
.kg-entity-docs-empty {
  font-size: var(--type-meta-size);
  color: var(--ink-300);
  padding: var(--space-2) 2px;
  font-style: italic;
}
.kg-entity-docs-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 260px;
  overflow-y: auto;
}
.kg-entity-doc-item {
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-1);
  background: var(--paper-cool);
  border: 1px solid var(--ink-100);
  transition: all var(--duration-fast) var(--ease-out);
}
.kg-entity-doc-item:hover {
  background: var(--paper-warm);
  border-color: var(--ink-200);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}
.ed-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--type-sub-size);
  font-weight: 500;
  color: var(--ink-900);
  line-height: 1.4;
  margin-bottom: 3px;
}
.ed-title a { color: var(--signal-blue); text-decoration: none; }
.ed-title a:hover { text-decoration: underline; }
.ed-edge { margin-left: auto; }
.ed-oneline {
  font-size: 11.5px;
  color: var(--ink-500);
  line-height: 1.45;
  margin-bottom: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ed-meta {
  font-size: var(--type-micro-size);
  color: var(--ink-300);
  display: flex;
  gap: var(--space-1);
}
</style>
