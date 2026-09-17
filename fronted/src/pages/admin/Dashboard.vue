<template>
  <div>
    <el-row :gutter="12">
      <el-col :span="8">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>集群健康</span>
              <el-tag v-if="ctx.clusterStatus?.anomaly" type="danger" effect="dark" round>异常</el-tag>
              <el-tag v-else type="success" effect="dark" round>健康</el-tag>
            </div>
          </template>
          <div class="kv">
            <div class="k">TEE 节点</div>
            <div class="v">
              <span class="clickable" @click="go('/admin/nodes')">{{ ctx.clusterStatus?.nodes_total || 0 }}</span>
              （在线 <span class="clickable" @click="go('/admin/nodes?status=online')">{{ ctx.clusterStatus?.nodes_online || 0 }}</span>）
            </div>
          </div>
          <div class="kv">
            <div class="k">机密容器</div>
            <div class="v">
              <span class="clickable" @click="go('/admin/containers')">{{ ctx.clusterStatus?.containers_total || 0 }}</span>
              （进行中 <span class="clickable" @click="go('/admin/containers?status=InProgress')">{{ ctx.clusterStatus?.containers_running || 0 }}</span>）
            </div>
          </div>
          <div class="kv">
            <div class="k">今日审计事件</div>
            <div class="v" :style="{ color: (ctx.clusterStatus?.today_anomalies_count || 0) > 0 ? '#ef4444' : '#0f172a' }">
              <span class="clickable" @click="go('/admin/audit-logs?time=today')">{{ ctx.clusterStatus?.today_audit_count || 0 }}</span>
              （异常 <span class="clickable" @click="go('/admin/audit-logs?time=today&result=fail')">{{ ctx.clusterStatus?.today_anomalies_count || 0 }}</span>）
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="16">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>最近审计事件（5条）</span>
              <el-button text @click="go('/admin/audit-logs')">查看全部</el-button>
            </div>
          </template>
          <el-timeline v-if="ctx.recentAudit.length">
            <el-timeline-item
              v-for="e in ctx.recentAudit"
              :key="e.id"
              :timestamp="fmt(e.time)"
              :type="e.result === 'fail' ? 'danger' : 'primary'"
              @click="openAudit(e)"
              style="cursor:pointer"
            >
              <div style="font-weight: 700">{{ e.operation_type }}</div>
              <div class="tl-sub">{{ e.object_type }} · {{ e.object_id }} · {{ e.result === 'fail' ? '失败' : '成功' }}</div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无审计事件" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="24">
        <el-card class="quick-actions-card">
          <div class="quick-actions">
            <el-button type="primary" plain @click="go('/admin/containers')">机密容器列表</el-button>
            <el-button @click="go('/admin/audit-logs')">查看审计日志</el-button>
            <el-button @click="go('/admin/nodes?expand=1')">扩容节点</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAdminContextStore } from '../../stores/adminContext'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()
const ctx = useAdminContextStore()

function fmt(iso) {
  return new Date(iso).toLocaleString()
}

function go(p) {
  router.push(p)
}

function openAudit(e) {
  // 直接跳转到审计日志页面，并带上查询条件（演示版）
  go(`/admin/audit-logs?detailId=${encodeURIComponent(e.id)}`)
}

onMounted(async () => {
  // placeholder
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.kv {
  margin: 24px 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.k {
  color: #64748b;
  font-weight: 600;
  text-align: center;
  font-size: 14px;
  margin-bottom: 8px;
  width: 100%;
}
.v {
  font-size: 20px;
  font-weight: 800;
  text-align: center;
  line-height: 1.4;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
/* 调整集群健康卡片的内容垂直居中 */
.el-card__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  overflow: hidden;
}
/* 统一卡片高度 */
.el-card {
  height: 500px;
  display: flex;
  flex-direction: column;
}
.el-card__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.kv:last-child {
  margin-bottom: 10px;
}
/* 确保时间线内容不溢出 */
.el-timeline {
  flex: 1;
  overflow-y: auto;
  margin: 0;
}
.tl-sub {
  color: #64748b;
  font-size: 12px;
  margin-top: 2px;
}
.quick-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

/* 调整快速操作卡片的高度和内边距 */
.quick-actions-card {
  height: auto !important;
  min-height: 80px;
}

.quick-actions-card .el-card__body {
  padding: 12px !important;
  display: flex;
  align-items: center;
  justify-content: flex-start;
}

.clickable {
  cursor: pointer;
  color: #3b82f6;
  transition: color 0.3s ease;
}

.clickable:hover {
  color: #2563eb;
  text-decoration: underline;
}
</style>

