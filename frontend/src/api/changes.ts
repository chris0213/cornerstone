import request from './axios'

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
  created_at: string
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
  operator?: string
  keyword?: string
  start?: string
  end?: string
  skip?: number
  limit?: number
}

export async function listChanges(params: ChangeQuery = {}): Promise<ChangeItem[]> {
  const response = await request.get('/changes', { params })
  return response.data
}

export async function getChangesSummary(params: { start?: string; end?: string } = {}): Promise<ChangeSummary> {
  const response = await request.get('/changes/summary', { params })
  return response.data
}
