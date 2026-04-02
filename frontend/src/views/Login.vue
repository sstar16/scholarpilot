<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="always">
      <div class="logo">
        <div class="brand">
          <span class="brand-icon">S<span class="brand-dot">.</span>P</span>
        </div>
        <h1>Scholar<b>Pilot</b></h1>
        <p class="subtitle">AI-Powered Research Intelligence</p>
      </div>
      <el-form :model="form" label-position="top" @submit.prevent="handleLogin">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" type="email" placeholder="your@email.com" size="large" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="••••••••" size="large" show-password />
        </el-form-item>
        <el-button type="primary" native-type="submit" size="large" :loading="loading" style="width:100%">
          登录
        </el-button>
      </el-form>
      <div class="bottom-links">
        <router-link to="/register">还没有账号？立即注册</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ email: '', password: '' })

async function handleLogin() {
  loading.value = true
  try {
    await auth.login(form.email, form.password)
    router.push('/dashboard')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
  position: relative;
  overflow: hidden;
}
.login-wrap::before {
  content: '';
  position: absolute;
  width: 600px; height: 600px;
  background: radial-gradient(circle, rgba(13,148,136,0.15) 0%, transparent 70%);
  top: -200px; right: -100px;
  pointer-events: none;
}
.login-wrap::after {
  content: '';
  position: absolute;
  width: 400px; height: 400px;
  background: radial-gradient(circle, rgba(37,99,235,0.1) 0%, transparent 70%);
  bottom: -150px; left: -50px;
  pointer-events: none;
}
.login-card {
  width: 420px; padding: 32px;
  border-radius: 16px;
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.97);
  backdrop-filter: blur(20px);
  box-shadow: 0 25px 50px rgba(0,0,0,0.25);
  z-index: 1;
}
.logo { text-align: center; margin-bottom: 28px; }
.brand { margin-bottom: 12px; }
.brand-icon {
  font-family: 'DM Sans', sans-serif;
  font-size: 36px; font-weight: 700;
  color: #0f172a; letter-spacing: 2px;
}
.brand-dot { color: #0d9488; }
.logo h1 {
  font-size: 22px; margin: 0; color: #1e293b;
  font-family: 'DM Sans', sans-serif; font-weight: 500;
  letter-spacing: -0.3px;
}
.logo h1 b { font-weight: 800; color: #0f172a; }
.subtitle {
  color: #94a3b8; margin: 6px 0 0; font-size: 13px;
  letter-spacing: 0.5px; font-weight: 500;
}
.bottom-links { text-align: center; margin-top: 16px; font-size: 14px; }
</style>
