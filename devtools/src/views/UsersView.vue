<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import AppNav from '../components/AppNav.vue'
import {
  listUsers, getUserStats, updateUser, deleteUser, getUserActivity,
  listInvitations, createInvitations, deleteInvitation, getInvitationStats,
  type UserInfo, type UserStats, type Invitation, type InvitationStats,
  type InvitationStatusFilter, type UserActivityPayload,
} from '../api/client'

// ─── Tab 切换 ───
type Tab = 'users' | 'invitations'
const activeTab = ref<Tab>('users')

// ─── Users 状态 ───
const users = ref<UserInfo[]>([])
const userStats = ref<UserStats>({ total: 0, admins: 0, inactive: 0, new_today: 0, online: 0 })
const userTotal = ref(0)
const userPage = ref(1)
const userPageSize = ref(50)
const userSearch = ref('')
const userStatusFilter = ref<'all' | 'online' | 'admin' | 'inactive'>('all')
const userLoading = ref(false)
const userError = ref<string>('')

// 活动抽屉
const activityOpen = ref(false)
const activityLoading = ref(false)
const activityData = ref<UserActivityPayload | null>(null)
const activityDays = ref(7)

async function fetchUsers() {
  userLoading.value = true
  userError.value = ''
  try {
    const [{ data }, { data: stats }] = await Promise.all([
      listUsers({
        search: userSearch.value || undefined,
        status: userStatusFilter.value,
        page: userPage.value,
        page_size: userPageSize.value,
      }),
      getUserStats(),
    ])
    users.value = data.items
    userTotal.value = data.total
    userStats.value = stats
  } catch (e: any) {
    userError.value = e?.response?.data?.detail || '加载用户失败'
  } finally {
    userLoading.value = false
  }
}

function onSearch() {
  userPage.value = 1
  fetchUsers()
}

async function toggleAdmin(u: UserInfo) {
  if (!confirm(`${u.is_admin ? '撤销' : '授予'} ${u.email} 的管理员权限？`)) return
  try {
    await updateUser(u.id, { is_admin: !u.is_admin })
    await fetchUsers()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '操作失败')
  }
}

async function toggleActive(u: UserInfo) {
  if (!confirm(`${u.is_active ? '禁用' : '启用'} ${u.email}？`)) return
  try {
    await updateUser(u.id, { is_active: !u.is_active })
    await fetchUsers()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '操作失败')
  }
}

async function removeUser(u: UserInfo) {
  if (!confirm(`确定删除用户 ${u.email}？\n该操作不可撤销，会同时删除其所有项目和对话会话。`)) return
  const second = prompt(`再次确认：请输入 ${u.email} 以继续`)
  if (second !== u.email) {
    alert('邮箱不匹配，已取消')
    return
  }
  try {
    await deleteUser(u.id)
    await fetchUsers()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '删除失败')
  }
}

async function openActivity(u: UserInfo) {
  activityOpen.value = true
  activityLoading.value = true
  activityData.value = null
  try {
    const { data } = await getUserActivity(u.id, activityDays.value)
    activityData.value = data
  } catch (e: any) {
    alert(e?.response?.data?.detail || '加载活动失败')
    activityOpen.value = false
  } finally {
    activityLoading.value = false
  }
}

function closeActivity() {
  activityOpen.value = false
  activityData.value = null
}

async function reloadActivity() {
  if (!activityData.value) return
  activityLoading.value = true
  try {
    const { data } = await getUserActivity(activityData.value.user.id, activityDays.value)
    activityData.value = data
  } finally {
    activityLoading.value = false
  }
}

// ─── Invitations 状态 ───
const invitations = ref<Invitation[]>([])
const inviteStats = ref<InvitationStats>({ total: 0, used: 0, expired: 0, available: 0 })
const inviteFilter = ref<InvitationStatusFilter>('all')
const inviteLoading = ref(false)

const genCount = ref(1)
const genNote = ref('')
const genExpiresDays = ref<number | null>(null)
const generating = ref(false)

async function fetchInvitations() {
  inviteLoading.value = true
  try {
    const [{ data: list }, { data: stats }] = await Promise.all([
      listInvitations(inviteFilter.value),
      getInvitationStats(),
    ])
    invitations.value = list
    inviteStats.value = stats
  } catch (e: any) {
    alert(e?.response?.data?.detail || '加载邀请码失败')
  } finally {
    inviteLoading.value = false
  }
}

async function doGenerate() {
  if (genCount.value < 1 || genCount.value > 200) {
    alert('数量必须在 1-200')
    return
  }
  generating.value = true
  try {
    await createInvitations(genCount.value, genNote.value.trim() || undefined, genExpiresDays.value ?? undefined)
    genNote.value = ''
    genCount.value = 1
    await fetchInvitations()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '生成失败')
  } finally {
    generating.value = false
  }
}

async function copyCode(code: string) {
  try {
    await navigator.clipboard.writeText(code)
  } catch {
    // fallback
    const ta = document.createElement('textarea')
    ta.value = code
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}

async function removeInvitation(inv: Invitation) {
  if (inv.used_at) {
    alert('已使用的邀请码不能删除')
    return
  }
  if (!confirm(`删除邀请码 ${inv.code}？`)) return
  try {
    await deleteInvitation(inv.id)
    await fetchInvitations()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '删除失败')
  }
}

function switchTab(tab: Tab) {
  activeTab.value = tab
  if (tab === 'users') fetchUsers()
  else fetchInvitations()
}

// ─── 生命周期 ───
let refreshTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await fetchUsers()
  // 15s 刷新（主要更新在线状态）
  refreshTimer = setInterval(() => {
    if (activeTab.value === 'users' && !activityOpen.value) fetchUsers()
  }, 15_000)
})

onUnmounted(() => {
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
})

// ─── 显示辅助 ───
function formatDt(iso?: string | null) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    return `${y}-${m}-${dd} ${hh}:${mm}`
  } catch {
    return iso
  }
}

function relativeTime(iso?: string | null) {
  if (!iso) return '未登录过'
  try {
    const delta = (Date.now() - new Date(iso).getTime()) / 1000
    if (delta < 60) return `${Math.floor(delta)}秒前`
    if (delta < 3600) return `${Math.floor(delta / 60)}分钟前`
    if (delta < 86400) return `${Math.floor(delta / 3600)}小时前`
    return `${Math.floor(delta / 86400)}天前`
  } catch {
    return iso
  }
}

const pageMax = computed(() => Math.max(1, Math.ceil(userTotal.value / userPageSize.value)))

function prevPage() {
  if (userPage.value > 1) { userPage.value--; fetchUsers() }
}
function nextPage() {
  if (userPage.value < pageMax.value) { userPage.value++; fetchUsers() }
}
</script>

<template>
  <div class="users-view">
    <AppNav />

    <main class="content">
      <!-- Tab 切换 -->
      <div class="tabs">
        <button
          class="tab-btn" :class="{ active: activeTab === 'users' }"
          @click="switchTab('users')"
        >👤 用户管理</button>
        <button
          class="tab-btn" :class="{ active: activeTab === 'invitations' }"
          @click="switchTab('invitations')"
        >🎟️ 邀请码</button>
      </div>

      <!-- ─── Users Tab ─── -->
      <section v-if="activeTab === 'users'" class="panel">
        <!-- Stats -->
        <div class="stats-row">
          <div class="stat-card">
            <div class="stat-label">总用户</div>
            <div class="stat-value">{{ userStats.total }}</div>
          </div>
          <div class="stat-card stat-online">
            <div class="stat-label">当前在线</div>
            <div class="stat-value">{{ userStats.online }}</div>
          </div>
          <div class="stat-card stat-admin">
            <div class="stat-label">管理员</div>
            <div class="stat-value">{{ userStats.admins }}</div>
          </div>
          <div class="stat-card stat-inactive">
            <div class="stat-label">已禁用</div>
            <div class="stat-value">{{ userStats.inactive }}</div>
          </div>
          <div class="stat-card stat-new">
            <div class="stat-label">今日新增</div>
            <div class="stat-value">{{ userStats.new_today }}</div>
          </div>
        </div>

        <!-- Filters -->
        <div class="toolbar">
          <input
            v-model="userSearch"
            @keyup.enter="onSearch"
            placeholder="搜索邮箱/用户名"
            class="input"
          />
          <select v-model="userStatusFilter" @change="onSearch" class="input">
            <option value="all">全部</option>
            <option value="online">在线</option>
            <option value="admin">管理员</option>
            <option value="inactive">已禁用</option>
          </select>
          <button class="btn btn-primary" @click="onSearch">搜索</button>
          <button class="btn" @click="fetchUsers">↻ 刷新</button>
        </div>

        <div v-if="userError" class="error-box">{{ userError }}</div>

        <!-- Table -->
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 80px">状态</th>
                <th>邮箱</th>
                <th>名称</th>
                <th style="width: 70px">项目</th>
                <th style="width: 70px">权限</th>
                <th style="width: 140px">注册时间</th>
                <th style="width: 130px">最近活跃</th>
                <th style="width: 220px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="userLoading && !users.length">
                <td colspan="8" class="loading">加载中...</td>
              </tr>
              <tr v-else-if="!users.length">
                <td colspan="8" class="loading">没有匹配的用户</td>
              </tr>
              <tr v-for="u in users" :key="u.id">
                <td>
                  <span class="dot" :class="u.is_online ? 'dot-online' : (u.is_active ? 'dot-idle' : 'dot-off')"></span>
                  <span class="dot-label">{{ u.is_online ? '在线' : (u.is_active ? '离线' : '禁用') }}</span>
                </td>
                <td class="mono">{{ u.email }}</td>
                <td>{{ u.name }}</td>
                <td class="tc">{{ u.project_count }}</td>
                <td>
                  <span class="badge" :class="u.is_admin ? 'badge-admin' : 'badge-user'">
                    {{ u.is_admin ? 'Admin' : '普通' }}
                  </span>
                </td>
                <td class="mono-sm">{{ formatDt(u.created_at) }}</td>
                <td class="mono-sm" :title="formatDt(u.last_seen_at)">{{ relativeTime(u.last_seen_at) }}</td>
                <td class="actions">
                  <button class="btn-sm" @click="openActivity(u)">📊 活动</button>
                  <button class="btn-sm" @click="toggleAdmin(u)">{{ u.is_admin ? '撤 Admin' : '授 Admin' }}</button>
                  <button class="btn-sm" @click="toggleActive(u)">{{ u.is_active ? '禁用' : '启用' }}</button>
                  <button class="btn-sm btn-danger" @click="removeUser(u)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        <div class="pager">
          <span>共 {{ userTotal }} 人 · 第 {{ userPage }} / {{ pageMax }} 页</span>
          <button class="btn-sm" :disabled="userPage <= 1" @click="prevPage">← 上一页</button>
          <button class="btn-sm" :disabled="userPage >= pageMax" @click="nextPage">下一页 →</button>
        </div>
      </section>

      <!-- ─── Invitations Tab ─── -->
      <section v-else class="panel">
        <div class="stats-row">
          <div class="stat-card">
            <div class="stat-label">总邀请码</div>
            <div class="stat-value">{{ inviteStats.total }}</div>
          </div>
          <div class="stat-card stat-online">
            <div class="stat-label">可用</div>
            <div class="stat-value">{{ inviteStats.available }}</div>
          </div>
          <div class="stat-card stat-admin">
            <div class="stat-label">已使用</div>
            <div class="stat-value">{{ inviteStats.used }}</div>
          </div>
          <div class="stat-card stat-inactive">
            <div class="stat-label">已过期</div>
            <div class="stat-value">{{ inviteStats.expired }}</div>
          </div>
        </div>

        <div class="generate-box">
          <h4>生成邀请码</h4>
          <div class="form-row">
            <label>数量 <input v-model.number="genCount" type="number" min="1" max="200" class="input input-sm" /></label>
            <label>备注 <input v-model="genNote" placeholder="可选" class="input" /></label>
            <label>过期天数
              <input v-model.number="genExpiresDays" type="number" min="1" placeholder="永不" class="input input-sm" />
            </label>
            <button class="btn btn-primary" :disabled="generating" @click="doGenerate">
              {{ generating ? '生成中...' : '➕ 生成' }}
            </button>
          </div>
        </div>

        <div class="toolbar">
          <select v-model="inviteFilter" @change="fetchInvitations" class="input">
            <option value="all">全部</option>
            <option value="unused">未使用</option>
            <option value="used">已使用</option>
            <option value="expired">已过期</option>
          </select>
          <button class="btn" @click="fetchInvitations">↻ 刷新</button>
        </div>

        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>邀请码</th>
                <th>备注</th>
                <th style="width: 140px">创建时间</th>
                <th style="width: 140px">过期时间</th>
                <th style="width: 140px">使用时间</th>
                <th>使用者</th>
                <th style="width: 170px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="inviteLoading && !invitations.length">
                <td colspan="7" class="loading">加载中...</td>
              </tr>
              <tr v-else-if="!invitations.length">
                <td colspan="7" class="loading">没有邀请码</td>
              </tr>
              <tr v-for="inv in invitations" :key="inv.id">
                <td class="mono">{{ inv.code }}</td>
                <td>{{ inv.note || '—' }}</td>
                <td class="mono-sm">{{ formatDt(inv.created_at) }}</td>
                <td class="mono-sm">{{ inv.expires_at ? formatDt(inv.expires_at) : '永不' }}</td>
                <td class="mono-sm">{{ inv.used_at ? formatDt(inv.used_at) : '—' }}</td>
                <td class="mono-sm">{{ inv.used_by_email || '—' }}</td>
                <td class="actions">
                  <button class="btn-sm" @click="copyCode(inv.code)">📋 复制</button>
                  <button
                    class="btn-sm btn-danger" :disabled="!!inv.used_at"
                    @click="removeInvitation(inv)"
                  >删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>

    <!-- ─── Activity Drawer ─── -->
    <div v-if="activityOpen" class="drawer-mask" @click.self="closeActivity">
      <aside class="drawer">
        <header class="drawer-header">
          <div>
            <h3>用户活动</h3>
            <p class="drawer-sub mono" v-if="activityData">{{ activityData.user.email }}</p>
          </div>
          <div class="drawer-controls">
            <select v-model.number="activityDays" @change="reloadActivity" class="input input-sm">
              <option :value="1">最近 1 天</option>
              <option :value="7">最近 7 天</option>
              <option :value="30">最近 30 天</option>
              <option :value="90">最近 90 天</option>
            </select>
            <button class="btn-sm" @click="closeActivity">✕</button>
          </div>
        </header>
        <div v-if="activityLoading" class="drawer-loading">加载中...</div>
        <div v-else-if="activityData" class="drawer-body">
          <div v-if="activityData.partial_errors && activityData.partial_errors.length" class="partial-err-box">
            <div class="pe-title">⚠ 部分数据加载失败（其余照常显示）</div>
            <div v-for="err in activityData.partial_errors" :key="err" class="pe-item">{{ err }}</div>
          </div>
          <div class="mini-stats">
            <div><b>{{ activityData.stats.total_projects }}</b><span>项目</span></div>
            <div><b>{{ activityData.stats.total_sessions }}</b><span>会话</span></div>
            <div><b>{{ activityData.stats.log_events }}</b><span>日志</span></div>
            <div class="err"><b>{{ activityData.stats.errors }}</b><span>错误</span></div>
          </div>

          <h4>最近项目 ({{ activityData.recent_projects.length }})</h4>
          <div class="list" v-if="activityData.recent_projects.length">
            <div v-for="p in activityData.recent_projects" :key="p.id" class="list-item">
              <span class="list-title">{{ p.title }}</span>
              <span v-if="p.domain" class="state-badge">{{ p.domain }}</span>
              <span class="list-meta">第 {{ p.current_round }} 轮 · {{ formatDt(p.created_at) }}</span>
            </div>
          </div>
          <div v-else class="list-empty">无项目</div>

          <h4>最近会话 ({{ activityData.recent_sessions.length }})</h4>
          <div class="list" v-if="activityData.recent_sessions.length">
            <div v-for="s in activityData.recent_sessions" :key="s.id" class="list-item">
              <span class="list-title mono-sm">{{ s.id.slice(0, 8) }}</span>
              <span class="state-badge">{{ s.current_state || 'idle' }}</span>
              <span class="list-meta">{{ formatDt(s.last_activity_at || s.created_at) }}</span>
            </div>
          </div>
          <div v-else class="list-empty">无会话</div>

          <h4>日志事件 ({{ activityData.recent_logs.length }})</h4>
          <div class="list" v-if="activityData.recent_logs.length">
            <div v-for="lg in activityData.recent_logs" :key="lg.id" class="list-item log-item" :class="`log-${lg.level.toLowerCase()}`">
              <span class="log-level">{{ lg.level }}</span>
              <span class="log-source mono-sm">{{ lg.source }}</span>
              <span class="log-msg">{{ lg.message }}</span>
              <span class="list-meta">{{ formatDt(lg.created_at) }}</span>
            </div>
          </div>
          <div v-else class="list-empty">无日志</div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.users-view {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 40%, #0f0f24 100%);
  color: #e0e0e0;
}

.content {
  padding: 20px 24px;
  max-width: 1600px;
  margin: 0 auto;
}

/* ─── Tabs ─── */
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.tab-btn {
  padding: 8px 20px;
  border: 1px solid rgba(124, 58, 237, 0.2);
  background: rgba(124, 58, 237, 0.04);
  color: #8888aa;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.tab-btn:hover { color: #c4b5fd; }
.tab-btn.active { color: #c4b5fd; background: rgba(124, 58, 237, 0.18); border-color: rgba(124, 58, 237, 0.5); }

.panel { display: flex; flex-direction: column; gap: 16px; }

/* ─── Stats ─── */
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
.stat-card {
  padding: 14px 18px;
  border: 1px solid rgba(42, 42, 74, 0.6);
  background: rgba(19, 19, 43, 0.55);
  border-radius: 10px;
}
.stat-label { font-size: 11px; color: #8888aa; text-transform: uppercase; letter-spacing: 1px; }
.stat-value { font-size: 26px; font-weight: 700; color: #e0e0e0; margin-top: 4px; }
.stat-online { border-color: rgba(74, 222, 128, 0.35); }
.stat-online .stat-value { color: #4ade80; }
.stat-admin { border-color: rgba(124, 58, 237, 0.4); }
.stat-admin .stat-value { color: #c4b5fd; }
.stat-inactive { border-color: rgba(248, 113, 113, 0.3); }
.stat-inactive .stat-value { color: #f87171; }
.stat-new { border-color: rgba(251, 191, 36, 0.3); }
.stat-new .stat-value { color: #fbbf24; }

/* ─── Toolbar & Inputs ─── */
.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.input {
  padding: 7px 12px;
  border: 1px solid rgba(74, 74, 107, 0.5);
  background: rgba(10, 10, 26, 0.6);
  color: #e0e0e0;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
}
.input:focus { border-color: rgba(124, 58, 237, 0.6); }
.input-sm { width: 100px; }

.btn, .btn-primary, .btn-sm {
  padding: 7px 14px;
  border: 1px solid rgba(74, 74, 107, 0.5);
  background: rgba(19, 19, 43, 0.6);
  color: #e0e0e0;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn:hover, .btn-sm:hover { background: rgba(124, 58, 237, 0.12); border-color: rgba(124, 58, 237, 0.35); }
.btn-primary {
  background: rgba(124, 58, 237, 0.18);
  border-color: rgba(124, 58, 237, 0.5);
  color: #c4b5fd;
}
.btn-primary:hover { background: rgba(124, 58, 237, 0.3); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.btn-sm:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-danger { color: #f87171; border-color: rgba(248, 113, 113, 0.4); }
.btn-danger:hover { background: rgba(248, 113, 113, 0.18); }

/* ─── Table ─── */
.table-wrapper {
  border: 1px solid rgba(42, 42, 74, 0.4);
  border-radius: 10px;
  overflow-x: auto;
  background: rgba(19, 19, 43, 0.3);
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.data-table th {
  padding: 10px 12px;
  text-align: left;
  background: rgba(10, 10, 26, 0.6);
  color: #8888aa;
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  border-bottom: 1px solid rgba(42, 42, 74, 0.6);
}
.data-table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.3);
  vertical-align: middle;
}
.data-table tbody tr:hover { background: rgba(124, 58, 237, 0.05); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.mono-sm { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: #aaaacc; }
.tc { text-align: center; }
.actions { display: flex; gap: 4px; flex-wrap: wrap; }

.loading, .list-empty {
  padding: 40px 12px;
  text-align: center;
  color: #8888aa;
  font-size: 12px;
}

.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.dot-online { background: #4ade80; box-shadow: 0 0 6px rgba(74, 222, 128, 0.6); }
.dot-idle { background: #666; }
.dot-off { background: #f87171; }
.dot-label { font-size: 11px; color: #aaaacc; }

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 600;
}
.badge-admin { background: rgba(124, 58, 237, 0.15); color: #c4b5fd; }
.badge-user { background: rgba(74, 74, 107, 0.3); color: #8888aa; }

.pager { display: flex; gap: 10px; align-items: center; justify-content: flex-end; font-size: 12px; color: #8888aa; }

.error-box {
  padding: 10px 14px;
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.35);
  border-radius: 6px;
  color: #f87171;
  font-size: 12px;
}

/* ─── Generate box ─── */
.generate-box {
  padding: 14px 18px;
  border: 1px solid rgba(124, 58, 237, 0.25);
  background: rgba(124, 58, 237, 0.04);
  border-radius: 10px;
}
.generate-box h4 { margin: 0 0 10px; font-size: 13px; color: #c4b5fd; }
.form-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.form-row label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: #8888aa; }

/* ─── Drawer ─── */
.drawer-mask {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  z-index: 200;
  display: flex; justify-content: flex-end;
}
.drawer {
  width: min(560px, 100vw);
  height: 100%;
  background: rgba(10, 10, 26, 0.98);
  border-left: 1px solid rgba(124, 58, 237, 0.25);
  display: flex; flex-direction: column;
  overflow: hidden;
}
.drawer-header {
  padding: 16px 20px;
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid rgba(42, 42, 74, 0.5);
}
.drawer-header h3 { margin: 0; font-size: 15px; color: #fff; }
.drawer-sub { margin: 4px 0 0; font-size: 11px; color: #aaaacc; }
.drawer-controls { display: flex; gap: 8px; align-items: center; }
.drawer-loading { padding: 40px; text-align: center; color: #8888aa; }
.drawer-body { overflow-y: auto; padding: 16px 20px; flex: 1; }
.drawer-body h4 { font-size: 12px; color: #c4b5fd; text-transform: uppercase; letter-spacing: 1px; margin: 18px 0 8px; }
.drawer-body h4:first-child { margin-top: 0; }

.mini-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.mini-stats > div {
  padding: 10px;
  background: rgba(19, 19, 43, 0.6);
  border: 1px solid rgba(42, 42, 74, 0.4);
  border-radius: 8px;
  text-align: center;
}
.mini-stats b { display: block; font-size: 20px; color: #e0e0e0; }
.mini-stats span { font-size: 10px; color: #8888aa; }
.mini-stats .err b { color: #f87171; }

.partial-err-box {
  margin-bottom: 14px;
  padding: 10px 12px;
  background: rgba(251, 191, 36, 0.08);
  border: 1px solid rgba(251, 191, 36, 0.3);
  border-radius: 6px;
  font-size: 11px;
}
.pe-title { color: #fbbf24; font-weight: 600; margin-bottom: 4px; }
.pe-item { color: #aaaacc; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }

.list { display: flex; flex-direction: column; gap: 6px; }
.list-item {
  display: flex; gap: 10px; align-items: center;
  padding: 8px 10px;
  background: rgba(19, 19, 43, 0.4);
  border-left: 2px solid rgba(124, 58, 237, 0.3);
  border-radius: 4px;
  font-size: 12px;
}
.list-title { flex: 0 0 auto; font-weight: 600; color: #e0e0e0; }
.list-meta { margin-left: auto; font-size: 10px; color: #8888aa; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.state-badge {
  font-size: 10px;
  padding: 1px 6px;
  background: rgba(124, 58, 237, 0.15);
  color: #c4b5fd;
  border-radius: 3px;
}

.log-item { gap: 8px; }
.log-level { font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 3px; min-width: 45px; text-align: center; }
.log-source { color: #c4b5fd; min-width: 60px; }
.log-msg { flex: 1; color: #aaaacc; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-info .log-level { background: rgba(100, 180, 255, 0.15); color: #93c5fd; }
.log-warn .log-level, .log-warning .log-level { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
.log-error .log-level { background: rgba(248, 113, 113, 0.2); color: #f87171; }
.log-debug .log-level { background: rgba(74, 74, 107, 0.3); color: #8888aa; }
</style>
