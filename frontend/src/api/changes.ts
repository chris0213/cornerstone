import request from './axios'

/** 字段级明细（批次聚合内） */
export interface ChangeFieldDetail {
  field: string
  old_value: string
  new_value: string
}

/** 变更记录（按操作批次聚合：同一次多字段编辑折叠为一条，明细在 changes 数组） */
export interface ChangeItem {
  id: string
  source: 'circuit' | 'config'
  object_id: number | null
  object_name: string
  change_type: string
  field: string
  old_value: string
  new_value: string
  operator: string
  remark: string
  batch_id: string
  created_at: string
  /** 批次聚合字段：字段级明细（config 来源恒为单条） */
  changes: ChangeFieldDetail[]
  field_count: number
}

export interface ChangeListPage {
  items: ChangeItem[]
  total: number
  skip: number
  limit: number
}

export interface ChangeSummary {
  total: number
  circuit_count: number
  config_count: number
  object_count: number
  start: string
  end: string
}

export interface ChangeQuery {
  source?: string
  object_id?: number
  change_type?: string
  operator?: string
  keyword?: string
  start?: string
  end?: string
  skip?: number
  limit?: number
}

/** 变更列表（按操作批次聚合，含 total） */
export async function listChanges(params: ChangeQuery = {}): Promise<ChangeListPage> {
  const response = await request.get('/changes', { params })
  return response.data
}

export async function getChangesSummary(params: { start?: string; end?: string } = {}): Promise<ChangeSummary> {
  const response = await request.get('/changes/summary', { params })
  return response.data
}

/** 受影响对象（当前筛选范围内去重） */
export interface ChangeObjectItem {
  source: 'circuit' | 'config'
  object_id: number | null
  object_name: string
  change_count: number
  last_change_at: string | null
}

/** 受影响对象清单（与列表共用筛选参数） */
export async function getChangeObjects(params: ChangeQuery = {}): Promise<{ items: ChangeObjectItem[]; total: number }> {
  const response = await request.get('/changes/objects', { params })
  return response.data
}

/** 操作人下拉选项（去重后的用户名列表） */
export async function getChangesOperators(): Promise<string[]> {
  const response = await request.get('/changes/operators')
  return response.data
}

/** 按当前筛选导出全量变更（后端写审计；上限 10000 条） */
export async function exportChanges(params: ChangeQuery = {}): Promise<{ items: ChangeItem[]; count: number }> {
  const response = await request.get('/changes/export', { params })
  return response.data
}
