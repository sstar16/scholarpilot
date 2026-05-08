<template>
  <div class="admin-users">
    <header class="au-head">
      <h2>
        <el-icon><User /></el-icon>
        管理员控制台
      </h2>
      <div class="au-tabs">
        <button
          class="au-tab"
          :class="{ 'is-active': activeTab === 'users' }"
          @click="activeTab = 'users'"
          data-testid="tab-users"
        >
          用户管理
        </button>
        <button
          class="au-tab"
          :class="{ 'is-active': activeTab === 'invitations' }"
          @click="activeTab = 'invitations'"
          data-testid="tab-invitations"
        >
          邀请码管理
        </button>
      </div>
      <div class="head-right">
        <el-button size="small" @click="refresh()" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </header>

    <!-- ─── 用户管理 ─── -->
    <section v-if="activeTab === 'users'" class="au-section" data-testid="users-section">
      <div class="au-toolbar">
        <el-input
          v-model="userFilter.search"
          placeholder="按邮箱/姓名搜索"
          size="small"
          clearable
          style="width: 240px"
          @change="loadUsers()"
        />
        <el-select
          v-model="userFilter.status"
          size="small"
          style="width: 140px"
          @change="loadUsers()"
        >
          <el-option label="全部" value="all" />
          <el-option label="在线" value="online" />
          <el-option label="管理员" value="admin" />
          <el-option label="已禁用" value="inactive" />
        </el-select>
      </div>

      <div v-if="loading && !users.length" class="au-empty">
        <el-icon class="is-loading"><Loading /></el-icon>
        加载中...
      </div>

      <el-table
        v-else
        :data="users"
        size="small"
        stripe
        border
        empty-text="暂无用户"
        data-testid="users-table"
      >
        <el-table-column prop="email" label="邮箱" min-width="200">
          <template #default="{ row }">
            <span>{{ row.email }}</span>
            <el-tag v-if="row.is_admin" size="small" type="warning" style="margin-left: 6px">
              ADMIN
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="姓名" width="120" />
        <el-table-column label="注册来源" width="110">
          <template #default="{ row }">
            <el-tag
              :type="row.invited_by_code ? 'info' : 'success'"
              size="small"
              effect="plain"
            >
              {{ row.invited_by_code ? '邀请码' : '开放注册' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="注册时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="last_seen_at" label="最近活跃" width="170">
          <template #default="{ row }">
            <span v-if="row.is_online" class="au-online">● 在线</span>
            <span v-else-if="row.last_seen_at" class="au-offline">
              {{ formatTime(row.last_seen_at) }}
            </span>
            <span v-else class="au-offline">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '正常' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button
              size="small"
              text
              type="primary"
              @click="showActivity(row)"
              data-testid="btn-view-activity"
            >
              查看活动
            </el-button>
            <el-button
              size="small"
              text
              :type="row.is_admin ? 'warning' : 'primary'"
              @click="toggleAdmin(row)"
            >
              {{ row.is_admin ? '撤销 admin' : '设为 admin' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="userTotal > userFilter.page_size" class="au-pager">
        <el-pagination
          small
          background
          layout="prev, pager, next, total"
          :total="userTotal"
          :page-size="userFilter.page_size"
          :current-page="userFilter.page"
          @current-change="(p: number) => { userFilter.page = p; loadUsers() }"
        />
      </div>
    </section>

    <!-- ─── 邀请码管理 ─── -->
    <section v-else class="au-section" data-testid="invitations-section">
      <div class="au-toolbar">
        <el-select
          v-model="inviteStatus"
          size="small"
          style="width: 140px"
          @change="loadInvitations()"
        >
          <el-option label="全部" value="all" />
          <el-option label="未使用" value="unused" />
          <el-option label="已使用" value="used" />
          <el-option label="已过期" value="expired" />
        </el-select>
        <el-input-number
          v-model="newInviteCount"
          size="small"
          :min="1"
          :max="50"
          controls-position="right"
          style="width: 110px"
        />
        <el-input
          v-model="newInviteNote"
          size="small"
          placeholder="备注（可选）"
          style="width: 200px"
        />
        <el-input-number
          v-model="newInviteDays"
          size="small"
          :min="0"
          :max="365"
          placeholder="过期天数（0=永久）"
          controls-position="right"
          style="width: 130px"
        />
        <el-button
          size="small"
          type="primary"
          :loading="creatingInvite"
          @click="createInvite()"
          data-testid="btn-create-invite"
        >
          + 生成邀请码
        </el-button>
      </div>

      <el-table
        :data="invitations"
        size="small"
        stripe
        border
        empty-text="暂无邀请码"
        data-testid="invitations-table"
      >
        <el-table-column prop="code" label="邀请码" min-width="180">
          <template #default="{ row }">
            <code class="au-code">{{ row.code }}</code>
            <el-button size="small" text @click="copyCode(row.code)">复制</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="160" />
        <el-table-column prop="created_at" label="生成时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="expires_at" label="过期时间" width="170">
          <template #default="{ row }">
            {{ row.expires_at ? formatTime(row.expires_at) : '永不过期' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.used_at" type="info" size="small">
              已用 · {{ row.used_by_email || '-' }}
            </el-tag>
            <el-tag v-else-if="row.expires_at && new Date(row.expires_at).getTime() < Date.now()" type="danger" size="small">
              已过期
            </el-tag>
            <el-tag v-else type="success" size="small">未使用</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button
              v-if="!row.used_at"
              size="small"
              text
              type="danger"
              @click="deleteInvite(row)"
            >删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 用户活动弹窗 -->
    <el-dialog
      v-model="activityVisible"
      title="用户活动"
      width="600px"
      data-testid="activity-dialog"
    >
      <div v-if="activeUser" class="au-activity">
        <p><strong>邮箱：</strong>{{ activeUser.email }}</p>
        <p><strong>姓名：</strong>{{ activeUser.name }}</p>
        <p><strong>注册时间：</strong>{{ formatTime(activeUser.created_at) }}</p>
        <p><strong>最近活跃：</strong>
          <span v-if="activeUser.is_online" class="au-online">● 当前在线</span>
          <span v-else>{{ activeUser.last_seen_at ? formatTime(activeUser.last_seen_at) : '从未活跃' }}</span>
        </p>
        <p><strong>注册来源：</strong>
          {{ activeUser.invited_by_code ? `邀请码 ${activeUser.invited_by_code}` : '开放注册（无邀请码）' }}
        </p>
        <p><strong>权限：</strong>
          <el-tag :type="activeUser.is_admin ? 'warning' : 'info'" size="small">
            {{ activeUser.is_admin ? '管理员' : '普通用户' }}
          </el-tag>
          <el-tag :type="activeUser.is_active ? 'success' : 'danger'" size="small" style="margin-left: 6px">
            {{ activeUser.is_active ? '正常' : '已禁用' }}
          </el-tag>
        </p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { User, Loading, Refresh } from '@element-plus/icons-vue'
import {
  adminApi,
  type AdminUserItem,
  type AdminInvitationItem,
} from '../api/client'

const activeTab = ref<'users' | 'invitations'>('users')
const loading = ref(false)

// ─── 用户列表 ───
const users = ref<AdminUserItem[]>([])
const userTotal = ref(0)
const userFilter = reactive({
  search: '',
  status: 'all' as 'all' | 'online' | 'admin' | 'inactive',
  page: 1,
  page_size: 50,
})

// ─── 邀请码 ───
const invitations = ref<AdminInvitationItem[]>([])
const inviteStatus = ref<'all' | 'unused' | 'used' | 'expired'>('all')
const newInviteCount = ref(1)
const newInviteNote = ref('')
const newInviteDays = ref(0)
const creatingInvite = ref(false)

// ─── 活动弹窗 ───
const activityVisible = ref(false)
const activeUser = ref<AdminUserItem | null>(null)

async function loadUsers() {
  loading.value = true
  try {
    const { data } = await adminApi.listUsers({
      search: userFilter.search || undefined,
      status: userFilter.status,
      page: userFilter.page,
      page_size: userFilter.page_size,
    })
    users.value = data.items
    userTotal.value = data.total
  } catch (e: any) {
    if (e?.response?.status === 403) {
      ElMessage.error('需要管理员权限')
    } else {
      ElMessage.error('加载用户失败')
    }
  } finally {
    loading.value = false
  }
}

async function loadInvitations() {
  loading.value = true
  try {
    const { data } = await adminApi.listInvitations(inviteStatus.value)
    invitations.value = data
  } catch (e: any) {
    if (e?.response?.status === 403) {
      ElMessage.error('需要管理员权限')
    } else {
      ElMessage.error('加载邀请码失败')
    }
  } finally {
    loading.value = false
  }
}

async function refresh() {
  if (activeTab.value === 'users') await loadUsers()
  else await loadInvitations()
}

function showActivity(row: AdminUserItem) {
  activeUser.value = row
  activityVisible.value = true
}

async function toggleAdmin(row: AdminUserItem) {
  const next = !row.is_admin
  try {
    await ElMessageBox.confirm(
      next ? `确认将 ${row.email} 设为管理员？` : `确认撤销 ${row.email} 的管理员权限？`,
      '权限变更',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await adminApi.patchUser(row.id, { is_admin: next })
    row.is_admin = next
    ElMessage.success('权限已更新')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '权限更新失败')
  }
}

async function createInvite() {
  creatingInvite.value = true
  try {
    const { data } = await adminApi.createInvitations({
      count: newInviteCount.value,
      note: newInviteNote.value.trim() || null,
      expires_in_days: newInviteDays.value > 0 ? newInviteDays.value : null,
    })
    ElMessage.success(`生成 ${data.length} 个邀请码`)
    newInviteNote.value = ''
    await loadInvitations()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成失败')
  } finally {
    creatingInvite.value = false
  }
}

async function deleteInvite(row: AdminInvitationItem) {
  try {
    await ElMessageBox.confirm(`确认删除邀请码 ${row.code}？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await adminApi.deleteInvitation(row.id)
    ElMessage.success('已删除')
    await loadInvitations()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function copyCode(code: string) {
  navigator.clipboard?.writeText(code).then(() => ElMessage.success('已复制'))
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.admin-users {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}
.au-head {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.au-head h2 {
  margin: 0;
  font-size: 18px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #0f172a;
}
.au-tabs {
  display: flex;
  gap: 4px;
  margin-left: 8px;
}
.au-tab {
  padding: 6px 14px;
  border: 1px solid #cbd5e1;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
  color: #475569;
  border-radius: 6px;
  font-family: inherit;
  transition: all 0.15s;
}
.au-tab.is-active {
  background: #0d9488;
  color: #fff;
  border-color: #0d9488;
}
.head-right { margin-left: auto; }
.au-section { margin-top: 4px; }
.au-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.au-empty {
  text-align: center;
  padding: 60px 0;
  color: #94a3b8;
}
.au-online {
  color: #10b981;
  font-weight: 600;
}
.au-offline { color: #94a3b8; }
.au-code {
  font-family: ui-monospace, SFMono-Regular, monospace;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
}
.au-pager {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}
.au-activity p {
  margin: 8px 0;
  font-size: 13.5px;
  color: #1e293b;
}
.au-activity strong {
  display: inline-block;
  width: 100px;
  color: #475569;
}
</style>
