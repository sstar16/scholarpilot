<script setup lang="ts">
/**
 * 公共顶部导航栏（Logo + Links + 右侧插槽）。
 * 取代每个 View 重复声明的 header，方便新增/删除面板只改一处。
 */
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <header class="app-nav">
    <div class="nav-left">
      <div class="brand">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" class="brand-icon">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
                stroke="#7c3aed" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span class="brand-text">ScholarPilot</span>
        <span class="brand-badge">DEVTOOLS</span>
      </div>
      <nav class="nav-links">
        <router-link to="/" class="nav-link">Dashboard</router-link>
        <router-link to="/sources" class="nav-link">Sources</router-link>
        <router-link to="/local-data" class="nav-link">Local Data</router-link>
        <router-link to="/logs" class="nav-link">Logs</router-link>
        <router-link to="/users" class="nav-link">Users</router-link>
        <router-link to="/telemetry" class="nav-link">Telemetry</router-link>
        <router-link to="/cleanup" class="nav-link">Cleanup</router-link>
      </nav>
    </div>
    <div class="nav-right">
      <slot name="actions" />
      <span class="user-email mono">{{ auth.user?.email }}</span>
      <button class="logout-btn" @click="handleLogout">Logout</button>
    </div>
  </header>
</template>

<style scoped>
.app-nav {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: rgba(10, 10, 26, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(42, 42, 74, 0.4);
}

.nav-left { display: flex; align-items: center; }

.brand { display: flex; align-items: center; gap: 10px; }
.brand-icon { filter: drop-shadow(0 0 6px rgba(124, 58, 237, 0.5)); }
.brand-text { font-size: 18px; font-weight: 700; color: #fff; letter-spacing: -0.3px; }
.brand-badge {
  font-size: 9px;
  font-weight: 700;
  color: #7c3aed;
  background: rgba(124, 58, 237, 0.12);
  border: 1px solid rgba(124, 58, 237, 0.25);
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: 2px;
}

.nav-links {
  display: flex;
  gap: 4px;
  margin-left: 24px;
}
.nav-link {
  font-size: 12px;
  font-weight: 600;
  color: #8888aa;
  text-decoration: none;
  padding: 4px 12px;
  border-radius: 6px;
  transition: all 0.2s;
}
.nav-link:hover { color: #c4b5fd; background: rgba(124, 58, 237, 0.1); }
.nav-link.router-link-exact-active { color: #c4b5fd; background: rgba(124, 58, 237, 0.15); }

.nav-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.user-email { font-size: 12px; color: #8888aa; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

.logout-btn {
  padding: 5px 14px;
  border: 1px solid rgba(248, 113, 113, 0.25);
  border-radius: 6px;
  background: rgba(248, 113, 113, 0.06);
  color: #f87171;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.logout-btn:hover {
  background: rgba(248, 113, 113, 0.12);
  border-color: rgba(248, 113, 113, 0.4);
}
</style>
