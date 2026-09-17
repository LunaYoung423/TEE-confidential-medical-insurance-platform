<template>
  <el-card>
    <template #header>
      <div class="header-row">
        <div class="title">任务管理</div>
        <div class="actions">
          <el-button type="primary" @click="go('/user/new-task')">新建任务</el-button>
        </div>
      </div>
    </template>

    <div class="filters">
      <el-select v-model="filters.status" placeholder="状态" style="width: 180px" @change="load">
        <el-option label="全部" value="all" />
        <el-option label="成功" value="success" />
        <el-option label="运行中" value="running" />
        <el-option label="失败" value="failed" />
      </el-select>

      <el-select v-model="filters.timePreset" placeholder="时间范围" style="width: 180px" @change="applyPreset">
        <el-option label="全部" value="all" />
        <el-option label="今天" value="today" />
        <el-option label="本周" value="week" />
        <el-option label="本月" value="month" />
      </el-select>

      <el-date-picker
        v-model="filters.range"
        type="datetimerange"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        @change="load"
      />
    </div>

    <el-table
      :data="rows"
      style="width: 100%"
    >
      <el-table-column prop="id" label="任务ID" width="100" />
      <el-table-column prop="name" label="任务名称" min-width="180" />
      <el-table-column prop="created_at_fmt" label="创建时间" width="160" />
      <el-table-column prop="finished_at_fmt" label="完成时间" width="160" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" align="left" header-align="left">
        <template #default="{ row }">
          <div style="display: flex; justify-content: flex-start; align-items: center;">
            <el-button size="small" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="row.status === 'success'"
              size="small"
              type="primary"
              @click="openDownload(row)"
              style="margin-left: 8px;"
            >
              下载
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        background
        layout="total, prev, pager, next, sizes"
        :total="total"
        :page-size="page.size"
        :current-page="page.page"
        :page-sizes="[5, 10, 20, 50]"
        @size-change="onSizeChange"
        @current-change="onPageChange"
      />
    </div>
  </el-card>

  <!-- 详情抽屉 -->
  <el-drawer v-model="drawer.open" size="520px" :title="drawer.title">
    <div v-if="drawer.task" class="drawer-body">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="任务ID">{{ drawer.task.id }}</el-descriptions-item>
        <el-descriptions-item label="任务名称">{{ drawer.task.name }}</el-descriptions-item>
        <el-descriptions-item label="算法">{{ drawer.task.algorithm }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusLabel(drawer.task.status) }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ drawer.task.created_at_fmt }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">{{ drawer.task.finished_at_fmt || '-' }}</el-descriptions-item>
      </el-descriptions>

      <div class="drawer-actions">
        <el-button @click="go(`/user/tasks/${drawer.task.id}`)">打开详情页</el-button>
        <el-button
          v-if="drawer.task.status === 'success'"
          type="primary"
          @click="openDownload(drawer.task)"
        >
          下载结果
        </el-button>
      </div>
    </div>
  </el-drawer>

  <!-- 下载弹窗 -->
  <el-dialog v-model="download.open" title="选择下载文件" width="520px">
    <div v-if="download.task">
      <el-alert
        type="info"
        show-icon
        :closable="false"
        title="提示：文件已使用您的公钥加密，下载后请用私钥解密"
        style="margin-bottom: 12px"
      />

      <el-radio-group v-model="download.fileType">
        <el-radio-button label="model">模型下载</el-radio-button>
        <el-radio-button label="attestation">远程证明报告</el-radio-button>
        <el-radio-button label="key">密钥材料</el-radio-button>
      </el-radio-group>
    </div>
    <template #footer>
      <el-button @click="download.open = false">取消</el-button>
      <el-button type="primary" :loading="download.loading" @click="doDownload">
        下载
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { downloadTaskResult, getTasks } from '../../api'
import { useUserContextStore } from '../../stores/userContext'

const router = useRouter()
const route = useRoute()
const ctx = useUserContextStore()

const filters = reactive({
  status: 'all',
  timePreset: 'week',
  range: []
})

const page = reactive({ page: 1, size: 10 })
const total = ref(0)
const rows = ref([])
const pollingTimer = ref(null)
const loading = ref(false)

const drawer = reactive({ open: false, title: '任务详情', task: null })
const download = reactive({ open: false, task: null, fileType: 'model', loading: false })

function go(p) {
  router.push(p)
}

function statusLabel(s) {
  if (s === 'success') return '成功'
  if (s === 'running') return '运行中'
  if (s === 'failed') return '失败'
  return s || '-'
}

function statusTagType(s) {
  if (s === 'success') return 'success'
  if (s === 'running') return 'primary'
  if (s === 'failed') return 'danger'
  return 'info'
}

function fmt(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

function stripTaskIdSuffix(name, taskId) {
  const n = String(name || '').trim()
  const id = String(taskId || '').trim()
  if (!n || !id) return n
  const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return n
    .replace(new RegExp(`\\s*\\(${escaped}\\)\\s*$`), '')
    .replace(new RegExp(`\\s*（${escaped}）\\s*$`), '')
    .trim()
}

function applyPreset() {
  if (filters.timePreset === 'all') {
    filters.range = []
    page.page = 1
    load()
    return
  }
  const [startAt, endAt] = resolveRangeByPreset()
  filters.range = [startAt, endAt]
  page.page = 1
  load()
}

function resolveRangeByPreset() {
  const now = new Date()
  const start = new Date(now)
  if (filters.timePreset === 'today') {
    start.setHours(0, 0, 0, 0)
  } else if (filters.timePreset === 'week') {
    start.setDate(now.getDate() - 7)
  } else if (filters.timePreset === 'month') {
    start.setMonth(now.getMonth() - 1)
  }
  return [start, now]
}

function toApiIso(d) {
  if (!d) return ''
  const dt = d instanceof Date ? d : new Date(d)
  if (Number.isNaN(dt.getTime())) return ''
  // 后端按业务墙钟时间（本地无时区 datetime）过滤，不能传 UTC 的 toISOString()
  const y = dt.getFullYear()
  const m = String(dt.getMonth() + 1).padStart(2, '0')
  const day = String(dt.getDate()).padStart(2, '0')
  const hh = String(dt.getHours()).padStart(2, '0')
  const mm = String(dt.getMinutes()).padStart(2, '0')
  const ss = String(dt.getSeconds()).padStart(2, '0')
  return `${y}-${m}-${day}T${hh}:${mm}:${ss}`
}

async function load() {
  if (!ctx.currentAccountId) return
  if (loading.value) return
  loading.value = true
  let start = null
  let end = null
  // 预设时间范围下，每次查询都用“当前时刻”作为结束时间，避免界面停在旧时间
  if (filters.timePreset === 'today' || filters.timePreset === 'week' || filters.timePreset === 'month') {
    ;[start, end] = resolveRangeByPreset()
    filters.range = [start, end]
  } else if (filters.timePreset === 'all') {
    start = null
    end = null
  } else {
    ;[start, end] = filters.range || []
  }
  try {
    const res = await getTasks({
      account_id: ctx.currentAccountId,
      status: filters.status,
      start_time: toApiIso(start),
      end_time: toApiIso(end),
      page: page.page,
      size: page.size
    })
    total.value = res.total
    rows.value = (res.items || []).map(t => ({
      ...t,
      name: stripTaskIdSuffix(t.name, t.id),
      scene_name: t.scene_name || t.scene,
      created_at_fmt: fmt(t.created_at),
      finished_at_fmt: t.finished_at ? fmt(t.finished_at) : ''
    }))
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  // 任务状态实时刷新：每 5 秒拉取一次当前筛选页
  pollingTimer.value = setInterval(() => {
    load()
  }, 5000)
}

function stopPolling() {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}

function handleVisibilityChange() {
  if (document.hidden) return
  load()
}

function onSizeChange(s) {
  page.size = s
  page.page = 1
  load()
}

function onPageChange(p) {
  page.page = p
  load()
}

function openDetail(row) {
  drawer.task = row
  drawer.open = true
}

function openDownload(row) {
  download.task = row
  download.fileType = 'model'
  download.open = true
}

function triggerBrowserDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function doDownload() {
  if (!download.task) return
  download.loading = true
  try {
    const blob = await downloadTaskResult(download.task.id, download.fileType)
    const ext = download.fileType === 'model' ? 'enc' : 'json'
    const filename = `${download.task.id}_${download.fileType}.${ext}`
    triggerBrowserDownload(blob, filename)
    ElMessage.success('已开始下载')
    download.open = false
  } finally {
    download.loading = false
  }
}

onMounted(async () => {
  if (!ctx.accounts.length) await ctx.bootstrap()
  
  // 检查URL参数中的status
  const urlStatus = route.query.status
  if (urlStatus) {
    filters.status = urlStatus
  }
  
  applyPreset()
  await load()
  startPolling()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

watch(
  () => ctx.currentAccountId,
  async () => {
    page.page = 1
    await load()
  }
)

// 监听URL参数变化
watch(
  () => route.query.status,
  async (newStatus) => {
    if (newStatus) {
      filters.status = newStatus
      page.page = 1
      await load()
    }
  }
)
</script>

<style scoped>
.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.title {
  font-weight: 800;
}
.actions {
  display: flex;
  gap: 10px;
}
.filters {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.drawer-body {
  display: grid;
  gap: 12px;
}
.drawer-actions {
  display: flex;
  gap: 10px;
}
/* 表头文字居中对齐 */
:deep(.el-table__header-wrapper th) {
  text-align: center !important;
}
/* 表格内容居中对齐 */
:deep(.el-table__body-wrapper td) {
  text-align: center !important;
}
</style>

