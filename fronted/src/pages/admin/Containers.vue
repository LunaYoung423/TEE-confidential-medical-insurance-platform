<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>机密容器管理</span>
          <div class="header-right">
            <el-button
              type="danger"
              :disabled="!selected.length"
              @click="batchDestroy"
            >
              批量销毁
            </el-button>
          </div>
        </div>
      </template>

      <div class="filters">
        <el-select v-model="filters.status" placeholder="状态" style="width: 160px" clearable @change="load">
          <el-option value="Pending" label="等待中" />
          <el-option value="InProgress" label="进行中" />
        </el-select>

        <el-select v-model="filters.nodeId" placeholder="节点" style="width: 200px" clearable @change="load">
          <el-option v-for="n in nodes" :key="n.id" :value="n.id" :label="n.name" />
        </el-select>
      </div>

      <el-alert
        type="warning"
        show-icon
        :closable="false"
        title="提醒：10分钟不使用的容器将自动删除"
        style="margin: 10px 0 2px"
      />

      <el-table
        :data="rows"
        border
        stripe
        style="width: 100%; margin-top: 12px"
        v-loading="loading"
        @selection-change="onSelect"
        row-key="id"
        :default-sort="{ prop: 'created_at', order: 'descending' }"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column prop="name" label="容器名" min-width="180" />
        <el-table-column prop="image" label="镜像" min-width="240" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" effect="dark" round>
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="node_name" label="所在节点" width="160" />
        <el-table-column label="容器与csv保护区内存占比" min-width="260">
          <template #default="{ row }">
            <el-progress :percentage="row.mem_pct" :stroke-width="10" />
            <div class="epc-text">{{ row.mem_used_mb }}MB / {{ row.mem_total_mb }}MB</div>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="200">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="goDetail(row.id)">详情</el-button>
            <el-button size="small" @click="pause(row)" :disabled="row.status !== 'InProgress'">暂停</el-button>
            <el-button size="small" type="danger" @click="destroy(row)">销毁</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          background
          layout="total, prev, pager, next"
          :total="total"
          :page-size="page.size"
          :current-page="page.page"
          @current-change="p => { page.page = p; load(); }"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteContainers,
  getAdminContainers,
  getAdminNodes,
  pauseContainer,
  destroyAdminContainer
} from '../../api'

const router = useRouter()
const route = useRoute()

const nodes = ref([])
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = reactive({ page: 1, size: 10 })

const filters = reactive({
  status: '',
  nodeId: ''
})

function syncStatusFilterFromRoute() {
  const q = route.query.status
  if (q === undefined || q === null || q === '') {
    filters.status = ''
    return
  }
  let s = String(q)
  if (s === 'Running') s = 'InProgress'
  if (s === 'Stopped' || s === 'Failed') s = ''
  filters.status = s
}

watch(
  () => route.query.status,
  () => {
    syncStatusFilterFromRoute()
    load()
  }
)

const selected = ref([])

function statusTagType(s) {
  if (s === 'InProgress') return 'success'
  if (s === 'Pending') return 'info'
  return 'info'
}

function statusText(s) {
  if (s === 'InProgress') return '进行中'
  if (s === 'Pending') return '等待中'
  return s || '-'
}

function formatDate(dateString) {
  if (!dateString) return '-'
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function onSelect(list) {
  selected.value = list
}

async function load() {
  loading.value = true
  try {
    const res = await getAdminContainers({
      status: filters.status,
      node_id: filters.nodeId,
      page: page.page,
      size: page.size
    })
    total.value = res.total || 0
    const nodeNameMap = Object.fromEntries(nodes.value.map(n => [n.id, n.name]))
    rows.value = (res.items || []).map(c => ({
      ...c,
      node_name: nodeNameMap[c.node_id] || c.node_name || '-',
      mem_pct: Math.max(0, Math.min(100, Math.round(Number(c.mem_pct) || 0))),
      mem_used_mb: Math.max(0, Math.round(Number(c.mem_used_mb) || 0)),
      mem_total_mb: Math.max(1, Math.round(Number(c.mem_total_mb) || c.epc_limit_mb || 512))
    }))
  } finally {
    loading.value = false
  }
}

function goDetail(id) {
  router.push(`/admin/containers/${id}`)
}

async function batchDestroy() {
  if (!selected.value.length) return
  await ElMessageBox.confirm(`确认批量销毁 ${selected.value.length} 个容器？`, '批量销毁', { type: 'warning' })
  const ids = selected.value.map(x => x.id)
  await deleteContainers(ids)
  ElMessage.success('批量销毁成功')
  selected.value = []
  await load()
}

async function destroy(row) {
  await ElMessageBox.confirm(`确认销毁容器：${row.name}？`, '销毁', { type: 'warning' })
  await destroyAdminContainer(row.id)
  ElMessage.success('已销毁')
  await load()
}

async function pause(row) {
  try {
    await pauseContainer(row.id)
    ElMessage.success('已暂停')
    await load()
  } catch (error) {
    ElMessage.error(error?.message || '暂停失败')
  }
}

onMounted(async () => {
  const ns = await getAdminNodes()
  nodes.value = ns || []
  syncStatusFilterFromRoute()
  await load()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-right {
  display: flex;
  gap: 10px;
}
.filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.epc-text {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
:deep(.el-table__header-wrapper th) {
  text-align: center !important;
}
:deep(.el-table__body-wrapper td) {
  text-align: center !important;
}
</style>
