<template>
  <div class="pie-chart-container">
    <div ref="chartRef" style="width: 100%; height: 200px;"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import { useTaskStore } from '../stores/task'

const taskStore = useTaskStore()
const chartRef = ref(null)
let chart = null

// 计算三种状态的数量
const computeStats = () => {
  const containers = taskStore.containers || []
  // 安静态：容器 running 但无关联的训练任务（需要从任务列表判断）
  // 这里简单处理：假设所有 running 容器都作为安静态，实际应根据任务状态细分
  // 更精确的做法需要结合每个容器的训练任务状态，由 Home.vue 传入
  // 为简化，我们直接在 Home.vue 中计算好传入
  return {
    idle: 0,
    running: 0,
    destroyed: 0
  }
}

const updateChart = (stats) => {
  if (!chart) return
  chart.setOption({
    tooltip: { trigger: 'item' },
    legend: { orient: 'vertical', left: 'left' },
    series: [
      {
        name: '容器状态',
        type: 'pie',
        radius: '50%',
        data: [
          { name: '安静态', value: stats.idle, itemStyle: { color: '#909399' } },
          { name: '运行中', value: stats.running, itemStyle: { color: '#67c23a' } },
          { name: '已销毁', value: stats.destroyed, itemStyle: { color: '#f56c6c' } }
        ],
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0 } }
      }
    ]
  })
}

// 接收外部传入的统计数据
const props = defineProps({
  stats: {
    type: Object,
    default: () => ({ idle: 0, running: 0, destroyed: 0 })
  }
})

watch(() => props.stats, (newStats) => {
  updateChart(newStats)
}, { deep: true })

onMounted(() => {
  chart = echarts.init(chartRef.value)
  updateChart(props.stats)
})

onUnmounted(() => {
  if (chart) chart.dispose()
})
</script>