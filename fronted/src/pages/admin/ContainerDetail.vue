<template>
  <div class="container-detail-page">
    <el-card class="detail-card block-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">{{ container?.name || '容器' }}</span>
          <div class="card-header-tags">
            <el-tag :type="statusTagType(container?.status)" effect="dark" round>
              {{ statusText(container?.status) || '-' }}
            </el-tag>
          </div>
        </div>
      </template>

      <el-descriptions :column="2" border class="detail-descriptions" size="small">
        <el-descriptions-item label="容器 ID" :span="2">
          <span class="mono-wrap">{{ container?.id || '-' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="镜像" :span="2">
          <span class="text-wrap">{{ container?.image || '-' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="节点">
          <span class="text-wrap">{{ container?.node_name || '-' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">
          {{ fmtTime(container?.created_at) }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card class="detail-card block-card">
      <template #header>
        <div class="card-header card-header--split">
          <span class="section-label">容器与csv保护区内存占比</span>
          <span class="section-meta">
            {{ latestMetrics?.csv_memory_pct ?? 0 }}% · {{ latestMetrics?.used_mb ?? '-' }} /
            {{ latestMetrics?.pool_mb ?? '-' }} MB · 每 5 秒更新
          </span>
        </div>
      </template>
      <div ref="metricsChartRef" class="chart-area"></div>
    </el-card>

    <el-card class="detail-card block-card log-card">
      <template #header>
        <div class="card-header card-header--split">
          <span class="section-label">标准输出 / 标准错误</span>
          <span class="section-meta">{{ logLineCount }} 行</span>
        </div>
      </template>
      <div class="log-viewport">
        <pre v-if="logsText" class="log-pre">{{ logsText }}</pre>
        <div v-else class="log-empty">暂无日志</div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getContainerDetail, getContainerMetrics } from '../../api'

const route = useRoute()

const loading = ref(false)
const container = ref(null)

const metricsChartRef = ref(null)
let metricsChart = null
let pollTimer = null

const latestMetrics = ref({ csv_memory_pct: 0, used_mb: 0, pool_mb: 0 })
const metricsSeries = { time: [], csv: [] }

const logsText = ref('')

function fmtTime(v) {
  if (!v) return '-'
  try {
    return new Date(v).toLocaleString('zh-CN')
  } catch {
    return String(v)
  }
}

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

const logLineCount = computed(() => {
  const t = logsText.value
  if (!t) return 0
  return t.split('\n').length
})

function initChart() {
  if (!metricsChartRef.value) return
  if (!metricsChart) {
    metricsChart = echarts.init(metricsChartRef.value)
  }
  metricsChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['内存占比'], top: 8 },
    grid: { left: 44, right: 12, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: metricsSeries.time, boundaryGap: false },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        name: '内存占比',
        type: 'line',
        smooth: true,
        data: metricsSeries.csv,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { color: '#0ea5e9', width: 2 },
        itemStyle: { color: '#0ea5e9' },
        areaStyle: { color: 'rgba(14,165,233,0.12)' }
      }
    ]
  })
}

function updateChart(m) {
  if (!m) return
  latestMetrics.value = {
    csv_memory_pct: m.csv_memory_pct,
    used_mb: m.used_mb,
    pool_mb: m.pool_mb
  }
  const t = m.time || new Date().toLocaleTimeString()
  metricsSeries.time.push(t)
  metricsSeries.csv.push(Number(m.csv_memory_pct || 0))
  if (metricsSeries.time.length > 30) {
    metricsSeries.time.shift()
    metricsSeries.csv.shift()
  }
  metricsChart?.setOption({
    xAxis: { data: metricsSeries.time },
    series: [{ name: '内存占比', data: metricsSeries.csv }]
  })
}

async function load() {
  const id = String(route.params.id || '')
  if (!id) return
  loading.value = true
  metricsSeries.time = []
  metricsSeries.csv = []
  try {
    const res = await getContainerDetail(id)
    container.value = res.container
    logsText.value = (res.logs || []).join('\n')

    await nextTick()
    initChart()
    try {
      const m = await getContainerMetrics(id)
      updateChart(m)
    } catch {
      /* 容器已回收或 metrics 暂不可用时仍可查看详情与日志 */
    }
    pollTimer = setInterval(async () => {
      try {
        const mm = await getContainerMetrics(id)
        updateChart(mm)
      } catch {
        /* 轮询失败时跳过本次 */
      }
    }, 5000)
  } catch (e) {
    ElMessage.error(e?.message || '加载容器详情失败')
    container.value = null
    logsText.value = ''
  } finally {
    loading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
  if (metricsChart) metricsChart.dispose()
  metricsChart = null
})
</script>

<style scoped>
.container-detail-page {
  max-width: 100%;
  box-sizing: border-box;
  overflow-x: hidden;
}

.detail-card {
  max-width: 100%;
  overflow: hidden;
}

.block-card {
  margin-bottom: 12px;
}

.block-card:last-child {
  margin-bottom: 0;
}

.log-card :deep(.el-card__body) {
  padding: 0;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.card-title {
  min-width: 0;
  flex: 1 1 auto;
  word-break: break-word;
  overflow-wrap: anywhere;
  line-height: 1.4;
}

.card-header-tags {
  flex-shrink: 0;
}

.card-header--split {
  width: 100%;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 16px;
}

.section-label {
  font-weight: 600;
  font-size: 15px;
  color: #0f172a;
}

.section-meta {
  margin-left: auto;
  font-size: 12px;
  color: #64748b;
  font-variant-numeric: tabular-nums;
  text-align: right;
  min-width: 0;
  word-break: break-all;
}

/* 描述列表：固定表格宽度，内容区强制换行 */
.detail-descriptions :deep(.el-descriptions__body .el-descriptions__table) {
  table-layout: fixed;
  width: 100%;
}

.detail-descriptions :deep(.el-descriptions__label) {
  width: 96px;
  vertical-align: top;
}

.detail-descriptions :deep(.el-descriptions__content) {
  word-break: break-word;
  overflow-wrap: anywhere;
  white-space: normal;
  vertical-align: top;
}

.mono-wrap {
  display: inline-block;
  max-width: 100%;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
    monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #334155;
  word-break: break-all;
  overflow-wrap: anywhere;
}

.text-wrap {
  display: inline-block;
  max-width: 100%;
  font-size: 13px;
  line-height: 1.5;
  color: #334155;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.chart-area {
  width: 100%;
  height: 240px;
}

.log-viewport {
  max-height: min(52vh, 520px);
  overflow: auto;
  background: #0f172a;
  border-top: 1px solid #e2e8f0;
}

.log-pre {
  box-sizing: border-box;
  margin: 0;
  padding: 14px 16px 18px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.55;
  color: #cbd5e1;
  white-space: pre;
  tab-size: 4;
}

.log-empty {
  margin: 0;
  padding: 32px 16px;
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
  background: #0f172a;
  border-top: 1px solid #1e293b;
}
</style>
