<template>
  <div v-loading="loading">
    <el-row :gutter="12" class="top-row">
      <el-col :span="14" class="top-col">
        <el-card class="top-card">
          <template #header>
            <div class="card-header">
              <span>基本信息</span>
              <el-tag :type="statusTagType(task?.status)" effect="light">{{ statusLabel(task?.status) }}</el-tag>
            </div>
          </template>
          <el-descriptions v-if="task" :column="2" border>
            <el-descriptions-item label="任务名称">{{ task.name }}</el-descriptions-item>
            <el-descriptions-item label="用户名">{{ username }}</el-descriptions-item>
            <el-descriptions-item label="场景类型">{{ task.scene_name }}</el-descriptions-item>
            <el-descriptions-item label="算法">{{ task.algorithm }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ fmt(task.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="完成时间">{{ task.finished_at ? fmt(task.finished_at) : '-' }}</el-descriptions-item>
          </el-descriptions>

          <div v-if="task" class="params">
            <div class="params-title">训练参数</div>
            <el-tag v-for="(v, k) in taskParamsSafe" :key="k" style="margin-right: 8px; margin-bottom: 8px">
              {{ k }}={{ v }}
            </el-tag>
          </div>
        </el-card>
      </el-col>

      <el-col :span="10" class="top-col">
        <el-card class="result-download-card top-card">
          <template #header>
            <div class="card-header"><span>下载区</span></div>
          </template>
          <el-alert type="warning" show-icon :closable="false" style="margin-bottom: 12px">
            <template #title>
              <span>
                <strong>密态模型 .enc</strong>：训练侧经证明代理 SM4 封装后的字节流。
                <strong>attestation_report.json</strong>：向导「远程证明」通过后由 controller 落盘的真实证据与 verify 响应。
                <strong>key_material.json</strong>：含 <code>key_id</code>、RSA 信封 <code>wrapped_dek_base64</code> 与
                <code>dek_hex</code>（SM4 明文密钥，可离线解密本任务 CSV 密文）；属高敏感文件，请按单位密钥制度保管。
              </span>
            </template>
          </el-alert>
          <el-table :data="downloadItems" size="small">
            <el-table-column prop="label" label="下载类型" width="160" />
            <el-table-column prop="name" label="文件名" />
            <el-table-column prop="size" label="大小" width="90" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="primary"
                  :disabled="downloadDisabled(row)"
                  @click="download(row)"
                >
                  下载
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="section-card">
      <template #header>
        <div class="card-header"><span>执行时间线</span></div>
      </template>
      <el-empty v-if="!task?.timeline?.length" description="暂无时间线" />
      <div v-else class="timeline-scroll">
        <div class="timeline-track">
          <div v-for="(s, idx) in task.timeline" :key="s.key + idx" class="timeline-node">
            <div class="timeline-dot">✓</div>
            <div class="timeline-card">
              <div class="timeline-title">{{ s.title }}</div>
              <div class="timeline-time">{{ fmt(s.time) }}</div>
            </div>
            <div v-if="idx < task.timeline.length - 1" class="timeline-line"></div>
          </div>
        </div>
      </div>
    </el-card>

    <el-card class="section-card">
      <template #header>
        <div class="card-header"><span>审计摘要</span></div>
      </template>
      <el-table :data="audit" size="small">
        <el-table-column prop="time_fmt" label="时间" width="170" />
        <el-table-column prop="type" label="事件类型" />
        <el-table-column prop="node_name" label="TEE节点名" />
        <el-table-column prop="container_name" label="TEE容器名" />
        <el-table-column prop="result" label="结果" width="90" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { downloadTaskResult, getTaskAudit, getTaskDetail } from '../../api'
import { useUserContextStore } from '../../stores/userContext'

const route = useRoute()
const ctx = useUserContextStore()

const loading = ref(false)
const task = ref(null)
const audit = ref([])
const downloadItems = computed(() => {
  if (!task.value) return []
  const art = task.value.artifacts || {}
  const rows = [
    {
      label: '密态模型',
      file_type: 'model',
      name: `model_${task.value.id}.enc`,
      size: '-',
      needsSuccess: true
    }
  ]
  if (art.attestation_report) {
    rows.push({
      label: '远程证明材料',
      file_type: 'attestation',
      name: 'attestation_report.json',
      size: '-',
      needsSuccess: false
    })
  }
  if (art.key_material) {
    rows.push({
      label: '密钥材料（含 DEK）',
      file_type: 'key',
      name: 'key_material.json',
      size: '-',
      needsSuccess: false
    })
  }
  return rows
})

function downloadDisabled(row) {
  if (!task.value) return true
  if (row.needsSuccess) return task.value.status !== 'success'
  return false
}

const username = computed(() => ctx.user?.username || '医保管理员')

const taskParamsSafe = computed(() => {
  const p = task.value?.params
  return p && typeof p === 'object' && !Array.isArray(p) ? p : {}
})

function fmt(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString()
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

async function download(row) {
  if (!task.value) return
  const ext = row.file_type === 'model' ? 'enc' : 'json'
  try {
    const blob = await downloadTaskResult(task.value.id, row.file_type)
    triggerBrowserDownload(blob, `${task.value.id}_${row.file_type}.${ext}`)
    ElMessage.success('已开始下载')
  } catch (e) {
    ElMessage.error(e?.message || '下载失败')
  }
}

async function load() {
  const id = String(route.params.id || '')
  if (!id) return
  loading.value = true
  audit.value = []
  try {
    task.value = await getTaskDetail(id)
    try {
      const res = await getTaskAudit(id)
      audit.value = (res || []).map(a => ({
        ...a,
        time_fmt: fmt(a.time),
        node_name: a.node_name || task.value?.node_name || '-',
        container_name: a.container_name || task.value?.containerInfo?.name || '-'
      }))
    } catch (e) {
      console.warn('getTaskAudit', e)
      ElMessage.warning(e?.message || '审计摘要加载失败，可稍后刷新重试')
    }
  } catch (e) {
    ElMessage.error(e?.message || '任务详情加载失败')
    task.value = null
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!ctx.accounts.length) await ctx.bootstrap()
  await load()
})

watch(
  () => route.params.id,
  async () => {
    await load()
  }
)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.top-row {
  align-items: stretch;
}
.top-col {
  display: flex;
}
.top-card {
  width: 100%;
  min-height: 320px;
}
.section-card {
  margin-top: 12px;
}
.timeline-scroll {
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 6px;
}
.timeline-track {
  display: flex;
  align-items: flex-start;
  min-width: max-content;
  gap: 10px;
}
.timeline-node {
  display: flex;
  align-items: center;
}
.timeline-dot {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #22c55e;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  box-shadow: 0 2px 8px rgba(34, 197, 94, 0.28);
}
.timeline-card {
  margin-left: 8px;
  min-width: 170px;
  max-width: 210px;
  padding: 10px 12px;
  border: 1px solid #dcfce7;
  background: #f0fdf4;
  border-radius: 10px;
}
.timeline-title {
  font-size: 14px;
  font-weight: 600;
  color: #166534;
  line-height: 1.35;
}
.timeline-time {
  margin-top: 4px;
  font-size: 12px;
  color: #4b5563;
}
.timeline-line {
  width: 26px;
  height: 2px;
  background: #86efac;
  margin-left: 10px;
}

.params {
  margin-top: 12px;
}

.params-title {
  font-weight: 700;
  margin-bottom: 8px;
  color: #0f172a;
}

/* 结果下载区卡片高度与基本信息表一致 */
.result-download-card {
  min-height: 320px;
  display: flex;
  flex-direction: column;
}

/* 审计摘要表在下面填充空间 */
.el-card {
  display: flex;
  flex-direction: column;
}

.el-card__body {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.el-table {
  flex: 1;
}

.el-descriptions {
  flex: 1;
}
</style>

