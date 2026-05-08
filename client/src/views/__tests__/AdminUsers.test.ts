// @vitest-environment happy-dom
/**
 * AdminUsers.vue 单测：
 * - mock adminApi → 渲染用户表格
 * - 切到 invitations tab 渲染邀请码列表
 * - 生成新邀请码触发 createInvitations
 * - 403 时提示需要管理员权限
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

// ─── adminApi mock ───
const _listUsersFn = vi.fn()
const _listInvitationsFn = vi.fn()
const _createInvitationsFn = vi.fn()
const _patchUserFn = vi.fn()
const _deleteInvitationFn = vi.fn()

vi.mock('../../api/client', () => ({
  adminApi: {
    listUsers: (...args: any[]) => _listUsersFn(...args),
    listInvitations: (...args: any[]) => _listInvitationsFn(...args),
    createInvitations: (...args: any[]) => _createInvitationsFn(...args),
    patchUser: (...args: any[]) => _patchUserFn(...args),
    deleteUser: vi.fn(),
    deleteInvitation: (...args: any[]) => _deleteInvitationFn(...args),
    userStats: vi.fn(),
    invitationStats: vi.fn(),
  },
}))

// element-plus icon stubs（happy-dom 不需要真渲染）
vi.mock('@element-plus/icons-vue', () => ({
  User: { name: 'User', render: () => null },
  Loading: { name: 'Loading', render: () => null },
  Refresh: { name: 'Refresh', render: () => null },
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  ElMessageBox: {
    confirm: vi.fn(() => Promise.resolve()),
  },
}))

import AdminUsers from '../AdminUsers.vue'

const _defaultUsers = [
  {
    id: 'u-1',
    email: 'admin@example.com',
    name: 'Admin',
    is_active: true,
    is_admin: true,
    created_at: '2026-05-01T00:00:00Z',
    last_seen_at: '2026-05-08T10:00:00Z',
    is_online: true,
    invited_by_code: null,
  },
  {
    id: 'u-2',
    email: 'user2@example.com',
    name: 'User2',
    is_active: true,
    is_admin: false,
    created_at: '2026-05-05T00:00:00Z',
    last_seen_at: null,
    is_online: false,
    invited_by_code: 'abc123',
  },
]

const _defaultInvitations = [
  {
    id: 'i-1',
    code: 'invitation01',
    note: '内测',
    created_at: '2026-05-01T00:00:00Z',
    expires_at: null,
    used_at: null,
    used_by_email: null,
  },
]

// 全局 stubs：让 el-* 组件渲染为简单 div / 透传 slot 内容
const _globalStubs = {
  ElIcon: { template: '<i><slot/></i>' },
  ElButton: {
    props: ['loading', 'type', 'text', 'size'],
    emits: ['click'],
    template: '<button @click="$emit(\'click\', $event)"><slot/></button>',
  },
  ElInput: {
    props: ['modelValue'],
    emits: ['update:modelValue', 'change'],
    template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\')" />',
  },
  ElSelect: {
    props: ['modelValue'],
    emits: ['update:modelValue', 'change'],
    template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\')"><slot/></select>',
  },
  ElOption: {
    props: ['label', 'value'],
    template: '<option :value="value">{{ label }}</option>',
  },
  ElInputNumber: {
    props: ['modelValue', 'min', 'max'],
    emits: ['update:modelValue'],
    template: '<input type="number" :value="modelValue" @input="$emit(\'update:modelValue\', Number($event.target.value))" />',
  },
  ElTable: {
    props: ['data'],
    template: '<table data-stub-table><tbody><tr v-for="(row, i) in (data || [])" :key="i" data-row><slot :row="row" :$index="i"/></tr></tbody></table>',
  },
  ElTableColumn: {
    props: ['label', 'prop'],
    template: '<td><slot :row="$parent.$data?.row || {}" /></td>',
  },
  ElTag: {
    props: ['type', 'size', 'effect'],
    template: '<span class="el-tag-stub"><slot/></span>',
  },
  ElPagination: { template: '<div class="el-pagination-stub"></div>' },
  ElDialog: {
    props: ['modelValue'],
    template: '<div v-if="modelValue" class="el-dialog-stub"><slot/></div>',
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  _listUsersFn.mockResolvedValue({
    data: { items: _defaultUsers, total: 2, page: 1, page_size: 50 },
  })
  _listInvitationsFn.mockResolvedValue({ data: _defaultInvitations })
  _createInvitationsFn.mockResolvedValue({ data: [{ ..._defaultInvitations[0], id: 'i-2', code: 'newcode99' }] })
  _patchUserFn.mockResolvedValue({ data: {} })
  _deleteInvitationFn.mockResolvedValue({ data: {} })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AdminUsers.vue', () => {
  it('mount 时调用 listUsers + 渲染 users-section', async () => {
    const wrapper = mount(AdminUsers, { global: { stubs: _globalStubs } })
    await flushPromises()
    await nextTick()
    expect(_listUsersFn).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="users-section"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="users-table"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('切到邀请码 tab → 调 listInvitations + 渲染 invitations-section', async () => {
    const wrapper = mount(AdminUsers, { global: { stubs: _globalStubs } })
    await flushPromises()
    await nextTick()

    // 切 tab
    const inviteTab = wrapper.find('[data-testid="tab-invitations"]')
    expect(inviteTab.exists()).toBe(true)
    await inviteTab.trigger('click')
    await flushPromises()
    await nextTick()

    expect(wrapper.find('[data-testid="invitations-section"]').exists()).toBe(true)
    // 用户主动点 refresh 才会触发；测试通过手动触发
    const vm = wrapper.vm as any
    await vm.loadInvitations()
    await flushPromises()
    expect(_listInvitationsFn).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('生成新邀请码 → 调 createInvitations 并刷新列表', async () => {
    const wrapper = mount(AdminUsers, { global: { stubs: _globalStubs } })
    await flushPromises()

    const vm = wrapper.vm as any
    vm.activeTab = 'invitations'
    await nextTick()

    vm.newInviteCount = 3
    vm.newInviteNote = 'beta-tester'
    vm.newInviteDays = 30
    await vm.createInvite()
    await flushPromises()

    expect(_createInvitationsFn).toHaveBeenCalledWith({
      count: 3,
      note: 'beta-tester',
      expires_in_days: 30,
    })
    // 创建成功后会再次 listInvitations 刷新
    expect(_listInvitationsFn).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('listUsers 403 → 提示需要管理员权限', async () => {
    const { ElMessage } = await import('element-plus')
    _listUsersFn.mockRejectedValueOnce({ response: { status: 403 } })

    const wrapper = mount(AdminUsers, { global: { stubs: _globalStubs } })
    await flushPromises()
    await nextTick()

    expect(ElMessage.error).toHaveBeenCalledWith('需要管理员权限')
    wrapper.unmount()
  })

  it('showActivity → activityVisible=true + activeUser 设定', async () => {
    const wrapper = mount(AdminUsers, { global: { stubs: _globalStubs } })
    await flushPromises()
    await nextTick()
    const vm = wrapper.vm as any
    expect(vm.activityVisible).toBe(false)
    vm.showActivity(_defaultUsers[1])
    await nextTick()
    expect(vm.activityVisible).toBe(true)
    expect(vm.activeUser?.email).toBe('user2@example.com')
    wrapper.unmount()
  })
})
