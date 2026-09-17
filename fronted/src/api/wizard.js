/**
 * 新建任务向导专用 API（独立文件，避免仅同步 index.js 时缺导出导致白屏）
 */
import { http, unwrap } from './http.js'

export async function wizardInit(payload) {
  const res = await http.post('/wizard/init', {
    name: payload.name,
    scene: payload.scene || 'fraud',
    account_id: payload.account_id
  })
  return unwrap(res)
}

export async function wizardCreateContainer(payload) {
  const res = await http.post('/wizard/container', {
    task_id: payload.task_id,
    resources: payload.resources
  })
  return unwrap(res)
}

export async function wizardAttest(payload) {
  const res = await http.post('/wizard/attest', { task_id: payload.task_id })
  return unwrap(res)
}

export async function wizardUploadCsv(taskId, file, algorithm, params) {
  const fd = new FormData()
  fd.append('task_id', taskId)
  fd.append('file', file.raw || file)
  fd.append('algorithm', algorithm)
  fd.append('params', JSON.stringify(params || {}))
  const res = await http.post('/wizard/upload', fd)
  return unwrap(res)
}

export async function wizardProtectData(payload) {
  const res = await http.post('/wizard/protect-data', { task_id: payload.task_id })
  return unwrap(res)
}

export async function wizardStartTrain(payload) {
  const res = await http.post('/wizard/train', { task_id: payload.task_id })
  return unwrap(res)
}

export async function wizardTrainStatus(taskId) {
  const res = await http.get('/wizard/train-status', { params: { task_id: taskId } })
  return unwrap(res)
}

export async function wizardDownloadModelBlob(taskId) {
  const res = await http.get('/wizard/model-download', {
    params: { task_id: taskId },
    responseType: 'blob'
  })
  return res.data
}

export async function wizardDownloadAttestationBlob(taskId) {
  const res = await http.get(`/tasks/${taskId}/result`, {
    params: { file_type: 'attestation' },
    responseType: 'blob'
  })
  return res.data
}
