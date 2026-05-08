import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: { guest: true },
  },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/sources',
    name: 'Sources',
    component: () => import('../views/SourcesView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/local-data',
    name: 'LocalData',
    component: () => import('../views/LocalDataView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/logs',
    name: 'LogsHistory',
    component: () => import('../views/LogsHistoryView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/users',
    name: 'Users',
    component: () => import('../views/UsersView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/telemetry',
    name: 'Telemetry',
    component: () => import('../views/TelemetryView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/cleanup',
    name: 'Cleanup',
    component: () => import('../views/CleanupView.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.meta.requiresAuth) {
    if (!auth.token) {
      return { name: 'Login' }
    }
    if (!auth.user) {
      const ok = await auth.checkAuth()
      if (!ok) return { name: 'Login' }
    }
  }

  if (to.meta.guest && auth.token && auth.user) {
    return { name: 'Dashboard' }
  }
})

export default router
