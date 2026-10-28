import api from '@/api/axios'
import type { Prefix, IPAddress } from '../types/domain'
import { snakeToCamel } from '../lib/utils'

// Prefix API
export async function getPrefixes(): Promise<Prefix[]> {
  const response = await api.get('/ipam/prefixes/')
  return snakeToCamel(response.data)
}

export async function createPrefix(prefix: Omit<Prefix, 'id'>): Promise<Prefix> {
  const payload: any = {
    ...prefix,
    aggregate_id: prefix.aggregateId,
    site_id: prefix.siteId,
  }
  delete payload.aggregateId
  delete payload.siteId
  if (prefix.customScanPorts !== undefined) {
    payload.custom_scan_ports = prefix.customScanPorts
    delete payload.customScanPorts
  }
  if (prefix.autoScanEnabled !== undefined) {
    payload.auto_scan_enabled = prefix.autoScanEnabled
    delete payload.autoScanEnabled
  }
  if (prefix.scanCron !== undefined) {
    payload.scan_cron = prefix.scanCron
    delete payload.scanCron
  }
  const response = await api.post('/ipam/prefixes/', payload)
  return snakeToCamel(response.data)
}

export async function updatePrefix(id: string | number, data: Partial<Prefix>): Promise<Prefix> {
  const payload: any = { ...data }
  if (data.aggregateId !== undefined) {
    payload.aggregate_id = data.aggregateId ? Number(data.aggregateId) : null
    delete payload.aggregateId
  }
  if (data.siteId !== undefined) {
    payload.site_id = data.siteId ? Number(data.siteId) : null
    delete payload.siteId
  }
  if (data.customScanPorts !== undefined) {
    payload.custom_scan_ports = data.customScanPorts
    delete payload.customScanPorts
  }
  if (data.autoScanEnabled !== undefined) {
    payload.auto_scan_enabled = data.autoScanEnabled
    delete payload.autoScanEnabled
  }
  if (data.scanCron !== undefined) {
    payload.scan_cron = data.scanCron
    delete payload.scanCron
  }
  const response = await api.put(`/ipam/prefixes/${id}`, payload)
  return snakeToCamel(response.data)
}

export async function deletePrefix(id: string | number): Promise<void> {
  await api.delete(`/ipam/prefixes/${id}`)
}

// 后端 open_ports 存的是 JSON 字符串（如 "[22, 80]"），解析为数组
function normalizeOpenPortsOne(ip: IPAddress): IPAddress {
  const v = (ip as any).openPorts
  if (typeof v === 'string') {
    try {
      ;(ip as any).openPorts = JSON.parse(v)
    } catch {
      ;(ip as any).openPorts = []
    }
  }
  return ip
}

function normalizeOpenPorts(list: IPAddress[]): IPAddress[] {
  for (const item of list) normalizeOpenPortsOne(item)
  return list
}

// IP Address API
export async function getIPAddresses(prefixId?: number): Promise<IPAddress[]> {
  const params: any = {}
  if (prefixId !== undefined) params.prefix_id = prefixId
  const response = await api.get('/ipam/addresses/', { params })
  return normalizeOpenPorts(snakeToCamel(response.data))
}

// 按 id 批量精确取回（后端 ids 参数，不受分页限制），
// 用于补拉分页窗口之外、被设备引用的管理 IP
export async function getIPAddressesByIds(ids: Array<number | string>): Promise<IPAddress[]> {
  const valid = ids.filter(id => id !== null && id !== undefined && id !== '').map(String)
  if (valid.length === 0) return []
  const response = await api.get('/ipam/addresses/', { params: { ids: valid.join(',') } })
  return normalizeOpenPorts(snakeToCamel(response.data))
}

// 按地址精确查找 IP（keyword 模糊查询 + 客户端精确匹配），
// 用于保存设备时查重，避免把分页窗口外的已有 IP 误判为不存在而重复创建
export async function findIPAddressByAddress(address: string): Promise<IPAddress | undefined> {
  const response = await api.get('/ipam/addresses/', { params: { keyword: address, limit: 50 } })
  const list = normalizeOpenPorts(snakeToCamel(response.data)) as IPAddress[]
  return list.find(ip => ip.address === address)
}

export async function createIPAddress(ip: Omit<IPAddress, 'id'>): Promise<IPAddress> {
  const payload = {
    ...ip,
    prefix_id: ip.prefixId,
    device_id: ip.deviceId,
  }
  delete (payload as any).prefixId
  delete (payload as any).deviceId
  const response = await api.post('/ipam/addresses/', payload)
  return normalizeOpenPortsOne(snakeToCamel(response.data))
}

export async function updateIPAddress(id: string | number, data: Partial<IPAddress>): Promise<IPAddress> {
  const payload: any = { ...data }
  if (data.prefixId !== undefined) {
    payload.prefix_id = data.prefixId
    delete payload.prefixId
  }
  if (data.deviceId !== undefined) {
    payload.device_id = data.deviceId
    delete payload.deviceId
  }
  const response = await api.put(`/ipam/addresses/${id}`, payload)
  return normalizeOpenPortsOne(snakeToCamel(response.data))
}

export async function deleteIPAddress(id: string | number): Promise<void> {
  await api.delete(`/ipam/addresses/${id}`)
}

export interface NextAvailableIPResponse {
  code: number
  message: string
  data: {
    ip_address: string
    total_ips: number
    used_count: number
    available_count: number
    usage_rate: number
  } | null
}

export async function getNextAvailableIP(prefixId: number): Promise<NextAvailableIPResponse> {
  const response = await api.get(`/ipam/prefixes/${prefixId}/next-available`)
  return response.data
}

export async function scanPrefix(prefixId: number): Promise<{ task_id: string; message: string }> {
  const response = await api.post(`/ipam/prefixes/${prefixId}/scan`)
  return response.data
}