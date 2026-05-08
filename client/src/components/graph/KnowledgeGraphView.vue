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
        <el-button
          v-if="rawNodes.length > 0"
          size="small"
          text
          class="open-fullpage"
          @click="openFullpage"
        >
          全屏视图 →
        </el-button>
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
        <span class="lg-item"><i class="lg-bar lg-cite"></i>引用 / cites</span>
        <span class="lg-item"><i class="lg-bar lg-extends"></i>extends / 延伸</span>
        <span class="lg-item"><i class="lg-bar lg-topic"></i>topic / 概念</span>
        <span class="lg-item"><i class="lg-bar lg-coauthor"></i>coauthor / 作者</span>
      </div>

      <!-- Cytoscape container (子组件 CytoscapeCanvas 全权管理 cy 实例) -->
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
        <div v-if="!loading && rawNodes.length === 0" class="kg-empty">
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
        <CytoscapeCanvas
          v-show="!loading && rawNodes.length > 0"
          ref="canvasRef"
          class="kg-network"
          :nodes="cyNodes"
          :edges="cyEdges"
          :layout="null"
          initial-layout="fcose"
          @node-click="onNodeClick"
          @background-click="onBackgroundClick"
        />
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
/**
 * KnowledgeGraphView — bucket-aware 知识图谱 dialog（顶部入口 / BucketSidebar / Banner 复用）。
 *
 * 2026-05-08 重构：
 *   - 旧实现用 vis-network/standalone 直接 mount Network。Vue 3 Proxy 拦截 + DataSet 类型不匹配
 *     的坑长期存在，与全页 KnowledgeGraph.vue 视觉/层叠/交互也分裂。
 *   - 新实现把渲染层换成 `CytoscapeCanvas`（与全页一致），保留：
 *     * 后端 bucket-aware graph API (`/api/projects/<id>/graph?bucket=...`)
 *     * hubs / gaps / rebuild / entity docs 二次联动
 *     * Dialog 形态 + bucket 切换器 + 中文 legend
 *   - 后端 `node_id`、`node_type` 与客户端 GraphRepo 字段不同，这里做一层适配：
 *     `{node_id,label,node_type}` → `{label,type,weight,source_doc_ids}`
 *     边走 `{source,target,edge_type}` → `{source,target,relation,weight}`，
 *     注意 cytoscape 用 `n.label` 当 id，所以 source/target 要映射到 label。
 *   - 提供 "全屏视图 →" 入口跳路由 `/projects/:projectId/graph`，给本地大图用。
 */
import { ref, watch, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Loading } from '@element-plus/icons-vue'

import api from '../../api/client'
import CytoscapeCanvas from './CytoscapeCanvas.vue'
import type { GraphNode, GraphEdge } from '@/data/graph/graphRepo'

const props = defineProps<{
  projectId: string
}>()

const visible = defineModel<boolean>('visible', { default: false })
const bucketModel = defineModel<string>('bucket', { default: 'very_relevant' })

const router = useRouter()

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

// node_type → 颜色（与全页 KnowledgeGraph 一致；通过 GraphRepo type 着色，这里仅用于 info panel tag）
const TYPE_COLORS: Record<string, string> = {
  document: '#4E79A7',
  paper: '#4E79A7',
  author: '#F28E2B',
  concept: '#59A14F',
  method: '#76B7B2',
  technology: '#B07AA1',
  organization: '#E15759',
  topic: '#E15759',
  journal: '#76B7B2',
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

/** 后端原始 nodes/edges（用于 stats / 详情面板邻居计算）。 */
const rawNodes = ref<any[]>([])
const rawEdges = ref<any[]>([])
const stats = ref<any>(null)
const hubs = ref<any[]>([])
const gaps = ref<any[]>([])
const selectedNode = ref<any>(null)

/** 子组件 CytoscapeCanvas 引用（全屏跳转/未来扩展 focus 用）。 */
const canvasRef = ref<InstanceType<typeof CytoscapeCanvas> | null>(null)

/**
 * 后端 graph API 返回的 nodes 用 `id`/`label`/`node_type`，cytoscape 这边的 GraphRepo
 * 用 `label`/`type`/`weight`/`source_doc_ids`。这里用 node_id → label 反查表把
 * edge.source/target 映射成 cytoscape 的 id（label）。
 */
const cyNodes = computed<GraphNode[]>(() => {
  return rawNodes.value.map((n) => ({
    label: n.label || String(n.id || ''),
    type: (n.node_type as GraphNode['type']) || 'concept',
    weight: typeof n.weight === 'number' ? n.weight : 0.5,
    source_doc_ids: Array.isArray(n.source_doc_ids) ? n.source_doc_ids : [],
  }))
})

const cyEdges = computed<GraphEdge[]>(() => {
  // 后端 edge 用 node_id → 通过 idToLabel 映射到 cytoscape id
  const idToLabel: Record<string, string> = {}
  for (const n of rawNodes.value) {
    if (n.id != null) idToLabel[String(n.id)] = n.label || String(n.id)
  }
  const out: GraphEdge[] = []
  const seen = new Set<string>()
  for (const e of rawEdges.value) {
    const src = idToLabel[String(e.source)] ?? String(e.source)
    const tgt = idToLabel[String(e.target)] ?? String(e.target)
    if (!src || !tgt) continue
    const key = `${src}|${tgt}|${e.edge_type || e.relation || ''}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({
      source: src,
      target: tgt,
      relation: (e.edge_type || e.relation || 'topic') as GraphEdge['relation'],
      weight: typeof e.weight === 'number' ? e.weight : (typeof e.llm_confidence === 'number' ? e.llm_confidence : 0.5),
    })
  }
  return out
})

/** 节点 id 映射（点击事件回查后端 raw 数据）。 */
const labelToRaw = computed<Record<string, any>>(() => {
  const m: Record<string, any> = {}
  for (const n of rawNodes.value) {
    const label = n.label || String(n.id || '')
    m[label] = n
  }
  return m
})

// Reload on visibility or bucket change
watch([visible, bucketModel], async ([v]) => {
  if (!v) return
  await loadGraph()
})

async function loadGraph() {
  loading.value = true
  rawNodes.value = []
  rawEdges.value = []
  selectedNode.value = null
  try {
    const bucketParam = bucketModel.value === 'all' ? '' : `?bucket=${bucketModel.value}`
    const graphUrl = `/api/projects/${props.projectId}/graph${bucketParam}`

    const [graphRes, hubsRes, gapsRes] = await Promise.all([
      api.get(graphUrl),
      api.get(`/api/projects/${props.projectId}/graph/hubs?top_k=8`),
      api.get(`/api/projects/${props.projectId}/graph/gaps`),
    ])
    rawNodes.value = graphRes.data.nodes || []
    rawEdges.value = graphRes.data.edges || []
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
      if (rawNodes.value.length > 0) break
    }
  } catch (e) {
    console.error('Rebuild failed', e)
  } finally {
    rebuilding.value = false
  }
}

function onNodeClick(_id: string, rawLabel: string, _type: string) {
  const raw = labelToRaw.value[rawLabel]
  if (!raw) {
    selectedNode.value = null
    entityDocs.value = []
    return
  }
  // 计算 degree / neighbors（基于 raw edges + nodeId）
  const nodeId = raw.id != null ? String(raw.id) : rawLabel
  let degree = 0
  const neighborIds: string[] = []
  for (const e of rawEdges.value) {
    if (String(e.source) === nodeId) {
      degree++
      neighborIds.push(String(e.target))
    } else if (String(e.target) === nodeId) {
      degree++
      neighborIds.push(String(e.source))
    }
  }
  const idToLabel: Record<string, string> = {}
  for (const n of rawNodes.value) {
    if (n.id != null) idToLabel[String(n.id)] = n.label || String(n.id)
  }
  selectedNode.value = {
    node_id: nodeId,
    label: raw.label || rawLabel,
    node_type: raw.node_type || 'concept',
    community: raw.community,
    degree,
    neighbors: neighborIds.slice(0, 12).map((id) => idToLabel[id] || id),
  }
  if (!nodeId.startsWith('doc:')) {
    fetchEntityDocs(nodeId)
  } else {
    entityDocs.value = []
  }
}

function onBackgroundClick() {
  selectedNode.value = null
  entityDocs.value = []
}

function openFullpage() {
  visible.value = false
  router.push({
    name: 'KnowledgeGraph',
    params: { projectId: props.projectId },
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
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
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
.open-fullpage {
  margin-left: auto;
  font-size: 12px;
  color: var(--signal-teal);
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
.kg-legend .lg-cite { background: #2563eb; }
.kg-legend .lg-extends { background: #f97316; }
.kg-legend .lg-topic { background: #a855f7; }
.kg-legend .lg-coauthor { background: #cbd5e1; }

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
