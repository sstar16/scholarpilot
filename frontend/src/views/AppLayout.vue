<template>
  <div class="app-shell">
    <header class="app-header">
      <router-link to="/dashboard" class="logo">
        <span class="logo-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
          </svg>
        </span>
        <span class="logo-type">Scholar<b>Pilot</b></span>
      </router-link>

      <nav class="header-nav">
        <router-link to="/dashboard" class="nav-link">
          <el-icon><Folder /></el-icon> 项目
        </router-link>
      </nav>

      <div class="header-right">
        <button class="icon-btn" @click="router.push('/settings')" title="设置">
          <el-icon><Setting /></el-icon>
        </button>
        <el-dropdown @command="handleCommand" trigger="click">
          <button class="user-pill">
            <span class="avatar">{{ (auth.user?.name || '?')[0] }}</span>
            <span class="name">{{ auth.user?.name }}</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>
    <main class="app-body">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
const router = useRouter()
const auth = useAuthStore()
function handleCommand(cmd: string) {
  if (cmd === 'logout') { auth.logout(); router.push('/login') }
}
</script>

<style scoped>
.app-shell { min-height: 100vh; background: var(--paper-cool); }

.app-header {
  height: 52px;
  display: flex; align-items: center; gap: 24px;
  padding: 0 20px;
  background: var(--ink-900);
  color: var(--ink-200);
  position: sticky; top: 0; z-index: 200;
  border-bottom: 1px solid var(--ink-700);
}

.logo {
  display: flex; align-items: center; gap: 8px;
  text-decoration: none; color: #fff;
  flex-shrink: 0;
}
.logo-icon {
  width: 30px; height: 30px; border-radius: 8px;
  background: var(--signal-teal);
  display: flex; align-items: center; justify-content: center;
  color: #fff; transition: transform var(--duration-normal) var(--ease-spring);
}
.logo:hover .logo-icon { transform: rotate(-8deg) scale(1.08); }
.logo-type {
  font-family: var(--font-body);
  font-size: 15px; font-weight: 300; letter-spacing: 0.02em;
  color: var(--ink-200);
}
.logo-type b { font-weight: 700; color: #fff; }

.header-nav { display: flex; gap: 4px; margin-left: 8px; }
.nav-link {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 12px; border-radius: var(--radius-sm);
  font-size: 13px; font-weight: 500; color: var(--ink-300);
  text-decoration: none;
  transition: all var(--duration-fast);
}
.nav-link:hover, .nav-link.router-link-active {
  background: var(--ink-700); color: #fff;
}

.header-right {
  margin-left: auto;
  display: flex; align-items: center; gap: 6px;
}

.icon-btn {
  width: 32px; height: 32px; border-radius: var(--radius-sm);
  border: 1px solid var(--ink-600); background: transparent;
  color: var(--ink-300); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--duration-fast);
}
.icon-btn:hover { border-color: var(--ink-400); color: #fff; background: var(--ink-700); }

.user-pill {
  display: flex; align-items: center; gap: 7px;
  padding: 3px 10px 3px 3px; border-radius: var(--radius-full);
  border: 1px solid var(--ink-600); background: transparent;
  cursor: pointer; color: var(--ink-200);
  transition: all var(--duration-fast);
}
.user-pill:hover { border-color: var(--ink-400); background: var(--ink-700); }
.avatar {
  width: 26px; height: 26px; border-radius: 50%;
  background: var(--signal-teal);
  color: #fff; font-size: 11px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.name { font-size: 12px; font-weight: 500; }

.app-body { padding: 0; }
</style>
