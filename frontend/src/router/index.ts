import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/register', component: () => import('../views/Register.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../views/AppLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'projects/new', component: () => import('../views/ProjectCreate.vue') },
      { path: 'projects/:id', component: () => import('../views/ProjectView.vue') },
      { path: 'settings', component: () => import('../views/Settings.vue') },
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
