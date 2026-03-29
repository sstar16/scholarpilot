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

        <!-- 高级配置（默认收起） -->
        <el-collapse v-model="activeCollapse" class="config-collapse">
          <el-collapse-item title="高级搜索配置" name="advanced">
            <div class="config-section">
              <el-form-item label="检索轮数">
                <el-input-number v-model="form.maxRounds" :min="1" :max="10" />
                <span class="config-hint">默认5轮，可根据需要增减</span>
              </el-form-item>

              <el-form-item label="启用专利搜索">
                <el-switch v-model="form.enablePatents" />
                <span class="config-hint">搜索 USPTO 美国专利数据库</span>
              </el-form-item>

              <el-form-item label="启用临床试验搜索">
                <el-switch v-model="form.enableClinicalTrials" />
                <span class="config-hint">搜索 ClinicalTrials.gov 临床试验</span>
              </el-form-item>

              <el-divider content-position="left">检索范围</el-divider>

              <el-form-item label="年份策略">
                <el-select v-model="form.yearStrategy" style="width:100%">
                  <el-option label="逐步扩展（默认）：近5年→10年→20年→全时间" value="progressive" />
                  <el-option label="固定：近5年" value="last5" />
                  <el-option label="固定：近10年" value="last10" />
                  <el-option label="固定：近20年" value="last20" />
                  <el-option label="全时间" value="all" />
                </el-select>
              </el-form-item>

              <el-form-item label="语言优先级">
                <el-radio-group v-model="form.languageScope">
                  <el-radio value="chinese_first">中文优先</el-radio>
                  <el-radio value="english_first">英文优先</el-radio>
                  <el-radio value="bilingual">中英双语</el-radio>
                </el-radio-group>
              </el-form-item>

              <el-form-item label="每轮返回结果数">
                <el-input-number
                  v-model="form.topK"
                  :min="5" :max="200" :step="5"
                  :disabled="form.topKAll"
                />
                <el-checkbox v-model="form.topKAll" style="margin-left:16px">全部结果</el-checkbox>
                <div class="config-hint">「全部结果」将返回所有检索到的文献并按综合评分排序</div>
              </el-form-item>

              <el-divider content-position="left">评分权重</el-divider>
              <div class="weight-sliders">
                <div class="weight-row">
                  <span class="weight-label">关键词相关性</span>
                  <el-slider v-model="weights.keyword" :min="0" :max="100" :step="5" />
                  <span class="weight-value">{{ weights.keyword }}%</span>
                </div>
                <div class="weight-row">
                  <span class="weight-label">引用影响力</span>
                  <el-slider v-model="weights.citation" :min="0" :max="100" :step="5" />
                  <span class="weight-value">{{ weights.citation }}%</span>
                </div>
                <div class="weight-row">
                  <span class="weight-label">发表时效性</span>
                  <el-slider v-model="weights.recency" :min="0" :max="100" :step="5" />
                  <span class="weight-value">{{ weights.recency }}%</span>
                </div>
                <div v-if="weightSum !== 100" class="weight-warning">
                  <el-text type="warning" size="small">权重之和应为100%（当前{{ weightSum }}%）</el-text>
                </div>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>

        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin: 16px 0"
        >
          <template #title>
            AI 将分{{ form.maxRounds }}轮渐进式检索，每轮结束后您对结果评分，AI 据此优化下一轮的检索方向
          </template>
        </el-alert>

        <el-button type="primary" native-type="submit" size="large" :loading="loading" style="width:100%">
          创建项目并开始第1轮检索
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectApi } from '../api/client'

const router = useRouter()
const loading = ref(false)
const activeCollapse = ref<string[]>([])

const form = reactive({
  title: '',
  description: '',
  domains: [] as string[],
  maxRounds: 5,
  enablePatents: false,
  enableClinicalTrials: false,
  yearStrategy: 'progressive',
  languageScope: 'chinese_first',
  topK: 10,
  topKAll: false,
})

const weights = reactive({ keyword: 60, citation: 25, recency: 15 })
const weightSum = computed(() => weights.keyword + weights.citation + weights.recency)

async function handleCreate() {
  if (!form.title || !form.description || form.domains.length === 0) {
    ElMessage.warning('请填写项目名称、选择至少一个领域、并填写描述')
    return
  }
  if (weightSum.value !== 100) {
    ElMessage.warning('评分权重之和必须为100%')
    return
  }

  loading.value = true
  try {
    const searchConfig: any = {
      enable_patents: form.enablePatents,
      enable_clinical_trials: form.enableClinicalTrials,
      year_strategy: form.yearStrategy,
      language_scope: form.languageScope,
      top_k: form.topKAll ? null : form.topK,
      scoring_weights: {
        keyword: weights.keyword / 100,
        citation: weights.citation / 100,
        recency: weights.recency / 100,
      },
    }

    const res = await projectApi.create({
      title: form.title,
      description: form.description,
      domain: form.domains[0],  // 向后兼容
      domains: form.domains,
      max_rounds: form.maxRounds,
      search_config: searchConfig,
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
.create-wrap { max-width: 700px; margin: 32px auto; padding: 0 16px; }
.card-header { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; }
.hint { display: block; color: #909399; font-size: 12px; font-weight: normal; margin-top: 2px; }
.config-collapse { margin-bottom: 8px; }
.config-section { padding: 0 8px; }
.config-hint { color: #909399; font-size: 12px; margin-left: 12px; }
.weight-sliders { margin-top: 8px; }
.weight-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.weight-label { min-width: 100px; font-size: 14px; }
.weight-row .el-slider { flex: 1; }
.weight-value { min-width: 40px; text-align: right; font-size: 14px; color: #606266; }
.weight-warning { margin-top: 4px; }
</style>
