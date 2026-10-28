import request from './axios'

export interface DashboardStats {
  sites: {
    total: number
  }
  circuits: {
    total: number
    normal: number
    bandwidth: number
  }
  devices: {
    total: number
    online: number
    offline: number
  }
  ip: {
    total: number
    used: number
    percent: number
  }
  backups: {
    total: number
    successful: number
    failed: number
  }
  health: {
    score: number
    status: 'excellent' | 'good' | 'warning' | 'critical'
  }
  alerts: {
    pending: number
  }
}

export interface PrefixUsage {
  id: number
  network: string
  vlan: number | null
  usage: string
  usage_percent: number
}

export interface AuditLogItem {
  id: number
  user: string
  action: string
  resource: string
  detail: string
  success: string
  created_at: string
}

export interface DeviceTypeItem {
  name: string
  value: number
  type: string
}

export interface CircuitTypeItem {
  name: string
  value: number
  bandwidth: number
  type: string
  color: string
}

export async function getDashboardStats(timeRange?: string): Promise<DashboardStats> {
  const response = await request.get('/dashboard/stats', {
    params: timeRange ? { time_range: timeRange } : {}
  })
  return response.data
}

export async function getPrefixesUsage(): Promise<PrefixUsage[]> {
  const response = await request.get('/dashboard/prefixes-usage')
  return response.data
}

export async function getRecentLogs(limit = 8): Promise<AuditLogItem[]> {
  const response = await request.get('/dashboard/recent-logs', { params: { limit } })
  return response.data
}

export async function getDeviceTypes(): Promise<DeviceTypeItem[]> {
  const response = await request.get('/dashboard/device-types')
  return response.data
}

export async function getCircuitTypes(): Promise<CircuitTypeItem[]> {
  const response = await request.get('/dashboard/circuit-types')
  return response.data
}

// ==================== IT负责人管理看板接口 ====================

export interface ManagerStats {
  availability: {
    current: number | null
    last_month: number | null
    trend: 'up' | 'down' | 'stable' | null
    /** 本月有探测记录但全部异常（区分"0%"与"探测全失败"） */
    all_failed: boolean
    /** 上月是否有探测数据（false 时前端显示"上月无数据"） */
    last_month_available: boolean
  }
  circuit_cost: {
    /** 合同期内（已开通且未到期，无 contract_end 视为持续有效） */
    in_contract: number
    /** 已到期未续约（contract_end<今天 且 status 仍在册） */
    expired_unrenewed: number
    /** 兼容字段 = in_contract + expired_unrenewed */
    current: number
    last_month: number | null
    trend: 'up' | 'down' | 'stable' | null
  }
  open_incidents: {
    count: number
    max_duration_hours: number
  }
  expiring_soon: {
    urgent_count: number
    warning_count: number
    total_count: number
    urgent_items: ExpiringItem[]
    warning_items: ExpiringItem[]
  }
}

export interface ExpiringItem {
  type: string
  name: string
  expire_date: string
  days_left: number
  detail: string
}

export interface RiskItem {
  severity: 'high' | 'medium' | 'low'
  category: string
  title: string
  description: string
  count: number
  resource_ids: number[]
  action_url: string
}

export interface RisksResponse {
  risks: RiskItem[]
  high_count: number
  medium_count: number
  low_count: number
}

export interface CircuitCostTrend {
  months: string[]
  total_costs: number[]
  by_type: {
    '互联网专线': number[]
    'MPLS': number[]
    'SD-WAN': number[]
    '其他': number[]
  }
}

export interface AgeDistribution {
  range: string
  count: number
  color: string
}

export interface OldDevice {
  id: number
  name: string
  model: string
  purchase_date: string
  age_years: number
  site: string
}

export interface DeviceLifecycle {
  age_distribution: AgeDistribution[]
  old_devices: OldDevice[]
}

export interface Incident {
  id: number
  title: string
  circuit_name: string
  severity: string
  started_at: string
  duration_hours: number
  status: string
}

export interface MonthlyIncidents {
  total: number
  last_month_total: number
  avg_recovery_hours: number
  max_duration: {
    hours: number
    circuit: string
    date: string
  } | null
  incidents: Incident[]
}

export async function getManagerStats(): Promise<ManagerStats> {
  const response = await request.get('/dashboard/manager-stats')
  return response.data
}

export async function getRisks(): Promise<RisksResponse> {
  const response = await request.get('/dashboard/risks')
  return response.data
}

export async function getCircuitCostTrend(): Promise<CircuitCostTrend> {
  const response = await request.get('/dashboard/circuit-cost-trend')
  return response.data
}

export async function getDeviceLifecycle(): Promise<DeviceLifecycle> {
  const response = await request.get('/dashboard/device-lifecycle')
  return response.data
}

export async function getMonthlyIncidents(): Promise<MonthlyIncidents> {
  const response = await request.get('/dashboard/monthly-incidents')
  return response.data
}

export async function downloadMonthlyReport(month: string): Promise<Blob> {
  const response = await request.get('/dashboard/monthly-report', {
    params: { month },
    responseType: 'blob'
  })
  return response.data
}
