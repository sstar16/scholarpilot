<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElForm, ElFormItem, ElInput, ElInputNumber, ElTag, ElButton, ElMessage } from 'element-plus'
import { uploadApi } from '@/api/client'

const props = defineProps<{
  payload: {
    job_id: string
    doc_id: string
    filename: string
    metadata_draft: {
      title?: string
      title_zh?: string | null
      authors?: string[]
      year?: number | null
      abstract?: string | null
      doi?: string | null
      journal?: string | null
      one_line_summary?: string
      concept_tags?: string[]
    }
  }
}>()

const emit = defineEmits<{
  (e: 'confirmed', docId: string): void
  (e: 'cancelled', jobId: string): void
}>()

const m = props.payload.metadata_draft || {}
const form = ref({
  title: m.title || '',
  title_zh: m.title_zh || '',
  authors: (m.authors || []).slice(),
  year: m.year ?? null,
  abstract: m.abstract || '',
  doi: m.doi || '',
  journal: m.journal || '',
  one_line_summary: m.one_line_summary || '',
  concept_tags: (m.concept_tags || []).slice(),
})

const newAuthor = ref('')
const newTag = ref('')
const saving = ref(false)
const submitted = ref(false)

function addAuthor() {
  const v = newAuthor.value.trim()
  if (v) { form.value.authors.push(v); newAuthor.value = ''; persistDraft() }
}
function removeAuthor(i: number) { form.value.authors.splice(i, 1); persistDraft() }
function addTag() {
  const v = newTag.value.trim()
  if (v) { form.value.concept_tags.push(v); newTag.value = ''; persistDraft() }
}
function removeTag(i: number) { form.value.concept_tags.splice(i, 1); persistDraft() }

const draftKey = `pdf_import_draft:${props.payload.job_id}`
onMounted(() => {
  const saved = localStorage.getItem(draftKey)
  if (saved) {
    try { Object.assign(form.value, JSON.parse(saved)) } catch { /* noop */ }
  }
})
function persistDraft() {
  localStorage.setItem(draftKey, JSON.stringify(form.value))
}

async function confirm() {
  if (!form.value.title.trim()) return ElMessage.error('标题必填')
  if (!form.value.authors.length) return ElMessage.error('至少一位作者')
  if (!form.value.one_line_summary.trim()) return ElMessage.error('一句话主题必填')

  saving.value = true
  try {
    await uploadApi.confirmImport(props.payload.doc_id, {
      title: form.value.title,
      title_zh: form.value.title_zh || null,
      authors: form.value.authors,
      year: form.value.year || null,
      abstract: form.value.abstract || null,
      doi: form.value.doi || null,
      journal: form.value.journal || null,
      one_line_summary: form.value.one_line_summary,
      concept_tags: form.value.concept_tags,
    })
    localStorage.removeItem(draftKey)
    submitted.value = true
    emit('confirmed', props.payload.doc_id)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function cancel() {
  try {
    await uploadApi.cancelImport(props.payload.job_id)
    localStorage.removeItem(draftKey)
    emit('cancelled', props.payload.job_id)
  } catch {
    ElMessage.error('取消失败')
  }
}
</script>

<template>
  <div class="pdf-edit">
    <div class="header">📝 核对元数据：{{ payload.filename }}</div>

    <div class="section">
      <div class="section-title">基础元数据</div>
      <ElForm label-width="80px" size="small">
        <ElFormItem label="标题">
          <ElInput v-model="form.title" @blur="persistDraft" />
        </ElFormItem>
        <ElFormItem label="中文标题">
          <ElInput v-model="form.title_zh" @blur="persistDraft" />
        </ElFormItem>
        <ElFormItem label="作者">
          <div class="tag-list">
            <ElTag
              v-for="(a, i) in form.authors"
              :key="i"
              closable
              @close="removeAuthor(i)"
            >
              {{ a }}
            </ElTag>
            <ElInput
              v-model="newAuthor"
              size="small"
              placeholder="添加作者"
              style="width: 140px"
              @keydown.enter.prevent="addAuthor"
            />
          </div>
        </ElFormItem>
        <ElFormItem label="年份">
          <ElInputNumber
            v-model="form.year"
            :min="1900"
            :max="2100"
            @change="persistDraft"
          />
        </ElFormItem>
        <ElFormItem label="DOI">
          <ElInput v-model="form.doi" @blur="persistDraft" />
        </ElFormItem>
        <ElFormItem label="期刊">
          <ElInput v-model="form.journal" @blur="persistDraft" />
        </ElFormItem>
        <ElFormItem label="摘要">
          <ElInput
            v-model="form.abstract"
            type="textarea"
            :rows="3"
            @blur="persistDraft"
          />
        </ElFormItem>
      </ElForm>
    </div>

    <div class="section">
      <div class="section-title">主题</div>
      <ElForm label-width="80px" size="small">
        <ElFormItem label="一句话">
          <ElInput
            v-model="form.one_line_summary"
            maxlength="500"
            show-word-limit
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 6 }"
            @blur="persistDraft"
          />
        </ElFormItem>
        <ElFormItem label="概念标签">
          <div class="tag-list">
            <ElTag
              v-for="(t, i) in form.concept_tags"
              :key="i"
              closable
              @close="removeTag(i)"
            >
              {{ t }}
            </ElTag>
            <ElInput
              v-model="newTag"
              size="small"
              placeholder="添加标签"
              style="width: 120px"
              @keydown.enter.prevent="addTag"
            />
          </div>
        </ElFormItem>
      </ElForm>
    </div>

    <div class="section hint">
      📊 保存后自动生成 AI 摘要 + 评分
    </div>

    <div class="actions">
      <ElButton :disabled="submitted || saving" @click="cancel">取消</ElButton>
      <ElButton
        type="primary"
        :loading="saving"
        :disabled="submitted"
        @click="confirm"
      >
        {{ submitted ? '✓ 已保存' : '保存并继续' }}
      </ElButton>
    </div>
  </div>
</template>

<style scoped>
.pdf-edit {
  border: 1px solid var(--ink-200);
  border-radius: 10px;
  padding: 16px;
  background: var(--paper);
  /* 与助手气泡对齐：头像 36px + gap 10px = 46px 左缩进；宽度跟随助手气泡 max-width 85% */
  margin: 4px 0 16px 46px !important;
  max-width: calc(85% - 46px) !important;
  box-sizing: border-box;
}
.header { font-weight: 600; margin-bottom: 12px; color: var(--ink-900); }
.section { margin-bottom: 12px; }
.section-title {
  font-size: 13px;
  color: var(--ink-500);
  margin-bottom: 8px;
}
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.hint {
  background: var(--ink-100);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--ink-400);
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
