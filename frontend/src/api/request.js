import axios from 'axios'
import router from '@/router'

const TOKEN_KEY = 'drama_token'
const USER_KEY = 'drama_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
}
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}
export function getStoredUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
}

const request = axios.create({
  baseURL: '/',
  timeout: 120000
})

// 请求拦截：自动带 token
request.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 从后端错误结构里提取中文信息
export function extractError(err) {
  if (err?.response?.data?.detail) {
    const d = err.response.data.detail
    return typeof d === 'string' ? d : JSON.stringify(d)
  }
  if (err?.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  if (err?.message === 'Network Error') return '网络异常，无法连接服务器'
  return err?.message || '请求失败'
}

// 响应拦截：401 清登录态并跳登录页
request.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    if (err?.response?.status === 401) {
      clearAuth()
      if (router.currentRoute.value.name !== 'login') {
        router.replace({ name: 'login' })
      }
    }
    return Promise.reject(err)
  }
)

export default request
