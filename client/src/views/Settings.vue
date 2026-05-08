<template>
  <div class="settings-page">
    <div class="sp-grid" aria-hidden="true" />

    <!-- Masthead -->
    <div class="sp-masthead">
      <div class="sp-masthead__left">
        <button class="sp-back" @click="router.push('/dashboard')">← BACK</button>
        <div class="sp-masthead__brand">SCHOLARPILOT</div>
      </div>
      <div class="sp-masthead__center">§ SETTINGS · 系统偏好</div>
      <div class="sp-masthead__right">
        <span class="sp-status"><span class="sp-status__dot" />{{ activeCount }} ACTIVE</span>
        <span class="sp-status__sep">·</span>
        <span>自动保存</span>
      </div>
    </div>

    <!-- Body: 左目录 + 右内容 -->
    <div class="sp-body">
      <!-- Left nav -->
      <nav class="sp-nav">
        <div class="sp-nav__label">— CONTENTS —</div>
        <button
          v-for="it in NAV_ITEMS"
          :key="it.id"
          class="sp-nav__item"
          :class="{ 'is-on': activeSection === it.id }"
          @click="activeSection = it.id"
        >
          <span class="sp-nav__num">{{ it.num }}</span>
          <span>
            <span class="sp-nav__title">{{ it.label }}</span>
            <span class="sp-nav__sub">{{ it.sub }}</span>
          </span>
        </button>
      </nav>

      <!-- Right content -->
      <div class="sp-content">
        <!-- ─────────── §01 LLM ─────────── -->
        <div v-if="activeSection === 'llm'">
          <div class="sp-header">
            <div class="sp-header__eyebrow">— LLM · API 配置 —</div>
            <div class="sp-header__title-row">
              <span class="sp-header__num">§01</span>
              <h1 class="sp-header__title">模型来源 &amp; 密钥<span class="sp-accent-dot">.</span></h1>
            </div>
            <div class="sp-header__sub">—— 为 ScholarPilot 接入你自己的大模型账号。Key 仅存于服务端配置，不会回传浏览器。</div>
          </div>

          <div class="sp-bar">
            <span>共 {{ providers.length }} 个来源 · {{ activeCount }} 个已配置</span>
            <span>当前激活：<b>{{ activeProviderLabel || '—' }}</b></span>
          </div>

          <div v-if="loading" class="sp-loading">
            <el-skeleton :rows="3" animated />
          </div>
          <div v-else-if="providers.length === 0" class="sp-empty">
            <div class="sp-empty__sub">后端暂无可用 provider</div>
          </div>
          <div v-else>
            <div
              v-for="(p, i) in providers"
              :key="p.provider_id"
              class="sp-acc"
              :class="{ 'is-open': openProvider === p.provider_id }"
              :style="{ animationDelay: `${0.1 + i * 0.04}s` }"
            >
              <button class="sp-acc__head" @click="toggleProvider(p.provider_id)">
                <div class="sp-acc__stripe" :style="{ background: p.configured ? providerBrand(p.provider_id) : 'rgba(20,20,20,.15)' }" />
                <div class="sp-acc__glyph" :style="{ background: `${providerBrand(p.provider_id)}14`, borderColor: providerBrand(p.provider_id), color: providerBrand(p.provider_id) }">
                  {{ (p.display_name || p.provider_id).charAt(0).toUpperCase() }}
                </div>
                <div class="sp-acc__body">
                  <div class="sp-acc__name">
                    {{ p.display_name || p.provider_id }}
                    <span v-if="p.provider_id === activeProvider" class="sp-acc__badge">ACTIVE</span>
                  </div>
                  <div class="sp-acc__meta">
                    <span v-if="p.configured">{{ p.model || '未指定模型' }}</span>
                    <span v-else class="sp-acc__meta-dim">— 未配置 —</span>
                    <template v-if="p.max_tokens">
                      <span class="sp-acc__meta-sep">·</span>
                      <span>{{ p.max_tokens.toLocaleString() }} tokens</span>
                    </template>
                  </div>
                </div>
                <div class="sp-acc__status" :style="{ color: statusColor(p) }">
                  <span class="sp-acc__status-dot" :style="{ background: statusColor(p) }">
                    <span v-if="testing === p.provider_id" class="sp-acc__status-pulse" :style="{ background: statusColor(p) }" />
                  </span>
                  {{ statusLabel(p) }}
                </div>
                <div class="sp-acc__chev" :class="{ 'is-open': openProvider === p.provider_id }">›</div>
              </button>

              <div v-if="openProvider === p.provider_id" class="sp-acc__panel">
                <div class="sp-acc__divider" />
                <div class="sp-fields">
                  <div class="sp-field sp-field--full">
                    <div class="sp-field__label">模型名称</div>
                    <input
                      v-model="editForm.model"
                      class="sp-input sp-input--mono"
                      :placeholder="p.provider_id === 'ollama' ? 'qwen2.5:7b' : 'gpt-4o / claude-sonnet-4-5 / ...'"
                    />
                  </div>
                  <div class="sp-field">
                    <div class="sp-field__label">BASE URL · 自定义代理</div>
                    <input
                      v-model="editForm.base_url"
                      class="sp-input sp-input--mono"
                      placeholder="留空 = 官方端点"
                    />
                  </div>
                  <div class="sp-field">
                    <div class="sp-field__label">MAX TOKENS</div>
                    <input
                      v-model.number="editForm.max_tokens"
                      type="number"
                      min="256"
                      max="65536"
                      step="256"
                      class="sp-input sp-input--mono"
                    />
                    <div class="sp-hint">单次回复生成上限，不是上下文窗口。deepseek-chat 最大 8192，deepseek-reasoner 最大 65536，超出会被后端自动下调。</div>
                  </div>
                  <div class="sp-field sp-field--full">
                    <div class="sp-field__label">API KEY</div>
                    <div class="sp-keyinput">
                      <input
                        :type="revealKey ? 'text' : 'password'"
                        v-model="editForm.api_key"
                        class="sp-keyinput__input"
                        :placeholder="p.provider_id === 'ollama' ? 'Ollama 无需 key' : 'sk-...'"
                      />
                      <button
                        class="sp-keyinput__eye"
                        type="button"
                        @click="revealKey = !revealKey"
                      >
                        {{ revealKey ? '隐藏' : '显示' }}
                      </button>
                    </div>
                    <div class="sp-hint">Key 以密文保存在后端配置；此输入框只用作"更新"，不显示已有值</div>
                  </div>
                </div>
                <div class="sp-acc__actions">
                  <button
                    class="sp-btn sp-btn--ghost"
                    :disabled="saving === p.provider_id"
                    @click="onTest(p.provider_id)"
                  >
                    <span v-if="testing === p.provider_id">· · ·</span>
                    <span v-else>测试连接</span>
                  </button>
                  <button
                    class="sp-btn sp-btn--primary"
                    :disabled="saving === p.provider_id"
                    @click="onSave(p.provider_id)"
                  >
                    <span v-if="saving === p.provider_id">保存中…</span>
                    <span v-else>保存配置</span>
                  </button>
                  <button
                    v-if="p.configured && p.provider_id !== activeProvider"
                    class="sp-btn sp-btn--ghost"
                    @click="onSwitch(p.provider_id)"
                  >
                    切为当前
                  </button>
                  <div class="sp-acc__actions-spacer" />
                  <button
                    v-if="p.configured"
                    class="sp-btn sp-btn--danger"
                    @click="onDelete(p.provider_id)"
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div class="sp-note">
            <div class="sp-note__eyebrow">§ NOTE</div>
            <div class="sp-note__body">
              「自建端点」适用于任何实现了 OpenAI Chat Completions 协议的服务 —— 包括 vLLM、Ollama、LiteLLM、OneAPI、Cloudflare AI Gateway 等代理。
            </div>
          </div>
        </div>

        <!-- ─────────── §02 BYOK · 我的 API Key (M3) ─────────── -->
        <div v-else-if="activeSection === 'byok'">
          <div class="sp-header">
            <div class="sp-header__eyebrow">— BYOK · 自带 API Key —</div>
            <div class="sp-header__title-row">
              <span class="sp-header__num">§02</span>
              <h1 class="sp-header__title">用我自己的 LLM<span class="sp-accent-dot">.</span></h1>
            </div>
            <div class="sp-header__sub">—— 配置后所有走 backend 的 LLM 调用（对话 / deep dive 等）都用您填的 Key 调；Key 仅 per-request 临时使用，不存储。</div>
          </div>

          <div class="sp-bar">
            <span v-if="byokIsActive && byokConfig">🟢 已启用 · {{ byokProviderLabel }} · {{ byokConfig.model || '默认 model' }}</span>
            <span v-else-if="byokConfig && !byokIsActive">⚪ 已配置但未启用（当前用 ScholarPilot 默认 LLM）</span>
            <span v-else>⚫ 未配置 · 当前用 ScholarPilot 默认 LLM</span>
            <span v-if="byokConfig" style="display:flex; gap:8px;">
              <el-button size="small" @click="toggleByokActive">{{ byokIsActive ? '禁用' : '启用' }}</el-button>
              <el-button size="small" type="danger" plain @click="clearByok">清除</el-button>
            </span>
          </div>

          <el-form label-width="100px" style="margin-top: 16px;">
            <el-form-item label="Provider">
              <el-select v-model="byokForm.provider" style="width: 280px;">
                <el-option label="OpenAI" value="openai" />
                <el-option label="Anthropic" value="anthropic" />
                <el-option label="DeepSeek" value="deepseek" />
                <el-option label="Moonshot" value="moonshot" />
                <el-option label="自定义（OpenAI 兼容）" value="custom" />
              </el-select>
            </el-form-item>
            <el-form-item label="API Key">
              <el-input
                v-model="byokForm.api_key"
                :type="byokShowKey ? 'text' : 'password'"
                placeholder="sk-..."
                style="max-width: 480px;"
              >
                <template #append>
                  <el-button @click="byokShowKey = !byokShowKey">{{ byokShowKey ? '隐藏' : '显示' }}</el-button>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item label="Model">
              <el-input v-model="byokForm.model" :placeholder="byokModelHint" style="max-width: 480px;" />
            </el-form-item>
            <el-form-item label="Base URL">
              <el-input v-model="byokForm.base_url" placeholder="可选 · 自定义中转地址" style="max-width: 480px;" />
            </el-form-item>
          </el-form>

          <div class="sp-note">
            <div class="sp-note__eyebrow">§ 隐私说明</div>
            <div class="sp-note__body">
              ⚠️ 您的 API Key 会随每个请求经过 ScholarPilot 服务器代为调用 LLM。本平台承诺不存储、不记录 Key（仅 per-request 临时使用）。<br/>
              ⓘ 检索流程的 LLM 调用（QueryPlan / Scoring / Summary）由 Celery worker 跑，**不**用 BYOK，永远走 ScholarPilot 默认。
            </div>
          </div>

          <div v-if="byokTestResult" :style="{
            margin: '12px 0', padding: '8px 12px', borderRadius: '6px', fontSize: '13px',
            background: byokTestResult.ok ? '#f0f9eb' : '#fef0f0',
            color: byokTestResult.ok ? '#67c23a' : '#f56c6c',
          }">
            {{ byokTestResult.message }}
          </div>

          <div style="display: flex; gap: 8px; margin-top: 12px;">
            <el-button :loading="byokTesting" @click="testByok">测试连接</el-button>
            <el-button type="primary" :loading="byokSaving" @click="saveByok">保存并启用</el-button>
          </div>
        </div>

        <!-- ─────────── §03 Params ─────────── -->
        <div v-else-if="activeSection === 'params'">
          <div class="sp-header">
            <div class="sp-header__eyebrow">— GENERATION · 生成参数 —</div>
            <div class="sp-header__title-row">
              <span class="sp-header__num">§03</span>
              <h1 class="sp-header__title">采样与长度<span class="sp-accent-dot">.</span></h1>
            </div>
            <div class="sp-header__sub">—— 这些是浏览器本地偏好，仅作用于临时对话提示；最终调用参数由后端任务上下文决定。</div>
          </div>

          <div class="sp-slider-list">
            <div class="sp-slider">
              <div class="sp-slider__head">
                <span class="sp-slider__name">Temperature <em>· 随机度</em></span>
                <span class="sp-slider__val">{{ localParams.temperature.toFixed(2) }}</span>
              </div>
              <input
                type="range"
                min="0"
                max="2"
                step="0.05"
                v-model.number="localParams.temperature"
                class="sp-range"
              />
              <div class="sp-slider__hint">
                — {{ localParams.temperature < 0.3 ? '确定性输出 · 适合检索与事实问答'
                   : localParams.temperature < 0.9 ? '均衡 · 科研场景推荐'
                   : '发散 · 适合头脑风暴' }}
              </div>
            </div>
            <div class="sp-slider">
              <div class="sp-slider__head">
                <span class="sp-slider__name">Top-P <em>· 核采样</em></span>
                <span class="sp-slider__val">{{ localParams.top_p.toFixed(2) }}</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                v-model.number="localParams.top_p"
                class="sp-range"
              />
              <div class="sp-slider__hint">— 与 temperature 二选一微调即可</div>
            </div>
            <div class="sp-slider">
              <div class="sp-slider__head">
                <span class="sp-slider__name">Max Tokens <em>· 单次上限</em></span>
                <span class="sp-slider__val">{{ localParams.max_tokens.toLocaleString() }}</span>
              </div>
              <input
                type="range"
                min="256"
                max="32768"
                step="256"
                v-model.number="localParams.max_tokens"
                class="sp-range"
              />
              <div class="sp-slider__hint">— 过大可能提高费用与延迟 · 长文综述建议 8k+</div>
            </div>
          </div>
        </div>

        <!-- ─────────── §04 About ─────────── -->
        <div v-else-if="activeSection === 'about'">
          <div class="sp-header">
            <div class="sp-header__eyebrow">— COLOPHON · 关于 —</div>
            <div class="sp-header__title-row">
              <span class="sp-header__num">§04</span>
              <h1 class="sp-header__title">ScholarPilot<span class="sp-accent-dot">.</span></h1>
            </div>
            <div class="sp-header__sub">Vol. II · Issue {{ issueNumber }} · {{ monthName }} {{ currentYear }}</div>
          </div>

          <div class="sp-about">
            让科研人员把时间花在
            <em class="sp-about__em">思考</em>
            上，而不是在文献的海洋里捞针。
          </div>

          <div class="sp-about__foot">
            <div>
              <div class="sp-about__dim">VERSION</div>
              3.0.0-dev
            </div>
            <div>
              <div class="sp-about__dim">BUILD</div>
              {{ currentYear }}.{{ issueNumber }}
            </div>
            <div>
              <div class="sp-about__dim">ISSN</div>
              {{ currentYear }}-{{ issueNumber }}{{ String(new Date().getDate()).padStart(2, '0') }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useToast } from '../composables/useToast'
import api, { llmApi } from '../api/client'
import {
  saveByokConfig, loadByokConfig, clearByokConfig,
  getByokActive, setByokActive,
  type ByokConfig, type ByokProvider,
} from '../api/byok_config'
import axios from 'axios'
import { DEFAULT_BASE_URLS } from '@/data/llm/types'
import { llmManager } from '@/data/llm/manager'

type Section = 'llm' | 'byok' | 'params' | 'about'
type Provider = {
  provider_id: string
  display_name?: string
  description?: string
  configured?: boolean
  model?: string
  max_tokens?: number
}

const router = useRouter()
const toast = useToast()

const NAV_ITEMS: { id: Section; num: string; label: string; sub: string }[] = [
  { id: 'llm', num: '01', label: 'LLM · API 配置', sub: '云端模型来源与密钥' },
  { id: 'byok', num: '02', label: 'BYOK · 我的 Key', sub: '自带 API Key 透传' },
  { id: 'params', num: '03', label: '生成参数', sub: 'temperature / tokens · 本地偏好' },
  { id: 'about', num: '04', label: '关于', sub: '版本 · ISSN' },
]

const PROVIDER_BRANDS: Record<string, string> = {
  ollama: '#475569',
  openai: '#10a37f',
  anthropic: '#d97757',
  gemini: '#4285f4',
  deepseek: '#4d6bfe',
  qwen: '#605bec',
  kimi: '#1a1a1a',
  moonshot: '#1a1a1a',
  jiekou: '#0d9488',
}
function providerBrand(id: string): string {
  return PROVIDER_BRANDS[id] || '#64748b'
}

const activeSection = ref<Section>('llm')
const providers = ref<Provider[]>([])
const activeProvider = ref<string>('')
const loading = ref(true)

const openProvider = ref<string | null>(null)
const revealKey = ref(false)
const testing = ref<string | null>(null)
const saving = ref<string | null>(null)

const editForm = reactive({
  model: '',
  base_url: '',
  api_key: '',
  max_tokens: 4096,
})

// Params (本地偏好，localStorage 持久化)
const PARAMS_KEY = 'sp_llm_params_v1'
const localParams = reactive(
  JSON.parse(
    localStorage.getItem(PARAMS_KEY) || JSON.stringify({ temperature: 0.3, top_p: 1.0, max_tokens: 4096 })
  )
)
function saveLocalParams() {
  localStorage.setItem(PARAMS_KEY, JSON.stringify(localParams))
}

// 简易响应：当 localParams 变化时写入 storage
import { watch } from 'vue'
watch(localParams, saveLocalParams, { deep: true })

// ── Stats ──
const activeCount = computed(() => providers.value.filter((p) => p.configured).length)
const activeProviderLabel = computed(() => {
  const p = providers.value.find((x) => x.provider_id === activeProvider.value)
  return p?.display_name ?? activeProvider.value
})

// ── Issue label ──
const now = new Date()
const MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
const currentYear = now.getFullYear()
const monthName = MONTH_NAMES[now.getMonth()]
const issueNumber = String(now.getMonth() + 1).padStart(2, '0')

// ── Status helpers ──
function statusLabel(p: Provider): string {
  if (testing.value === p.provider_id) return '测试中'
  if (p.provider_id === activeProvider.value) return '已激活'
  if (p.configured) return '已配置'
  return '未配置'
}
function statusColor(p: Provider): string {
  if (testing.value === p.provider_id) return 'var(--signal-amber)'
  if (p.provider_id === activeProvider.value) return 'var(--signal-teal)'
  if (p.configured) return 'var(--signal-emerald)'
  return 'rgba(20, 20, 20, 0.35)'
}

// ── API actions ──
async function loadProviders() {
  loading.value = true
  try {
    const res = await llmApi.listProviders()
    providers.value = res.data.providers ?? []
    activeProvider.value = res.data.active ?? ''
  } catch (e: any) {
    toast.error(e.response?.data?.detail || 'Providers 加载失败')
  } finally {
    loading.value = false
  }
}

function toggleProvider(id: string) {
  if (openProvider.value === id) {
    openProvider.value = null
    return
  }
  openProvider.value = id
  // Prefill editForm with the provider's current settings
  const p = providers.value.find((x) => x.provider_id === id)
  editForm.model = p?.model || ''
  editForm.base_url = ''
  editForm.api_key = ''
  editForm.max_tokens = p?.max_tokens || 4096
  revealKey.value = false
}

async function onSave(id: string) {
  if (!editForm.model) {
    toast.warning('请填写模型名称')
    return
  }
  saving.value = id
  try {
    const res = await llmApi.configureProvider({
      provider_id: id,
      model: editForm.model,
      base_url: editForm.base_url,
      api_key: editForm.api_key,
      max_tokens: editForm.max_tokens,
    })
    await loadProviders()

    // 后端可能对 max_tokens 做了 clamp，把实际生效值回填到输入框，避免 UI 与服务端状态脱节
    const warnings: string[] = res.data?.warnings ?? []
    const actualMaxTokens: number | undefined = res.data?.max_tokens
    if (typeof actualMaxTokens === 'number' && actualMaxTokens !== editForm.max_tokens) {
      editForm.max_tokens = actualMaxTokens
    }
    if (warnings.length > 0) {
      warnings.forEach((w) => toast.warning(w))
    } else {
      toast.success('配置已保存')
    }
    editForm.api_key = ''
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = null
  }
}

async function onTest(id: string) {
  testing.value = id
  try {
    // 切到 provider 再测试
    if (id !== activeProvider.value) {
      await llmApi.switchProvider(id)
      activeProvider.value = id
    }
    const res = await llmApi.testProvider()
    const preview = String(res.data?.response ?? '').slice(0, 60)
    toast.success(`测试成功${preview ? ': ' + preview : ''}`)
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '测试失败')
  } finally {
    testing.value = null
  }
}

async function onSwitch(id: string) {
  try {
    await llmApi.switchProvider(id)
    activeProvider.value = id
    const p = providers.value.find((x) => x.provider_id === id)
    toast.success(`已切换到 ${p?.display_name ?? id}`)
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '切换失败')
  }
}

async function onDelete(id: string) {
  const p = providers.value.find((x) => x.provider_id === id)
  try {
    await ElMessageBox.confirm(`确认删除 ${p?.display_name ?? id} 的配置？`, '提示', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await llmApi.deleteProvider(id)
    await loadProviders()
    toast.success('已删除')
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(loadProviders)

// ────────────────── M3 BYOK state + handlers ──────────────────
const byokIsActive = ref(false)
const byokConfig = ref<ByokConfig | null>(null)
const byokShowKey = ref(false)
const byokForm = reactive({
  provider: 'openai' as ByokProvider,
  api_key: '',
  model: '',
  base_url: '',
})
const byokTesting = ref(false)
const byokTestResult = ref<{ ok: boolean; message: string } | null>(null)
const byokSaving = ref(false)

const byokModelHint = computed(() => ({
  openai: 'gpt-4o',
  anthropic: 'claude-3-5-sonnet-20241022',
  deepseek: 'deepseek-chat',
  moonshot: 'moonshot-v1-8k',
  custom: '由 base_url 决定',
}[byokForm.provider]))

const byokProviderLabel = computed(() => {
  if (!byokConfig.value) return '—'
  const m: Record<ByokProvider, string> = {
    openai: 'OpenAI', anthropic: 'Anthropic', deepseek: 'DeepSeek',
    moonshot: 'Moonshot', custom: '自定义',
  }
  return m[byokConfig.value.provider]
})

async function loadByokState() {
  byokIsActive.value = await getByokActive()
  byokConfig.value = await loadByokConfig()
  if (byokConfig.value) {
    byokForm.provider = byokConfig.value.provider
    byokForm.api_key = byokConfig.value.api_key
    byokForm.model = byokConfig.value.model || ''
    byokForm.base_url = byokConfig.value.base_url || ''
  }
}

function _byokHumanError(code: string | null): string {
  switch (code) {
    case 'provider_init_failed': return '配置无效（model 名错误？base_url 错误？）'
    case 'llm_call_failed': return 'LLM 调用失败（key 无效 / 网络 / 限速）'
    case 'llm_returned_none': return 'LLM 返回为空'
    default: return code || '未知错误'
  }
}

async function testByok() {
  if (!byokForm.api_key) {
    toast.warning('请先填 API Key')
    return
  }
  byokTesting.value = true
  byokTestResult.value = null
  const start = performance.now()
  try {
    const baseUrl = (byokForm.base_url
      || DEFAULT_BASE_URLS[byokForm.provider]
      || ''
    ).replace(/\/+$/, '')
    if (!baseUrl) throw new Error('base_url 缺失（自定义 provider 必须填）')

    let response
    if (byokForm.provider === 'anthropic') {
      response = await axios.post(
        `${baseUrl}/v1/messages`,
        {
          model: byokForm.model || 'claude-haiku-4-5-20251001',
          max_tokens: 16,
          messages: [{ role: 'user', content: 'Hi' }],
          temperature: 0,
        },
        {
          headers: {
            'x-api-key': byokForm.api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
          },
          timeout: 20_000,
          validateStatus: () => true,
        },
      )
    } else {
      response = await axios.post(
        `${baseUrl}/chat/completions`,
        {
          model: byokForm.model || 'gpt-4o-mini',
          messages: [{ role: 'user', content: 'Hi' }],
          temperature: 0,
          max_tokens: 16,
        },
        {
          headers: {
            'Authorization': `Bearer ${byokForm.api_key}`,
            'Content-Type': 'application/json',
          },
          timeout: 20_000,
          validateStatus: () => true,
        },
      )
    }

    const latency = Math.round(performance.now() - start)
    if (response.status >= 200 && response.status < 300) {
      const data = response.data ?? {}
      let sample = ''
      if (byokForm.provider === 'anthropic') {
        for (const block of data.content ?? []) {
          if (block.type === 'text') { sample = String(block.text ?? ''); break }
        }
      } else {
        sample = String(data.choices?.[0]?.message?.content ?? '')
      }
      byokTestResult.value = {
        ok: true,
        message: `✓ 测试通过（${latency}ms）："${sample.slice(0, 80)}"`,
      }
    } else {
      const errBody = response.data
      const detail = typeof errBody === 'string'
        ? errBody.slice(0, 400)
        : JSON.stringify(errBody?.error ?? errBody ?? {}).slice(0, 400)
      byokTestResult.value = {
        ok: false,
        message: `✗ 测试失败 HTTP ${response.status}：${detail}`,
      }
    }
  } catch (err) {
    const e = err as any
    const status = e?.response?.status
    const body = e?.response?.data
    const bodyStr = body
      ? (typeof body === 'string' ? body.slice(0, 400) : JSON.stringify(body).slice(0, 400))
      : ''
    const msg = status
      ? `HTTP ${status} ${bodyStr}`
      : (e?.code ? `${e.code} ${e.message}` : (e?.message || String(err)))
    byokTestResult.value = { ok: false, message: `✗ 调用错误：${msg}` }
  } finally {
    byokTesting.value = false
  }
}

async function saveByok() {
  if (!byokForm.api_key) {
    toast.warning('请先填 API Key')
    return
  }
  byokSaving.value = true
  try {
    await saveByokConfig({
      provider: byokForm.provider,
      api_key: byokForm.api_key,
      model: byokForm.model || null,
      base_url: byokForm.base_url || null,
      configured_at: Date.now(),
    })
    await llmManager.reload()
    toast.success('BYOK 配置已保存并启用')
    await loadByokState()
  } catch (err) {
    toast.error('保存失败：' + (err as Error).message)
  } finally {
    byokSaving.value = false
  }
}

async function toggleByokActive() {
  await setByokActive(!byokIsActive.value)
  byokIsActive.value = !byokIsActive.value
  await llmManager.reload()
  toast.success(byokIsActive.value ? 'BYOK 已启用' : 'BYOK 已暂停（配置保留）')
}

async function clearByok() {
  try {
    await ElMessageBox.confirm(
      '确认清除 BYOK 配置？API Key 将从 keychain 删除。',
      '清除 BYOK',
      { type: 'warning', confirmButtonText: '清除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await clearByokConfig()
  await llmManager.reload()
  byokConfig.value = null
  byokIsActive.value = false
  byokForm.provider = 'openai'
  byokForm.api_key = ''
  byokForm.model = ''
  byokForm.base_url = ''
  toast.success('已清除 BYOK 配置')
}

onMounted(loadByokState)
</script>

<style scoped>
.settings-page {
  position: relative;
  min-height: 100vh;
  background: var(--paper-warm);
  color: var(--ink-950);
  font-family: var(--font-body);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.sp-grid {
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(120, 100, 80, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120, 100, 80, 0.04) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
}

/* ── Masthead ── */
.sp-masthead {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 48px;
  border-bottom: 1px solid rgba(20, 20, 20, 0.14);
  background: var(--paper-warm);
  z-index: 2;
  animation: sp-mod-in 0.5s var(--ease-out) both;
}
.sp-masthead__left,
.sp-masthead__right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.sp-masthead__brand {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 900;
  letter-spacing: 0.05em;
}
.sp-masthead__center {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.5);
  letter-spacing: 0.2em;
}
.sp-back {
  background: transparent;
  border: 1px solid rgba(20, 20, 20, 0.2);
  padding: 7px 14px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--ink-950);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.sp-back:hover {
  background: var(--ink-950);
  color: var(--paper-warm);
}
.sp-status {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.15em;
  color: var(--signal-teal);
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.sp-status__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--signal-teal);
}
.sp-status__sep {
  color: rgba(20, 20, 20, 0.3);
  font-family: var(--font-mono);
  font-size: 10px;
}

/* ── Body ── */
.sp-body {
  flex: 1;
  display: grid;
  grid-template-columns: 260px 1fr;
  overflow: hidden;
  position: relative;
  z-index: 1;
}

/* ── Left nav ── */
.sp-nav {
  border-right: 1px solid rgba(20, 20, 20, 0.12);
  padding: 40px 0 40px 48px;
  overflow: auto;
  background: var(--paper-warm);
  animation: sp-mod-in 0.5s 0.1s var(--ease-out) both;
}
.sp-nav__label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.35em;
  color: var(--signal-teal);
  margin-bottom: 18px;
  padding-right: 24px;
}
.sp-nav__item {
  width: 100%;
  text-align: left;
  padding: 14px 24px 14px 0;
  background: transparent;
  border: none;
  cursor: pointer;
  border-bottom: 1px solid rgba(20, 20, 20, 0.08);
  position: relative;
  display: grid;
  grid-template-columns: 30px 1fr;
  gap: 14px;
  align-items: baseline;
  color: rgba(20, 20, 20, 0.65);
  font-family: inherit;
  transition: color var(--duration-fast) var(--ease-out);
}
.sp-nav__item.is-on { color: var(--ink-950); }
.sp-nav__item:hover { color: var(--ink-900); }
.sp-nav__item.is-on::after {
  content: '';
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: #c6ac57;
  animation: sp-accent-bar 0.25s var(--ease-out) both;
}
.sp-nav__num {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  color: rgba(20, 20, 20, 0.35);
  transition: color var(--duration-fast) var(--ease-out);
}
.sp-nav__item.is-on .sp-nav__num { color: #c6ac57; }
.sp-nav__title {
  display: block;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.2px;
  margin-bottom: 2px;
}
.sp-nav__item.is-on .sp-nav__title { font-weight: 900; }
.sp-nav__sub {
  display: block;
  font-size: 11px;
  color: rgba(20, 20, 20, 0.5);
  font-style: italic;
  font-family: var(--font-display);
}

/* ── Right content ── */
.sp-content {
  overflow: auto;
  padding: 40px 56px 60px;
  position: relative;
}

/* ── Section header ── */
.sp-header {
  margin-bottom: 28px;
  animation: sp-mod-in 0.5s 0.15s var(--ease-out) both;
}
.sp-header__eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.4em;
  color: var(--signal-teal);
  margin-bottom: 10px;
}
.sp-header__title-row {
  display: flex;
  align-items: baseline;
  gap: 14px;
}
.sp-header__num {
  font-family: var(--font-mono);
  font-size: 13px;
  color: rgba(20, 20, 20, 0.4);
  letter-spacing: 0.1em;
}
.sp-header__title {
  font-family: var(--font-display);
  font-size: 48px;
  font-weight: 900;
  letter-spacing: -1px;
  line-height: 1;
  margin: 0;
  color: var(--ink-950);
}
.sp-accent-dot { color: #c6ac57; }
.sp-header__sub {
  font-family: var(--font-display);
  font-size: 14px;
  font-style: italic;
  color: rgba(20, 20, 20, 0.55);
  margin-top: 8px;
}

.sp-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 0;
  border-top: 1px solid rgba(20, 20, 20, 0.15);
  border-bottom: 1px solid rgba(20, 20, 20, 0.15);
  margin-bottom: 20px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.15em;
  color: rgba(20, 20, 20, 0.55);
}
.sp-bar b { color: var(--signal-teal); font-weight: 700; }

/* ── Accordion ── */
.sp-acc {
  background: var(--paper);
  border: 1px solid rgba(20, 20, 20, 0.12);
  border-bottom: none;
  animation: sp-mod-in 0.4s var(--ease-spring) both;
}
.sp-acc:last-of-type { border-bottom: 1px solid rgba(20, 20, 20, 0.12); }
.sp-acc.is-open {
  border-bottom: 1px solid rgba(20, 20, 20, 0.12);
  margin-bottom: 12px;
  box-shadow: 0 10px 30px -18px rgba(20, 20, 20, 0.25);
}

.sp-acc__head {
  width: 100%;
  background: transparent;
  border: none;
  cursor: pointer;
  display: grid;
  grid-template-columns: 6px 48px 1fr auto auto;
  gap: 18px;
  align-items: center;
  padding: 16px 20px 16px 0;
  text-align: left;
  font-family: inherit;
}
.sp-acc__stripe {
  width: 6px;
  height: 48px;
  transition: background var(--duration-fast) var(--ease-out);
}
.sp-acc__glyph {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  border: 1.5px solid;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 900;
  letter-spacing: -0.5px;
}
.sp-acc__body { min-width: 0; }
.sp-acc__name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.2px;
  color: var(--ink-950);
}
.sp-acc__badge {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.2em;
  padding: 2px 7px;
  background: var(--signal-teal);
  color: #fff;
  font-weight: 700;
}
.sp-acc__meta {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: rgba(20, 20, 20, 0.5);
  margin-top: 4px;
  letter-spacing: 0.05em;
}
.sp-acc__meta-sep { color: rgba(20, 20, 20, 0.3); margin: 0 10px; }
.sp-acc__meta-dim { color: rgba(20, 20, 20, 0.4); }
.sp-acc__status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.15em;
  min-width: 88px;
  text-transform: uppercase;
}
.sp-acc__status-dot {
  position: relative;
  width: 8px;
  height: 8px;
  border-radius: 4px;
}
.sp-acc__status-pulse {
  position: absolute;
  inset: 0;
  border-radius: 4px;
  animation: sp-ping 1.2s ease-out infinite;
}
.sp-acc__chev {
  font-family: var(--font-mono);
  font-size: 18px;
  color: rgba(20, 20, 20, 0.4);
  transition: transform var(--duration-fast) var(--ease-out);
  padding-right: 20px;
}
.sp-acc__chev.is-open { transform: rotate(90deg); }

/* Accordion panel */
.sp-acc__panel {
  padding: 4px 28px 24px 72px;
  overflow: hidden;
  animation: sp-accordion 0.3s var(--ease-out) both;
}
.sp-acc__divider {
  border-top: 1px dashed rgba(20, 20, 20, 0.15);
  padding-top: 18px;
}
.sp-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px 28px;
}
.sp-field--full { grid-column: 1 / -1; }
.sp-field__label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.25em;
  color: rgba(20, 20, 20, 0.55);
  margin-bottom: 8px;
}
.sp-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid rgba(20, 20, 20, 0.18);
  background: var(--paper-warm);
  outline: none;
  font-family: inherit;
  font-size: 13px;
  color: var(--ink-950);
  box-sizing: border-box;
  transition: border-color var(--duration-fast) var(--ease-out);
}
.sp-input:focus { border-color: var(--ink-950); }
.sp-input--mono {
  font-family: var(--font-mono);
  font-size: 12px;
}

.sp-keyinput {
  display: flex;
  align-items: center;
  border: 1px solid rgba(20, 20, 20, 0.18);
  background: var(--paper-warm);
  padding: 0 12px;
}
.sp-keyinput__input {
  flex: 1;
  padding: 10px 0;
  background: transparent;
  border: none;
  outline: none;
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--ink-950);
  letter-spacing: 0.02em;
}
.sp-keyinput__eye {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 4px 8px;
  color: rgba(20, 20, 20, 0.5);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.15em;
}
.sp-keyinput__eye:hover { color: var(--ink-950); }

.sp-hint {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.45);
  margin-top: 7px;
  letter-spacing: 0.04em;
  line-height: 1.5;
}

.sp-acc__actions {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px dashed rgba(20, 20, 20, 0.12);
}
.sp-acc__actions-spacer { flex: 1; }

/* ── Buttons ── */
.sp-btn {
  padding: 10px 18px;
  border: 1px solid;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.2em;
  cursor: pointer;
  font-weight: 700;
  white-space: nowrap;
  transition: all var(--duration-fast) var(--ease-out);
}
.sp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.sp-btn--primary {
  background: var(--ink-950);
  color: var(--paper-warm);
  border-color: var(--ink-950);
}
.sp-btn--primary:hover:not(:disabled) { background: var(--ink-800); }
.sp-btn--ghost {
  background: transparent;
  color: var(--ink-950);
  border-color: rgba(20, 20, 20, 0.25);
}
.sp-btn--ghost:hover:not(:disabled) {
  background: var(--ink-950);
  color: var(--paper-warm);
}
.sp-btn--danger {
  background: transparent;
  color: var(--signal-coral);
  border-color: var(--signal-coral);
}
.sp-btn--danger:hover:not(:disabled) {
  background: var(--signal-coral);
  color: #fff;
}

/* ── Loading & empty ── */
.sp-loading {
  padding: 24px;
  background: var(--paper);
  border: 1px solid rgba(20, 20, 20, 0.1);
}
.sp-empty {
  padding: 40px 24px;
  background: var(--paper);
  border: 1px dashed rgba(20, 20, 20, 0.2);
  text-align: center;
}
.sp-empty__sub {
  font-family: var(--font-display);
  font-style: italic;
  color: rgba(20, 20, 20, 0.55);
}

/* ── Note box ── */
.sp-note {
  margin-top: 32px;
  padding: 18px 22px;
  background: var(--paper);
  border: 1px dashed rgba(20, 20, 20, 0.18);
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.sp-note__eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  color: #c6ac57;
  letter-spacing: 0.2em;
  margin-top: 2px;
  flex-shrink: 0;
}
.sp-note__body {
  font-size: 12.5px;
  color: rgba(20, 20, 20, 0.7);
  line-height: 1.7;
  font-family: var(--font-display);
  font-style: italic;
}

/* ── Params sliders ── */
.sp-slider-list {
  display: flex;
  flex-direction: column;
  gap: 32px;
  max-width: 600px;
}
.sp-slider__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 10px;
}
.sp-slider__name {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: -0.2px;
}
.sp-slider__name em {
  font-family: var(--font-display);
  font-size: 13px;
  font-style: italic;
  color: rgba(20, 20, 20, 0.5);
  margin-left: 8px;
  font-weight: 400;
}
.sp-slider__val {
  font-family: var(--font-mono);
  font-size: 16px;
  font-weight: 700;
  color: var(--ink-950);
  font-variant-numeric: tabular-nums;
}
.sp-range {
  width: 100%;
  accent-color: #c6ac57;
  cursor: pointer;
}
.sp-slider__hint {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.45);
  margin-top: 8px;
  letter-spacing: 0.05em;
}

/* ── About ── */
.sp-about {
  max-width: 520px;
  font-family: var(--font-display);
  font-size: 15px;
  line-height: 1.8;
  color: rgba(20, 20, 20, 0.75);
  font-style: italic;
}
.sp-about__em {
  font-weight: 900;
  background: linear-gradient(135deg, #c6ac57, var(--signal-teal));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.sp-about__foot {
  margin-top: 32px;
  border-top: 1px solid rgba(20, 20, 20, 0.15);
  padding-top: 20px;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: rgba(20, 20, 20, 0.55);
  letter-spacing: 0.1em;
}
.sp-about__dim {
  color: rgba(20, 20, 20, 0.35);
  margin-bottom: 4px;
}

@keyframes sp-mod-in {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes sp-ping {
  0% { transform: scale(1); opacity: 1; }
  100% { transform: scale(2.8); opacity: 0; }
}
@keyframes sp-accordion {
  from { opacity: 0; max-height: 0; }
  to { opacity: 1; max-height: 1200px; }
}
@keyframes sp-accent-bar {
  from { width: 0; }
  to { width: 3px; }
}

/* ── Responsive ── */
@media (max-width: 900px) {
  .sp-body { grid-template-columns: 1fr; }
  .sp-nav {
    border-right: none;
    border-bottom: 1px solid rgba(20, 20, 20, 0.12);
    padding: 24px;
  }
  .sp-content { padding: 32px 24px; }
  .sp-header__title { font-size: 36px; }
  .sp-fields { grid-template-columns: 1fr; }
  .sp-masthead { padding: 14px 20px; }
  .sp-masthead__center { display: none; }
}
</style>
