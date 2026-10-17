import api from './axios'

export interface RackStats {
  total_u: number
  used_u: number
  free_u: number
  utilization: number
  device_count: number
}

export interface RackDevice {
  id: number
  name: string
  type: string | null
  vendor: string | null
  model: string | null
  sn: string | null
  u_position: number | null
  u_size: number
  status: string
  mgmt_ip?: string | null
}

export interface RackResponse {
  id: number
  name: string
  site_id: number | null
  room: string | null
  row_position: number
  total_u: number
  status: string
  description: string | null
  created_at: string
  updated_at: string | null
  used_u?: number
  utilization?: number
  device_count?: number
}

export interface RackDetailResponse extends RackResponse {
  devices: RackDevice[]
  stats: RackStats | null
}

export interface RackCreate {
  name: string
  site_id?: number | null
  room?: string | null
  row_position?: number
  total_u?: number
  status?: string
  description?: string | null
}

export interface RackUpdate {
  name?: string
  site_id?: number | null
  room?: string | null
  row_position?: number
  total_u?: number
  status?: string
  description?: string | null
}

export interface DevicePositionUpdate {
  rack_id?: number | null
  u_position?: number | null
  u_size?: number
}

export async function listRacks(params?: { site_id?: number; skip?: number; limit?: number }): Promise<RackResponse[]> {
  const response = await api.get('/racks/', { params })
  return response.data
}

export async function getRack(id: number): Promise<RackDetailResponse> {
  const response = await api.get(`/racks/${id}`)
  return response.data
}

export async function getRackStats(id: number): Promise<RackStats> {
  const response = await api.get(`/racks/${id}/stats`)
  return response.data
}

export async function createRack(data: RackCreate): Promise<RackResponse> {
  const response = await api.post('/racks/', data)
  return response.data
}

export async function updateRack(id: number, data: RackUpdate): Promise<RackResponse> {
  const response = await api.put(`/racks/${id}`, data)
  return response.data
}

export async function deleteRack(id: number): Promise<void> {
  await api.delete(`/racks/${id}`)
}

export async function updateDevicePosition(deviceId: number, data: DevicePositionUpdate): Promise<RackDevice | null> {
  const response = await api.put(`/racks/devices/${deviceId}/rack-position`, data)
  return response.data
}
