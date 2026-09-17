// 纯演示版 API，所有函数返回模拟数据，无真实网络请求
import { useTaskStore } from '../stores/task'
import { http, unwrap } from './http.js'

const delay = (ms = 500) => new Promise(resolve => setTimeout(resolve, ms))

export async function login(data) {
  const res = await http.post('/auth/login', data)
  const d = unwrap(res)
  return {
    code: 0,
    token: d.token,
    role: d.role,
    user: d.user,
    default_account_id: d.default_account_id
  }
}

export async function getNodes() {
  await delay()
  return [
    { id: 'TEE-01', name: '可信节点1', status: 'online', cpu: 30, memory: 40 },
    { id: 'TEE-02', name: '可信节点2', status: 'online', cpu: 65, memory: 70 },
    { id: 'TEE-03', name: '可信节点3', status: 'offline', cpu: 0, memory: 0 }
  ]
}

export async function createTrainingContainer(resources = {}, taskData = {}) {
  await delay(1500)
  const containerId = 'cont-' + Math.random().toString(36).substring(2, 10)
  return {
    code: 0,
    data: {
      container_id: containerId,
      attestation_address: `localhost:${Math.floor(Math.random() * 1000 + 30000)}`,
      training_address: `localhost:${Math.floor(Math.random() * 1000 + 31000)}`,
      status: 'running',
      image: 'csv-training-service:latest',
      image_hash: 'sha256:' + Math.random().toString(36).substring(2, 10),
      created_at: new Date().toISOString()
    }
  }
}

export async function getContainers() {
  await delay()
  const store = useTaskStore()
  const containers = store.tasks
    .filter(t => t.containerInfo && t.trainingStatus !== 'destroyed')
    .map(t => ({
      id: t.containerInfo.container_id,
      name: t.containerInfo.name || 'training-container',
      status: t.trainingStatus === 'running' ? 'running' : 'exited',
      attestation_address: t.containerInfo.attestation_address,
      training_address: t.containerInfo.training_address,
      image: t.containerInfo.image,
      image_hash: t.containerInfo.image_hash,
      created_at: t.containerInfo.created_at
    }))
  return { data: containers }
}

export async function destroyContainer(containerId) {
  await delay(800)
  const store = useTaskStore()
  const task = store.tasks.find(t => t.containerInfo?.container_id === containerId)
  if (task) {
    task.trainingStatus = 'destroyed'
    task.containerInfo = null
  }
  return { code: 0, message: 'destroyed' }
}

export async function attestContainer(attestAddr, challenge) {
  await delay(1000)
  return {
    data: {
      evidence: {
        type: 'csv_simulated',
        challenge,
        pubkey_hash: 'mock-pubkey-hash',
        app_measurement: 'mock-measurement',
        evidence: 'mock-evidence-base64',
        timestamp: Date.now() / 1000,
        service_type: 'training'
      },
      public_key: `-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCqGKukO1De7zhZj6+H0qtjTkVxwTCpvKe4eCZ0
FPqri0cb2JZfXJ/DgYSF6vUpwmJG8wVQZKjeGcjDOL5UlsuusFncCzWBQ7RKNUSesmQRMSGkVb1/
3j+skZ6UtW+5u09lHNsj6tQ51s1SPrCBkedbNf0Tp0GbMJDyR4e9T04ZZwIDAQAB
-----END PUBLIC KEY-----`
    }
  }
}

export async function verifyEvidence(evidence) {
  await delay(800)
  return {
    data: {
      valid: true,
      token: 'mock-token-' + Math.random().toString(36).substring(2),
      session_id: 'mock-session-' + Math.random().toString(36).substring(2),
      expires_at: Date.now() / 1000 + 3600,
      measurements: {
        csv_status: 'simulated',
        app_measurement: evidence.app_measurement,
        evidence_hash: 'simulated'
      }
    }
  }
}

export async function injectKey(attestAddr, encryptedKey) {
  await delay(600)
  return {
    code: 0,
    data: {
      key_id: 'key-' + Math.random().toString(36).substring(2, 10),
      client_id: 'client-' + Math.random().toString(36).substring(2, 8),
      expires_at: Date.now() / 1000 + 3600
    }
  }
}

export async function uploadEncryptedFile(formData) {
  await delay(1200)
  return {
    code: 0,
    uri: 'file:///data/encrypted/' + Math.random().toString(36).substring(2) + '.bin'
  }
}

export async function createTrainingTask(trainAddr, algorithm, dataUri, keyId, params) {
  await delay(1000)
  return {
    task_id: 'task-' + Math.random().toString(36).substring(2, 10)
  }
}

export async function getTaskStatus(trainAddr, taskId) {
  await delay(300)
  const store = useTaskStore()
  const task = store.tasks.find(t => t.taskId === taskId)
  if (!task) return { status: 'pending' }
  if (task.simProgress === undefined) task.simProgress = 0
  task.simProgress += 30
  if (task.simProgress >= 100) {
    return { status: 'completed' }
  } else if (task.simProgress >= 30) {
    return { status: 'running' }
  } else {
    return { status: 'pending' }
  }
}

export async function getTaskResult(trainAddr, taskId) {
  await delay(800)
  const mockModel = 'mock model data for demonstration'
  const encoder = new TextEncoder()
  const data = encoder.encode(mockModel)
  const hex = Array.from(data).map(b => b.toString(16).padStart(2, '0')).join('')
  return {
    model: hex,
    metadata: { algorithm: 'SM4-ECB (simulated)', key_id: 'mock-key', padding: 'PKCS7' }
  }
}

// =========================
// 普通用户（医保数据管理员）原型 API（模拟后端）
// =========================

const mockAccounts = [
  { id: 'acc-a', name: 'A市医保局', created_at: '2025-11-02 09:12:00' },
  { id: 'acc-b', name: 'B保险公司', created_at: '2026-01-15 14:40:00' }
]

const sceneLabel = {
  fraud: '欺诈检测',
  claim_amount: '理赔金额预测',
  anomaly_cluster: '异常行为聚类'
}

function nowMinus(minutes) {
  return new Date(Date.now() - minutes * 60 * 1000).toISOString()
}

const mockTasksByAccount = {
  'acc-a': [],
  'acc-b': []
}

const mockAuditByTaskId = {
  't-1001': [
    { time: nowMinus(24 * 60 - 1), type: '数据授权', result: '允许' },
    { time: nowMinus(24 * 60 - 3), type: '远程证明', result: '通过' },
    { time: nowMinus(24 * 60 - 4), type: '密钥调用', result: '成功' }
  ],
  't-1002': [
    { time: nowMinus(6 * 60 - 1), type: '数据授权', result: '允许' },
    { time: nowMinus(6 * 60 - 2), type: '远程证明', result: '通过' }
  ]
}

export async function getUserAccounts() {
  const res = await http.get('/accounts')
  const d = unwrap(res)
  return d.items || []
}

export async function getNotifications() {
  const accountId = localStorage.getItem('current_account_id') || ''
  const res = await http.get('/notifications', { params: { account_id: accountId } })
  const d = unwrap(res)
  return d.items || []
}

export async function getAccountStats(accountId) {
  const res = await http.get(`/accounts/${accountId}/stats`)
  return unwrap(res)
}

function inTimeRange(iso, start, end) {
  const ts = new Date(iso).getTime()
  if (start && ts < new Date(start).getTime()) return false
  if (end && ts > new Date(end).getTime()) return false
  return true
}

export async function getTasks(query = {}) {
  const res = await http.get('/tasks', { params: query })
  const d = unwrap(res)
  return {
    items: d.items || [],
    total: Number(d.total || 0)
  }
}

export async function getTaskDetail(taskId) {
  const res = await http.get(`/tasks/${taskId}`)
  return unwrap(res)
}

export async function getTaskAudit(taskId) {
  const res = await http.get(`/tasks/${taskId}/audit`)
  const d = unwrap(res)
  return d.items || []
}

export async function createTask(payload) {
  const res = await http.post('/tasks', payload)
  const d = unwrap(res)
  return { task_id: d.task_id }
}

export * from './wizard.js'

// 返回“加密文件流”的原型：这里用 Blob 触发下载，并提示已用公钥加密
export async function downloadTaskResult(taskId, fileType) {
  const res = await http.get(`/tasks/${taskId}/result`, {
    params: { file_type: fileType },
    responseType: 'blob'
  })
  const ct = (res.headers && (res.headers['content-type'] || res.headers['Content-Type'])) || ''
  if (typeof ct === 'string' && ct.includes('application/json')) {
    const text = await res.data.text()
    let msg = '下载失败'
    try {
      const j = JSON.parse(text)
      msg = j.message || msg
    } catch {
      msg = text.slice(0, 200) || msg
    }
    throw new Error(msg)
  }
  return res.data
}

// =========================
// 管理员界面（系统运维）原型 API（模拟后端）
// =========================

const mockAdminState = {
  nodes: [
    {
      id: 'an-01',
      name: 'TEE节点A',
      ip: '192.168.10.11',
      cpu_model: '海光',
      tee_type: 'CSV',
      status: 'online',
      epc_total_mb: 1024,
      epc_used_mb: 520,
      csv_protected_size: 512,
      csv_protection_level: 'enhanced',
      hardware: { kernel_version: '5.15.0-103', tee_driver_version: 'tee-driver-1.2.0', cpu_cores: 32, memory_total_gb: 128 },
      recent_proofs: [
        { time: new Date(Date.now() - 40 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
        { time: new Date(Date.now() - 120 * 60 * 1000).toISOString(), result: 'fail', reason: 'PCR 不一致' },
        { time: new Date(Date.now() - 200 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
        { time: new Date(Date.now() - 260 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
        { time: new Date(Date.now() - 330 * 60 * 1000).toISOString(), result: 'pass', reason: '-' }
      ]
    },
    {
      id: 'an-02',
      name: 'TEE节点B',
      ip: '192.168.10.12',
      cpu_model: '海光',
      tee_type: 'CSV',
      status: 'offline',
      epc_total_mb: 2048,
      epc_used_mb: 880,
      hardware: { kernel_version: '5.10.0-116', tee_driver_version: 'tee-driver-2.0.1', cpu_cores: 48, memory_total_gb: 256 },
      recent_proofs: [
        { time: new Date(Date.now() - 35 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
        { time: new Date(Date.now() - 95 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
        { time: new Date(Date.now() - 165 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
        { time: new Date(Date.now() - 240 * 60 * 1000).toISOString(), result: 'fail', reason: '证据哈希校验失败' },
        { time: new Date(Date.now() - 310 * 60 * 1000).toISOString(), result: 'pass', reason: '-' }
      ]
    },
    {
      id: 'an-03',
      name: 'TEE节点C',
      ip: '192.168.10.13',
      cpu_model: '海光',
      tee_type: 'CSV',
      status: 'offline',
      epc_total_mb: 1024,
      epc_used_mb: 210,
      csv_protected_size: 512,
      csv_protection_level: 'enhanced',
      hardware: { kernel_version: '6.1.0-7', tee_driver_version: 'tee-driver-1.1.4', cpu_cores: 24, memory_total_gb: 64 },
      recent_proofs: [
        { time: new Date(Date.now() - 15 * 60 * 1000).toISOString(), result: 'fail', reason: '环境测量失败（演示）' },
        { time: new Date(Date.now() - 85 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
        { time: new Date(Date.now() - 155 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
        { time: new Date(Date.now() - 225 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
        { time: new Date(Date.now() - 295 * 60 * 1000).toISOString(), result: 'pass', reason: '-' }
      ]
    }
  ],
  containers: [
    {
      id: 'c-101',
      name: 'fraud-detect-train-20260413',
      image: 'csv-training-service:v1.3.2',
      status: 'InProgress',
      node_id: 'an-01',
      node_name: 'TEE节点A',
      tee_type: 'CSV',
      epc_limit_mb: 512,
      epc_used_mb: 286,
      created_at: new Date(Date.now() - 36 * 60 * 1000).toISOString(),
      logs: [
        '[INFO] image pull complete: csv-training-service:v1.3.2',
        '[INFO] remote attestation passed',
        '[INFO] key injected: kms-key-001',
        '[INFO] dataset loaded: claims_q2_authorized.csv',
        '[INFO] training epoch 42/120'
      ],
      audit: [
        { id: 'au-1', time: new Date(Date.now() - 34 * 60 * 1000).toISOString(), type: '远程证明', result: 'success', detail_json: { pcr: '0x6ac...', hash: '0x8bf1...' } },
        { id: 'au-2', time: new Date(Date.now() - 31 * 60 * 1000).toISOString(), type: '密钥调用', result: 'success', detail_json: { key_id: 'kms-key-001' } }
      ]
    },
    {
      id: 'c-102',
      name: 'risk-score-regression-20260413',
      image: 'risk-trainer:v2.0.1',
      status: 'Pending',
      node_id: 'an-01',
      node_name: 'TEE节点A',
      tee_type: 'CSV',
      epc_limit_mb: 512,
      epc_used_mb: 74,
      created_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
      logs: [
        '[INFO] container created',
        '[INFO] waiting for scheduler slot',
        '[INFO] preparing encrypted dataset mount'
      ],
      audit: [
        { id: 'au-3', time: new Date(Date.now() - 10 * 60 * 1000).toISOString(), type: '数据授权', result: 'success', detail_json: { dataset: 'claims_q2_authorized.csv', account_id: 'acc-a' } }
      ]
    },
    {
      id: 'c-103',
      name: 'behavior-cluster-job-20260412',
      image: 'csv-training-service:v1.3.1',
      status: 'Pending',
      node_id: 'an-03',
      node_name: 'TEE节点C',
      tee_type: 'CSV',
      epc_limit_mb: 512,
      epc_used_mb: 398,
      created_at: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(),
      logs: [
        '[INFO] container started',
        '[INFO] remote attestation requested',
        '[ERROR] attestation verification failed: PCR mismatch'
      ],
      audit: [
        { id: 'au-4', time: new Date(Date.now() - 3.8 * 60 * 60 * 1000).toISOString(), type: '远程证明', result: 'fail', detail_json: { pcr: '0x111...', expected: '0x222...', reason: 'PCR 不一致（演示）' } }
      ]
    }
  ],
  auditEvents: [],
  alertRules: [],
  systemConfig: {
    cert_valid_until: new Date(Date.now() + 60 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
    audit_retention_days: 30,
    tee_driver_path: '/dev/tee0',
    crypto_lib_version: 'v1.2.3'
  },
  metricsState: {},
  attestationReports: []
}

// 初始化一些审计事件、告警、证明报告（基于当前时间）
;(function initAdminMocks() {
  const now = Date.now()
  // 不再注入预置“假”审计日志；仅展示真实操作产生的事件
  mockAdminState.auditEvents = []
  mockAdminState.alerts = []

  // 证明报告：为 node & task 生成示例
  const nodeIds = mockAdminState.nodes.map(n => n.id)
  const taskIds = ['t-1001', 't-1002', 't-1003']
  mockAdminState.attestationReports = []
  nodeIds.forEach((nid, i) => {
    const passed = i !== 2
    mockAdminState.attestationReports.push(
      {
        id: 'rep-' + nid + '-1',
        node_id: nid,
        task_id: '',
        time: new Date(now - 70 * 60 * 1000 + i * 15 * 60 * 1000).toISOString(),
        validation: { passed, tcb_version: 'tcb-' + (i + 1), pcr: '0x' + (5000 + i).toString(16), token: 'token-' + nid + '-1' },
        Evidence: { type: 'csv_simulated', challenge: 'ch-' + i, pubkey_hash: '0x' + (8000 + i).toString(16) },
        Quote: { report_id: 'rq-' + i, cpu_svn: '0x' + (9000 + i).toString(16) },
        benchmark: i === 0 ? { diff_rows: [{ field: 'PCR', base: '0x123', current: '0x124', diff: '1 bit flip' }] } : null
      },
      {
        id: 'rep-' + nid + '-2',
        node_id: nid,
        task_id: '',
        time: new Date(now - 35 * 60 * 1000 + i * 20 * 60 * 1000).toISOString(),
        validation: { passed: true, tcb_version: 'tcb-' + (i + 1), pcr: '0x' + (6000 + i).toString(16), token: 'token-' + nid + '-2' },
        Evidence: { type: 'csv_simulated', challenge: 'ch-' + (i + 10), pubkey_hash: '0x' + (8200 + i).toString(16) },
        Quote: { report_id: 'rq-' + (i + 10), cpu_svn: '0x' + (9100 + i).toString(16) }
      }
    )
  })
  taskIds.forEach((tid, i) => {
    mockAdminState.attestationReports.push({
      id: 'rep-task-' + tid,
      node_id: '',
      task_id: tid,
      time: new Date(now - 40 * 60 * 1000 + i * 25 * 60 * 1000).toISOString(),
      validation: { passed: i !== 2, tcb_version: 'tcb-task-' + (i + 1), pcr: '0x' + (7000 + i).toString(16), token: 'token-' + tid },
      Evidence: { type: 'csv_simulated', challenge: 'ch-task-' + i, pubkey_hash: '0x' + (8800 + i).toString(16) },
      Quote: { report_id: 'rq-task-' + i, cpu_svn: '0x' + (9900 + i).toString(16) }
    })
  })
})()

/** @returns {Promise<Array>} 仅节点列表（兼容旧接口：data 为数组或 { nodes }） */
export async function getAdminNodes() {
  const res = await http.get('/admin/nodes')
  const d = unwrap(res)
  if (Array.isArray(d)) return d
  if (d && Array.isArray(d.nodes)) return d.nodes
  return []
}

/** 一次请求：节点列表 + 各节点 live_metrics（后端单次 Docker 快照，减轻卡顿） */
export async function getAdminNodesPanel() {
  const res = await http.get('/admin/nodes')
  const d = unwrap(res)
  if (Array.isArray(d)) return { nodes: d, live_metrics: {} }
  return { nodes: d.nodes || [], live_metrics: d.live_metrics || {} }
}

export async function getNodeLiveMetrics(nodeId) {
  const res = await http.get(`/admin/nodes/${nodeId}/live-metrics`)
  return unwrap(res)
}

export async function setNodePower(nodeId, power) {
  const res = await http.post(`/admin/nodes/${nodeId}/power`, { power })
  return unwrap(res)
}

export async function getNodeDetail(nodeId) {
  const res = await http.get(`/admin/nodes/${nodeId}/detail`)
  return unwrap(res)
}

export async function createNode(payload) {
  await delay(500)
  const id = 'an-' + Math.random().toString(16).slice(2, 6)
  const teeType = payload.tee_type || 'CSV'
  const epcTotalMb = teeType === 'TrustZone' ? 2048 : 1024
  const node = {
    id,
    name: 'TEE节点' + id.slice(-2),
    ip: payload.ip,
    cpu_model: '海光',
    tee_type: teeType,
    status: 'online',
    epc_total_mb: epcTotalMb,
    epc_used_mb: Math.round((teeType === 'TrustZone' ? 0.35 : 0.22) * epcTotalMb),
    hardware: { kernel_version: '5.15.0-demo', tee_driver_version: 'tee-driver-demo', cpu_cores: 32, memory_total_gb: 128 },
    recent_proofs: [
      { time: new Date().toISOString(), result: 'pass', reason: '-' },
      { time: new Date(Date.now() - 60 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
      { time: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
      { time: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(), result: 'pass', reason: '-' },
      { time: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(), result: 'pass', reason: '-' }
    ]
  }
  
  // 添加 CSV 资源相关字段
  if (teeType === 'CSV') {
    node.csv_protected_size = 512
    node.csv_protection_level = 'enhanced'
  }
  
  mockAdminState.nodes.unshift(node)
  return { node_id: id }
}

export async function drainNodeTasks(nodeId) {
  await delay(400)
  const node = mockAdminState.nodes.find(n => n.id === nodeId)
  if (!node) throw new Error('节点不存在')
  // 演示：将节点标记为维护中
  node.status = 'maintenance'
  return { code: 0 }
}

export async function deleteNode(nodeId) {
  await delay(500)
  const idx = mockAdminState.nodes.findIndex(n => n.id === nodeId)
  if (idx === -1) throw new Error('节点不存在')
  // 演示：删除节点同时将其容器清理
  mockAdminState.nodes.splice(idx, 1)
  mockAdminState.containers = mockAdminState.containers.filter(c => c.node_id !== nodeId)
  return { code: 0 }
}

export async function triggerNodeAttestation(nodeId) {
  await delay(650)
  const node = mockAdminState.nodes.find(n => n.id === nodeId)
  if (!node) throw new Error('节点不存在')
  const ok = Math.random() > 0.2
  const rec = { time: new Date().toISOString(), result: ok ? 'pass' : 'fail', reason: ok ? '-' : 'PCR 不一致（演示）' }
  node.recent_proofs.unshift(rec)
  node.recent_proofs = node.recent_proofs.slice(0, 5)
  node.status = ok ? 'online' : 'proof_failed'
  return { code: 0, result: ok ? 'pass' : 'fail' }
}

export async function restartNodeDriver(nodeId) {
  await delay(500)
  const node = mockAdminState.nodes.find(n => n.id === nodeId)
  if (!node) throw new Error('节点不存在')
  node.status = 'online'
  node.epc_used_mb = Math.round(node.epc_total_mb * (0.2 + Math.random() * 0.6))
  return { code: 0 }
}

export async function updateCsvResourcesApi(nodeId, config) {
  const body = {}
  if (config.epc_total_mb != null) body.epc_total_mb = config.epc_total_mb
  if (config.protected_size != null) body.protected_size = config.protected_size
  if (config.protection_level != null) body.protection_level = config.protection_level
  const res = await http.post(`/admin/nodes/${nodeId}/resources`, body)
  return unwrap(res)
}

export async function getClusterStatus() {
  await delay(250)
  const nodes_total = mockAdminState.nodes.length
  const nodes_online = mockAdminState.nodes.filter(n => n.status === 'online').length
  const containers_total = mockAdminState.containers.length
  const containers_running = mockAdminState.containers.filter(
    (c) => c.status === 'InProgress' || c.status === 'Running'
  ).length
  const now = Date.now()
  const todayStart = new Date(new Date(now).toDateString()).getTime()
  const todayEvents = mockAdminState.auditEvents.filter(e => new Date(e.time).getTime() >= todayStart)
  const today_audit_count = todayEvents.length
  const today_anomalies_count = todayEvents.filter(e => e.result === 'fail').length
  return {
    nodes_total,
    nodes_online,
    containers_total,
    containers_running,
    today_audit_count,
    today_anomalies_count,
    anomaly: today_anomalies_count > 0
  }
}

export async function getEpcUsage() {
  await delay(200)
  const total_mb = mockAdminState.nodes.reduce((s, n) => s + (n.epc_total_mb || 0), 0) || 1
  const used_mb = mockAdminState.nodes.reduce((s, n) => s + (n.epc_used_mb || 0), 0)
  return { used_mb, total_mb }
}

export async function getAudit({ limit = 5 } = {}) {
  await delay(200)
  const items = mockAdminState.auditEvents.slice().sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime()).slice(0, Number(limit))
  return { items }
}

export async function getAdminAlerts() {
  await delay(120)
  return mockAdminState.alerts || []
}

export async function getAdminContainers(query = {}) {
  const { status, node_id, tee_type, page = 1, size = 10 } = query
  const res = await http.get('/containers')
  const d = unwrap(res)
  const raw = Array.isArray(d) ? d : []
  let filtered = raw.map(c => {
    const mem = String(c?.resources?.memory || '').toLowerCase()
    const memMb = mem.endsWith('g')
      ? Math.round(Number(mem.replace('g', '')) * 1024)
      : (mem.endsWith('m') ? Math.round(Number(mem.replace('m', ''))) : 512)
    const epcLimit = Number.isFinite(memMb) && memMb > 0 ? memMb : 512
    const td = c.task_data && typeof c.task_data === 'object' ? c.task_data : {}
    const userWizard = String(td.portal_task_id || '').trim()
    const adminStatus = String(c.admin_status || '').trim()
    const statusNorm = adminStatus === 'InProgress' ? 'InProgress' : 'Pending'
    return {
      id: c.id,
      name: c.name || String(c.id || '').slice(0, 12),
      image: c.image || '-',
      status: statusNorm,
      node_id: c.node_id || 'docker-host',
      node_name: userWizard ? 'TEE节点A' : (c.node_name || 'docker-host'),
      tee_type: c.tee_type || 'CSV',
      epc_limit_mb: epcLimit,
      created_at: c.created_at
    }
  })
  if (status) filtered = filtered.filter(c => c.status === status)
  if (node_id) filtered = filtered.filter(c => c.node_id === node_id)
  if (tee_type) filtered = filtered.filter(c => c.tee_type === tee_type)
  filtered.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
  const total = filtered.length
  const s = Number(size)
  const p = Number(page)
  const start = (p - 1) * s
  const pageItems = filtered.slice(start, start + s)
  // 与容器详情页同一套 metrics 接口，保证列表「内存占比」与详情一致
  const items = await Promise.all(
    pageItems.map(async (c) => {
      try {
        const m = await getContainerMetrics(c.id)
        const used = Math.round(Number(m.used_mb) || 0)
        const pool = Math.max(1, Math.round(Number(m.pool_mb) || c.epc_limit_mb || 512))
        const pct = Math.max(0, Math.min(100, Math.round(Number(m.csv_memory_pct) || 0)))
        return {
          ...c,
          mem_pct: pct,
          mem_used_mb: used,
          mem_total_mb: pool
        }
      } catch {
        const pool = Math.max(1, c.epc_limit_mb || 512)
        return {
          ...c,
          mem_pct: 0,
          mem_used_mb: 0,
          mem_total_mb: pool
        }
      }
    })
  )
  return { items, total }
}

export async function deleteContainers(ids = []) {
  await Promise.all((ids || []).map(id => http.delete(`/containers/${id}`)))
  return { code: 0 }
}

export async function destroyAdminContainer(containerId) {
  await http.delete(`/containers/${containerId}`)
  return { code: 0 }
}

export async function pauseContainer(containerId) {
  throw new Error('当前后端未提供暂停容器接口')
}

export async function resumeContainer(containerId) {
  await delay(250)
  const c = mockAdminState.containers.find(x => x.id === containerId)
  if (!c) throw new Error('容器不存在')
  c.status = 'InProgress'
  c.logs.push('[INFO] container resumed')
  return { code: 0 }
}

export async function getContainerDetail(containerId) {
  const [cRes, lRes] = await Promise.all([
    http.get(`/containers/${containerId}`),
    http.get(`/containers/${containerId}/logs`, { params: { tail: 400 } })
  ])
  const container = unwrap(cRes)
  const logsPayload = unwrap(lRes)
  const lines = logsPayload.lines || []
  return { container, logs: lines }
}

export async function getContainerMetrics(containerId) {
  const res = await http.get(`/containers/${containerId}/metrics`)
  const d = unwrap(res)
  const t = d.time || new Date().toISOString()
  const local = new Date(t).toLocaleTimeString()
  return {
    time: local,
    csv_memory_pct: Number(d.csv_memory_pct || 0),
    used_mb: d.used_mb,
    pool_mb: d.pool_mb
  }
}

export async function getAuditLogs(query = {}) {
  const params = { ...query }
  if (Array.isArray(params.types)) params.types = params.types.join(',')
  if (Array.isArray(params.results)) params.results = params.results.join(',')
  const res = await http.get('/audit/logs', { params })
  const d = unwrap(res)
  return {
    items: d.items || [],
    total: Number(d.total || 0)
  }
}

export async function exportAuditLogs(query = {}) {
  await delay(200)
  const {
    start_time,
    end_time,
    types = [],
    object_id_like = '',
    results = [],
    format = 'json'
  } = query
  const res = await getAuditLogs({
    start_time,
    end_time,
    types,
    object_id_like,
    results,
    page: 1,
    size: 500
  })
  const items = res.items || []
  if (format === 'csv') {
    const header = ['time', 'operation_type', 'object_type', 'object_id', 'actor', 'result', 'detail_json']
    const lines = [header.join(',')]
    items.forEach(i => {
      const row = header.map(k => `"${String(i[k] ?? '').replace(/"/g, '""')}"`).join(',')
      lines.push(row)
    })
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    return blob
  }
  const blob = new Blob([JSON.stringify(items, null, 2)], { type: 'application/json' })
  return blob
}

export async function getAttestationReports(query = {}) {
  await delay(250)
  const { node_id = '', task_id = '', limit = 10 } = query
  let filtered = mockAdminState.attestationReports.slice()
  if (node_id) filtered = filtered.filter(r => r.node_id === node_id)
  if (task_id) filtered = filtered.filter(r => r.task_id === task_id)
  filtered.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
  const items = filtered.slice(0, Number(limit)).map(r => ({
    time: r.time,
    validation: r.validation,
    evidence: r.Evidence,
    quote: r.Quote,
    benchmark: r.benchmark || null
  }))
  return { items }
}

export async function getAllTasks() {
  await delay(160)
  // 给证明查看器选择“按任务”用（演示数据）
  return [
    { id: 't-1001', name: '欺诈检测-一季度样本' },
    { id: 't-1002', name: '理赔金额预测-回归基线' },
    { id: 't-1003', name: '异常行为聚类-探索版' }
  ]
}

export async function getSystemConfig() {
  const res = await http.get('/admin/system-config')
  return unwrap(res)
}

export async function updateSystemConfig(newConfig) {
  const res = await http.patch('/admin/system-config', newConfig)
  return unwrap(res)
}

export async function updateCertificate(payload) {
  await delay(300)
  // 演示：更新时间在当前日期往后 90 天
  mockAdminState.systemConfig.cert_valid_until = new Date(Date.now() + 90 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
  return { code: 0, file_name: payload?.file_name || '' }
}

export async function clearAuditLogs() {
  const res = await http.delete('/admin/audit/logs')
  return unwrap(res)
}
