<template>
  <el-row :gutter="12">
    <el-col :span="16">
      <el-card>
        <template #header>
          <div class="card-header">
            <span>新建任务向导</span>
            <el-button text @click="resetAll">重置</el-button>
          </div>
        </template>

        <el-steps :active="step" align-center finish-status="success">
          <el-step v-for="(title, idx) in stepTitles" :key="idx" :title="title" />
        </el-steps>

        <div class="panel">
          <div v-show="step === 0">
            <el-form label-width="120px">
              <el-form-item label="任务名称">
                <el-input v-model="form.name" placeholder="请输入任务名称" style="width: 400px" />
              </el-form-item>
            </el-form>
          </div>

          <div v-show="step === 1">
            <el-alert
              v-if="runtime.containerId"
              type="success"
              :closable="false"
              show-icon
              title="训练容器已由后端创建"
            />
            <el-alert v-else type="info" :closable="false" show-icon title="正在创建训练容器…" />
            <el-descriptions :column="1" border style="margin-top: 12px">
              <el-descriptions-item label="容器ID">{{ runtime.containerId || '-' }}</el-descriptions-item>
              <el-descriptions-item label="镜像">{{ runtime.containerImage || '-' }}</el-descriptions-item>
              <el-descriptions-item label="状态">{{ runtime.containerStatus || '-' }}</el-descriptions-item>
            </el-descriptions>
          </div>

          <div v-show="step === 2">
            <el-alert
              v-if="runtime.proofId"
              type="success"
              :closable="false"
              show-icon
              title="远程证明已由后端完成（容器内取证 + attestation-service 校验）"
            />
            <el-alert v-else type="info" :closable="false" show-icon title="正在进行远程证明…" />
            <el-descriptions :column="1" border style="margin-top: 12px">
              <el-descriptions-item label="证明编号">{{ runtime.proofId || '-' }}</el-descriptions-item>
              <el-descriptions-item label="证明摘要">{{ runtime.proofDigest || '-' }}</el-descriptions-item>
            </el-descriptions>
            <el-button type="primary" plain style="margin-top: 12px" :disabled="!runtime.proofId" @click="downloadProof">
              下载远程证明报告 (.json)
            </el-button>
          </div>

          <div v-show="step === 3">
            <el-form label-width="120px">
              <el-form-item label="上传数据">
                <el-upload
                  action="#"
                  :auto-upload="false"
                  :on-change="handleFileUpload"
                  accept=".csv"
                  :show-file-list="true"
                  :limit="1"
                >
                  <el-button type="primary">选择本地 CSV 文件</el-button>
                </el-upload>
                <el-text type="info" style="margin-left: 10px">训练服务要求样本数 ≥ 2000（最后一列为标签）</el-text>
              </el-form-item>
              <el-form-item label="算法">
                <el-select v-model="form.algorithm" style="width: 280px" @change="applyDefaults">
                  <el-option label="逻辑回归" value="逻辑回归" />
                  <el-option label="XGBoost 分类" value="XGBoost 分类" />
                  <el-option label="XGBoost 回归" value="XGBoost 回归" />
                </el-select>
              </el-form-item>
              <el-form-item v-for="f in paramFields" :key="f.key" :label="f.label">
                <el-input-number v-model="form.params[f.key]" :min="f.min" :max="f.max" :step="f.step" />
              </el-form-item>
            </el-form>
          </div>

          <div v-show="step === 4">
            <el-alert type="info" :closable="false" show-icon title="下一步将生成 DEK、向 TEE 注入密钥，并用 SM4-ECB 加密您上传的 CSV（在 controller 内完成）。" />
            <el-descriptions v-if="runtime.dekId" :column="1" border style="margin-top: 12px">
              <el-descriptions-item label="DEK 指纹">{{ runtime.dekId }}</el-descriptions-item>
              <el-descriptions-item label="加密状态">{{ runtime.encryptionStatus || '-' }}</el-descriptions-item>
            </el-descriptions>
          </div>

          <div v-show="step === 5">
            <el-form label-width="120px">
              <el-form-item label="密钥注入">
                <el-radio-group v-model="form.injectKey">
                  <el-radio label="yes">是，执行密钥注入与数据加密（必选以继续训练）</el-radio>
                  <el-radio label="no">否（将无法训练）</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-form>
          </div>

          <div v-show="step === 6">
            <el-alert
              v-if="runtime.trainError"
              type="error"
              :closable="false"
              show-icon
              :title="runtime.trainError"
            />
            <el-alert v-else-if="runtime.trainPhase === 'done'" type="success" :closable="false" show-icon title="训练已完成" />
            <el-alert v-else type="warning" :closable="false" show-icon title="训练任务由后端提交至密态训练服务并轮询状态" />
            <el-progress :percentage="runtime.progress" style="margin-top: 12px" />
            <el-text v-if="runtime.trainingTaskId" type="info" size="small">训练实例 ID：{{ runtime.trainingTaskId }}</el-text>
          </div>

          <div v-show="step === 7">
            <el-alert type="success" :closable="false" show-icon title="训练完成，可从下方下载密态模型文件" />
            <el-descriptions :column="1" border style="margin-top: 12px">
              <el-descriptions-item label="门户任务 ID">{{ portalTaskId || '-' }}</el-descriptions-item>
              <el-descriptions-item label="任务名称">{{ form.name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="算法">{{ form.algorithm }}</el-descriptions-item>
            </el-descriptions>
            <el-button type="primary" plain style="margin-top: 12px" :disabled="!portalTaskId" @click="downloadResult">
              下载加密模型 (.enc)
            </el-button>
          </div>
        </div>

        <div class="footer">
          <el-button :disabled="step === 0 || working" @click="prev">上一步</el-button>
          <!-- 步骤 6 由轮询完成后自动进入步骤 7，避免训练未完成就点「下一步」 -->
          <el-button
            v-if="step < 7 && step !== 6"
            type="primary"
            :loading="working"
            :disabled="step === 1 && !runtime.containerId"
            @click="next"
          >
            下一步
          </el-button>
          <el-button v-if="step === 7" type="primary" @click="finish">进入任务详情</el-button>
        </div>
      </el-card>
    </el-col>

    <el-col :span="8">
      <el-card>
        <template #header>
          <div class="card-header"><span>流程说明</span></div>
        </template>
        <el-timeline>
          <el-timeline-item v-for="(title, idx) in stepTitles" :key="title" :timestamp="`步骤 ${idx + 1}`" type="primary">
            {{ title }}
          </el-timeline-item>
        </el-timeline>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  wizardInit,
  wizardCreateContainer,
  wizardAttest,
  wizardUploadCsv,
  wizardProtectData,
  wizardStartTrain,
  wizardTrainStatus,
  wizardDownloadAttestationBlob,
  wizardDownloadModelBlob
} from '../../api/wizard.js'
import { useUserContextStore } from '../../stores/userContext'

const router = useRouter()
const ctx = useUserContextStore()

const stepTitles = [
  '任务名称',
  '创建容器',
  '远程证明',
  '数据与算法',
  'DEK加密',
  '密钥注入',
  '开始训练',
  '完成下载'
]

const step = ref(0)
const working = ref(false)
const portalTaskId = ref('')
const uploadedFile = ref(null)
const trainPollTimer = ref(null)

const gate = reactive({
  container: false,
  attest: false,
  train: false
})

const form = ref({
  account_id: '',
  name: '',
  scene: 'fraud',
  algorithm: 'XGBoost 分类',
  params: {},
  injectKey: 'yes'
})

const runtime = ref({
  containerId: '',
  containerStatus: '',
  containerImage: '',
  proofId: '',
  proofDigest: '',
  dekId: '',
  encryptionStatus: '',
  progress: 0,
  trainPhase: '',
  trainError: '',
  trainingTaskId: ''
})

const paramFields = computed(() => {
  if (form.value.algorithm === '逻辑回归') {
    return [
      { key: 'iterations', label: '迭代次数', min: 10, max: 2000, step: 10 },
      { key: 'learning_rate', label: '学习率', min: 0.001, max: 1, step: 0.01 }
    ]
  }
  return [
    { key: 'iterations', label: '迭代次数', min: 10, max: 2000, step: 10 },
    { key: 'learning_rate', label: '学习率', min: 0.001, max: 1, step: 0.01 },
    { key: 'max_depth', label: '最大深度', min: 1, max: 20, step: 1 }
  ]
})

function applyDefaults() {
  if (form.value.algorithm === '逻辑回归') {
    form.value.params = { iterations: 120, learning_rate: 0.05 }
  } else {
    form.value.params = { iterations: 200, learning_rate: 0.1, max_depth: 6 }
  }
}

function handleFileUpload(file) {
  const raw = file.raw
  if (!raw || !raw.name?.endsWith('.csv')) {
    ElMessage.error('请上传 .csv 格式文件')
    return
  }
  uploadedFile.value = raw
  ElMessage.success(`已选择：${raw.name}`)
}

async function downloadProof() {
  if (!portalTaskId.value) return
  working.value = true
  try {
    const blob = await wizardDownloadAttestationBlob(portalTaskId.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `attestation_${portalTaskId.value}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('已开始下载远程证明报告')
  } catch (e) {
    ElMessage.error(e?.message || '下载远程证明报告失败')
  } finally {
    working.value = false
  }
}

async function downloadResult() {
  if (!portalTaskId.value) return
  working.value = true
  try {
    const blob = await wizardDownloadModelBlob(portalTaskId.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `model_${portalTaskId.value}.enc`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('已开始下载加密模型')
  } catch (e) {
    ElMessage.error(e?.message || '下载失败')
  } finally {
    working.value = false
  }
}

function stopTrainPoll() {
  if (trainPollTimer.value) {
    clearInterval(trainPollTimer.value)
    trainPollTimer.value = null
  }
}

async function pollTrainOnce() {
  if (!portalTaskId.value) return
  try {
    const st = await wizardTrainStatus(portalTaskId.value)
    runtime.value.progress = Math.min(99, Number(st.progress || 0))
    runtime.value.trainPhase = st.phase || ''
    runtime.value.trainError = st.error || ''
    runtime.value.trainingTaskId = st.training_task_id || runtime.value.trainingTaskId
    if (st.phase === 'done') {
      runtime.value.progress = 100
      stopTrainPoll()
      ElMessage.success('训练完成')
      step.value = 7
    } else if (st.phase === 'error') {
      stopTrainPoll()
      ElMessage.error(st.error || '训练失败')
    }
  } catch (e) {
    stopTrainPoll()
    runtime.value.trainError = e?.message || String(e)
    ElMessage.error(runtime.value.trainError)
  }
}

watch(
  () => step.value,
  async (s) => {
    if (!portalTaskId.value) return
    if (s === 1 && !gate.container) {
      gate.container = true
      working.value = true
      try {
        const d = await wizardCreateContainer({ task_id: portalTaskId.value })
        runtime.value.containerId = d.container_id || ''
        runtime.value.containerStatus = d.container_status || ''
        runtime.value.containerImage = d.image || ''
      } catch (e) {
        gate.container = false
        ElMessage.error(e?.message || '创建容器失败')
      } finally {
        working.value = false
      }
    }
    if (s === 2 && !gate.attest) {
      if (!runtime.value.containerId) {
        ElMessage.warning('请等待上一步「创建容器」成功后再进入远程证明（若刚失败请先点「重置」或返回上一步重试）')
        return
      }
      gate.attest = true
      working.value = true
      try {
        const d = await wizardAttest({ task_id: portalTaskId.value })
        runtime.value.proofId = d.proof_id || ''
        runtime.value.proofDigest = d.proof_digest || ''
      } catch (e) {
        gate.attest = false
        ElMessage.error(e?.message || '远程证明失败')
      } finally {
        working.value = false
      }
    }
    if (s === 6 && !gate.train) {
      gate.train = true
      working.value = true
      try {
        await wizardStartTrain({ task_id: portalTaskId.value })
        runtime.value.trainPhase = 'running'
        runtime.value.progress = 10
        trainPollTimer.value = setInterval(pollTrainOnce, 2000)
        await pollTrainOnce()
      } catch (e) {
        gate.train = false
        runtime.value.trainError = e?.message || String(e)
        ElMessage.error(runtime.value.trainError)
      } finally {
        working.value = false
      }
    }
  }
)

async function next() {
  if (step.value === 0) {
    if (!form.value.name?.trim()) {
      ElMessage.warning('请输入任务名称')
      return
    }
    if (portalTaskId.value) {
      step.value = 1
      return
    }
    working.value = true
    try {
      const d = await wizardInit({
        name: form.value.name.trim(),
        scene: form.value.scene,
        account_id: form.value.account_id
      })
      portalTaskId.value = d.task_id
      step.value = 1
    } catch (e) {
      ElMessage.error(e?.message || '创建任务失败')
    } finally {
      working.value = false
    }
    return
  }

  if (step.value === 3) {
    if (!uploadedFile.value) {
      ElMessage.warning('请先选择 CSV 文件')
      return
    }
    working.value = true
    try {
      await wizardUploadCsv(portalTaskId.value, uploadedFile.value, form.value.algorithm, form.value.params)
    } catch (e) {
      ElMessage.error(e?.message || '上传失败')
      working.value = false
      return
    } finally {
      working.value = false
    }
  }

  if (step.value === 5) {
    if (form.value.injectKey !== 'yes') {
      ElMessage.warning('必须选择「执行密钥注入」才能完成密态训练')
      return
    }
    working.value = true
    try {
      const d = await wizardProtectData({ task_id: portalTaskId.value })
      runtime.value.dekId = d.dek_id || ''
      runtime.value.encryptionStatus = d.encryption_status || ''
    } catch (e) {
      ElMessage.error(e?.message || '密钥注入或加密失败')
      working.value = false
      return
    } finally {
      working.value = false
    }
  }

  if (step.value < 7) step.value += 1
}

function prev() {
  if (step.value > 0) step.value -= 1
}

function resetAll() {
  stopTrainPoll()
  step.value = 0
  portalTaskId.value = ''
  uploadedFile.value = null
  gate.container = false
  gate.attest = false
  gate.train = false
  runtime.value = {
    containerId: '',
    containerStatus: '',
    containerImage: '',
    proofId: '',
    proofDigest: '',
    dekId: '',
    encryptionStatus: '',
    progress: 0,
    trainPhase: '',
    trainError: '',
    trainingTaskId: ''
  }
  form.value = {
    account_id: ctx.currentAccountId || '',
    name: '',
    scene: 'fraud',
    algorithm: 'XGBoost 分类',
    params: {},
    injectKey: 'yes'
  }
  applyDefaults()
}

function finish() {
  if (portalTaskId.value) router.push(`/user/tasks/${portalTaskId.value}`)
  else router.push('/user/tasks')
}

onMounted(async () => {
  if (!ctx.accounts.length) await ctx.bootstrap()
  form.value.account_id = ctx.currentAccountId
  applyDefaults()
})

watch(
  () => ctx.currentAccountId,
  id => {
    form.value.account_id = id
  }
)

onBeforeUnmount(() => {
  stopTrainPoll()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.panel {
  margin-top: 18px;
  min-height: 360px;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 12px;
}

:deep(.el-steps) {
  margin-top: 4px;
}

:deep(.el-step__head) {
  width: 28px;
}

:deep(.el-step__title) {
  font-size: 16px;
  font-weight: 500;
  line-height: 1.3;
  white-space: nowrap;
}
</style>
