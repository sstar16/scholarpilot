<template>
  <div class="settings-wrap">
    <div class="page-header">
      <h2>设置</h2>
    </div>

    <el-card class="settings-card" shadow="never">
      <template #header>
        <span class="card-title">LLM 配置</span>
      </template>

      <div v-if="loading" style="padding:40px">
        <el-skeleton :rows="3" animated />
      </div>

      <template v-else>
        <div class="provider-list">
          <el-card
            v-for="p in providers"
            :key="p.provider_id"
            class="provider-item"
            shadow="never"
            :class="{ active: p.provider_id === activeProvider }"
          >
            <div class="provider-row">
              <div>
                <span class="provider-name">{{ PROVIDER_LABELS[p.provider_id] ?? p.provider_id }}</span>
                <el-tag v-if="p.provider_id === activeProvider" type="success" size="small" style="margin-left:8px">使用中</el-tag>
                <span class="provider-model">{{ p.model }}</span>
              </div>
              <div class="provider-actions">
                <el-button size="small" text type="primary" :disabled="p.provider_id === activeProvider"
                  @click="switchProvider(p.provider_id)">切换</el-button>
                <el-button size="small" text type="primary" :loading="testing === p.provider_id"
                  @click="testCurrent(p.provider_id)">测试</el-button>
                <el-button size="small" text type="danger"
                  @click="deleteProvider(p.provider_id)">删除</el-button>
              </div>
            </div>
          </el-card>
          <el-empty v-if="providers.length === 0" description="暂无配置的 LLM 提供商" :image-size="60" />
        </div>

        <el-divider>添加 / 更新提供商</el-divider>

        <el-form :model="form" label-position="top" @submit.prevent="addProvider">
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="提供商类型">
                <el-select v-model="form.provider_id" style="width:100%">
                  <el-option v-for="(label, val) in PROVIDER_LABELS" :key="val" :label="label" :value="val" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="模型名称">
                <el-input v-model="form.model" placeholder="例：qwen2.5:7b 或 gpt-4o" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="Base URL（Ollama 或自定义端点）">
                <el-input v-model="form.base_url" placeholder="http://localhost:11434" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="API Key（非 Ollama 必填）">
                <el-input v-model="form.api_key" type="password" show-password placeholder="sk-..." />
              </el-form-item>
            </el-col>
          </el-row>
          <el-button type="primary" native-type="submit" :loading="adding">保存提供商配置</el-button>
        </el-form>
      </template>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { llmApi } from '../api/client'

const PROVIDER_LABELS: Record<string, string> = {
  ollama: 'Ollama（本地）',
  openai_compatible: 'OpenAI 兼容 API',
  anthropic: 'Anthropic Claude',
  deepseek: 'DeepSeek',
  moonshot: 'Moonshot (Kimi)',
}

const loading = ref(true)
const adding = ref(false)
const testing = ref<string | null>(null)
const providers = ref<any[]>([])
const activeProvider = ref<string>('')

const form = reactive({ provider_id: 'ollama', model: '', base_url: '', api_key: '' })

onMounted(async () => {
  await loadProviders()
  loading.value = false
})

async function loadProviders() {
  const res = await llmApi.listProviders()
  providers.value = res.data.providers ?? []
  activeProvider.value = res.data.active ?? ''
}

async function addProvider() {
  if (!form.model) { ElMessage.warning('请填写模型名称'); return }
  adding.value = true
  try {
    await llmApi.configureProvider(form)
    await loadProviders()
    ElMessage.success('配置已保存')
    form.model = ''; form.api_key = ''; form.base_url = ''
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    adding.value = false
  }
}

async function switchProvider(id: string) {
  try {
    await llmApi.switchProvider(id)
    activeProvider.value = id
    ElMessage.success(`已切换到 ${PROVIDER_LABELS[id] ?? id}`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '切换失败')
  }
}

async function testCurrent(id: string) {
  testing.value = id
  try {
    await llmApi.switchProvider(id)
    activeProvider.value = id
    const res = await llmApi.testProvider()
    ElMessage.success(`测试成功：${String(res.data.response ?? '').slice(0, 60)}`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '测试失败')
  } finally {
    testing.value = null
  }
}

async function deleteProvider(id: string) {
  await ElMessageBox.confirm(`确认删除 "${PROVIDER_LABELS[id] ?? id}"？`, '提示', { type: 'warning' })
  try {
    await llmApi.deleteProvider(id)
    providers.value = providers.value.filter((p) => p.provider_id !== id)
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}
</script>

<style scoped>
.settings-wrap { max-width: 860px; margin: 0 auto; padding: 24px; }
.page-header { margin-bottom: 24px; }
.page-header h2 { margin: 0; }
.card-title { font-size: 15px; font-weight: 600; }
.provider-list { display: flex; flex-direction: column; gap: 10px; margin-bottom: 20px; }
.provider-item { border: 1px solid #e4e7ed; }
.provider-item.active { border-color: var(--el-color-primary); }
.provider-row { display: flex; justify-content: space-between; align-items: center; }
.provider-name { font-size: 14px; font-weight: 600; }
.provider-model { display: block; font-size: 12px; color: #909399; margin-top: 2px; }
.provider-actions { display: flex; gap: 4px; }
</style>
