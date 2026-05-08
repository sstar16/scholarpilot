import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api/client'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('urip_token') || '')
  const user = ref<any>(null)

  const isLoggedIn = computed(() => !!token.value)

  async function login(email: string, password: string) {
    const res = await authApi.login({ email, password })
    token.value = res.data.access_token
    localStorage.setItem('urip_token', token.value)
    await fetchMe()
  }

  async function register(email: string, name: string, password: string, invitationCode: string) {
    const res = await authApi.register({ email, name, password, invitation_code: invitationCode })
    token.value = res.data.access_token
    localStorage.setItem('urip_token', token.value)
    await fetchMe()
  }

  async function fetchMe() {
    try {
      const res = await authApi.me()
      user.value = res.data
    } catch {
      logout()
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('urip_token')
  }

  return { token, user, isLoggedIn, login, register, fetchMe, logout }
})
