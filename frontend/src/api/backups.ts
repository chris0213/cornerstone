import api from '@/api/axios'
import { snakeToCamel } from '@/lib/utils'
import type { Backup, Credential, BackupTask } from '../types/domain'

function credentialToPayload(data: Partial<Credential>): any {
  return {
    name: data.name,
    device_id: data.deviceId,
    protocol: data.protocol,
    port: data.port,
    username: data.username,
    password: data.password,
    enable_password: data.enablePassword,
    auth_type: data.authType,
    private_key: data.privateKey,
    jump_host: data.jumpHost,
    jump_port: data.jumpPort,
    jump_username: data.jumpUsername,
    jump_password: data.jumpPassword,
    description: data.description,
  }
}

// Backup API
export async function getBackups(params?: {
  skip?: number
  limit?: number
  deviceId?: number
  status?: string
  trigger?: string
  hasChange?: boolean
}): Promise<Backup[]> {
  const response = await api.get('/backups/', { params })
  return snakeToCamel(response.data)
}

export async function getBackup(id: number): Promise<Backup> {
  const response = await api.get(`/backups/${id}`)
  return snakeToCamel(response.data)
}

export async function getBackupContent(id: number): Promise<{ content: string }> {
  const response = await api.get(`/backups/${id}/content`, {
    timeout: 30000, // 30 秒超时
  })
  return response.data
}

export async function getBackupDiff(backupIdA: number, backupIdB: number): Promise<{
  backupAId: number
  backupBId: number
  hasChange: boolean
  addedLines: number
  removedLines: number
  diffText: string
  changeSummary: string
}> {
  const response = await api.get('/backups/diff', {
    params: { backup_id_a: backupIdA, backup_id_b: backupIdB }
  })
  return snakeToCamel(response.data)
}

export async function updateBackupTag(id: number, tag: string): Promise<Backup> {
  const response = await api.patch(`/backups/${id}/tag`, null, {
    params: { tag }
  })
  return snakeToCamel(response.data)
}

export async function deleteBackup(id: number): Promise<void> {
  await api.delete(`/backups/${id}`)
}

export async function triggerBackup(deviceId: number, tag?: string): Promise<{
  taskId: string
  success: boolean
  message?: string
}> {
  // 后端要求 Body(embed=True)，还原等长耗时操作统一放宽超时
  const response = await api.post('/backups/trigger', {
    device_id: deviceId,
    tag: tag || '',
  }, {
    timeout: 300000, // 5分钟超时
  })
  return response.data
}

export async function triggerBatchBackup(deviceIds: number[], tag?: string): Promise<{
  taskId: string
  total: number
  success: number
  failed: number
}> {
  const response = await api.post('/backups/trigger-batch', deviceIds, {
    params: { tag: tag || '' }
  })
  return response.data
}

export async function restoreBackup(backupId: number, ipAddress: string): Promise<{
  success: boolean
  message: string
  durationMs: number
}> {
  const response = await api.post(`/backups/${backupId}/restore`, {
    ip_address: ipAddress
  }, {
    timeout: 300000, // 5分钟超时
  })
  return response.data
}

// Credential API
export async function getCredentials(deviceId?: number): Promise<Credential[]> {
  const params = deviceId ? { device_id: deviceId } : undefined
  const response = await api.get('/backups/credentials', { params })
  return snakeToCamel(response.data)
}

export async function getCredential(id: number): Promise<Credential> {
  const response = await api.get(`/backups/credentials/${id}`)
  return snakeToCamel(response.data)
}

export async function createCredential(data: Partial<Credential>): Promise<Credential> {
  const payload = credentialToPayload(data)
  if (!payload.password) delete payload.password
  if (!payload.enable_password) delete payload.enable_password
  if (!payload.private_key) delete payload.private_key
  if (!payload.jump_password) delete payload.jump_password

  const response = await api.post('/backups/credentials', payload)
  return snakeToCamel(response.data)
}

export async function updateCredential(id: number, data: Partial<Credential>): Promise<Credential> {
  const payload = credentialToPayload(data)
  if (payload.password === '********' || !payload.password) delete payload.password
  if (payload.enable_password === '********' || !payload.enable_password) delete payload.enable_password
  if (payload.private_key === '********' || !payload.private_key) delete payload.private_key
  if (payload.jump_password === '********' || !payload.jump_password) delete payload.jump_password

  const response = await api.put(`/backups/credentials/${id}`, payload)
  return snakeToCamel(response.data)
}

export async function deleteCredential(id: number): Promise<void> {
  await api.delete(`/backups/credentials/${id}`)
}

export async function testCredential(id: number, testIp: string): Promise<{
  success: boolean
  message: string
  durationMs: number
}> {
  const response = await api.post(`/backups/credentials/${id}/test`, {
    test_ip: testIp
  })
  const data = response.data
  return {
    success: data.success,
    message: data.message,
    durationMs: data.duration_ms || 0
  }
}

// Backup Task API
export async function getBackupTasks(): Promise<BackupTask[]> {
  const response = await api.get('/backup-tasks/')
  return snakeToCamel(response.data)
}

export async function getBackupTask(id: number): Promise<BackupTask> {
  const response = await api.get(`/backup-tasks/${id}`)
  return snakeToCamel(response.data)
}

export async function createBackupTask(data: {
  name: string
  cronExpr: string
  credentialId: number
  deviceIds?: number[]
  siteId?: number
  retentionCount?: number
  retentionDays?: number
  notifyOnChange?: boolean
  notifyOnFail?: boolean
  isEnabled?: boolean
}): Promise<BackupTask> {
  const payload: any = { ...data }
  const response = await api.post('/backup-tasks/', payload)
  return snakeToCamel(response.data)
}

export async function updateBackupTask(id: number, data: Partial<{
  name: string
  cronExpr: string
  credentialId: number
  deviceIds?: number[]
  siteId?: number
  retentionCount?: number
  retentionDays?: number
  notifyOnChange?: boolean
  notifyOnFail?: boolean
  isEnabled?: boolean
}>): Promise<BackupTask> {
  const payload: any = { ...data }
  const response = await api.put(`/backup-tasks/${id}`, payload)
  return snakeToCamel(response.data)
}

export async function deleteBackupTask(id: number): Promise<void> {
  await api.delete(`/backup-tasks/${id}`)
}

export async function toggleBackupTask(id: number): Promise<{ isEnabled: boolean }> {
  const response = await api.patch(`/backup-tasks/${id}/toggle`)
  return response.data
}

export async function runBackupTaskNow(id: number): Promise<{ message: string }> {
  const response = await api.post(`/backup-tasks/${id}/run-now`)
  return response.data
}

export async function getBackupTaskHistory(id: number, limit?: number): Promise<{
  time: string
  success: number
  failed: number
  total: number
  backups: { id: number; deviceId: number; status: string; durationMs: number }[]
}[]> {
  const response = await api.get(`/backup-tasks/${id}/history`, {
    params: { limit: limit || 20 }
  })
  return response.data
}
