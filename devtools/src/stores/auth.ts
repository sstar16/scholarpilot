import { defineStore } from 'pinia'
import { ref } from 'vue'
import { login as apiLogin, getMe } from '../api/client'

export interface AuthUser {
  id: string
  email: string
  name: string
  is_active: boolean
  is_admin: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('devtools_token'))
  const user = ref<AuthUser | null>(null)
  const loading = ref(false)

  async function login(email: string, password: string) {
    loading.value = true
    try {
      const { data } = await apiLogin(email, password)
      const accessToken = data.access_token
      localStorage.setItem('devtools_token', accessToken)
      token.value = accessToken

      const { data: me } = await getMe()
      if (!me.is_admin) {
        logout()
        throw new Error('Admin access required')
      }
      user.value = me
    } finally {
      loading.value = false
    }
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('devtools_token')
  }

  async function checkAuth() {
    if (!token.value) return false
    loading.value = true
    try {
      const { data: me } = await getMe()
      if (!me.is_admin) {
        logout()
        return false
      }
      user.value = me
      return true
    } catch {
      logout()
      return false
    } finally {
      loading.value = false
    }
  }

  return { token, user, loading, login, logout, checkAuth }
})
