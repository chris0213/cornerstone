/**
 * 后端错误提示本地化工具
 *
 * 后端 VLAN 模块已将 HTTPException 的 detail 结构化为 { code, message, params }；
 * 其他模块仍是纯字符串中文。本工具统一提取并按 code 走 i18n 映射，
 * 无 code（旧格式）时回退显示原始 message，保证兼容。
 */
import { i18n } from '../i18n'

/** 与后端约定的错误码 → 前端 i18n key 映射（vlan.errors.* / backups.credentialErrors.* 命名空间） */
const ERROR_CODE_KEYS: Record<string, string> = {
  'vlan.group_not_empty': 'vlan.errors.groupNotEmpty',
  'vlan.vid_out_of_range': 'vlan.errors.vidOutOfRange',
  'vlan.vid_exists': 'vlan.errors.vidExists',
  'vlan.has_prefixes': 'vlan.errors.hasPrefixes',
  'credential.in_use': 'backups.credentialErrors.inUse',
  'credential.test_rate_limited': 'backups.credentialErrors.testRateLimited',
  'credential.test_ip_not_allowed': 'backups.credentialErrors.testIpNotAllowed',
  'credential.test_ip_invalid': 'backups.credentialErrors.testIpInvalid',
  'backup_task.already_running': 'backups.taskConflict',
  'backup_task.scope_required': 'backups.scopeRequiredPrompt',
}

interface StructuredDetail {
  code?: string
  message?: string
  params?: Record<string, unknown>
}

/** 从 axios 错误中提取后端 detail（字符串或结构化对象） */
export function extractErrorDetail(error: unknown): string | StructuredDetail | undefined {
  return (error as { response?: { data?: { detail?: string | StructuredDetail } } })?.response?.data?.detail
}

/** 从 axios 错误中提取 HTTP 状态码 */
export function extractErrorStatus(error: unknown): number | undefined {
  return (error as { response?: { status?: number } })?.response?.status
}

/**
 * 后端 params 字段名与 i18n 占位符对齐：
 * - credential.test_rate_limited: 后端 retry_after_seconds → 文案 {seconds}
 * - credential.in_use: 后端 tasks 为 [{id,name}] → 文案 {count}（数量）与 {tasks}（任务名串）
 */
function normalizeErrorParams(code: string | undefined, params?: Record<string, unknown>): Record<string, unknown> {
  if (!params) return {}
  if (code === 'credential.test_rate_limited' && params.retry_after_seconds !== undefined) {
    return { ...params, seconds: params.retry_after_seconds }
  }
  if (code === 'credential.in_use' && Array.isArray(params.tasks)) {
    const tasks = params.tasks as Array<{ name?: string }>
    return {
      ...params,
      count: tasks.length,
      tasks: tasks.map((t) => t?.name).filter(Boolean).join('、'),
    }
  }
  return params
}

/**
 * 将 axios 错误转为可直接展示的本地化文案。
 * detail 为结构化且 code 已映射 → t(key, params)；否则回退原始 message/字符串。
 * 403 统一提示无权限，不透出后端 message。
 */
export function resolveErrorMessage(error: unknown, fallbackKey?: string): string {
  if (extractErrorStatus(error) === 403) {
    return i18n.global.t('backups.noPermission')
  }
  const detail = extractErrorDetail(error)
  if (detail && typeof detail === 'object') {
    const { code, message, params } = detail
    const key = code ? ERROR_CODE_KEYS[code] : undefined
    if (key) return i18n.global.t(key, normalizeErrorParams(code, params as Record<string, unknown>))
    if (message) return message
  } else if (typeof detail === 'string' && detail) {
    return detail
  }
  return fallbackKey ? i18n.global.t(fallbackKey) : ''
}
