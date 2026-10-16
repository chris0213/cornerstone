import api from './axios'

export interface DeviceResponse {
  id: number
  name: string
  type: string
  vendor: string | null
  model: string
  sn: string
  site_id: number | null
  location: string | null
  mgmt_ip_id: number | null
  rack_id: number | null
  u_position: number | null
  u_size: number
  status: string
  purchase_date: string | null
  warranty_end: string | null
  purchase_amount: number | null
  owner: string | null
  note: string | null
  created_at: string
  updated_at: string | null
}

export interface DeviceCreate {
  name: string
  type: string
  vendor: string | null
  model: string
  sn: string
  site_id: number | null
  location: string | null
  mgmt_ip_id: number | null
  status: string
  purchase_date: string | null
  warranty_end: string | null
  purchase_amount: number | null
  owner: string | null
  note: string | null
}

// 列表接口默认 limit=100，需要按 skip/limit 循环拉取全量（每页上限 1000）
export async function getDevices(): Promise<DeviceResponse[]> {
  const pageSize = 1000
  const all: DeviceResponse[] = []
  let skip = 0
  while (true) {
    const response = await api.get('/devices/', { params: { skip, limit: pageSize } })
    const batch: DeviceResponse[] = response.data
    all.push(...batch)
    if (batch.length < pageSize) break
    skip += pageSize
  }
  return all
}

export async function getDevice(id: number): Promise<DeviceResponse> {
  const response = await api.get(`/devices/${id}`)
  return response.data
}

export async function createDevice(data: DeviceCreate): Promise<DeviceResponse> {
  const response = await api.post('/devices/', data)
  return response.data
}

export async function updateDevice(id: number, data: Partial<DeviceCreate>): Promise<DeviceResponse> {
  const response = await api.put(`/devices/${id}`, data)
  return response.data
}

export async function deleteDevice(id: number): Promise<void> {
  await api.delete(`/devices/${id}`)
}
