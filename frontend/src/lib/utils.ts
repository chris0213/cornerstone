export function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
}

export function snakeToCamel(obj: any): any {
  if (typeof obj !== 'object' || obj === null) {
    return obj
  }
  
  if (Array.isArray(obj)) {
    return obj.map(item => snakeToCamel(item))
  }
  
  const result: any = {}
  for (const key in obj) {
    if (obj.hasOwnProperty(key)) {
      const camelKey = key.replace(/_([a-z])/g, (_match, letter) => letter.toUpperCase())
      result[camelKey] = snakeToCamel(obj[key])
    }
  }
  return result
}

export function daysUntil(dateText: string | null | undefined): number {
  if (!dateText) return -999
  const target = parseServerDate(dateText)
  if (!target) return -999
  // 与「本地时区的今天零点」比较，避免用 UTC 日期导致跨零点差一天
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const targetDay = new Date(target.getFullYear(), target.getMonth(), target.getDate())
  return Math.round((targetDay.getTime() - today.getTime()) / 86400000)
}

import { getLocale } from '../i18n'

export function money(value: number | string | undefined | null): string {
  if (value === undefined || value === null || value === '') return '-'
  const num = Number(value)
  if (isNaN(num)) return '-'
  return num.toLocaleString(getLocale() || 'zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/**
 * 把后端返回的时间字符串解析为 Date（统一入口）
 *
 * 后端已统一返回带时区的 UTC，例如 `2026-11-12T10:03:28+00:00`：
 * - 带 `Z` / `+08:00` / `-05:00` 等时区标记：按原样解析，得到绝对时刻
 * - `YYYY-MM-DD HH:mm:ss` 之类无时区标记的旧格式：按后端存储约定当作 UTC 补 `Z`
 * - 纯日期 `YYYY-MM-DD`：按本地零点解析（避免被当成 UTC 零点而偏移一天）
 */
export function parseServerDate(dateText: string | null | undefined): Date | null {
  if (!dateText) return null
  const text = String(dateText).trim()
  if (!text) return null

  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    const [y, m, d] = text.split('-').map(Number)
    const local = new Date(y, m - 1, d)
    return isNaN(local.getTime()) ? null : local
  }

  let normalized = text.replace(' ', 'T')
  const hasZone = /[Zz]$/.test(normalized) || /[+-]\d{2}:?\d{2}$/.test(normalized)
  if (!hasZone) normalized += 'Z'

  const date = new Date(normalized)
  return isNaN(date.getTime()) ? null : date
}

const pad2 = (n: number): string => String(n).padStart(2, '0')

export function formatDate(dateText: string | null | undefined): string {
  if (!dateText) return '—'
  const date = parseServerDate(dateText)
  if (!date) return dateText as string
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

/**
 * 统一日期时间格式化（按浏览器本地时区显示）
 * 传入带时区的后端时间后，自动换算为当前用户本地时间。
 */
export function formatDateTime(
  dateText: string | null | undefined,
  options: { seconds?: boolean } = {}
): string {
  if (!dateText) return '-'
  const date = parseServerDate(dateText)
  if (!date) return dateText as string
  const fmt: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }
  if (options.seconds !== false) fmt.second = '2-digit'
  return date.toLocaleString(getLocale() || 'zh-CN', fmt)
}

/** HH:mm（本地时区） */
export function formatTimeHM(dateText: string | null | undefined): string {
  const date = parseServerDate(dateText)
  if (!date) return '-'
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

/** HH:mm:ss（本地时区） */
export function formatTimeHMS(dateText: string | null | undefined): string {
  const date = parseServerDate(dateText)
  if (!date) return '-'
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
}

/** MM-DD（本地时区） */
export function formatMonthDay(dateText: string | null | undefined): string {
  const date = parseServerDate(dateText)
  if (!date) return '-'
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

/** MM-DD HH:mm（本地时区） */
export function formatMonthDayHM(dateText: string | null | undefined): string {
  const date = parseServerDate(dateText)
  if (!date) return '-'
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

/** 统一文件大小格式化：B / KB / MB / GB */
export function formatFileSize(bytes: number | null | undefined): string {
  if (!bytes || bytes < 1024) return `${bytes || 0} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = bytes
  let i = -1
  do {
    size /= 1024
    i++
  } while (size >= 1024 && i < units.length - 1)
  return `${size.toFixed(1)} ${units[i]}`
}

export function statusTag(value: string): string {
  const cls =
    {
      正常: 'ok',
      在线: 'ok',
      成功: 'ok',
      已分配: 'ok',
      预留: 'warn',
      故障: 'danger',
      离线: 'danger',
      失败: 'danger',
      维修: 'warn',
      停用: 'warn',
      报废: 'danger',
    }[value] || ''
  return cls
}

// 简化的拼音转换（首字母）
const pinyinMap: Record<string, string> = {
  '啊': 'a', '阿': 'a', '爱': 'ai', '安': 'an', '暗': 'an',
  '吧': 'b', '把': 'b', '八': 'b', '百': 'b', '办': 'b',
  '才': 'c', '参': 'c', '查': 'c', '产': 'c', '长': 'c',
  '大': 'd', '的': 'd', '第': 'd', '电': 'd', '定': 'd',
  '额': 'e', '儿': 'e', '而': 'e', '发': 'f', '法': 'f',
  '该': 'g', '高': 'g', '公': 'g', '工': 'g', '国': 'g',
  '好': 'h', '号': 'h', '和': 'h', '互': 'h', '话': 'h',
  '机': 'j', '级': 'j', '技': 'j', '加': 'j', '建': 'j',
  '开': 'k', '看': 'k', '可': 'k', '空': 'k', '口': 'k',
  '了': 'l', '来': 'l', '理': 'l', '联': 'l', '路': 'l',
  '码': 'm', '吗': 'm', '买': 'm', '忙': 'm', '没': 'm',
  '你': 'n', '那': 'n', '南': 'n', '内': 'n', '年': 'n',
  '哦': 'o', '欧': 'o',
  '排': 'p', '配': 'p', '平': 'p', '普': 'p',
  '去': 'q', '期': 'q', '器': 'q', '企': 'q', '全': 'q',
  '人': 'r', '日': 'r', '如': 'r', '入': 'r',
  '是': 's', '上': 's', '说': 's', '使': 's', '社': 's',
  '他': 't', '天': 't', '通': 't', '条': 't', '铁': 't',
  '我': 'w', '为': 'w', '文': 'w', '无': 'w', '物': 'w',
  '下': 'x', '向': 'x', '现': 'x', '线': 'x', '信': 'x',
  '一': 'y', '有': 'y', '以': 'y', '用': 'y', '研': 'y',
  '在': 'z', '总': 'z', '中': 'z', '站': 'z', '专': 'z',
  '网': 'w',
}

export function toPinyin(text: string): string {
  let result = ''
  for (const char of text) {
    result += pinyinMap[char] || char
  }
  return result
}

export function filterByQuery<T>(
  items: T[],
  fields: ((item: T) => string | number | undefined | null)[],
  query: string
): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return items
  return items.filter((item) =>
    fields.some((field) => {
      const value = String(field(item) || '')
      // 精确匹配
      if (value.toLowerCase().includes(q)) return true
      // 拼音首字母匹配
      const pinyin = toPinyin(value).toLowerCase()
      return pinyin.includes(q)
    })
  )
}
