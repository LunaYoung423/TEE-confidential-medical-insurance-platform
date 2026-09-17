<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>远程证明报告查看器</span>
        </div>
      </template>

      <div class="selectors">
        <el-radio-group v-model="mode">
          <el-radio-button label="node">按节点</el-radio-button>
          <el-radio-button label="task">按任务</el-radio-button>
        </el-radio-group>

        <el-select
          v-if="mode === 'node'"
          v-model="selectedNodeId"
          placeholder="选择节点"
          style="width: 260px"
          clearable
          @change="loadReports"
        >
          <el-option v-for="n in nodes" :key="n.id" :value="n.id" :label="`${n.name}(${n.ip})`" />
        </el-select>

        <el-select
          v-if="mode === 'task'"
          v-model="selectedTaskId"
          placeholder="选择任务"
          style="width: 260px"
          clearable
          @change="loadReports"
        >
          <el-option v-for="t in tasks" :key="t.id" :value="t.id" :label="t.name" />
        </el-select>

        <el-select
          v-if="reports.length"
          v-model="selectedReportTime"
          placeholder="选择某次证明记录（时间）"
          style="width: 360px"
          @change="onPickReport"
        >
          <el-option v-for="r in reports" :key="r.time" :value="r.time" :label="fmt(r.time)" />
        </el-select>
      </div>

      <div v-if="selectedReport" class="report-head">
        <el-tag v-if="selectedReport.validation?.passed" type="success" effect="dark" round>
          证明通过
        </el-tag>
        <el-tag v-else type="danger" effect="dark" round>
          证明失败
        </el-tag>
        <div class="kv">
          <div><span class="k">TCB版本：</span><span class="v">{{ selectedReport.validation?.tcb_version || '-' }}</span></div>
          <div><span class="k">PCR值：</span><span class="v">{{ selectedReport.validation?.pcr || '-' }}</span></div>
          <div><span class="k">验证token：</span><span class="v">{{ selectedReport.validation?.token || '-' }}</span></div>
        </div>
      </div>

      <el-row :gutter="12" style="margin-top: 12px" v-if="selectedReport">
        <el-col :span="12">
          <el-card>
            <template #header><div class="card-header"><span>Evidence / Quote / 验证结果（树形）</span></div></template>
            <el-tree :data="treeData" node-key="key" default-expand-all :props="{ children: 'children', label: 'label' }" />
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card>
            <template #header><div class="card-header"><span>对比基准（可选，演示）</span></div></template>
            <el-empty v-if="!selectedReport.benchmark" description="暂无基准报告" />
            <el-table v-else :data="selectedReport.benchmark.diff_rows" size="small" border stripe>
              <el-table-column prop="field" label="字段" />
              <el-table-column prop="base" label="基准" />
              <el-table-column prop="current" label="当前" />
              <el-table-column prop="diff" label="差异" />
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <el-empty v-else description="请选择节点/任务与证明记录" style="margin-top: 12px" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getAdminNodes, getAttestationReports, getAllTasks } from '../../api'

const mode = ref('node')
const nodes = ref([])
const tasks = ref([])

const selectedNodeId = ref('')
const selectedTaskId = ref('')

const reports = ref([])
const selectedReportTime = ref('')
const selectedReport = ref(null)

const treeData = computed(() => {
  if (!selectedReport.value) return []
  return buildTree(selectedReport.value)
})

function fmt(iso) {
  return new Date(iso).toLocaleString()
}

function onPickReport() {
  const t = selectedReportTime.value
  selectedReport.value = reports.value.find(r => r.time === t) || null
}

function buildTree(obj) {
  const walk = (value, keyPath) => {
    if (value === null || value === undefined) {
      return { key: keyPath, label: `${keyPath}: ${String(value)}` }
    }
    if (typeof value !== 'object') {
      return { key: keyPath, label: `${keyPath}: ${String(value)}` }
    }
    const children = []
    if (Array.isArray(value)) {
      value.forEach((v, i) => children.push(walk(v, `${keyPath}[${i}]`)))
      return { key: keyPath, label: `${keyPath}`, children }
    }
    const entries = Object.entries(value)
    entries.forEach(([k, v]) => children.push(walk(v, keyPath ? `${keyPath}.${k}` : k)))
    return { key: keyPath || 'root', label: keyPath || 'root', children }
  }

  // 只取顶层 key 作为根节点，避免树太大
  const top = selectedReport.value
  return Object.entries(top).slice(0, 8).map(([k, v]) => walk(v, k))
}

async function loadReports() {
  try {
    const res = await getAttestationReports({
      node_id: mode.value === 'node' ? selectedNodeId.value : '',
      task_id: mode.value === 'task' ? selectedTaskId.value : '',
      limit: 10
    })
    reports.value = res.items || []
    if (reports.value.length) {
      selectedReportTime.value = reports.value[0].time
      selectedReport.value = reports.value[0]
    } else {
      selectedReport.value = null
      selectedReportTime.value = ''
    }
  } catch (e) {
    ElMessage.error('加载证明报告失败（演示）：' + e.message)
  }
}

onMounted(async () => {
  const [ns, ts] = await Promise.all([getAdminNodes(), getAllTasks()])
  nodes.value = ns || []
  tasks.value = ts || []
  if (nodes.value.length && !selectedNodeId.value) selectedNodeId.value = nodes.value[0].id
  if (tasks.value.length && !selectedTaskId.value) selectedTaskId.value = tasks.value[0].id
  await loadReports()
})

watch(mode, async () => {
  await loadReports()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.selectors {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.report-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-top: 12px;
}
.kv .k {
  display: inline-block;
  width: 92px;
  color: #64748b;
  font-weight: 700;
}
.kv .v {
  color: #0f172a;
  font-weight: 700;
}
.kv > div {
  margin-top: 6px;
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

