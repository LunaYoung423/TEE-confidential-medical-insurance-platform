<template>
  <div class="login-page">
    <div class="login-container">
      <div class="login-left">
        <div class="brand">
          <h1>🔐 密态训练</h1>
          <p>可信执行环境 · 安全协同计算</p>
        </div>
        <div class="feature-list">
          <div class="feature-item">
            <el-icon><Lock /></el-icon>
            <span>硬件级加密隔离</span>
          </div>
          <div class="feature-item">
            <el-icon><Checked /></el-icon>
            <span>远程证明 · 环境可信</span>
          </div>
          <div class="feature-item">
            <el-icon><DataLine /></el-icon>
            <span>密态训练 · 模型安全</span>
          </div>
        </div>
      </div>

      <div class="login-right glass-effect">
        <h2>欢迎回来</h2>
        <p class="subtitle">请登录您的账户</p>
        <el-form @submit.prevent="handleLogin">
          <el-form-item>
            <el-input
              v-model="form.username"
              placeholder="用户名"
              :prefix-icon="User"
              size="large"
              clearable
            />
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              :prefix-icon="Lock"
              size="large"
              show-password
              clearable
            />
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              native-type="submit"
              :loading="loading"
              size="large"
              style="width: 100%"
            >
              登录
            </el-button>
          </el-form-item>
        </el-form>
        <div class="login-footer">
          <el-link type="info" :underline="false">忘记密码？</el-link>
          <el-link type="info" :underline="false">联系管理员</el-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Checked, DataLine } from '@element-plus/icons-vue'
import { login } from '../api'

const router = useRouter()
const form = ref({ username: '', password: '' })
const loading = ref(false)

async function handleLogin() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const res = await login(form.value)
    localStorage.setItem('token', res.token)
    localStorage.setItem('username', (res.user && res.user.username) || form.value.username)
    // 原型：用户名为 admin 则进入管理员界面（其余进入普通用户界面）
    const u = String(form.value.username || '').trim().toLowerCase()
    localStorage.setItem('role', u === 'admin' ? 'admin' : 'user')
    ElMessage.success('登录成功')
    router.push(u === 'admin' ? '/admin/dashboard' : '/user/dashboard')
  } catch (error) {
    ElMessage.error('登录失败：' + error.message)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}
.login-container {
  display: flex;
  width: 100%;
  max-width: 1100px;
  min-height: 600px;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(20px);
  border-radius: 32px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.login-left {
  flex: 1;
  padding: 60px 40px;
  background: rgba(0, 0, 0, 0.2);
  color: white;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.brand h1 {
  font-size: 42px;
  margin-bottom: 10px;
  font-weight: 700;
  background: linear-gradient(45deg, #fff, #e0e7ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.brand p {
  font-size: 16px;
  opacity: 0.8;
  margin-bottom: 40px;
}
.feature-list {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.feature-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 16px;
}
.feature-item .el-icon {
  font-size: 24px;
  color: #a78bfa;
}
.login-right {
  width: 420px;
  padding: 60px 40px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 32px 0 0 32px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.login-right h2 {
  font-size: 32px;
  font-weight: 600;
  color: #2c3e50;
  margin-bottom: 8px;
}
.login-right .subtitle {
  color: #6b7280;
  margin-bottom: 32px;
}
.login-footer {
  display: flex;
  justify-content: space-between;
  margin-top: 20px;
}
.glass-effect {
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.2);
}
@media (max-width: 768px) {
  .login-container {
    flex-direction: column;
    max-width: 100%;
  }
  .login-left {
    display: none;
  }
  .login-right {
    width: 100%;
    border-radius: 32px;
  }
}
</style>