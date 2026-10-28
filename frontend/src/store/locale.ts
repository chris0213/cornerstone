import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { setLocale as setI18nLocale, getLocale, type LocaleType } from '../i18n'
import api from '../api/axios'
import { getToken } from '../api/tokenStorage'

export const useLocaleStore = defineStore('locale', () => {
  // 状态
  const locale = ref<LocaleType>(getLocale())
  const isInitialized = ref(false)
  const isSyncing = ref(false)

  // 计算属性
  const currentLocale = computed(() => locale.value)
  const isZhCN = computed(() => locale.value === 'zh-CN')
  const isEnUS = computed(() => locale.value === 'en-US')

  // 初始化语言设置
  async function initialize() {
    if (isInitialized.value) return

    // 从 localStorage 读取用户之前保存的语言偏好
    const saved = localStorage.getItem('locale')
    if (saved && (saved === 'zh-CN' || saved === 'en-US')) {
      locale.value = saved as LocaleType
      setI18nLocale(saved as LocaleType)
    } else {
      // 首次访问：根据浏览器语言自动判断
      const browserLocale = navigator.language?.startsWith('zh') ? 'zh-CN' : 'en-US'
      locale.value = browserLocale as LocaleType
      setI18nLocale(browserLocale as LocaleType)
    }

    // 如果已登录，同步服务器设置（仅同步到服务器，不从服务器读取）
    const token = getToken()
    if (token) {
      await syncToServer()
    }

    isInitialized.value = true
  }

  // 设置语言
  async function setLocale(newLocale: LocaleType) {
    if (locale.value === newLocale) return

    locale.value = newLocale
    setI18nLocale(newLocale)
    // 将用户选择持久化到 localStorage
    localStorage.setItem('locale', newLocale)

    // 同步到服务器
    const token = getToken()
    if (token) {
      await syncToServer()
    }
  }

  // 从服务器同步语言设置
  async function syncFromServer() {
    if (isSyncing.value) return

    isSyncing.value = true
    try {
      const response = await api.get('/users/me/settings')
      if (response.data.locale) {
        const serverLocale = response.data.locale as LocaleType
        // 仅当用户从未手动选择过语言时，才用浏览器或服务器设置
        if (!localStorage.getItem('locale')) {
          const browserZh = navigator.language?.startsWith('zh')
          locale.value = browserZh ? 'zh-CN' : (serverLocale || 'zh-CN')
          setI18nLocale(locale.value)
        }
      }
    } catch (error) {
      // 忽略错误，使用本地设置
      console.warn('Failed to sync locale from server:', error)
    } finally {
      isSyncing.value = false
    }
  }

  // 同步语言设置到服务器
  async function syncToServer() {
    if (isSyncing.value) return

    isSyncing.value = true
    try {
      await api.put('/users/me/settings', {
        locale: locale.value
      })
    } catch (error) {
      // 忽略错误，不影响本地使用
      console.warn('Failed to sync locale to server:', error)
    } finally {
      isSyncing.value = false
    }
  }

  // 标记用户已手动选择语言（由 LanguageSwitcher 调用）
  function markAsManual() {
    // locale 已经在 setLocale() 中持久化到 localStorage，此处仅需记录
    localStorage.setItem('locale', locale.value)
  }

  // 重置为自动检测
  function resetToAuto() {
    localStorage.removeItem('locale')
    
    // 重新检测浏览器语言
    const browserLocale = navigator.language?.startsWith('en') ? 'en-US' : 'zh-CN'
    locale.value = browserLocale
    setI18nLocale(browserLocale)
  }

  return {
    // 状态
    locale,
    isInitialized,
    isSyncing,
    // 计算属性
    currentLocale,
    isZhCN,
    isEnUS,
    // 方法
    initialize,
    setLocale,
    syncFromServer,
    syncToServer,
    markAsManual,
    resetToAuto
  }
})
