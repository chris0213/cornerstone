import api from './axios'

export interface DatabaseBackupFile {
  name: string
  size_bytes: number
  size_mb: number
  modified_at: number
  trigger?: string // 'auto' | 'manual'（历史无标记按 manual 处理，永不被保留策略删除）
}

export interface DatabaseBackupList {
  dir: string
  exists: boolean
  files: DatabaseBackupFile[]
}

export const listDatabaseBackups = async (): Promise<DatabaseBackupList> => {
  const { data } = await api.get('/database-backups/files')
  return data
}

export const downloadDatabaseBackup = async (name: string): Promise<Blob> => {
  const { data } = await api.get(`/database-backups/files/${encodeURIComponent(name)}/download`, {
    responseType: 'blob',
  })
  return data
}

export interface CreateBackupResult {
  ok: boolean
  name: string
  size_bytes: number
}

export const createDatabaseBackup = async (): Promise<CreateBackupResult> => {
  const { data } = await api.post('/database-backups/create', {})
  return data
}

export const deleteDatabaseBackup = async (name: string): Promise<{ ok: boolean; name: string }> => {
  const { data } = await api.delete(`/database-backups/files/${encodeURIComponent(name)}`)
  return data
}

export interface VerifyCheck {
  table: string
  count: number | null
}

export interface VerifyResult {
  ok: boolean
  restored: boolean
  checks: VerifyCheck[]
  error?: string | null
}

export const verifyDatabaseBackup = async (name: string): Promise<VerifyResult> => {
  // 恢复到隔离库校验，耗时较长，单独放宽超时
  const { data } = await api.post('/database-backups/verify', { filename: name }, { timeout: 120000 })
  return data
}

// ==================== 本地备份调度配置 ====================

export interface BackupConfig {
  enabled: boolean
  schedule_time: string
  retention_days: number
  keep_last: number
  next_run?: string | null
}

export const getBackupConfig = async (): Promise<BackupConfig> => {
  const { data } = await api.get('/database-backups/config')
  return data
}

export const updateBackupConfig = async (
  payload: Pick<BackupConfig, 'enabled' | 'schedule_time' | 'retention_days' | 'keep_last'>,
): Promise<BackupConfig> => {
  const { data } = await api.put('/database-backups/config', payload)
  return data
}
