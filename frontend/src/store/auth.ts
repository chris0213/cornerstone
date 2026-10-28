import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAppStore } from './index'
import api from '../api/axios'
import { getToken, getRefreshToken, setTokens, clearTokens, isRemembered } from '../api/tokenStorage'
import { i18n } from '../i18n'

export interface User {
  id: number
  username: string
  display_name: string
  email: string
  role: string
  role_display_name: string
  permissions: string[]
  is_active: boolean
  is_superuser: boolean
  is_sso_user?: boolean
  last_login_at?: string
  last_login_ip?: string
  avatar?: string
  created_at?: string
  updated_at?: string
}

export interface SSOConfig {
  enabled: boolean
  login_methods: string[]
  has_oauth2: boolean
  has_saml: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken())
  const refreshToken = ref<string | null>(getRefreshToken())
  const user = ref<User | null>(null)
  const isLoggedIn = computed(() => !!token.value)
  const ssoConfig = ref<SSOConfig | null>(null)
  const isRefreshing = ref(false)
  
  function hasPermission(module: string, action?: string): boolean {
    if (!user.value) return false
    if (user.value.is_superuser) return true
    
    const permissionStr = action ? `${module}:${action}` : module
    return user.value.permissions.includes(permissionStr)
  }
  
  function hasRole(role: string): boolean {
    if (!user.value) return false
    return user.value.role === role
  }
  
  function isReadOnly(): boolean {
    return hasRole('viewer')
  }
  
  function isOperator(): boolean {
    return hasRole('engineer')
  }
  
  function isAdmin(): boolean {
    return hasRole('super_admin') || (user.value?.is_superuser ?? false)
  }

  async function login(username: string, password: string, remember: boolean = true) {
    try {
      const response = await api.post('/auth/token', new URLSearchParams({
        username,
        password,
      }))

      const data = response.data

      token.value = data.access_token
      refreshToken.value = data.refresh_token
      setTokens(data.access_token, data.refresh_token, remember)
      
      // 直接从响应中设置用户信息
      if (data.user) {
        user.value = {
          id: data.user.id,
          username: data.user.username,
          display_name: data.user.display_name,
          email: data.user.email,
          role: data.user.role,
          role_display_name: data.user.role_display_name,
          permissions: data.user.permissions || [],
          is_active: data.user.is_active,
          is_superuser: data.user.is_superuser || false,
        }
      }
      
      await fetchAuditLogs()
      return { success: true }
    } catch (error: any) {
      console.error('Login failed:', error)
      const errorMsg = error.response?.data?.detail || error.message || i18n.global.t('login.loginFailed')
      return { success: false, message: errorMsg }
    }
  }

  async function loginWithCaptcha(username: string, password: string, captchaId: string, captchaCode: string, remember: boolean = false) {
    try {
      const response = await api.post('/auth/login-with-captcha', {
        username,
        password,
        captcha_id: captchaId,
        captcha_code: captchaCode,
      }, {
        headers: {
          'Content-Type': 'application/json'
        }
      })

      const data = response.data

      token.value = data.access_token
      refreshToken.value = data.refresh_token
      setTokens(data.access_token, data.refresh_token, remember)
      
      // 直接从响应中设置用户信息
      if (data.user) {
        user.value = {
          id: data.user.id,
          username: data.user.username,
          display_name: data.user.display_name,
          email: data.user.email,
          role: data.user.role,
          role_display_name: data.user.role_display_name,
          permissions: data.user.permissions || [],
          is_active: data.user.is_active,
          is_superuser: data.user.is_superuser || false,
        }
      }
      
      await fetchAuditLogs()
      return { success: true }
    } catch (error: any) {
      console.error('Login failed:', error)
      throw error
    }
  }

  async function fetchAuditLogs() {
    const appStore = useAppStore()
    try {
      const response = await fetch('/api/v1/logs/', {
        headers: {
          Authorization: `Bearer ${token.value}`,
        },
      })
      
      if (response.ok) {
        const logs = await response.json()
        appStore.$patch({ auditLogs: logs })
        appStore.save()
      }
    } catch (error) {
      console.error('Fetch audit logs failed:', error)
    }
  }

  async function fetchUser(retries = 3) {
    if (!token.value) return
    
    for (let i = 0; i < retries; i++) {
      try {
        const response = await api.get('/auth/me')
        user.value = response.data
        return
      } catch (error: any) {
        if (error.response?.status === 401) {
          if (isRefreshing.value) {
            throw error
          }
          isRefreshing.value = true
          try {
            const refreshed = await refreshAccessToken()
            if (refreshed) {
              isRefreshing.value = false
              continue
            } else {
              throw error
            }
          } catch {
            isRefreshing.value = false
            throw error
          }
        }
        const isConnectionError = error.code === 'ECONNREFUSED' || 
          error.message?.includes('ECONNREFUSED') ||
          error.errno === 'ECONNREFUSED'
        if (i < retries - 1 && isConnectionError) {
          await new Promise(resolve => setTimeout(resolve, 1000))
          continue
        }
        console.error('Fetch user failed:', error)
        throw error
      }
    }
    throw new Error('fetchUser failed after retries')
  }

  async function refreshAccessToken() {
    if (!refreshToken.value) {
      logout()
      return false
    }
    
    try {
      const response = await api.post('/auth/refresh', {}, {
        headers: {
          'X-Refresh-Token': refreshToken.value,
        },
      })
      
      token.value = response.data.access_token
      refreshToken.value = response.data.refresh_token
      setTokens(response.data.access_token, response.data.refresh_token, isRemembered())
      return true
    } catch (error) {
      console.error('Refresh token failed:', error)
      logout()
      return false
    }
  }

  async function logout() {
    try {
      await api.post('/auth/logout')
    } catch (error) {
      console.error('Logout failed:', error)
    } finally {
      token.value = null
      refreshToken.value = null
      user.value = null
      clearTokens()
    }
  }

  async function changePassword(oldPassword: string, newPassword: string) {
    try {
      await api.post('/auth/change-password', { 
        old_password: oldPassword, 
        new_password: newPassword 
      })
      return { success: true }
    } catch (error: any) {
      return { 
        success: false, 
        message: error.response?.data?.detail || (error instanceof Error ? error.message : i18n.global.t('common.changePasswordFailed'))
      }
    }
  }

  async function fetchSSOConfig() {
    try {
      const response = await api.get('/auth/sso/config')
      ssoConfig.value = response.data
      return response.data
    } catch (error) {
      console.debug('Fetch SSO config failed, using defaults', error)
      ssoConfig.value = {
        enabled: false,
        login_methods: ['local'],
        has_oauth2: false,
        has_saml: false
      }
      return ssoConfig.value
    }
  }

  async function getSSOAuthorizeUrl() {
    try {
      const response = await api.get('/auth/sso/authorize')
      return response.data
    } catch (error) {
      console.error('Get SSO authorize URL failed:', error)
      throw error
    }
  }

  async function ssoCallback(code: string) {
    try {
      const response = await api.post('/auth/sso/callback', null, {
        params: {
          code,
        },
      })
      
      const data = response.data

      token.value = data.access_token
      refreshToken.value = data.refresh_token
      // SSO 登录无「记住我」复选框，保持既有行为：持久存储
      setTokens(data.access_token, data.refresh_token, true)
      
      // 设置用户信息
      if (data.user) {
        user.value = {
          id: data.user.id,
          username: data.user.username,
          display_name: data.user.display_name,
          email: data.user.email,
          role: data.user.role,
          role_display_name: data.user.role_display_name,
          permissions: data.user.permissions || [],
          is_active: data.user.is_active,
          is_superuser: data.user.is_superuser || false,
          is_sso_user: data.user.is_sso_user || false,
        }
      }
      
      await fetchAuditLogs()
      return { success: true }
    } catch (error: any) {
      console.error('SSO login failed:', error)
      const errorMsg = error.response?.data?.detail || error.message || i18n.global.t('login.ssoLoginFailed')
      return { success: false, message: errorMsg }
    }
  }

  return {
    token,
    refreshToken,
    user,
    isLoggedIn,
    ssoConfig,
    login,
    loginWithCaptcha,
    logout,
    fetchUser,
    fetchAuditLogs,
    refreshAccessToken,
    changePassword,
    fetchSSOConfig,
    getSSOAuthorizeUrl,
    ssoCallback,
    hasPermission,
    hasRole,
    isReadOnly,
    isOperator,
    isAdmin,
  }
})
