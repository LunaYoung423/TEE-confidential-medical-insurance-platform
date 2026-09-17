<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>审计日志</span>
          <div class="header-right">
            <el-button @click="openAlertRuleModal">告警规则配置</el-button>
            <el-select v-model="exportFormat" placeholder="导出格式" style="width: 140px" size="small">
              <el-option value="json" label="JSON" />
              <el-option value="csv" label="CSV" />
            </el-select>
            <el-button type="primary" @click="exportAudit">导出</el-button>
          </div>
        </div>
      </template>

      <div class="filters">
        <el-select v-model="filters.timePreset" placeholder="时间范围" style="width: 180px" @change="load">
          <el-option value="1h" label="最近1小时" />
          <el-option value="today" label="今天" />
          <el-option value="week" label="本周" />
          <el-option value="custom" label="自定义" />
        </el-select>

        <el-date-picker
          v-if="filters.timePreset === 'custom'"
          v-model="filters.range"
          type="datetimerange"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="YYYY-MM-DDTHH:mm:ss"
          @change="load"
        />

        <el-select
          v-model="filters.types"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="操作类型"
          style="width: 320px"
          @change="load"
        >
          <el-option value="创建容器" label="创建容器" />
          <el-option value="远程证明" label="远程证明" />
          <el-option value="数据与算法" label="数据与算法" />
          <el-option value="DEK加密" label="DEK加密" />
          <el-option value="密钥注入" label="密钥注入" />
          <el-option value="开始训练" label="开始训练" />
          <el-option value="完成下载" label="完成下载" />
        </el-select>

        <el-input
          v-model="filters.objectIdLike"
          placeholder="对象ID（模糊匹配）"
          style="width: 220px"
          clearable
          @input="debouncedLoad"
        />

        <el-select v-model="filters.results" multiple collapse-tags collapse-tags-tooltip placeholder="结果" style="width: 220px" @change="load">
          <el-option value="success" label="成功" />
          <el-option value="fail" label="失败" />
        </el-select>

        <el-button @click="load" type="primary" plain>查询</el-button>
      </div>

      <el-table
        :data="rows"
        border
        stripe
        size="small"
        v-loading="loading"
        style="width: 100%; margin-top: 12px"
      >
        <el-table-column prop="time_fmt" label="时间" width="190" sortable />
        <el-table-column prop="operation_type" label="操作类型" width="140" />
        <el-table-column prop="object_type" label="操作对象" width="160" />
        <el-table-column prop="object_id" label="对象ID" width="150" />
        <el-table-column prop="actor" label="操作人" width="120" />
        <el-table-column prop="result" label="结果" width="120">
          <template #default="{ row }">
            <el-tag :type="row.result === 'success' ? 'success' : 'danger'" effect="dark" round>
              {{ row.result === 'success' ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="详情" width="130">
          <template #default="{ row }">
            <el-popover placement="right" trigger="click" width="520">
              <template #reference>
                <el-button size="small">展开</el-button>
              </template>
              <pre class="json-pre">{{ row.detail_json }}</pre>
            </el-popover>
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

    <el-drawer v-model="detailDrawer.open" size="520px" title="审计事件详情（JSON）">
      <pre class="json-pre">{{ detailDrawer.detailJson }}</pre>
    </el-drawer>

    <el-dialog v-model="alertRuleModal.open" title="告警规则配置（演示版）" width="780px">
      <el-form label-width="140px" :model="alertRuleForm">
        <el-form-item label="规则名称">
          <el-input v-model="alertRuleForm.name" placeholder="例如：证明失败告警" />
        </el-form-item>
        <el-form-item label="规则描述">
          <el-input
            v-model="alertRuleForm.desc"
            placeholder="例如：1分钟内同一节点证明失败>3次"
          />
        </el-form-item>
        <el-form-item label="阈值（演示）">
          <el-input-number v-model="alertRuleForm.threshold" :min="0" />
        </el-form-item>
      </el-form>

      <el-alert type="info" show-icon :closable="false" style="margin-top: 12px" title="规则将保存在浏览器localStorage（演示）" />

      <div style="margin-top: 12px">
        <div style="font-weight: 800; margin-bottom: 8px">已保存的规则</div>
        <el-table :data="savedRules" size="small" border stripe>
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="desc" label="描述" />
          <el-table-column prop="threshold" label="阈值" width="100" />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" type="danger" @click="removeRule(row.name)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template #footer>
        <el-button @click="alertRuleModal.open = false">关闭</el-button>
        <el-button type="primary" @click="saveRule">保存规则</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import { exportAuditLogs, getAuditLogs } from '../../api'

const route = useRoute()

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = reactive({ page: 1, size: 10 })
const exportFormat = ref('json')

const filters = reactive({
  timePreset: '1h',
  range: [],
  types: [],
  objectIdLike: '',
  results: []
})

// 监听路由参数变化，处理时间和结果筛选
watch(
  () => route.query,
  (newQuery) => {
    if (newQuery.time === 'today') {
      filters.timePreset = 'today'
    }
    if (newQuery.result) {
      filters.results = [newQuery.result]
    }
    load()
  },
  { immediate: true, deep: true }
)

const debouncedLoadTimer = ref(null)
function debouncedLoad() {
  if (debouncedLoadTimer.value) clearTimeout(debouncedLoadTimer.value)
  debouncedLoadTimer.value = setTimeout(() => {
    load()
  }, 400)
}

const detailDrawer = reactive({ open: false, detailJson: '' })

const alertRuleModal = reactive({ open: false })
const alertRuleForm = reactive({ name: '', desc: '1分钟内同一节点证明失败>3次', threshold: 3 })

const savedRules = ref([])

function loadRulesFromStorage() {
  try {
    const raw = localStorage.getItem('admin_alert_rules') || '[]'
    savedRules.value = JSON.parse(raw)
  } catch {
    savedRules.value = []
  }
}

function openAlertRuleModal() {
  loadRulesFromStorage()
  alertRuleModal.open = true
}

async function removeRule(name) {
  await ElMessageBox.confirm(`确认删除规则：${name}？`, '删除规则', { type: 'warning' })
  savedRules.value = savedRules.value.filter(r => r.name !== name)
  localStorage.setItem('admin_alert_rules', JSON.stringify(savedRules.value))
  ElMessage.success('已删除')
}

function saveRule() {
  if (!alertRuleForm.name) {
    ElMessage.warning('请输入规则名称')
    return
  }
  const next = { name: alertRuleForm.name, desc: alertRuleForm.desc, threshold: alertRuleForm.threshold }
  const idx = savedRules.value.findIndex(r => r.name === next.name)
  if (idx >= 0) savedRules.value[idx] = next
  else savedRules.value.unshift(next)
  localStorage.setItem('admin_alert_rules', JSON.stringify(savedRules.value))
  ElMessage.success('保存成功')
}

function toTimeRange() {
  const now = new Date()
  if (filters.timePreset === 'today') {
    const start = new Date(now)
    start.setHours(0, 0, 0, 0)
    return [toApiLocalIso(start), toApiLocalIso(now)]
  }
  if (filters.timePreset === 'week') {
    const start = new Date(now)
    start.setDate(now.getDate() - 7)
    return [toApiLocalIso(start), toApiLocalIso(now)]
  }
  if (filters.timePreset === '1h') {
    const start = new Date(now.getTime() - 60 * 60 * 1000)
    return [toApiLocalIso(start), toApiLocalIso(now)]
  }
  const [s, e] = filters.range || []
  return [toApiLocalIso(s), toApiLocalIso(e)]
}

function toApiLocalIso(value) {
  if (!value) return ''
  // 自定义时间选择器已按 value-format 产出 YYYY-MM-DDTHH:mm:ss，直接透传
  if (typeof value === 'string') return value
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${y}-${m}-${day}T${hh}:${mm}:${ss}`
}

async function load() {
  loading.value = true
  try {
    const [start_time, end_time] = toTimeRange()
    const res = await getAuditLogs({
      start_time,
      end_time,
      types: filters.types,
      object_id_like: filters.objectIdLike,
      results: filters.results,
      page: page.page,
      size: page.size
    })
    total.value = res.total || 0
    rows.value = (res.items || []).map((x) => ({
      ...x,
      time_fmt: fmtTime(x.time)
    }))
  } finally {
    loading.value = false
  }
}

function fmtTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

async function exportAudit() {
  const [start_time, end_time] = toTimeRange()
  const format = exportFormat.value
  const blob = await exportAuditLogs({
    start_time,
    end_time,
    types: filters.types,
    object_id_like: filters.objectIdLike,
    results: filters.results,
    format
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `audit_logs_${Date.now()}.${format}`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  ElMessage.success('导出成功（演示）')
}

onMounted(async () => {
  // 如果从仪表盘跳转带 select，则可用于加载后高亮（演示：仅加载）
  await load()
  const detailId = route.query.detailId
  if (detailId) {
    const hit = (rows.value || []).find(r => String(r.id) === String(detailId))
    if (hit) {
      detailDrawer.detailJson = hit.detail_json
      detailDrawer.open = true
    } else {
      ElMessage.success('已跳转到审计日志（演示）：未在当前页找到详情：' + String(detailId))
    }
  }
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.header-right {
  display: flex;
  gap: 10px;
  align-items: center;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.json-pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 12px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
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

