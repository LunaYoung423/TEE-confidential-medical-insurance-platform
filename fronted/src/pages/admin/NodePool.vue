<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>TEE资源池 / 节点列表</span>
        </div>
      </template>

      <el-table :data="nodes" v-loading="loading" border stripe style="width: 100%" row-key="id">
        <el-table-column prop="name" label="节点名" min-width="120" />
        <el-table-column prop="cpu_model" label="CPU型号" min-width="100" />
        <el-table-column label="TEE类型" width="100">
          <template #default="{ row }">
            {{ teeTypeText(row.tee_type) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120" fixed="right">
          <template #default="{ row }">
            <el-tag
              :type="statusTagType(row.status)"
              effect="dark"
              round
            >
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="360" fixed="right">
          <template #default="{ row }">
            <div class="op-scroll">
              <div class="op-line">
                <el-button size="small" @click="openNodeDetail(row)">详情</el-button>
                <el-button
                  size="small"
                  type="success"
                  :disabled="row.status === 'online' || !!powerPhase[row.id]"
                  :loading="powerPhase[row.id] === '打开中'"
                  @click="togglePower(row, true)"
                >
                  {{ powerPhase[row.id] === '打开中' ? '打开中' : '打开' }}
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  plain
                  :disabled="row.status !== 'online' || !!powerPhase[row.id]"
                  :loading="powerPhase[row.id] === '关闭中'"
                  @click="togglePower(row, false)"
                >
                  {{ powerPhase[row.id] === '关闭中' ? '关闭中' : '关闭' }}
                </el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="resourceActionId === row.id"
                  :disabled="row.status !== 'online' || resourceActionId === row.id"
                  @click="scaleUp(row)"
                >
                  扩容
                </el-button>
                <el-button
                  size="small"
                  type="info"
                  :loading="resourceActionId === row.id"
                  :disabled="row.status !== 'online' || resourceActionId === row.id"
                  @click="scaleDown(row)"
                >
                  缩容
                </el-button>
                <el-button size="small" type="warning" @click="drainNode(row)" :disabled="row.status !== 'online'">
                  排水
                </el-button>
                <el-button size="small" type="danger" @click="deleteNode(row)" :disabled="row.status === 'offline'">
                  删除节点
                </el-button>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-top: 12px">
      <template #header>
        <div class="card-header">
          <span>节点资源使用监控</span>
          <el-select
            v-model="selectedNodeId"
            placeholder="选择TEE节点"
            style="width: 220px"
            @change="renderResourceCharts"
          >
            <el-option v-for="n in nodes" :key="n.id" :label="n.name" :value="n.id" />
          </el-select>
        </div>
      </template>
      <el-empty v-if="!selectedNode" description="暂无节点数据" />
      <el-row v-else :gutter="12">
        <el-col :span="14">
          <el-card shadow="never">
            <template #header>
              <div class="sub-title">CPU使用率趋势</div>
            </template>
            <div ref="cpuChartRef" class="monitor-chart"></div>
          </el-card>
        </el-col>
        <el-col :span="10">
          <el-card shadow="never">
            <template #header>
              <div class="sub-title">
                csv保护内存使用率
                <el-tooltip
                  content="统计口径：仅统计 csv-* 与 cc-training 训练容器内存；8192MB等数值是当前节点配置总容量，不是宿主机总内存"
                  placement="top"
                >
                  <el-tag size="small" effect="plain" type="info" style="margin-left: 8px;">说明</el-tag>
                </el-tooltip>
              </div>
            </template>
            <div ref="memChartRef" class="monitor-chart"></div>
          </el-card>
        </el-col>
      </el-row>
    </el-card>

    <!-- 节点详情抽屉 -->
    <el-drawer v-model="nodeDrawer.open" size="520px" :title="nodeDrawer.node?.name || '节点详情'">
      <div v-if="nodeDrawer.node">
        <el-card>
          <template #header>
            <div class="card-header"><span>硬件信息</span></div>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="内核版本">{{ nodeDrawer.node.hardware?.kernel_version || '-' }}</el-descriptions-item>
            <el-descriptions-item label="TEE驱动版本">{{ nodeDrawer.node.hardware?.tee_driver_version || '-' }}</el-descriptions-item>
            <el-descriptions-item label="CPU核数">{{ nodeDrawer.node.hardware?.cpu_cores || '-' }}</el-descriptions-item>
            <el-descriptions-item label="内存总量">{{ nodeDrawer.node.hardware?.memory_total_gb || '-' }} GB</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <el-card style="margin-top: 12px">
          <template #header>
            <div class="card-header"><span>运行中的容器</span></div>
          </template>
          <el-table :data="nodeDrawer.node.running_containers" size="small" v-if="nodeDrawer.node.running_containers?.length" border>
            <el-table-column prop="name" label="容器名" />
            <el-table-column prop="status" label="状态" width="120" />
            <el-table-column label="容器分配内存使用率" width="180">
              <template #default="{ row }">{{ row.epc_used_mb }}MB / {{ row.epc_limit_mb }}MB</template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="无运行中的容器" />
        </el-card>

        <el-card style="margin-top: 12px">
          <template #header>
            <div class="card-header">
              <span>最近5次远程证明记录</span>
              <div class="drawer-actions">
                <el-button size="small" type="primary" @click="triggerProof">触发立即证明</el-button>
                <el-button size="small" @click="restartDriver">重启TEE驱动</el-button>
              </div>
            </div>
          </template>
          <el-table :data="nodeDrawer.node.recent_proofs" size="small" border v-if="nodeDrawer.node.recent_proofs?.length">
            <el-table-column prop="time" label="时间" width="180" />
            <el-table-column prop="result" label="结果" width="120">
              <template #default="{ row }">
                <el-tag :type="row.result === 'pass' ? 'success' : 'danger'" effect="dark" round>
                  {{ row.result === 'pass' ? '通过' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="reason" label="失败原因" />
          </el-table>
          <el-empty v-else description="暂无证明记录" />
        </el-card>

      </div>
    </el-drawer>

  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteNode as deleteNodeApi,
  drainNodeTasks,
  getAdminNodesPanel,
  getNodeDetail,
  getNodeLiveMetrics,
  restartNodeDriver,
  setNodePower,
  triggerNodeAttestation,
  updateCsvResourcesApi
} from '../../api'

const loading = ref(false)
const nodes = ref([])
const selectedNodeId = ref('')
const cpuChartRef = ref(null)
const memChartRef = ref(null)
let cpuChart = null
let memChart = null
let monitorTimer = null
const cpuTimeSeries = ref([])
const cpuValueSeries = ref([])
const liveSnapshot = ref(null)
/** @type {Record<string, string>} 节点 id -> 打开中|关闭中 */
const powerPhase = reactive({})
/** 仅扩容/缩容按钮 loading，避免整表 v-loading 误判为卡死 */
const resourceActionId = ref('')

const nodeDrawer = reactive({ open: false, node: null })
const selectedNode = computed(() => nodes.value.find(n => n.id === selectedNodeId.value) || null)

/** 列表先出、监控后拉，减轻首屏卡顿 */
const METRICS_POLL_MS = 8000

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function apiErr(e) {
  const d = e?.response?.data
  if (d && typeof d === 'object' && d.message) return String(d.message)
  return e?.message || '请求失败'
}

function statusText(s) {
  if (s === 'online') return '在线'
  if (s === 'offline') return '离线'
  if (s === 'maintenance') return '维护中'
  if (s === 'proof_failed') return '证明失败'
  return s
}
function statusTagType(s) {
  if (s === 'online') return 'success'
  if (s === 'offline') return 'danger'
  if (s === 'maintenance') return 'warning'
  if (s === 'proof_failed') return 'warning'
  return 'info'
}

function teeTypeText(type) {
  if (type === 'CSV') return 'CSV'
  if (type === 'TrustZone') return 'TrustZone'
  return type
}

function normalizeCpuForDisplay(cpu, nodeId) {
  const raw = Number(cpu)
  if (!Number.isFinite(raw)) return 0
  const node = nodes.value.find(n => n.id === nodeId)
  // 在线节点若采样值过低，前端按 3% 展示，避免曲线长期贴地难以识别
  if (node?.status === 'online' && raw <= 0) return 3
  return raw
}

function applyLiveMetrics(m) {
  if (!m) return
  liveSnapshot.value = m
  const ts = m.time ? new Date(m.time).getTime() : Date.now()
  const t = Number.isFinite(ts) ? formatClock(ts) : formatClock(Date.now())
  cpuTimeSeries.value.push(t)
  cpuValueSeries.value.push(normalizeCpuForDisplay(m.cpu_percent, selectedNodeId.value))
  if (cpuTimeSeries.value.length > 24) cpuTimeSeries.value.shift()
  if (cpuValueSeries.value.length > 24) cpuValueSeries.value.shift()
  void nextTick(() => renderResourceCharts())
}

async function reloadNodes() {
  loading.value = true
  let panel = { nodes: [], live_metrics: {} }
  try {
    panel = await getAdminNodesPanel()
    nodes.value = panel.nodes || []
    if (!selectedNodeId.value && nodes.value.length) selectedNodeId.value = nodes.value[0].id
    if (selectedNodeId.value && !nodes.value.some(n => n.id === selectedNodeId.value)) {
      selectedNodeId.value = nodes.value[0]?.id || ''
    }
  } finally {
    loading.value = false
  }
  await nextTick()
  const id = selectedNodeId.value
  if (id && panel.live_metrics && panel.live_metrics[id]) {
    applyLiveMetrics(panel.live_metrics[id])
  } else {
    void fetchMetricsTick()
  }
}

function formatClock(ts) {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

async function fetchMetricsTick() {
  const id = selectedNodeId.value
  if (!id) return
  try {
    const m = await getNodeLiveMetrics(id)
    applyLiveMetrics(m)
  } catch {
    /* 忽略单次轮询失败 */
  }
}

function renderCpuChart() {
  if (!selectedNode.value) return

  if (cpuChartRef.value) {
    if (!cpuChart) cpuChart = echarts.init(cpuChartRef.value)
    cpuChart.setOption({
      grid: { left: 36, right: 16, top: 24, bottom: 28 },
      xAxis: { type: 'category', data: cpuTimeSeries.value, boundaryGap: false },
      yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
      series: [{
        type: 'line',
        smooth: false,
        data: cpuValueSeries.value,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { color: '#3b82f6', width: 2.4 },
        itemStyle: { color: '#3b82f6' },
        areaStyle: { color: 'rgba(59,130,246,0.12)' }
      }],
      tooltip: { trigger: 'axis' }
    })
  }
}

function renderMemChart() {
  const m = liveSnapshot.value
  if (!m || !memChartRef.value) return
  // pool_mb = 后端配置的节点总容量；已用可大于总容量（超配）时分扇区展示
  const poolMb = Math.max(1, Number(m.pool_mb) || 0)
  const usedMemMb = Math.max(0, Math.round(Number(m.used_mb) || 0))
  const rawPct = Number(m.csv_memory_pct ?? 0)
  const pctLabel = rawPct > 100 ? `${rawPct.toFixed(1)}%（超配）` : `${rawPct.toFixed(1)}%`
  const inCap = Math.min(usedMemMb, poolMb)
  const over = Math.max(0, usedMemMb - poolMb)
  const free = Math.max(0, poolMb - usedMemMb)
  const activeTrainContainers = Number(m.active_train_containers || 0)
  const noTrainLoad = activeTrainContainers <= 0 && usedMemMb <= 0
  const pieData = []
  if (inCap > 0) {
    pieData.push({
      name: `已用 ${inCap}MB`,
      value: inCap,
      itemStyle: { color: '#10b981' }
    })
  }
  if (over > 0) {
    pieData.push({
      name: `超配 ${over}MB`,
      value: over,
      itemStyle: { color: '#f97316' }
    })
  }
  if (free > 0) {
    pieData.push({
      name: `可用 ${free}MB`,
      value: free,
      itemStyle: { color: '#d1fae5' }
    })
  }
  if (!pieData.length) {
    pieData.push({ name: '暂无', value: 1, itemStyle: { color: '#e2e8f0' } })
  }
  if (!memChart) memChart = echarts.init(memChartRef.value)
  const summaryLine = `已用 ${usedMemMb}MB / 配置 ${Math.round(poolMb)}MB / 占比 ${pctLabel}`
  const loadHint = noTrainLoad ? '当前无训练负载' : ''
  const centerText = `${usedMemMb} / ${Math.round(poolMb)} MB`
  const centerSubtext = noTrainLoad ? `占比 ${pctLabel} · 暂无训练负载` : `占比 ${pctLabel}`
  memChart.setOption({
    title: {
      text: centerText,
      subtext: centerSubtext,
      left: 'center',
      top: '41%',
      textStyle: { fontSize: 14, fontWeight: 700, color: '#334155' },
      subtextStyle: { fontSize: 11, color: '#94a3b8', lineHeight: 16 }
    },
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const hint = loadHint ? `<br/>${loadHint}` : ''
        return `${summaryLine}${hint}<br/>${p.marker}${p.name}: ${p.value}MB（${p.percent}%）`
      }
    },
    series: [{
      type: 'pie',
      radius: ['55%', '78%'],
      label: {
        formatter: (p) => `${p.name}  ${p.percent}%`
      },
      labelLine: { length: 16, length2: 10 },
      data: pieData,
      emphasis: { scale: false }
    }]
  })
}

function renderResourceCharts() {
  renderCpuChart()
  renderMemChart()
}

async function openNodeDetail(row) {
  nodeDrawer.open = true
  nodeDrawer.node = await getNodeDetail(row.id)
}

async function drainNode(row) {
  await ElMessageBox.confirm('确认对该节点执行排水？将尝试迁移任务并进入维护状态。', '排水', { type: 'warning' })
  await drainNodeTasks(row.id)
  ElMessage.success('排水任务已提交')
  await reloadNodes()
}

async function togglePower(row, turnOn) {
  const id = row.id
  if (powerPhase[id]) return
  const label = turnOn ? '打开中' : '关闭中'
  powerPhase[id] = label
  try {
    await sleep(10000)
    await setNodePower(id, turnOn ? 'on' : 'off')
    ElMessage.success(turnOn ? `${row.name} 已开启` : `${row.name} 已关闭`)
  } catch (e) {
    ElMessage.error(apiErr(e))
  } finally {
    delete powerPhase[id]
    await reloadNodes()
  }
}

async function scaleUp(row) {
  resourceActionId.value = row.id
  try {
    const STEP_MB = 1024
    const cur = row.epc_total_mb ?? 8192
    const used = row.epc_used_mb || 0
    // 扩容 = 配置总容量按步增加，不把目标绑到「已用+余量」；仅当配置已低于已用时先抬到合法下限
    let nextTotal = cur + STEP_MB
    if (cur < used) nextTotal = Math.max(used, cur + STEP_MB)
    await updateCsvResourcesApi(row.id, { epc_total_mb: nextTotal })
    ElMessage.success(`扩容成功：${row.name} -> ${nextTotal}MB`)
    await reloadNodes()
  } catch (error) {
    console.error('扩容失败:', error)
    ElMessage.error(apiErr(error))
  } finally {
    resourceActionId.value = ''
  }
}

async function scaleDown(row) {
  resourceActionId.value = row.id
  try {
    const currentUsed = row.epc_used_mb || 0
    const nextTotal = Math.max((row.epc_total_mb || 1024) - 256, 256, currentUsed)
    await updateCsvResourcesApi(row.id, { epc_total_mb: nextTotal })
    ElMessage.success(`缩容成功：${row.name} -> ${nextTotal}MB`)
    await reloadNodes()
  } catch (error) {
    console.error('缩容失败:', error)
    ElMessage.error(apiErr(error))
  } finally {
    resourceActionId.value = ''
  }
}

async function deleteNode(row) {
  await ElMessageBox.confirm('确认删除该节点？将尝试迁移关联任务。', '删除节点', { type: 'warning' })
  await deleteNodeApi(row.id)
  ElMessage.success('节点已删除')
  await reloadNodes()
  nodeDrawer.open = false
}

async function triggerProof() {
  if (!nodeDrawer.node) return
  await triggerNodeAttestation(nodeDrawer.node.id)
  ElMessage.success('已触发远程证明')
  // 只做简单刷新
  nodeDrawer.node = await getNodeDetail(nodeDrawer.node.id)
  await reloadNodes()
}

async function restartDriver() {
  if (!nodeDrawer.node) return
  await restartNodeDriver(nodeDrawer.node.id)
  ElMessage.success('已重启 TEE 驱动')
  nodeDrawer.node = await getNodeDetail(nodeDrawer.node.id)
}

onMounted(async () => {
  await reloadNodes()
  monitorTimer = setInterval(() => {
    fetchMetricsTick()
  }, METRICS_POLL_MS)
})

watch(
  () => selectedNodeId.value,
  async () => {
    cpuTimeSeries.value = []
    cpuValueSeries.value = []
    liveSnapshot.value = null
    await nextTick()
    await fetchMetricsTick()
  }
)

onBeforeUnmount(() => {
  if (monitorTimer) clearInterval(monitorTimer)
  if (cpuChart) cpuChart.dispose()
  if (memChart) memChart.dispose()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.epc-cell {
  min-width: 200px;
}
.drawer-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.sub-title {
  font-weight: 600;
}
.monitor-chart {
  width: 100%;
  height: 240px;
}
.op-scroll {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
}
.op-line {
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  justify-content: flex-start;
  gap: 8px;
  min-width: max-content;
  padding-bottom: 2px;
}
.op-line :deep(.el-button) {
  min-width: 54px;
  padding: 6px 10px;
  margin-left: 0 !important;
  flex: 0 0 auto;
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

