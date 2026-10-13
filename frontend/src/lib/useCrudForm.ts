/**
 * CRUD 弹窗状态样板（第四批代码简化：收敛各页面重复的表单弹窗管理逻辑）
 *
 * 统一提供：弹窗显隐、当前编辑项、表单值、重置、新建/编辑打开、关闭。
 * 表单字段与校验仍归页面；本 composable 只管状态流转。
 *
 * 用法（变量名可解构重命名以保持模板不变）：
 *   const { showDialog, editing, form, openCreate, openEdit, closeDialog } = useCrudForm<Site, Partial<Site>>({
 *     createDefaults: () => ({ name: '', ... }),
 *     toForm: (site) => ({ ...site }),   // 可选，缺省浅拷贝
 *   })
 */
import { ref, type Ref } from 'vue'

export interface CrudFormOptions<I, T> {
  /** 生成表单默认值（每次打开新建/重置时调用，支持闭包读取上下文） */
  createDefaults: () => T
  /** 编辑时把列表项映射为表单值（缺省浅拷贝 item） */
  toForm?: (item: I) => T
}

export function useCrudForm<I, T extends object>(options: CrudFormOptions<I, T>) {
  const showDialog = ref(false)
  const editing: Ref<I | null> = ref(null)
  const form: Ref<T> = ref(options.createDefaults()) as Ref<T>

  /** 重置表单与编辑态（不改弹窗显隐） */
  const resetForm = () => {
    form.value = options.createDefaults()
    editing.value = null
  }

  /** 打开新建弹窗（表单为默认值） */
  const openCreate = () => {
    resetForm()
    showDialog.value = true
  }

  /** 打开编辑弹窗（表单为列表项映射值） */
  const openEdit = (item: I) => {
    editing.value = item
    form.value = options.toForm ? options.toForm(item) : { ...(item as unknown as T) }
    showDialog.value = true
  }

  /** 关闭弹窗并重置（保存成功/取消通用） */
  const closeDialog = () => {
    showDialog.value = false
    resetForm()
  }

  return { showDialog, editing, form, resetForm, openCreate, openEdit, closeDialog }
}
