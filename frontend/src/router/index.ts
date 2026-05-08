import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
  // Register 复用 Login 的高保真 hero 场景，通过 query.mode 切换为注册表单
  { path: '/register', redirect: { path: '/login', query: { mode: 'register' } }, meta: { public: true } },
  {
    // Dashboard 独立：HomeJournal 自带 masthead，不嵌 AppLayout 顶栏
    path: '/dashboard',
    component: () => import('../views/HomeJournal.vue'),
  },
  {
    // Settings 独立：期刊风 settings 自带 masthead
    path: '/settings',
    component: () => import('../views/Settings.vue'),
  },
  {
    // Profile 独立：期刊风 profile 自带 masthead
    path: '/profile',
    component: () => import('../views/ProfilePage.vue'),
  },
  {
    // Memory 独立：期刊风 .md 记忆（用户级 + 项目级）
    path: '/memory',
    component: () => import('../views/MemoryPage.vue'),
  },
  {
    path: '/',
    component: () => import('../views/AppLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'projects/new', component: () => import('../views/ConversationCreate.vue') },
      { path: 'projects/new-legacy', component: () => import('../views/ProjectCreate.vue') },
      { path: 'projects/:id', component: () => import('../views/ProjectView.vue') },
      { path: 'admin/feedback', component: () => import('../views/AdminFeedback.vue') },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳转到 /login
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.token) {
    return '/login'
  }
})
