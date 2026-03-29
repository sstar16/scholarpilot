<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="always">
      <div class="logo">
        <h1>🔬 科研情报平台</h1>
        <p class="subtitle">URIP · 智能文献检索与追踪</p>
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
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card { width: 400px; padding: 20px; }
.logo { text-align: center; margin-bottom: 24px; }
.logo h1 { font-size: 24px; margin: 0; color: #303133; }
.subtitle { color: #909399; margin: 4px 0 0; font-size: 14px; }
.bottom-links { text-align: center; margin-top: 16px; font-size: 14px; }
</style>
