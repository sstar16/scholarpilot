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
    path: '/',
    component: () => import('../views/AppLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'projects/new', component: () => import('../views/ConversationCreate.vue') },
      { path: 'projects/new-legacy', component: () => import('../views/ProjectCreate.vue') },
      { path: 'projects/:id', component: () => import('../views/ProjectView.vue') },
      {
        // 知识图谱独立全屏页（C11）：基于客户端 GraphRepo 本地数据 + cytoscape，
        // 与 components/graph/KnowledgeGraphView dialog（后端 bucket-aware API）并存。
        path: 'projects/:projectId/graph',
        name: 'KnowledgeGraph',
        component: () => import('../views/KnowledgeGraph.vue'),
      },
      { path: 'admin/feedback', component: () => import('../views/AdminFeedback.vue'), meta: { requiresAdmin: true } },
      { path: 'admin/users', component: () => import('../views/AdminUsers.vue'), meta: { requiresAdmin: true } },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳转到 /login；requiresAdmin 路由非 admin 跳 /dashboard
// 首次启动时 ensureInit 会从 OS keychain hydrate token 到 store ref；
// 之后 token 保持同步访问，每次路由判断不再触发 keychain I/O。
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.ensureInit()
  if (!to.meta.public && !auth.token) {
    return '/login'
  }
  if (to.meta.requiresAdmin && !auth.user?.is_admin) {
    return '/dashboard'
  }
})
