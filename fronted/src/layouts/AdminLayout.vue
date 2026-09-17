<template>
  <el-container class="admin-layout">
    <el-aside class="aside" width="240px">
      <div class="logo">
        <div class="logo-mark">TEE</div>
        <div class="logo-text">系统运维</div>
      </div>

      <el-menu
        class="menu"
        :default-active="activePath"
        router
        background-color="transparent"
        text-color="#ffffff"
        active-text-color="#1f63ff"
      >
        <el-menu-item index="/admin/dashboard">
          <el-icon><Odometer /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/admin/nodes">
          <el-icon><Monitor /></el-icon>
          <span>TEE资源池</span>
        </el-menu-item>
        <el-menu-item index="/admin/containers">
          <el-icon><Box /></el-icon>
          <span>机密容器管理</span>
        </el-menu-item>
        <el-menu-item index="/admin/audit-logs">
          <el-icon><Document /></el-icon>
          <span>审计日志</span>
        </el-menu-item>
        <el-menu-item index="/admin/system-config">
          <el-icon><Setting /></el-icon>
          <span>系统配置</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="left">
          <div class="page-title">{{ pageTitle }}</div>
        </div>
        <div class="right">
          <el-button :icon="Refresh" circle @click="refresh" />

          <el-popover placement="bottom-end" trigger="click" width="320">
            <template #reference>
              <el-badge :value="ctx.unhandledAlertsCount" :hidden="ctx.unhandledAlertsCount === 0">
                <el-button circle>
                  <el-icon><Bell /></el-icon>
                </el-button>
              </el-badge>
            </template>
            <div class="noti">
              <div class="noti-title">未处理告警</div>
              <el-empty v-if="!ctx.alerts.length" description="暂无告警" />
              <el-timeline v-else>
                <el-timeline-item
                  v-for="a in ctx.alerts"
                  :key="a.id"
                  :timestamp="fmt(a.time)"
                  :type="a.read ? 'info' : 'danger'"
                >
                  <div :style="{ fontWeight: a.read ? 400 : 700 }">{{ a.title }}</div>
                </el-timeline-item>
              </el-timeline>
              <div class="noti-actions">
                <el-button size="small" @click="ctx.markAllAlertsRead();">全部标记已读</el-button>
              </div>
            </div>
          </el-popover>

          <el-dropdown>
            <span class="avatar">
              <el-avatar :size="32">A</el-avatar>
              <span class="username">系统管理员</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="go('/admin/system-config')">系统设置</el-dropdown-item>
                <el-dropdown-item divided @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view :key="ctx.refreshKey" />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAdminContextStore } from '../stores/adminContext'
import {
  Odometer,
  Monitor,
  Box,
  Document,
  Setting,
  Bell,
  Refresh,
  ArrowDown
} from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const ctx = useAdminContextStore()

const activePath = computed(() => {
  if (route.path.startsWith('/admin/containers/')) return '/admin/containers'
  if (route.path.startsWith('/admin/containers')) return '/admin/containers'
  if (route.path.startsWith('/admin/nodes')) return '/admin/nodes'
  if (route.path.startsWith('/admin/audit-logs')) return '/admin/audit-logs'
  if (route.path.startsWith('/admin/system-config')) return '/admin/system-config'
  if (route.path.startsWith('/admin/dashboard')) return '/admin/dashboard'
  return '/admin/dashboard'
})

const pageTitle = computed(() => {
  if (route.path.startsWith('/admin/dashboard')) return '仪表盘'
  if (route.path.startsWith('/admin/nodes')) return 'TEE资源池'
  if (route.path.startsWith('/admin/containers')) return '机密容器管理'
  if (route.path.startsWith('/admin/audit-logs')) return '审计日志'
  if (route.path.startsWith('/admin/system-config')) return '系统配置'
  return '系统运维'
})

function fmt(iso) {
  try {
    return new Date(iso).toLocaleString()
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
  ElMessage.success('已退出')
  router.push('/login')
}

async function refresh() {
  ctx.bumpRefresh()
  await ctx.bootstrap()
}

onMounted(async () => {
  await ctx.bootstrap()
})
</script>

<style scoped>
.admin-layout {
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
.menu :deep(.el-menu-item.is-active) {
  background: #ffffff !important;
  color: #1f63ff !important;
  font-weight: 800;
}
.menu :deep(.el-menu-item.is-active .el-icon) {
  color: #1f63ff !important;
}
.menu :deep(.el-menu-item:hover),
.menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.16) !important;
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
.noti-actions {
  padding-top: 8px;
  text-align: right;
}
</style>

