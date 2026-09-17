<template>
  <el-container class="user-layout">
    <el-aside class="aside" width="240px">
      <div class="logo">
        <div class="logo-mark">TEE</div>
        <div class="logo-text">医保数据管理</div>
      </div>

      <el-menu
        class="menu"
        :default-active="activePath"
        background-color="transparent"
        text-color="#ffffff"
        active-text-color="#1f63ff"
        router
      >
        <el-menu-item index="/user/dashboard">
          <el-icon><Odometer /></el-icon>
          <span>账号看板</span>
        </el-menu-item>
        <el-menu-item index="/user/tasks">
          <el-icon><List /></el-icon>
          <span>任务管理</span>
        </el-menu-item>
        <el-menu-item index="/user/new-task">
          <el-icon><CirclePlus /></el-icon>
          <span>新建任务</span>
        </el-menu-item>
        <el-menu-item index="/user/settings">
          <el-icon><Setting /></el-icon>
          <span>个人设置</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="left">
          <div class="page-title">{{ pageTitle }}</div>
        </div>

        <div class="right">
          <el-popover
            placement="bottom-end"
            width="320"
            trigger="click"
            @show="onNotificationOpen"
          >
            <template #reference>
              <el-badge :value="ctx.unreadNotificationCount" :hidden="ctx.unreadNotificationCount === 0">
                <el-button circle>
                  <el-icon><Bell /></el-icon>
                </el-button>
              </el-badge>
            </template>

            <div class="noti">
              <div class="noti-title">通知</div>
              <el-empty v-if="!ctx.notifications.length" description="暂无通知" />
              <el-timeline v-else>
                <el-timeline-item
                  v-for="n in ctx.notifications"
                  :key="n.id"
                  :timestamp="fmt(n.time)"
                  :type="n.read ? 'info' : 'primary'"
                >
                  <div :style="{ fontWeight: n.read ? 400 : 600 }">{{ n.title }}</div>
                </el-timeline-item>
              </el-timeline>
            </div>
          </el-popover>

          <el-dropdown>
            <span class="avatar">
              <el-avatar :size="32">U</el-avatar>
              <span class="username">{{ displayUsername }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="go('/user/settings')">个人设置</el-dropdown-item>
                <el-dropdown-item divided @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view :key="ctx.currentAccountId" />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserContextStore } from '../stores/userContext'
import { Odometer, List, CirclePlus, Setting, Bell, ArrowDown } from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const ctx = useUserContextStore()

const activePath = computed(() => {
  if (route.path.startsWith('/user/tasks/') && route.params?.id) return '/user/tasks'
  return route.path
})

const pageTitle = computed(() => {
  if (route.path.startsWith('/user/dashboard')) return '账号看板'
  if (route.path.startsWith('/user/tasks/') && route.params?.id) return '任务详情'
  if (route.path.startsWith('/user/tasks')) return '任务管理'
  if (route.path.startsWith('/user/new-task')) return '新建任务'
  if (route.path.startsWith('/user/settings')) return '个人设置'
  return '工作台'
})

function usernameFromToken() {
  try {
    const token = String(localStorage.getItem('token') || '')
    const parts = token.split('.')
    if (parts.length < 2) return ''
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const pad = b64.length % 4 ? '='.repeat(4 - (b64.length % 4)) : ''
    const json = decodeURIComponent(
      atob(b64 + pad)
        .split('')
        .map(c => `%${c.charCodeAt(0).toString(16).padStart(2, '0')}`)
        .join('')
    )
    const payload = JSON.parse(json)
    return String(payload.username || payload.sub || '').trim()
  } catch {
    return ''
  }
}

const displayUsername = computed(() => {
  const fromStorage = String(localStorage.getItem('username') || '').trim()
  if (fromStorage) return fromStorage
  const fromToken = usernameFromToken()
  if (fromToken) return fromToken
  const acc = ctx.currentAccount || {}
  return acc.account_name || acc.name || '用户'
})

function fmt(iso) {
  try {
    const d = new Date(iso)
    return d.toLocaleString()
  } catch {
    return iso
  }
}

function go(p) {
  router.push(p)
}

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('role')
  localStorage.removeItem('username')
  ElMessage.success('已退出')
  router.push('/login')
}

function onNotificationOpen() {
  ctx.markAllNotificationsRead()
}

onMounted(async () => {
  if (!ctx.accounts.length) await ctx.bootstrap()
  if (!localStorage.getItem('username')) {
    const fromToken = usernameFromToken()
    if (fromToken) localStorage.setItem('username', fromToken)
  }
})
</script>

<style scoped>
.user-layout {
  min-height: 100vh;
  background: #f6f8fb;
}
.aside {
  background: #1f63ff;
  color: #ffffff;
  border-right: 1px solid rgba(255, 255, 255, 0.12);
}
.logo {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
}
.logo-mark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #60a5fa, #a78bfa);
  display: grid;
  place-items: center;
  font-weight: 800;
  color: #0b1220;
}
.logo-text {
  font-weight: 700;
  letter-spacing: 0.5px;
}
.menu {
  background: transparent;
  border-right: none;
}

/* Element Plus menu theming (scoped deep selectors) */
.menu :deep(.el-menu-item),
.menu :deep(.el-sub-menu__title) {
  color: #ffffff !important;
  border-radius: 14px;
  margin: 6px 10px;
}
.menu :deep(.el-menu-item .el-icon),
.menu :deep(.el-sub-menu__title .el-icon) {
  color: #ffffff !important;
}
.menu :deep(.el-menu-item:hover),
.menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.16) !important;
}
.menu :deep(.el-menu-item.is-active) {
  background: #ffffff !important;
  color: #1f63ff !important;
  font-weight: 800;
}
.menu :deep(.el-menu-item.is-active .el-icon) {
  color: #1f63ff !important;
}
.header {
  background: #ffffff;
  border-bottom: 1px solid #eef2f7;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
}
.page-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}
.right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.avatar {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
  color: #0f172a;
}
.username {
  font-weight: 600;
}
.main {
  padding: 16px;
}
.noti-title {
  font-weight: 700;
  margin-bottom: 8px;
}
</style>

