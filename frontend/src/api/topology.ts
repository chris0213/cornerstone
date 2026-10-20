import request from './axios'

export interface TopologyNode {
  id: string
  site_id: number
  name: string
  city: string
  status: string
  device_count: number
  circuit_count: number
  contact: string
  phone: string
  location: string
  room: string
}

export interface TopologyEdge {
  id: string
  circuit_id: number
  source: string
  target: string
  name: string
  provider: string
  type: string
  bandwidth: number
  bandwidth_label: string
  status: string
  monthly_cost: number | null
  contract_end: string | null
  days_to_expire: number | null
}

export interface DeviceNode {
  id: string
  device_id: number
  name: string
  ip_address: string
  type: string
  vendor: string
  status: string
  site_id: number | null
  site_name: string | null
  latency: number | null
  packet_loss: number | null
  // 互联网出口专线字段
  circuit_id?: number
  provider?: string
  bandwidth?: number
}

export interface SiteGraphResponse {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

export interface DeviceLink {
  id: number
  source_device_id: number | null
  source_interface: string | null
  target_device_id: number | null
  target_interface: string | null
  link_type: string
  confidence: number | null
  discovered_at: string | null
  verified_at: string | null
  note: string | null
  source_circuit_id: number | null
  target_circuit_id: number | null
}

export interface DeviceLinkCreate {
  source_device_id?: number | null
  source_interface?: string | null
  target_device_id?: number | null
  target_interface?: string | null
  link_type?: string
  confidence?: number | null
  note?: string | null
  source_circuit_id?: number | null
  target_circuit_id?: number | null
}

export interface DeviceLinkUpdate {
  source_device_id?: number | null
  source_interface?: string | null
  target_device_id?: number | null
  target_interface?: string | null
  link_type?: string
  confidence?: number | null
  verified_at?: string | null
  note?: string | null
  source_circuit_id?: number | null
  target_circuit_id?: number | null
}

export interface DeviceGraphResponse {
  nodes: DeviceNode[]
  edges: DeviceEdge[]
}

export interface DeviceEdge {
  id: string
  link_id: number
  source: string
  target: string
  source_interface: string | null
  target_interface: string | null
  link_type: string
  confidence: number | null
}

// 站点设备选项（用于专线连接设置）
export interface SiteDeviceOption {
  id: number
  name: string
  type: string
  ip_address: string | null
}

// 更新专线连接
export interface CircuitConnectionUpdate {
  connected_device_id: number | null
}

export async function getSiteGraph(): Promise<SiteGraphResponse> {
  const response = await request.get('/topology/site-graph')
  return response.data
}

export async function getDeviceGraph(siteId?: number): Promise<DeviceGraphResponse> {
  const params = siteId ? { site_id: siteId } : {}
  const response = await request.get('/topology/device-graph', { params })
  return response.data
}

export async function getDeviceLinks(skip = 0, limit = 100): Promise<DeviceLink[]> {
  const response = await request.get('/topology/device-links', { params: { skip, limit } })
  return response.data
}

export async function getDeviceLink(linkId: number): Promise<DeviceLink> {
  const response = await request.get(`/topology/device-links/${linkId}`)
  return response.data
}

export async function createDeviceLink(link: DeviceLinkCreate): Promise<DeviceLink> {
  const response = await request.post('/topology/device-links', link)
  return response.data
}

export async function updateDeviceLink(linkId: number, link: DeviceLinkUpdate): Promise<DeviceLink> {
  const response = await request.put(`/topology/device-links/${linkId}`, link)
  return response.data
}

export async function deleteDeviceLink(linkId: number): Promise<void> {
  await request.delete(`/topology/device-links/${linkId}`)
}

export interface DiscoveryStats {
  devices_total: number
  devices_ok: number
  devices_failed: number
  links_created: number
  links_updated: number
  unmatched_neighbors_total?: number
  unmatched_neighbors?: string[]
  unknown_endpoints_total?: number
  unknown_endpoints_sample?: string[]
  failed_devices?: { device: string; error: string }[]
}
// 拓扑发现（后台任务 + 进度轮询）
export interface DiscoveryStartResult {
  task_id: string
  running: boolean
}

export interface DiscoveryTask {
  task_id: string
  type: 'lldp' | 'mac'
  status: 'running' | 'completed' | 'failed'
  phase: string
  done: number
  total: number
  percent: number
  message: string
  result: DiscoveryStats | null
  error: string | null
  created_at: string
  finished_at: string | null
}

export async function startLldpDiscovery(): Promise<DiscoveryStartResult> {
  const response = await request.post('/topology/discover-lldp')
  return response.data
}

export async function startMacDiscovery(): Promise<DiscoveryStartResult> {
  const response = await request.post('/topology/discover-mac')
  return response.data
}

export async function getDiscoveryTask(taskId: string): Promise<DiscoveryTask> {
  const response = await request.get(`/topology/discovery-tasks/${taskId}`)
  return response.data
}

// 未知接入终端（拓扑发现中无法与既有资产关联的终端）
export interface UnknownEndpoint {
  id: number
  device_id: number
  device_name: string | null
  site_id: number | null
  local_interface: string
  mac_address: string
  ip_address: string | null
  first_seen_at: string | null
  last_seen_at: string | null
}

export interface AcceptEndpointPayload {
  name: string
  device_type?: string
  site_id?: number | null
  owner?: string | null
  note?: string | null
  create_ip?: boolean
}

export interface AcceptEndpointResult {
  device_id: number
  device_name: string
  ip_address_id: number | null
  message: string
}

export async function getUnknownEndpoints(deviceId?: number): Promise<UnknownEndpoint[]> {
  const params = deviceId ? { device_id: deviceId } : {}
  const response = await request.get('/topology/unknown-endpoints', { params })
  return response.data
}

export async function acceptUnknownEndpoint(
  endpointId: number,
  payload: AcceptEndpointPayload
): Promise<AcceptEndpointResult> {
  const response = await request.post(`/topology/unknown-endpoints/${endpointId}/accept`, payload)
  return response.data
}

export async function deleteUnknownEndpoint(endpointId: number): Promise<void> {
  await request.delete(`/topology/unknown-endpoints/${endpointId}`)
}

// 获取站点设备列表
export async function getSiteDevices(siteId: number): Promise<SiteDeviceOption[]> {
  const response = await request.get('/topology/site-devices', { params: { site_id: siteId } })
  return response.data
}

// 更新专线连接设备
export async function updateCircuitConnection(
  circuitId: number,
  connectedDeviceId: number | null
): Promise<any> {
  const response = await request.put(
    `/topology/circuits/${circuitId}/connect`,
    null,
    { params: { connected_device_id: connectedDeviceId } }
  )
  return response.data
}
