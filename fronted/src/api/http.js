import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

const envMs = Number(import.meta.env.VITE_HTTP_TIMEOUT_MS)
const configured =
  Number.isFinite(envMs) && envMs > 0 ? envMs : 300000
// 不低于 60s：避免旧 .env 写 15000、或审计锁排队时 bootstrap / 向导误超时
const HTTP_TIMEOUT_MS = Math.max(configured, 180000)

export const http = axios.create({
  baseURL: API_BASE,
  timeout: HTTP_TIMEOUT_MS
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export function unwrap(resp) {
  const payload = resp?.data
  if (!payload || typeof payload !== 'object') throw new Error('后端响应格式错误')
  if (payload.code !== 0) throw new Error(payload.message || '请求失败')
  return payload.data
}
