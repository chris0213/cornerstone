import request from './axios'

export interface AlertRule {
  id: number
  name: string
  description?: string
  device_id?: number
  condition_type: 'latency' | 'packet_loss' | 'status'
  operator: 'gt' | 'lt' | 'eq' | 'ne'
  threshold: number
  severity: 'info' | 'warning' | 'critical'
  enabled: boolean
  notification_channels: string[]
  created_at: string
  updated_at?: string
}

export interface AlertRecord {
  id: number
  rule_id?: number
  device_id: number
  target_ip?: string
  alert_type: string
  severity: 'info' | 'warning' | 'critical'
  message: string
  current_value?: number
  threshold?: number
  status: 'active' | 'acknowledged' | 'resolved'
  acknowledged_by?: number
  acknowledged_at?: string
  resolved_at?: string
  created_at: string
}

export interface AlertSummary {
  info: number
  warning: number
  critical: number
}

export interface TestResult {
  value: number | string
  matches: boolean
}

export const createAlertRule = async (data: {
  name: string
  description?: string
  device_id?: number
  condition_type: 'latency' | 'packet_loss' | 'status'
  operator: 'gt' | 'lt' | 'eq' | 'ne'
  threshold: number
  severity?: 'info' | 'warning' | 'critical'
  enabled?: boolean
  notification_channels?: string[]
}) => {
  const response = await request.post('/alerts/rules', data)
  return response.data
}

export const getAlertRules = async (params?: {
  device_id?: number
  enabled?: boolean
}) => {
  const response = await request.get('/alerts/rules', { params })
  return response.data.data as AlertRule[]
}

export const getAlertRule = async (ruleId: number) => {
  const response = await request.get(`/alerts/rules/${ruleId}`)
  return response.data.data as AlertRule
}

export const updateAlertRule = async (ruleId: number, data: {
  name?: string
  description?: string
  device_id?: number
  condition_type?: 'latency' | 'packet_loss' | 'status'
  operator?: 'gt' | 'lt' | 'eq' | 'ne'
  threshold?: number
  severity?: 'info' | 'warning' | 'critical'
  enabled?: boolean
  notification_channels?: string[]
}) => {
  const response = await request.put(`/alerts/rules/${ruleId}`, data)
  return response.data
}

export const deleteAlertRule = async (ruleId: number) => {
  const response = await request.delete(`/alerts/rules/${ruleId}`)
  return response.data
}

export const getAlertRecords = async (params?: {
  device_id?: number
  severity?: 'info' | 'warning' | 'critical'
  status?: 'active' | 'acknowledged' | 'resolved'
  limit?: number
}) => {
  const response = await request.get('/alerts/records', { params })
  return response.data.data as AlertRecord[]
}

export const getAlertRecord = async (recordId: number) => {
  const response = await request.get(`/alerts/records/${recordId}`)
  return response.data.data as AlertRecord
}

export const acknowledgeAlert = async (recordId: number) => {
  const response = await request.post(`/alerts/records/${recordId}/acknowledge`)
  return response.data
}

export const resolveAlert = async (recordId: number) => {
  const response = await request.post(`/alerts/records/${recordId}/resolve`)
  return response.data
}

export const muteAlertRule = async (ruleId: number, hours: number) => {
  const response = await request.post(`/alerts/rules/${ruleId}/mute`, { hours })
  return response.data
}

export const unmuteAlertRule = async (ruleId: number) => {
  const response = await request.post(`/alerts/rules/${ruleId}/unmute`)
  return response.data
}

export const getAlertSummary = async () => {
  const response = await request.get('/alerts/summary')
  return response.data.data as AlertSummary
}

export const testAlertRule = async (ruleId: number) => {
  const response = await request.post(`/alerts/test-rule/${ruleId}`)
  return response.data.data as TestResult[]
}
