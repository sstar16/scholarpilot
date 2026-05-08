<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const error = ref('')

async function handleLogin() {
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    router.push('/')
  } catch (e: any) {
    if (e.message === 'Admin access required') {
      error.value = 'Admin access required'
    } else if (e.response?.status === 401) {
      error.value = 'Invalid email or password'
    } else {
      error.value = e.message || 'Login failed'
    }
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <div class="logo-icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
                  stroke="#7c3aed" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <h1>ScholarPilot</h1>
        <p class="subtitle">DevTools Console</p>
      </div>

      <el-form @submit.prevent="handleLogin" class="login-form">
        <el-form-item>
          <el-input
            v-model="email"
            placeholder="Admin Email"
            prefix-icon="User"
            size="large"
            :disabled="auth.loading"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="Password"
            prefix-icon="Lock"
            size="large"
            show-password
            :disabled="auth.loading"
            @keyup.enter="handleLogin"
          />
        </el-form-item>

        <div v-if="error" class="error-msg">{{ error }}</div>

        <el-button
          type="primary"
          size="large"
          :loading="auth.loading"
          class="login-btn"
          @click="handleLogin"
        >
          Sign In
        </el-button>
      </el-form>
    </div>

    <!-- Background grid effect -->
    <div class="grid-bg"></div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 50%, #0a0a1a 100%);
  position: relative;
  overflow: hidden;
}

.grid-bg {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(124, 58, 237, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(124, 58, 237, 0.03) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
}

.login-card {
  position: relative;
  z-index: 1;
  width: 400px;
  max-width: 90vw;
  padding: 48px 40px;
  background: rgba(19, 19, 43, 0.85);
  border: 1px solid rgba(124, 58, 237, 0.25);
  border-radius: 16px;
  backdrop-filter: blur(20px);
  box-shadow:
    0 0 60px rgba(124, 58, 237, 0.08),
    0 25px 50px rgba(0, 0, 0, 0.5);
}

.login-header {
  text-align: center;
  margin-bottom: 36px;
}

.logo-icon {
  margin-bottom: 12px;
  animation: pulse-glow 3s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { filter: drop-shadow(0 0 4px rgba(124, 58, 237, 0.4)); }
  50% { filter: drop-shadow(0 0 12px rgba(124, 58, 237, 0.7)); }
}

.login-header h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  letter-spacing: -0.5px;
}

.subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: #8888aa;
  text-transform: uppercase;
  letter-spacing: 2px;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.login-form :deep(.el-input__wrapper) {
  background: rgba(10, 10, 26, 0.6) !important;
  border-radius: 8px;
  box-shadow: 0 0 0 1px rgba(124, 58, 237, 0.2) inset !important;
  transition: box-shadow 0.2s;
}

.login-form :deep(.el-input__wrapper:hover),
.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px rgba(124, 58, 237, 0.5) inset !important;
}

.login-form :deep(.el-input__inner) {
  color: #e0e0e0 !important;
}

.login-form :deep(.el-input__prefix .el-icon) {
  color: #8888aa;
}

.error-msg {
  color: #f87171;
  font-size: 13px;
  text-align: center;
  padding: 8px;
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.2);
  border-radius: 6px;
  margin-bottom: 8px;
}

.login-btn {
  width: 100%;
  margin-top: 8px;
  border-radius: 8px;
  background: linear-gradient(135deg, #7c3aed, #6d28d9) !important;
  border: none !important;
  font-weight: 600;
  letter-spacing: 0.5px;
  transition: all 0.2s;
}

.login-btn:hover {
  background: linear-gradient(135deg, #8b5cf6, #7c3aed) !important;
  box-shadow: 0 0 20px rgba(124, 58, 237, 0.4);
}
</style>
