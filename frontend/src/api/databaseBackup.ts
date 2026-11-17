import api from './axios'

export interface DatabaseBackupFile {
  name: string
  size_bytes: number
  size_mb: number
  modified_at: number
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
