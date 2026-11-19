import api from './axios'

export type OffsiteTargetType = 'rclone' | 'rsync' | 'sftp'

export interface OffsiteSyncConfig {
  enabled: boolean
  target_type: OffsiteTargetType
  schedule_time: string
  source_dir: string
  // rclone
  rclone_provider: string
  rclone_endpoint: string
  rclone_bucket: string
  rclone_region: string
  rclone_prefix: string
  // rsync
  rsync_host: string
  rsync_port: number
  rsync_user: string
  rsync_remote_path: string
  // sftp
  sftp_host: string
  sftp_port: number
  sftp_user: string
  sftp_remote_path: string
}

// GET 响应：敏感字段以 has_xxx + 尾号形式返回
export interface OffsiteSyncView extends Partial<OffsiteSyncConfig> {
  has_rclone_access_key_id?: boolean
  rclone_access_key_id_tail?: string
  has_rclone_secret_access_key?: boolean
  rclone_secret_access_key_tail?: string
  has_rsync_ssh_key?: boolean
  rsync_ssh_key_tail?: string
  has_sftp_ssh_key?: boolean
  sftp_ssh_key_tail?: string
}

// PUT 请求：密钥字段传空 = 留空不修改
export interface OffsiteSyncPayload extends Partial<OffsiteSyncConfig> {
  rclone_access_key_id?: string
  rclone_secret_access_key?: string
  rsync_ssh_key?: string
  sftp_ssh_key?: string
}

export interface OffsiteSyncResult {
  ok: boolean
  message: string
  target_type?: string
  duration_ms?: number
  error?: string | null
}

export interface OffsiteSyncStatus {
  last_sync: (OffsiteSyncResult & { at?: number; trigger?: string; operator?: string }) | null
  tools: { rclone: boolean; rsync: boolean; scp: boolean }
}

export const getOffsiteSyncConfig = async (): Promise<OffsiteSyncView> => {
  const { data } = await api.get('/offsite-sync/config')
  return data
}

export const updateOffsiteSyncConfig = async (payload: OffsiteSyncPayload): Promise<OffsiteSyncView> => {
  const { data } = await api.put('/offsite-sync/config', payload)
  return data
}

export const testOffsiteSync = async (): Promise<OffsiteSyncResult> => {
  const { data } = await api.post('/offsite-sync/test', {})
  return data
}

export const runOffsiteSync = async (): Promise<OffsiteSyncResult> => {
  const { data } = await api.post('/offsite-sync/run', {})
  return data
}

export const getOffsiteSyncStatus = async (): Promise<OffsiteSyncStatus> => {
  const { data } = await api.get('/offsite-sync/status')
  return data
}

// ==================== 运行台账 ====================

export interface OffsiteSyncRun {
  id: number
  created_at: string | null
  trigger: 'auto' | 'manual'
  status: 'success' | 'failed'
  operator?: string | null
  target_type?: string | null
  source_dir?: string | null
  duration_ms?: number | null
  message?: string | null
  error?: string | null
}

export const listOffsiteSyncRuns = async (limit = 50): Promise<OffsiteSyncRun[]> => {
  const { data } = await api.get('/offsite-sync/runs', { params: { limit } })
  return data.runs
}
