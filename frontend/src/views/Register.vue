<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="always">
      <div class="logo">
        <div class="brand">
          <span class="brand-icon">S<span class="brand-dot">.</span>P</span>
        </div>
        <h1>Scholar<b>Pilot</b></h1>
        <p class="subtitle">创建账号（内测阶段）</p>
      </div>
      <el-form :model="form" label-position="top" @submit.prevent="handleRegister">
        <el-form-item label="姓名">
          <el-input v-model="form.name" placeholder="您的姓名" size="large" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" type="email" placeholder="your@email.com" size="large" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="至少 6 位" size="large" show-password />
        </el-form-item>
        <el-form-item label="邀请码">
          <el-input
            v-model="form.invitationCode"
            placeholder="16 位内测邀请码"
            size="large"
            autocomplete="off"
            spellcheck="false"
          />
        </el-form-item>
        <el-button type="primary" native-type="submit" size="large" :loading="loading" style="width:100%">
          注册并开始使用
        </el-button>
      </el-form>
      <div class="bottom-links">
        <router-link to="/login">已有账号？去登录</router-link>
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
const form = reactive({ name: '', email: '', password: '', invitationCode: '' })

async function handleRegister() {
  if (!form.invitationCode.trim()) {
    ElMessage.warning('请填写邀请码')
    return
  }
  loading.value = true
  try {
    await auth.register(form.email, form.name, form.password, form.invitationCode.trim().toLowerCase())
    router.push('/dashboard')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* 与 Login.vue 对齐：dark canvas + radial teal 特例（DESIGN.md 第 4 节唯一允许 gradient 的 surface） */
.login-wrap {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
  position: relative; overflow: hidden;
}
.login-wrap::before {
  content: '';
  position: absolute; width: 600px; height: 600px;
  background: radial-gradient(circle, rgba(13, 148, 136, 0.15) 0%, transparent 70%);
  top: -200px; right: -100px; pointer-events: none;
}
.login-card {
  width: 420px; padding: var(--space-8); border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.97);
  backdrop-filter: blur(20px);
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.25);
  z-index: 1;
}
.logo { text-align: center; margin-bottom: 28px; }
.brand { margin-bottom: var(--space-3); }
.brand-icon {
  font-family: var(--font-body);
  font-size: 36px; font-weight: 700;
  color: var(--ink-900); letter-spacing: 2px;
}
.brand-dot { color: var(--signal-teal); }
.logo h1 {
  font-size: 22px; margin: 0; color: var(--ink-800);
  font-family: var(--font-body); font-weight: 500;
}
.logo h1 b { font-weight: 800; color: var(--ink-900); }
.subtitle { color: var(--ink-300); margin: var(--space-2) 0 0; font-size: var(--type-sub-size); font-weight: 500; }
.bottom-links { text-align: center; margin-top: var(--space-4); font-size: var(--type-body-size); }
</style>
