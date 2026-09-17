<template>
  <div>
    <el-row :gutter="12">
      <el-col :span="6">
        <el-card class="stat" @click="goToTasks('all')">
          <div class="label">总任务数</div>
          <div class="value">{{ stats.total }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat" @click="goToTasks('success')">
          <div class="label">已完成</div>
          <div class="value success">{{ stats.completed }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat" @click="goToTasks('running')">
          <div class="label">运行中</div>
          <div class="value running">{{ stats.running }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat" @click="goToTasks('success')">
          <div class="label">待下载结果</div>
          <div class="value warn">{{ stats.pending_download }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" class="main-row">
      <el-col :span="14" class="main-left">
        <el-card class="panel-card timeline-card">
          <template #header>
            <div class="card-header">
              <span>最近任务时间轴（5条）</span>
              <el-button text type="primary" @click="go('/user/tasks')">查看全部</el-button>
            </div>
          </template>
          <el-empty v-if="!recentTasks.length" description="暂无任务" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="t in recentTasks"
              :key="t.id"
              :timestamp="fmt(t.created_at)"
              :type="statusType(t.status)"
            >
              <div class="tl-title" @click="go(`/user/tasks/${t.id}`)">{{ t.name }}</div>
              <div class="tl-sub">{{ statusLabel(t.status) }}</div>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>

      <el-col :span="10" class="main-right">
        <el-card class="panel-card quick-card">
          <template #header>
            <div class="card-header">
              <span>快捷操作</span>
            </div>
          </template>
          <div class="quick-body">
            <div class="quick-tip">一键创建新任务并进入向导流程</div>
            <el-button type="primary" class="quick-main-btn" @click="go('/user/new-task')">
              新建理赔训练任务
            </el-button>
            <el-button text type="primary" class="quick-link-btn" @click="go('/user/tasks')">
              查看任务管理
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getAccountStats, getTasks } from '../../api'
import { useUserContextStore } from '../../stores/userContext'

const router = useRouter()
const ctx = useUserContextStore()

const stats = ref({
  total: 0,
  completed: 0,
  running: 0,
  pending_download: 0,
  epc_memory_mb_total: 0
})
const recentTasks = ref([])

const epcCapacityMb = 2048

function fmt(iso) {
  return new Date(iso).toLocaleString()
}

function statusType(s) {
  if (s === 'success') return 'success'
  if (s === 'running') return 'primary'
  if (s === 'failed') return 'danger'
  return 'info'
}

function statusLabel(s) {
  if (s === 'success') return '成功'
  if (s === 'running') return '运行中'
  if (s === 'failed') return '失败'
  return s || '-'
}

function go(p) {
  router.push(p)
}

function goToTasks(status) {
  router.push({
    path: '/user/tasks',
    query: { status: status }
  })
}

async function reload() {
  if (!ctx.currentAccountId) return
  stats.value = await getAccountStats(ctx.currentAccountId)
  const res = await getTasks({ account_id: ctx.currentAccountId, limit: 5 })
  recentTasks.value = res.items || []
}

onMounted(async () => {
  if (!ctx.accounts.length) await ctx.bootstrap()
  await reload()
})

watch(
  () => ctx.currentAccountId,
  async () => {
    await reload()
  }
)
</script>

<style scoped>
.stat {
  cursor: pointer;
  transition: all 0.3s ease;
  border-radius: 12px;
  border: 1px solid #e6edf7;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.05);
  height: 118px;
}

.stat:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.stat .label {
  color: #64748b;
  font-weight: 600;
}

.stat .value {
  font-size: 28px;
  font-weight: 800;
  margin-top: 8px;
  color: #0f172a;
}
.success { color: #16a34a; }
.running { color: #2563eb; }
.warn { color: #f59e0b; }
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 700;
}
.panel-card {
  border-radius: 12px;
  border: 1px solid #e6edf7;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
}
.main-row {
  margin-top: 12px;
  align-items: stretch;
}
.main-left,
.main-right {
  display: flex;
}
.main-left {
  min-height: 320px;
}
.main-right {
  min-height: 320px;
  flex-direction: column;
  gap: 0;
}
.timeline-card {
  width: 100%;
  height: 100%;
}
.quick-card {
  width: 100%;
  height: 100%;
  margin-top: 0;
}
.tl-title {
  font-weight: 700;
  cursor: pointer;
  color: #0f172a;
}
.tl-title:hover {
  color: #2563eb;
}
.tl-sub {
  color: #64748b;
  font-size: 12px;
  margin-top: 2px;
}

:deep(.stat .el-card__body) {
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

:deep(.quick-card .el-card__body) {
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
}

.quick-body {
  padding-top: 6px;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
}

.quick-tip {
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

.quick-main-btn {
  width: 100%;
  height: 40px;
  border-radius: 10px;
  font-weight: 600;
}

.quick-link-btn {
  align-self: flex-end;
  padding-right: 0;
}
:deep(.el-progress-bar__outer) {
  border-radius: 999px;
}

:deep(.el-progress-bar__inner) {
  border-radius: 999px;
}
</style>

