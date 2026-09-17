<template>
  <div class="settings-container">
    <el-card class="user-info-card">
      <template #header>
        <div class="card-header"><span>个人信息</span></div>
      </template>
      <div class="user-info-content">
        <div class="avatar-section">
          <el-avatar :size="120" :src="userInfo.avatar" class="user-avatar">
            {{ userInfo.username.charAt(0).toUpperCase() }}
          </el-avatar>
          <el-button type="primary" @click="uploadAvatarVisible = true">更换头像</el-button>
        </div>
        <el-form :model="userInfo" label-width="120px" style="margin-top: 20px">
          <el-form-item label="用户名">
            <el-input v-model="userInfo.username" disabled />
          </el-form-item>
          <el-form-item label="邮箱">
            <el-input v-model="userInfo.email" />
          </el-form-item>
          <el-form-item label="手机号">
            <el-input v-model="userInfo.phone" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveUserInfo">保存个人信息</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <el-card class="password-card">
      <template #header>
        <div class="card-header"><span>修改密码</span></div>
      </template>
      <el-form ref="passwordFormRef" :model="passwordForm" label-width="120px" :rules="passwordRules">
        <el-form-item label="当前密码" prop="currentPassword">
          <el-input v-model="passwordForm.currentPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="passwordForm.newPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirmPassword">
          <el-input v-model="passwordForm.confirmPassword" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :disabled="!isPasswordFormValid" @click="changePassword">修改密码</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="logs-card">
      <template #header>
        <div class="card-header"><span>操作日志</span></div>
      </template>
      <el-table :data="logs" size="small">
        <el-table-column prop="time" label="时间" width="170" />
        <el-table-column prop="taskName" label="任务名" min-width="180" />
        <el-table-column prop="taskId" label="任务ID" width="140" />
        <el-table-column prop="taskType" label="任务类型" width="120" />
        <el-table-column prop="result" label="结果" width="90" />
        <el-table-column label="操作详情" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="openOperationDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 操作详情抽屉 -->
    <el-drawer v-model="operationDetailVisible" title="操作详情" size="500px">
      <div v-if="currentOperation">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="任务名">{{ currentOperation.taskName }}</el-descriptions-item>
          <el-descriptions-item label="任务ID">{{ currentOperation.taskId }}</el-descriptions-item>
          <el-descriptions-item label="任务类型">{{ currentOperation.taskType }}</el-descriptions-item>
          <el-descriptions-item label="操作类型">{{ currentOperation.type }}</el-descriptions-item>
          <el-descriptions-item label="操作时间">{{ currentOperation.time }}</el-descriptions-item>
          <el-descriptions-item label="操作结果">{{ currentOperation.result }}</el-descriptions-item>
        </el-descriptions>
        <div style="margin-top: 20px;">
          <h3>操作时间轴</h3>
          <el-timeline>
            <el-timeline-item
              v-for="(item, index) in currentOperation.timeline"
              :key="index"
              :timestamp="item.time"
            >
              {{ item.title }}
            </el-timeline-item>
          </el-timeline>
        </div>
      </div>
    </el-drawer>

    <!-- 头像上传对话框 -->
    <el-dialog v-model="uploadAvatarVisible" title="更换头像">
      <el-upload
        class="avatar-uploader"
        action="#"
        :show-file-list="false"
        :on-change="handleAvatarChange"
        accept="image/*"
      >
        <img v-if="userInfo.avatar" :src="userInfo.avatar" class="avatar">
        <div v-else class="avatar-placeholder">
          <el-icon class="avatar-uploader-icon"><Plus /></el-icon>
          <div>点击上传</div>
        </div>
      </el-upload>
      <template #footer>
        <el-button @click="uploadAvatarVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmAvatarUpload">确认上传</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref, reactive, computed, watch } from 'vue'
import { useUserContextStore } from '../../stores/userContext'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAuditLogs, getTasks } from '../../api'

const ctx = useUserContextStore()
const logs = ref([])
const uploadAvatarVisible = ref(false)
const passwordFormRef = ref(null)
const passwordFormValid = ref(false)
const operationDetailVisible = ref(false)
const currentOperation = ref(null)

// 用户信息
const userInfo = reactive({
  username: ctx.user?.username || 'user',
  email: ctx.user?.email || '',
  phone: ctx.user?.phone || '',
  avatar: ctx.user?.avatar || ''
})

// 密码表单
const passwordForm = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

// 密码验证规则
const passwordRules = {
  currentPassword: [
    { required: true, message: '请输入当前密码', trigger: 'blur' }
  ],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少为6位', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (value !== passwordForm.newPassword) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ]
}

// 密码表单验证状态
const isPasswordFormValid = computed(() => {
  return passwordFormValid.value
})

// 监听密码表单变化
watch(
  [() => passwordForm.currentPassword, () => passwordForm.newPassword, () => passwordForm.confirmPassword],
  async () => {
    if (passwordFormRef.value) {
      await passwordFormRef.value.validate((valid) => {
        passwordFormValid.value = valid
      })
    }
  },
  { deep: true }
)

const saveUserInfo = () => {
  ElMessage.warning('个人信息接口未接入，当前不执行保存')
}

// 修改密码
const changePassword = async () => {
  if (!passwordFormRef.value) return

  await passwordFormRef.value.validate(async (valid) => {
    if (valid) {
      ElMessage.warning('修改密码接口未接入，当前不执行修改')
    }
  })
}

const handleAvatarChange = (file) => {
  const reader = new FileReader()
  reader.onload = (e) => {
    userInfo.avatar = e.target.result
  }
  reader.readAsDataURL(file.raw)
}

// 确认头像上传
const confirmAvatarUpload = () => {
  ElMessage.warning('头像上传接口未接入，当前不执行上传')
  uploadAvatarVisible.value = false
}

// 打开操作详情
const openOperationDetail = (row) => {
  currentOperation.value = row
  operationDetailVisible.value = true
}

async function loadLogs() {
  // 先按 task_id 建立任务名索引，补全“结果下载”等仅记录 task_id 的审计行。
  const taskNameById = {}
  try {
    const taskRes = await getTasks({ page: 1, size: 500 })
    const taskItems = taskRes?.items || []
    taskItems.forEach(t => {
      const tid = String(t.id || t.task_id || '').trim()
      if (tid) taskNameById[tid] = t.name || t.task_name || '-'
    })
  } catch {
    // 任务列表获取失败时不阻断日志展示，下面会回退为 "-"
  }

  const res = await getAuditLogs({ page: 1, size: 200 })
  const items = res?.items || []
  logs.value = items.map(item => {
    let detail = {}
    try {
      detail = typeof item.detail_json === 'string' ? JSON.parse(item.detail_json || '{}') : (item.detail_json || {})
    } catch {
      detail = {}
    }
    const taskId = detail.task_id || item.object_id || '-'
    const rawTaskName = detail.task_name || taskNameById[taskId] || '-'
    const taskName = typeof rawTaskName === 'string'
      ? rawTaskName
          .replace(new RegExp(`\\s*\\(${String(taskId).replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}\\)\\s*$`), '')
          .replace(new RegExp(`\\s*（${String(taskId).replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}）\\s*$`), '')
      : rawTaskName
    return {
      id: item.id,
      time: new Date(item.time).toLocaleString(),
      taskName: taskName || '-',
      taskId,
      taskType: item.operation_type || '-',
      type: item.operation_type || '-',
      result: item.result === 'success' ? '成功' : '失败',
      ip: detail.ip || '-',
      timeline: [
        { title: `开始：${item.operation_type || '-'}`, time: new Date(item.time).toLocaleString() },
        { title: `对象：${item.object_type || '-'} / ${item.object_id || '-'}`, time: new Date(item.time).toLocaleString() },
        { title: `结果：${item.result === 'success' ? '成功' : '失败'}`, time: new Date(item.time).toLocaleString() }
      ]
    }
  })
}

onMounted(async () => {
  await loadLogs()
})

</script>

<style scoped>
.settings-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
}

.user-info-card {
  width: 80%;
  margin: 0 auto;
}

.password-card,
.logs-card {
  width: 100%;
}

.user-info-content {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.avatar-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.user-avatar {
  border: 2px solid #e0e0e0;
  transition: all 0.3s ease;
}

.user-avatar:hover {
  transform: scale(1.05);
  box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
}

.avatar-uploader {
  text-align: center;
}

.avatar {
  width: 200px;
  height: 200px;
  border-radius: 50%;
  object-fit: cover;
}

.avatar-placeholder {
  width: 200px;
  height: 200px;
  border: 1px dashed #d9d9d9;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #999;
  cursor: pointer;
  transition: all 0.3s ease;
}

.avatar-placeholder:hover {
  border-color: #409eff;
  color: #409eff;
}

.avatar-uploader-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>

