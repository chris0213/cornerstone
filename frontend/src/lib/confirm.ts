/**
 * 确认后执行工具（第四批代码简化：统一各页面重复的删除确认样板）
 *
 * 典型形态：confirm 弹窗 → 执行动作（含列表更新等副作用）→ 成功提示；
 * 用户取消静默返回 false，执行抛错记录日志并提示 errorMessage。
 *
 * 用法：
 *   await confirmAndRun({
 *     message: t('sites.confirmDelete', { name }), title: t('sites.deleteConfirmTitle'),
 *     action: async () => { await deleteSite(id); sites.value = sites.value.filter(...) },
 *     successMessage: t('sites.deleteSuccess'), errorMessage: t('sites.deleteFailed'),
 *   })
 */
import { ElMessage, ElMessageBox } from 'element-plus'

export interface ConfirmRunOptions {
  /** 确认弹窗正文 */
  message: string
  /** 弹窗标题（缺省用 Element Plus 默认） */
  title?: string
  /** 确认按钮文案 */
  confirmText?: string
  /** 取消按钮文案 */
  cancelText?: string
  /** 确认按钮标红（删除等危险操作） */
  danger?: boolean
  /** 用户确认后执行的动作，可含列表更新等副作用 */
  action: () => Promise<unknown> | unknown
  /** 成功提示（缺省不提示） */
  successMessage?: string
  /** 失败提示（缺省不提示，仅记录日志） */
  errorMessage?: string
}

/** 确认后执行动作；返回 true=执行成功，false=用户取消或执行失败 */
export async function confirmAndRun({
  message,
  title,
  confirmText,
  cancelText,
  danger,
  action,
  successMessage,
  errorMessage,
}: ConfirmRunOptions): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, title, {
      confirmButtonText: confirmText,
      cancelButtonText: cancelText,
      confirmButtonClass: danger ? 'el-button--danger' : undefined,
      type: 'warning',
    })
    await action()
    if (successMessage) ElMessage.success(successMessage)
    return true
  } catch (error) {
    if (error !== 'cancel') {
      console.error('confirmAndRun failed:', error)
      if (errorMessage) ElMessage.error(errorMessage)
    }
    return false
  }
}
