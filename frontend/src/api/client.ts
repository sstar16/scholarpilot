import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30000,
})

// 自动注入 JWT
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('urip_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 401 自动跳转登录
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('urip_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api

export const authApi = {
  register: (data: { email: string; name: string; password: string }) =>
    api.post('/api/auth/register', data),
  login: (data: { email: string; password: string }) =>
    api.post('/api/auth/login', data),
  me: () => api.get('/api/auth/me'),
}

export const projectApi = {
  list: () => api.get('/api/projects'),
  create: (data: any) =>
    api.post('/api/projects', data),
  get: (id: string) => api.get(`/api/projects/${id}`),
  update: (id: string, data: any) => api.patch(`/api/projects/${id}`, data),
  delete: (id: string) => api.delete(`/api/projects/${id}`),
}

export const searchApi = {
  startRound: (projectId: string) =>
    api.post(`/api/projects/${projectId}/rounds/start`),
  getRoundStatus: (projectId: string, roundId: string) =>
    api.get(`/api/projects/${projectId}/rounds/${roundId}/status`),
  getRoundResults: (projectId: string, roundId: string) =>
    api.get(`/api/projects/${projectId}/rounds/${roundId}/results`),
  listRounds: (projectId: string) =>
    api.get(`/api/projects/${projectId}/rounds`),
}

export const feedbackApi = {
  submit: (projectId: string, roundId: string, feedbacks: any[]) =>
    api.post(`/api/projects/${projectId}/rounds/${roundId}/feedback`, { feedbacks }),
}

export const sseApi = {
  getRoundStreamUrl: (roundId: string) => {
    const token = localStorage.getItem('urip_token')
    const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
    return `${baseUrl}/api/stream/rounds/${roundId}?token=${token}`
  }
}

export const llmApi = {
  listProviders: () => api.get('/api/llm/providers'),
  configureProvider: (data: any) => api.post('/api/llm/configure', data),
  switchProvider: (providerId: string) => api.post(`/api/llm/switch/${providerId}`),
  testProvider: () => api.get('/api/llm/test'),
  deleteProvider: (providerId: string) => api.delete(`/api/llm/${providerId}`),
}
