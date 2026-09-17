<template>
  <div class="sys-config-page">
    <el-row :gutter="16" class="config-row">
      <el-col :span="14" class="left-col">
        <el-card class="panel-card fill-card">
          <template #header>
            <div class="card-header audit-header">
              <div>
                <div class="title-main">审计日志策略</div>
                <div class="sub-tip">影响日志存储与清理</div>
              </div>
              <el-tag type="warning" effect="light" round>高优先级</el-tag>
            </div>
          </template>

          <el-form label-width="150px" class="config-form">
            <el-form-item label="最大保留天数">
              <el-input-number v-model="config.audit_retention_days" :min="1" :max="3650" controls-position="right" />
            </el-form-item>
          </el-form>

          <el-alert type="warning" show-icon :closable="false" title="清理操作需要二次确认" class="warn-alert" />
          <div class="actions-row">
            <el-button type="danger" plain class="danger-btn" @click="clearAudit">
              手动清理
            </el-button>
          </div>
        </el-card>
      </el-col>

      <el-col :span="10" class="right-col">
        <el-card class="panel-card split-card">
          <template #header>
            <div class="card-header">
              <div>
                <div class="title-main">信创适配</div>
                <div class="sub-tip">运行时环境参数</div>
              </div>
            </div>
          </template>
          <el-form label-width="120px" class="config-form">
            <el-form-item label="TEE驱动路径">
              <el-input v-model="config.tee_driver_path" placeholder="/dev/tee0" />
            </el-form-item>
            <el-form-item label="算法库版本">
              <el-select v-model="config.crypto_lib_version" placeholder="请选择/输入" style="width: 100%">
                <el-option value="v1.0.0" label="v1.0.0" />
                <el-option value="v1.2.3" label="v1.2.3" />
                <el-option value="v2.0.0" label="v2.0.0" />
              </el-select>
            </el-form-item>
          </el-form>

          <el-button type="primary" class="save-btn" @click="saveConfig">保存配置</el-button>
          <el-button class="preview-btn" plain @click="previewOpen = true">
            当前配置预览
          </el-button>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="previewOpen" title="当前配置预览" width="560px">
      <pre class="json-pre">{{ JSON.stringify(config, null, 2) }}</pre>
      <template #footer>
        <el-button type="primary" @click="previewOpen = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSystemConfig, updateSystemConfig, clearAuditLogs } from '../../api'

const config = reactive({
  cert_valid_until: '-',
  audit_retention_days: 30,
  tee_driver_path: '/dev/tee0',
  crypto_lib_version: 'v1.2.3'
})
const previewOpen = ref(false)

async function reload() {
  const res = await getSystemConfig()
  Object.assign(config, res)
}

async function saveConfig() {
  await updateSystemConfig(config)
  ElMessage.success('配置保存成功')
}

async function clearAudit() {
  await ElMessageBox.confirm('确认清理审计日志？该操作不可逆', '确认清理', { type: 'warning' })
  const res = await clearAuditLogs()
  const cleared = res?.cleared || {}
  const total =
    Number(cleared.task_detail_timeline_rows || 0) +
    Number(cleared.task_audit_events || 0) +
    Number(cleared.admin_audit_events || 0) +
    Number(cleared.audit_log_chain_rows || 0)
  ElMessage.success(`审计日志已清理，累计处理 ${total} 条`)
}

onMounted(async () => {
  await reload()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sys-config-page {
  padding: 4px 4px;
}
.panel-card {
  border-radius: 12px;
  border: 1px solid #e8edf5;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
}
.config-row {
  align-items: stretch;
}
.left-col,
.right-col {
  display: flex;
}
.left-col {
  min-height: 320px;
}
.right-col {
  min-height: 320px;
  flex-direction: column;
  gap: 10px;
}
.fill-card {
  width: 100%;
  height: 100%;
}
.split-card {
  width: 100%;
  flex: 1;
}
.config-form {
  margin-top: 2px;
}
.title-main {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}
.sub-tip {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 500;
  margin-top: 2px;
}
.warn-alert {
  margin-top: 6px;
  border-radius: 10px;
}
.actions-row {
  margin-top: 8px;
  display: flex;
  justify-content: flex-start;
}
.danger-btn {
  min-width: 110px;
}
.save-btn {
  width: 100%;
  margin-top: 6px;
  height: 34px;
  border-radius: 8px;
  font-weight: 600;
}
.preview-btn {
  margin-top: 6px;
  width: 140px;
  align-self: flex-end;
  height: 30px;
  border-radius: 8px;
  border-color: #cbd5e1;
  color: #475569;
  background: #f8fafc;
  font-weight: 500;
}
.preview-btn:hover {
  border-color: #94a3b8;
  color: #334155;
  background: #f1f5f9;
}
.json-pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  white-space: pre-wrap;
  word-break: break-word;
}

:deep(.el-form-item__label) {
  font-weight: 600;
  color: #334155;
}

:deep(.panel-card .el-card__body) {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper),
:deep(.el-input-number) {
  border-radius: 8px;
}
</style>

