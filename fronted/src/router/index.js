import { createRouter, createWebHistory } from 'vue-router'
import Login from '../pages/Login.vue'
import UserLayout from '../layouts/UserLayout.vue'
import UserDashboard from '../pages/user/Dashboard.vue'
import UserTasks from '../pages/user/TaskManagement.vue'
import UserTaskDetail from '../pages/user/TaskDetail.vue'
import UserNewTask from '../pages/user/NewTaskWizard.vue'
import UserSettings from '../pages/user/UserSettings.vue'
import AdminLayout from '../layouts/AdminLayout.vue'
import AdminDashboard from '../pages/admin/Dashboard.vue'
import AdminNodes from '../pages/admin/NodePool.vue'
import AdminContainers from '../pages/admin/Containers.vue'
import AdminContainerDetail from '../pages/admin/ContainerDetail.vue'
import AdminAuditLogs from '../pages/admin/AuditLogs.vue'
import AdminSystemConfig from '../pages/admin/SystemConfig.vue'

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', component: Login },

  // 普通用户（医保数据管理员）界面
  {
    path: '/user',
    component: UserLayout,
    meta: { requiresAuth: true, role: 'user' },
    children: [
      { path: '', redirect: '/user/dashboard' },
      { path: 'dashboard', component: UserDashboard },
      { path: 'tasks', component: UserTasks },
      { path: 'tasks/:id', component: UserTaskDetail },
      { path: 'new-task', component: UserNewTask },
      { path: 'settings', component: UserSettings }
    ]
  },

  // 管理员界面（系统管理）
  {
    path: '/admin',
    component: AdminLayout,
    meta: { requiresAuth: true, role: 'admin' },
    children: [
      { path: '', redirect: '/admin/dashboard' },
      { path: 'dashboard', component: AdminDashboard },
      { path: 'nodes', component: AdminNodes },
      { path: 'containers', component: AdminContainers },
      { path: 'containers/:id', component: AdminContainerDetail },
      { path: 'audit-logs', component: AdminAuditLogs },
      { path: 'attestation-reports', redirect: '/admin/dashboard' },
      { path: 'system-config', component: AdminSystemConfig }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  const role = localStorage.getItem('role') || 'user'
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else {
    // 角色级路由隔离（演示版）
    if (token && role === 'user' && to.path !== '/login' && !to.path.startsWith('/user')) {
      next('/user/dashboard')
      return
    }
    if (token && role === 'admin' && to.path !== '/login' && !to.path.startsWith('/admin')) {
      next('/admin/dashboard')
      return
    }
    next()
  }
})

export default router