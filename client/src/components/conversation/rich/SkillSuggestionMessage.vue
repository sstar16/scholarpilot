<template>
  <div class="rich-msg rich-msg--skill" :class="{ 'is-run': !!result, 'is-failed': !!error }">
    <div class="rich-msg__header">
      <el-icon :size="18"><MagicStick /></el-icon>
      <span class="title">推荐技能：{{ payload.display_name || payload.skill_id }}</span>
      <el-tag size="small" type="info" class="skill-badge">Skill</el-tag>
      <div class="spacer" />
      <el-button
        v-if="!result && !running"
        type="primary"
        size="small"
        :disabled="!payload.skill_id || !payload.project_id"
        @click="runSkill"
      >
        运行
      </el-button>
      <el-button v-else-if="running" size="small" loading disabled>运行中</el-button>
      <el-tag v-else-if="result" type="success" size="small">已完成</el-tag>
    </div>
    <div class="rich-msg__body">
      <p class="reason">{{ payload.reason }}</p>

      <!-- 4 桶分布简览 -->
      <div v-if="payload.bucket_stats" class="bucket-stats">
        <span
          v-for="(n, label) in displayedBuckets"
          :key="label"
          class="bucket-pill"
          :class="`bucket-${label}`"
        >
          {{ bucketLabel(label) }} {{ n }}
        </span>
      </div>

      <!-- 运行结果预览 -->
      <div v-if="result" class="result-box">
        <div v-if="result.summary" class="result-summary">{{ result.summary }}</div>
        <div v-if="Array.isArray(result.top_citations) && result.top_citations.length > 0" class="result-list">
          <b>Top citations:</b>
          <div v-for="c in result.top_citations.slice(0, 6)" :key="c.citation" class="result-item">
            {{ c.citation }} <span class="count">×{{ c.count }}</span>
          </div>
        </div>
        <div v-if="Array.isArray(result.top_methods) && result.top_methods.length > 0" class="result-list">
          <b>Top methods:</b>
          <div v-for="m in result.top_methods.slice(0, 6)" :key="m.method" class="result-item">
            {{ m.method }} <span class="count">×{{ m.count }}</span>
          </div>
        </div>
        <div v-if="Array.isArray(result.rising_topics) && result.rising_topics.length > 0" class="result-list">
          <b>新兴主题:</b>
          <div v-for="t in result.rising_topics.slice(0, 6)" :key="t.topic" class="result-item">
            {{ t.topic }} <span class="count">↑{{ t.ratio }}x</span>
          </div>
        </div>
        <div v-if="result.grade" class="result-grade">
          健康度 <b>{{ result.grade }}</b>
          <span v-if="result.stats" class="grade-stats">· 共 {{ result.stats.total_docs }} 篇</span>
        </div>
        <ul v-if="Array.isArray(result.issues) && result.issues.length > 0" class="result-issues">
          <li v-for="(i, idx) in result.issues" :key="idx" :class="`sev-${i.severity}`">
            [{{ i.severity }}] {{ i.message }}
          </li>
        </ul>
        <div v-if="result.bibtex" class="bibtex-box">
          <div class="bibtex-header">
            <span>{{ result.filename }} · {{ result.count }} 条</span>
            <el-button size="small" text @click="copyBibtex">复制</el-button>
            <el-button size="small" text @click="downloadBibtex">下载 .bib</el-button>
          </div>
          <pre class="bibtex-preview">{{ (result.bibtex || '').slice(0, 800) }}{{ (result.bibtex || '').length > 800 ? '\n...' : '' }}</pre>
        </div>
      </div>

      <div v-if="error" class="error-box">⚠ {{ error }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { skillsApi } from '@/api/client'

const props = defineProps<{ payload: any }>()

const running = ref(false)
const result = ref<any>(null)
const error = ref<string>('')

const displayedBuckets = computed(() => {
  const s = props.payload?.bucket_stats || {}
  // 只显示关键 4 桶，有值的在前
  const preferred = ['highly_relevant', 'relevant', 'neutral', 'irrelevant']
  const out: Record<string, number> = {}
  for (const k of preferred) if (s[k] !== undefined) out[k] = s[k]
  return out
})

function bucketLabel(k: string): string {
  return {
    highly_relevant: '强相关',
    relevant: '相关',
    neutral: '中性',
    irrelevant: '无关',
  }[k] || k
}

async function runSkill() {
  if (!props.payload?.skill_id || !props.payload?.project_id) return
  running.value = true
  error.value = ''
  try {
    const resp = await skillsApi.run(props.payload.project_id, props.payload.skill_id)
    result.value = resp.data
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '运行失败'
  } finally {
    running.value = false
  }
}

async function copyBibtex() {
  try {
    await navigator.clipboard.writeText(result.value?.bibtex || '')
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选中')
  }
}

function downloadBibtex() {
  const blob = new Blob([result.value?.bibtex || ''], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = result.value?.filename || 'scholarpilot.bib'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.rich-msg {
  margin: 14px 0;
  border-radius: 12px;
  background: linear-gradient(180deg, #f5f3ff 0%, #faf5ff 100%);
  border: 1px solid #ddd6fe;
  overflow: hidden;
}
.rich-msg.is-run {
  background: #faf5ff;
  border-color: #c4b5fd;
}
.rich-msg.is-failed {
  background: #fef2f2;
  border-color: #fecaca;
}
.rich-msg__header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; font-weight: 600; font-size: 13px;
  color: #5b21b6;
  border-bottom: 1px solid rgba(221, 214, 254, 0.5);
}
.rich-msg__header .spacer { flex: 1; }
.skill-badge { font-weight: 600; }
.rich-msg__body { padding: 12px 14px; }
.reason {
  font-size: 13px; color: #475569;
  margin: 0 0 10px; line-height: 1.55;
}
.bucket-stats {
  display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px;
}
.bucket-pill {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: #ede9fe; color: #6d28d9; font-weight: 500;
}
.bucket-highly_relevant { background: #d1fae5; color: #065f46; }
.bucket-relevant { background: #dbeafe; color: #1e40af; }
.bucket-neutral { background: #f1f5f9; color: #475569; }
.bucket-irrelevant { background: #fee2e2; color: #b91c1c; }

.result-box {
  margin-top: 10px; padding: 10px; background: #fff;
  border: 1px solid #e9d5ff; border-radius: 8px;
  font-size: 12.5px; color: #334155;
}
.result-summary { margin-bottom: 8px; line-height: 1.6; }
.result-list { margin: 6px 0; }
.result-list b { color: #6d28d9; font-weight: 600; font-size: 12px; }
.result-item {
  display: inline-block; margin-right: 10px; padding: 2px 6px;
  background: #f5f3ff; border-radius: 4px; margin-bottom: 3px;
}
.result-item .count { color: #6d28d9; font-weight: 600; margin-left: 3px; }
.result-grade { margin-top: 6px; font-size: 13px; }
.result-grade b { font-size: 18px; color: #6d28d9; padding: 0 6px; }
.grade-stats { color: #64748b; margin-left: 6px; }
.result-issues {
  margin: 6px 0 0; padding-left: 18px; font-size: 12px;
}
.result-issues li { margin: 2px 0; color: #475569; }
.result-issues li.sev-high { color: #b91c1c; font-weight: 500; }
.result-issues li.sev-medium { color: #b45309; }
.result-issues li.sev-low { color: #64748b; }

.bibtex-box { margin-top: 8px; }
.bibtex-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: #6d28d9; margin-bottom: 4px;
}
.bibtex-preview {
  background: #f8fafc; border: 1px solid #e2e8f0;
  border-radius: 6px; padding: 8px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px; color: #334155;
  max-height: 220px; overflow: auto; margin: 0;
  white-space: pre-wrap; word-break: break-all;
}
.error-box {
  color: #b91c1c; background: #fef2f2;
  padding: 8px 10px; border-radius: 6px; font-size: 12px;
}
</style>
