/**
 * 列表关键词筛选工具（第四批代码简化：统一各页面重复的搜索过滤逻辑）
 *
 * 用法：
 *   const filtered = computed(() =>
 *     applyKeywordFilter(items.value, searchQuery.value, ['name', 'location', (x) => resolveName(x.siteId)]))
 *
 * 字段声明支持两种形式：
 *   - 字符串字段名（值为 string | number | null | undefined 均可）
 *   - getter 函数（用于关联表派生值，如站点名、IP 地址）
 */

/** 筛选字段声明：字段名或派生值 getter */
export type SearchField<T> = keyof T & string | ((item: T) => string | number | null | undefined)

function fieldText<T>(item: T, field: SearchField<T>): string {
  const value = typeof field === 'function' ? field(item) : (item[field] as string | number | null | undefined)
  return value == null ? '' : String(value).toLowerCase()
}

/** 单条记录是否命中关键词（任一字段包含即可；空关键词视为命中） */
export function matchKeyword<T>(item: T, keyword: string | null | undefined, fields: SearchField<T>[]): boolean {
  const q = (keyword || '').trim().toLowerCase()
  if (!q) return true
  return fields.some(field => fieldText(item, field).includes(q))
}

/** 关键词过滤列表（关键词为空时原样返回，字段值为空安全跳过） */
export function applyKeywordFilter<T>(items: T[], keyword: string | null | undefined, fields: SearchField<T>[]): T[] {
  const q = (keyword || '').trim().toLowerCase()
  if (!q) return items
  return items.filter(item => matchKeyword(item, q, fields))
}
