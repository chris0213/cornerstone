import { createI18n } from 'vue-i18n'
import zhCN from '../locales/zh-CN.json'
import enUS from '../locales/en-US.json'

export type LocaleType = 'zh-CN' | 'en-US'

export const SUPPORTED_LOCALES: { value: LocaleType; label: string }[] = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'en-US', label: 'English' }
]

// 创建 i18n 实例
export const i18n = createI18n({
  legacy: false, // 使用 Composition API 模式
  locale: 'zh-CN', // 始终默认中文
  fallbackLocale: 'zh-CN',
  // 缺失 key：开发环境 console.warn 提醒，避免把 key 裸露给用户
  missing(locale, key) {
    if (import.meta.env.DEV) {
      console.warn(`[i18n] missing key "${key}" in locale "${locale}"`)
    }
    // 返回 key 的最后一段（如 sites.hasAlert → hasAlert），比整条 key 路径更可读
    return key.split('.').pop() || key
  },
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS
  },
  datetimeFormats: {
    'zh-CN': {
      short: {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
      },
      long: {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      }
    },
    'en-US': {
      short: {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
      },
      long: {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      }
    }
  },
  numberFormats: {
    'zh-CN': {
      decimal: {
        style: 'decimal',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      },
      percent: {
        style: 'percent',
        minimumFractionDigits: 1,
        maximumFractionDigits: 1
      }
    },
    'en-US': {
      decimal: {
        style: 'decimal',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      },
      percent: {
        style: 'percent',
        minimumFractionDigits: 1,
        maximumFractionDigits: 1
      }
    }
  }
})

// 切换语言
export function setLocale(locale: LocaleType) {
  i18n.global.locale.value = locale
  localStorage.setItem('locale', locale)
  
  // 更新 HTML lang 属性
  document.documentElement.lang = locale
}

// 获取当前语言
export function getLocale(): LocaleType {
  return i18n.global.locale.value as LocaleType
}

export default i18n
