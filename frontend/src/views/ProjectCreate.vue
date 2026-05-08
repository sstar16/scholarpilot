<template>
  <div class="create-wrap">
    <el-card class="create-card" shadow="never">
      <template #header>
        <div class="card-header">
          <el-button text @click="router.back()"><el-icon><ArrowLeft /></el-icon></el-button>
          <span>描述您的研究项目</span>
        </div>
      </template>

      <el-form :model="form" label-position="top" size="large" @submit.prevent="handleCreate">
        <el-form-item label="项目名称">
          <el-input v-model="form.title" placeholder="例：纳米材料抗肿瘤药物递送系统研究" />
        </el-form-item>

        <el-form-item label="研究领域（可多选）">
          <el-select
            v-model="form.domains"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择一个或多个领域"
            style="width:100%"
          >
            <el-option label="生物医学 / Biology & Medicine" value="biology" />
            <el-option label="化学 / Chemistry" value="chemistry" />
            <el-option label="材料科学 / Materials Science" value="materials" />
            <el-option label="设备机械 / Mechanical Engineering" value="mechanical" />
            <el-option label="计算机科学 / Computer Science" value="cs" />
            <el-option label="物理学 / Physics" value="physics" />
            <el-option label="经济学 / Economics" value="economics" />
            <el-option label="环境科学 / Environmental Science" value="environment" />
            <el-option label="其他 / Other" value="other" />
          </el-select>
        </el-form-item>

        <el-form-item>
          <template #label>
            <span>项目描述和关键研究点</span>
            <span class="hint">请尽量详细描述，AI 将根据此描述检索和评估文献</span>
          </template>
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="8"
            placeholder="示例：本项目开发基于PLGA纳米粒子的靶向递药系统，用于肝癌治疗。关键技术点包括：
1. 纳米粒子表面修饰（叶酸靶向）
2. 药物（多柔比星）包载率优化
3. 体内外药代动力学评价
4. 肿瘤微环境响应性释放机制"
          />
        </el-form-item>

        <el-alert type="info" :closable="false" show-icon style="margin: 16px 0">
          <template #title>
            AI Agent 将自动规划检索策略，您可以随时开始新一轮检索或开启每日监控
          </template>
        </el-alert>

        <el-button type="primary" native-type="submit" size="large" :loading="loading" style="width:100%">
          创建项目
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectApi } from '../api/client'

const router = useRouter()
const loading = ref(false)

const form = reactive({
  title: '',
  description: '',
  domains: [] as string[],
})

async function handleCreate() {
  if (!form.title || !form.description || form.domains.length === 0) {
    ElMessage.warning('请填写项目名称、选择至少一个领域、并填写描述')
    return
  }

  loading.value = true
  try {
    const res = await projectApi.create({
      title: form.title,
      description: form.description,
      domain: form.domains[0],
      domains: form.domains,
    })
    router.push(`/projects/${res.data.id}`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.create-wrap { max-width: 720px; margin: 32px auto; padding: 0 16px; }
.card-header { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; }
.hint { display: block; color: #909399; font-size: 12px; font-weight: normal; margin-top: 2px; }
</style>
