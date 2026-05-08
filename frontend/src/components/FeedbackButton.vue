<template>
  <!-- 浮动按钮：页面右下角 -->
  <button
    class="fb-trigger"
    :class="{ 'fb-trigger--collapsed': collapsed }"
    @click="open = true"
    title="给我们反馈"
  >
    <el-icon :size="16"><ChatDotSquare /></el-icon>
    <span class="fb-trigger-label">反馈</span>
  </button>

  <el-dialog
    v-model="open"
    title="给 ScholarPilot 一些反馈"
    width="520px"
    :close-on-click-modal="false"
    align-center
  >
    <div class="fb-form">
      <div class="fb-row">
        <label class="fb-label">类别</label>
        <el-radio-group v-model="form.category" size="small">
          <el-radio-button value="bug">
            <el-icon><Warning /></el-icon>
            Bug
          </el-radio-button>
          <el-radio-button value="suggestion">
            <el-icon><MagicStick /></el-icon>
            建议
          </el-radio-button>
          <el-radio-button value="praise">
            <el-icon><Star /></el-icon>
            好评
          </el-radio-button>
          <el-radio-button value="other">其他</el-radio-button>
        </el-radio-group>
      </div>

      <div class="fb-row">
        <label class="fb-label">
          内容
          <span class="fb-required">*</span>
        </label>
        <el-input
          v-model="form.content"
          type="textarea"
          :rows="6"
          :maxlength="4000"
          show-word-limit
          :placeholder="placeholderForCategory"
        />
      </div>

      <div class="fb-row">
        <label class="fb-label">
          联系方式 <span class="fb-hint">（可选，方便我们跟进）</span>
        </label>
        <el-input
          v-model="form.contact"
          placeholder="邮箱 / 微信 / QQ，任一即可"
          :maxlength="255"
        />
      </div>

      <div class="fb-notice">
        <el-icon><InfoFilled /></el-icon>
        <span>
          当前页面会自动附带：{{ currentPageInfo }}。提交后我会第一时间看到。
        </span>
      </div>
    </div>

    <template #footer>
      <el-button @click="open = false">取消</el-button>
      <el-button
        type="primary"
        :loading="submitting"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ submitting ? '提交中…' : '提交反馈' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, defineProps } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ChatDotSquare, Warning, MagicStick, Star, InfoFilled,
} from '@element-plus/icons-vue'
import { siteFeedbackApi } from '../api/client'

defineProps<{
  /** 允许外部控制按钮是否折叠（例如某些页面只显示图标） */
  collapsed?: boolean
}>()

const open = ref(false)
const submitting = ref(false)

const form = reactive({
  category: 'suggestion' as 'bug' | 'suggestion' | 'praise' | 'other',
  content: '',
  contact: '',
})

const placeholderForCategory = computed(() => {
  switch (form.category) {
    case 'bug':
      return '具体报错现象 / 复现步骤，例如：\n1. 进入项目后点"协作研究"\n2. 勾选 3 篇文献后点确认\n3. 页面白屏，console 里有 XXX 错误'
    case 'suggestion':
      return '希望增加 / 优化的功能点，越具体越好'
    case 'praise':
      return '哪里用得顺手 ❤'
    default:
      return '随便写……'
  }
})

const currentPageInfo = computed(() => {
  const path = window.location.pathname + window.location.search
  return path.length > 60 ? path.slice(0, 60) + '…' : path
})

const canSubmit = computed(() => form.content.trim().length > 0)

async function submit() {
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  try {
    await siteFeedbackApi.submit({
      category: form.category,
      content: form.content.trim(),
      contact: form.contact.trim() || null,
      page_url: window.location.pathname + window.location.search,
    })
    ElMessage.success({
      message: '反馈已送达，谢谢 ❤ 我会看到的',
      duration: 2500,
    })
    open.value = false
    // 清空但保留 category（常用）
    form.content = ''
    form.contact = ''
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提交失败，请稍后再试')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.fb-trigger {
  position: fixed;
  right: 26px;
  bottom: 26px;
  z-index: 2000;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 11px 18px 11px 15px;
  border-radius: 999px;
  border: 1px solid rgba(198, 172, 87, 0.55);
  background: linear-gradient(135deg, #c6ac57, #d4bd6b);
  color: #0a0a0a;
  font-size: 12.5px;
  font-weight: 700;
  letter-spacing: 0.04em;
  font-family: var(--font-body);
  cursor: pointer;
  box-shadow:
    0 6px 20px rgba(198, 172, 87, 0.32),
    inset 0 1px 0 rgba(255, 255, 255, 0.35);
  transition: transform 0.2s var(--ease-spring), box-shadow 0.2s, background 0.2s;
  animation:
    slideInR 520ms var(--ease-spring) both,
    breathe-soft 3.6s ease-in-out 1s infinite;
}
.fb-trigger::before {
  content: '';
  position: absolute;
  inset: -6px;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(198, 172, 87, 0.35), transparent 70%);
  opacity: 0;
  transition: opacity 0.3s;
  pointer-events: none;
  z-index: -1;
}
.fb-trigger:hover {
  transform: translateY(-2px) scale(1.04);
  background: linear-gradient(135deg, #d4bd6b, #e0cc85);
  box-shadow:
    0 12px 32px rgba(198, 172, 87, 0.55),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
}
.fb-trigger:hover::before {
  opacity: 1;
}
.fb-trigger:active {
  transform: translateY(0) scale(0.98);
}
.fb-trigger--collapsed .fb-trigger-label {
  display: none;
}
.fb-trigger--collapsed {
  padding: 10px;
}

.fb-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.fb-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.fb-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-700);
}
.fb-required {
  color: var(--signal-coral);
  margin-left: 2px;
}
.fb-hint {
  font-weight: 400;
  color: var(--ink-300);
  font-size: 11px;
}
.fb-notice {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 10px;
  background: rgba(198, 172, 87, 0.08);
  border: 1px solid rgba(198, 172, 87, 0.3);
  border-radius: 6px;
  font-size: 11.5px;
  color: #8a7438;
  line-height: 1.5;
}
.fb-notice .el-icon {
  flex-shrink: 0;
  margin-top: 2px;
}
</style>
