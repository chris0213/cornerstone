import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../app/router'
import { getToken, getRefreshToken, setTokens, clearTokens } from './tokenStorage'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// 统一把 config.url 规范为相对 baseURL 的路径（去掉重复的 /api/v1 前缀）
function normalizeUrl(url?: string) {
  if (!url) return url
  if (url.startsWith('/api/v1/')) return url.slice('/api/v1'.length)
  if (url === '/api/v1' || url === '/api/v1/') return '/'
  return url
}

const NO_AUTH_ROUTES = ['/auth/token', '/auth/login-with-captcha', '/auth/captcha', '/auth/sso/config', '/auth/sso/authorize', '/auth/sso/callback', '/auth/sso/saml/callback', '/auth/ldap/enabled', '/auth/ldap/login', '/settings/public/brand', '/settings/logo']

// 正在进行中的 refresh Promise（用于多个 401 请求串行化 refresh）
let refreshPromise: Promise<string | null> | null = null

async function handle401(error: any) {
  const config = error.config
  const originalRequest = { ...config }

  // 已被标记为重试过的请求，不再重试，直接清 token 跳登录
  if (originalRequest._retry) {
    clearTokens()
    if (router.currentRoute.value.path !== '/login') {
      localStorage.setItem('redirect_after_login', router.currentRoute.value.fullPath)
      router.push('/login')
    }
    return Promise.reject(error)
  }

  // 如果正在 refresh，等待同一轮 refresh 结果
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refreshToken = getRefreshToken()
      if (!refreshToken) {
        return null
      }
      try {
        const resp = await axios.post('/api/v1/auth/refresh', {}, {
          headers: {
            'X-Refresh-Token': refreshToken,
          },
        })
        const newAccessToken = resp.data.access_token
        const newRefreshToken = resp.data.refresh_token
        // 沿用当前「记住我」存储位置
        setTokens(newAccessToken, newRefreshToken, localStorage.getItem('remember_me') === '1')
        return newAccessToken
      } catch {
        clearTokens()
        return null
      } finally {
        refreshPromise = null
      }
    })()
  }

  const newToken = await refreshPromise
  if (newToken) {
    originalRequest._retry = true
    originalRequest.headers = originalRequest.headers || {}
    originalRequest.headers.Authorization = `Bearer ${newToken}`
    // 重新发原请求
    return api.request(originalRequest)
  } else {
    // refresh 失败，清 token 跳登录
    if (router.currentRoute.value.path !== '/login') {
      localStorage.setItem('redirect_after_login', router.currentRoute.value.fullPath)
      router.push('/login')
    }
    return Promise.reject(error)
  }
}

api.interceptors.request.use(
  (config) => {
    const token = getToken()

    config.url = normalizeUrl(config.url)

    if (token && !NO_AUTH_ROUTES.includes(config.url || '')) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const url = normalizeUrl(error.config?.url)
      // refresh 接口本身返回 401 直接清 token，不走 refresh 流程
      if (url === '/auth/refresh') {
        clearTokens()
        if (router.currentRoute.value.path !== '/login') {
          localStorage.setItem('redirect_after_login', router.currentRoute.value.fullPath)
          router.push('/login')
        }
        return Promise.reject(error)
      }
      return handle401(error)
    }
    // IP 白名单拒绝（403）：token 本身有效，只是 IP 被拦，给出明确原因避免表现为莫名"掉登录"。
    // 登录页跳过全局 toast——页面内已有内联错误提示，避免双重弹窗。
    if (error.response?.status === 403) {
      const detail = error.response?.data?.detail
      if (
        typeof detail === 'string' &&
        detail.includes('白名单') &&
        router.currentRoute.value.path !== '/login'
      ) {
        ElMessage({ message: detail, type: 'error', duration: 6000, showClose: true })
      }
    }
    return Promise.reject(error)
  }
)

export default api
