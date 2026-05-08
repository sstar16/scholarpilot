<template>
  <el-container class="kg-page" data-testid="knowledge-graph-page">
    <el-header class="kg-header" height="64px">
      <div class="kg-header-left">
        <h2 class="kg-title">知识图谱</h2>
        <span class="kg-stats" v-if="!loading">
          <el-tag size="small">{{ filteredNodes.length }} / {{ nodes.length }} 节点</el-tag>
          <el-tag size="small" type="info">{{ filteredEdges.length }} / {{ edges.length }} 关系</el-tag>
          <el-tag v-if="lodActive" size="small" type="warning">LOD: {{ filterType.length }} 类</el-tag>
        </span>
      </div>
      <div class="kg-header-right">
        <el-input
          v-model="search"
          placeholder="搜节点..."
          size="small"
          clearable
          style="width: 200px"
          data-testid="graph-search"
        />
        <el-select
          v-model="filterType"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="过滤实体类型"
          size="small"
          style="width: 240px"
          data-testid="graph-filter-type"
        >
          <el-option
            v-for="opt in TYPE_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          >
            <span class="kg-dot" :style="{ background: opt.color }"></span>
            {{ opt.label }}
          </el-option>
        </el-select>
        <el-select v-model="layoutName" size="small" style="width: 120px" data-testid="graph-layout-select">
          <el-option label="力导向" value="fcose" />
          <el-option label="圆形" value="circle" />
          <el-option label="网格" value="grid" />
          <el-option label="同心" value="concentric" />
        </el-select>
        <el-button size="small" :icon="Refresh" @click="rerunLayout" data-testid="graph-rerun">重排</el-button>
        <el-button size="small" @click="saveCachedLayout">保存布局</el-button>
      </div>
    </el-header>

    <el-container class="kg-body">
      <el-main class="kg-main" v-loading="loading">
        <CytoscapeCanvas
          v-if="!loading"
          ref="canvasRef"
          :nodes="filteredNodes"
          :edges="filteredEdges"
          :layout="cachedLayout"
          :initial-layout="layoutName"
          @node-click="onNodeClick"
          @edge-click="onEdgeClick"
          @background-click="onBackgroundClick"
          @layout-saved="onLayoutSaved"
        />
        <div v-if="!loading && nodes.length === 0" class="kg-empty">
          <p>知识图谱还没有节点</p>
          <p class="kg-empty-hint">完成一轮检索后，agent 会自动抽取实体并填充图谱</p>
        </div>
      </el-main>

      <el-aside v-if="selectedNode" class="kg-aside" width="320px" data-testid="graph-node-detail">
        <div class="kg-aside-head">
          <span class="kg-aside-title">{{ selectedNode.label }}</span>
          <el-button text :icon="Close" @click="selectedNode = null" />
        </div>
        <div class="kg-aside-body">
          <div class="kg-meta-row">
            <span class="kg-meta-key">类型</span>
            <el-tag size="small" :color="entityColor(selectedNode.type)" effect="dark">
              {{ selectedNode.type }}
            </el-tag>
          </div>
          <div class="kg-meta-row">
            <span class="kg-meta-key">权重</span>
            <span class="kg-meta-val">{{ selectedNode.weight.toFixed(3) }}</span>
          </div>
          <div class="kg-meta-row">
            <span class="kg-meta-key">来源文献</span>
            <span class="kg-meta-val">{{ selectedNode.source_doc_ids.length }} 篇</span>
          </div>
          <div v-if="selectedNeighbors.length" class="kg-neighbors">
            <h4>邻居</h4>
            <ul>
              <li
                v-for="nb in selectedNeighbors.slice(0, 12)"
                :key="nb.label"
                class="kg-neighbor-item"
                @click="focusNode(nb.label)"
              >
                <span class="kg-dot" :style="{ background: entityColor(nb.type) }"></span>
                {{ nb.label }}
                <span class="kg-relation">{{ nb.relation }}</span>
              </li>
            </ul>
            <p v-if="selectedNeighbors.length > 12" class="kg-neighbor-more">
              +{{ selectedNeighbors.length - 12 }} 更多
            </p>
          </div>
        </div>
      </el-aside>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
/**
 * KnowledgeGraph.vue — 桌面客户端知识图谱独立页（C11）。
 *
 * 与 components/graph/KnowledgeGraphView.vue（旧 vis-network modal）并存：
 *  - 旧 modal 走后端 `/api/projects/<id>/graph`，仍是 ProjectView 顶部入口
 *  - 本页基于客户端 GraphRepo 本地数据 + cytoscape；独立路由 `/projects/:projectId/graph`
 *  - 支持增量更新：监听 EventBus `graph_updated` channel，子组件 addElements/removeElements
 *  - 支持 layout 缓存：fcose 跑完写 layout.json，下次直接 preset 加载（避免大图反复重排）
 *  - LOD：节点 > 500 时默认隐藏 concept/author，只留 paper/method/technology（OQ-C-graph-1 决策）
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh, Close } from '@element-plus/icons-vue'

import CytoscapeCanvas from '@/components/graph/CytoscapeCanvas.vue'
import { GraphRepo, type GraphNode, type GraphEdge } from '@/data/graph/graphRepo'
import { getEventBus } from '@/data/orchestrator/eventBus'
import { readText } from '@/data/fs/files'
import {
  ENTITY_TYPE_COLORS,
  type CachedLayout,
  type LayoutName,
} from '@/composables/useGraphRenderer'

// ─────────────── 静态配置 ───────────────

const TYPE_OPTIONS: Array<{ value: string; label: string; color: string }> = [
  { value: 'paper', label: '文献', color: ENTITY_TYPE_COLORS.paper },
  { value: 'concept', label: '概念', color: ENTITY_TYPE_COLORS.concept },
  { value: 'author', label: '作者', color: ENTITY_TYPE_COLORS.author },
  { value: 'organization', label: '机构', color: ENTITY_TYPE_COLORS.organization },
  { value: 'method', label: '方法', color: ENTITY_TYPE_COLORS.method },
  { value: 'technology', label: '技术', color: ENTITY_TYPE_COLORS.technology },
]

/** LOD 阈值（OQ-C-graph-1 决策）：节点超过这个数量自动开 LOD 过滤。 */
const LOD_NODE_THRESHOLD = 500

// ─────────────── 状态 ───────────────

const route = useRoute()
const projectId = computed(() => String(route.params.projectId ?? route.params.id ?? ''))

const loading = ref(true)
const nodes = ref<GraphNode[]>([])
const edges = ref<GraphEdge[]>([])
const cachedLayout = ref<CachedLayout | null>(null)
const filterType = ref<string[]>([])
const search = ref('')
const layoutName = ref<LayoutName>('fcose')
const selectedNode = ref<GraphNode | null>(null)
const lodActive = ref(false)

const canvasRef = ref<InstanceType<typeof CytoscapeCanvas> | null>(null)

let repo: GraphRepo | null = null
let unsubGraphUpdated: (() => void) | null = null

// ─────────────── 计算 ───────────────

const filteredNodes = computed<GraphNode[]>(() => {
  const typeSet = new Set(filterType.value)
  const q = search.value.trim().toLowerCase()
  return nodes.value.filter((n) => {
    if (filterType.value.length > 0 && !typeSet.has(n.type)) return false
    if (q && !n.label.toLowerCase().includes(q)) return false
    return true
  })
})

const filteredEdges = computed<GraphEdge[]>(() => {
  const ids = new Set(filteredNodes.value.map((n) => n.label))
  return edges.value.filter((e) => ids.has(e.source) && ids.has(e.target))
})

const selectedNeighbors = computed<Array<{ label: string; type: string; relation: string }>>(() => {
  if (!selectedNode.value) return []
  const targetLabel = selectedNode.value.label
  const nodeMap: Record<string, GraphNode> = {}
  for (const n of nodes.value) nodeMap[n.label] = n
  const out: Array<{ label: string; type: string; relation: string }> = []
  for (const e of edges.value) {
    if (e.source === targetLabel && nodeMap[e.target]) {
      out.push({ label: e.target, type: nodeMap[e.target].type, relation: e.relation })
    } else if (e.target === targetLabel && nodeMap[e.source]) {
      out.push({ label: e.source, type: nodeMap[e.source].type, relation: e.relation })
    }
  }
  return out
})

// ─────────────── 生命周期 ───────────────

onMounted(async () => {
  if (!projectId.value) {
    loading.value = false
    return
  }
  await loadAll()

  // EventBus 增量更新订阅
  const bus = getEventBus()
  unsubGraphUpdated = bus.subscribeChannel(`graph:${projectId.value}`, (evt) => {
    if (evt.event === 'graph_updated') {
      // 简化策略：拉一次最新的 nodes/edges，让 watch(props.nodes.length) 触发增量重建
      // （cytoscape 的 elements diff 太重，直接 reload 更稳）
      void loadAll(/* preserveSelection */ true)
    }
  })
})

onUnmounted(() => {
  if (unsubGraphUpdated) {
    unsubGraphUpdated()
    unsubGraphUpdated = null
  }
})

// 切换 layout 算法（dropdown） — 通知子组件
watch(layoutName, (n) => {
  if (canvasRef.value) {
    canvasRef.value.applyLayout(n)
  }
})

// 搜索词变化 → 高亮匹配节点
watch(search, (q) => {
  if (!canvasRef.value) return
  if (!q.trim()) {
    canvasRef.value.clearFocus()
    return
  }
  const match = filteredNodes.value.find((n) =>
    n.label.toLowerCase().includes(q.trim().toLowerCase()),
  )
  if (match) canvasRef.value.focusNode(match.label)
})

// ─────────────── 加载 ───────────────

async function loadAll(preserveSelection = false) {
  if (!projectId.value) return
  loading.value = !preserveSelection
  try {
    repo = new GraphRepo(projectId.value)
    const [n, e, layout] = await Promise.all([
      repo.loadNodes(),
      repo.loadEdges(),
      _loadLayoutCache(repo),
    ])
    nodes.value = n
    edges.value = e
    cachedLayout.value = layout

    // LOD 默认过滤（节点超阈值才启用，避免小图也被过滤）
    if (n.length > LOD_NODE_THRESHOLD && filterType.value.length === 0) {
      filterType.value = ['paper', 'method', 'technology']
      lodActive.value = true
    } else {
      lodActive.value = false
    }
  } catch (err) {
    console.error('[KnowledgeGraph] loadAll failed', err)
  } finally {
    loading.value = false
  }
}

/**
 * 读 layout.json — repo 当前没暴露 loadLayout，自己读 fs。
 * 文件不存在 / 损坏 → null（不抛）。
 */
async function _loadLayoutCache(r: GraphRepo): Promise<CachedLayout | null> {
  try {
    const text = await readText(r.layoutPath)
    if (!text) return null
    const obj = JSON.parse(text)
    if (obj && typeof obj === 'object' && obj.positions && typeof obj.generated_at === 'number') {
      return obj as CachedLayout
    }
    return null
  } catch {
    return null
  }
}

// ─────────────── 交互 ───────────────

function onNodeClick(_id: string, rawLabel: string, _type: string) {
  const found = nodes.value.find((n) => n.label === rawLabel)
  selectedNode.value = found ?? null
}

function onEdgeClick(_edgeId: string) {
  // 边点击暂时只清节点选择，未来可加边详情面板
  selectedNode.value = null
}

function onBackgroundClick() {
  selectedNode.value = null
  if (canvasRef.value) canvasRef.value.clearFocus()
}

function rerunLayout() {
  if (canvasRef.value) canvasRef.value.rerunLayout()
}

async function saveCachedLayout() {
  if (!canvasRef.value || !repo) return
  const layout = canvasRef.value.saveLayout()
  if (!layout) return
  await repo.exportLayout(layout)
  cachedLayout.value = layout
}

function onLayoutSaved(_layout: CachedLayout) {
  // saveLayout 已经 emit 这个事件；此处兜底，未来可加 toast
}

function focusNode(label: string) {
  if (canvasRef.value) canvasRef.value.focusNode(label)
}

function entityColor(type: string): string {
  return ENTITY_TYPE_COLORS[type] ?? '#64748b'
}
</script>

<style scoped>
.kg-page {
  height: 100vh;
  background: var(--paper, #fdfdfb);
}
.kg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e5e7eb;
  background: #fff;
  padding: 0 24px;
}
.kg-header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.kg-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
}
.kg-stats {
  display: inline-flex;
  gap: 6px;
}
.kg-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.kg-body {
  height: calc(100vh - 64px);
}
.kg-main {
  padding: 12px;
  position: relative;
}
.kg-empty {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #94a3b8;
}
.kg-empty-hint {
  font-size: 13px;
  margin-top: 4px;
}
.kg-aside {
  background: #fff;
  border-left: 1px solid #e5e7eb;
  padding: 16px;
  overflow-y: auto;
}
.kg-aside-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.kg-aside-title {
  font-weight: 600;
  font-size: 16px;
  color: #1e293b;
  word-break: break-word;
}
.kg-aside-body {
  font-size: 13px;
  color: #475569;
}
.kg-meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px dashed #e5e7eb;
}
.kg-meta-key {
  color: #94a3b8;
  font-size: 12px;
}
.kg-meta-val {
  color: #1e293b;
  font-weight: 500;
}
.kg-neighbors {
  margin-top: 16px;
}
.kg-neighbors h4 {
  font-size: 13px;
  margin: 0 0 8px;
  color: #475569;
}
.kg-neighbors ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.kg-neighbor-item {
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #1e293b;
  transition: background 0.15s;
}
.kg-neighbor-item:hover {
  background: #f1f5f9;
}
.kg-relation {
  margin-left: auto;
  font-size: 11px;
  color: #94a3b8;
}
.kg-neighbor-more {
  font-size: 11px;
  color: #94a3b8;
  margin: 6px 0 0;
}
.kg-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}
</style>
