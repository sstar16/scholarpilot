<template>
  <el-container style="min-height: 100vh;">
    <el-header class="app-header">
      <div class="header-left">
        <router-link to="/dashboard" class="logo-link">🔬 科研情报平台</router-link>
      </div>
      <div class="header-right">
        <el-button text @click="router.push('/settings')">
          <el-icon><Setting /></el-icon> 设置
        </el-button>
        <el-dropdown @command="handleCommand">
          <span class="user-info">{{ auth.user?.name }} <el-icon><ArrowDown /></el-icon></span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>
    <el-main>
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

function handleCommand(cmd: string) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.app-header {
  display: flex; align-items: center; justify-content: space-between;
  background: #fff; border-bottom: 1px solid #e4e7ed; padding: 0 24px;
}
.logo-link { font-size: 18px; font-weight: 600; text-decoration: none; color: #303133; }
.header-right { display: flex; align-items: center; gap: 16px; }
.user-info { cursor: pointer; display: flex; align-items: center; gap: 4px; font-size: 14px; }
</style>
