import api from './axios'

export interface UserResponse {
  id: number
  username: string
  email: string
  full_name: string | null
  is_active: boolean
  is_superuser: boolean
  created_at: string
  updated_at: string | null
}

export async function getUsers(): Promise<UserResponse[]> {
  const response = await api.get('/users/')
  return response.data
}

export async function getUser(id: number): Promise<UserResponse> {
  const response = await api.get(`/users/${id}`)
  return response.data
}

export async function createUser(data: {
  username: string
  email: string
  password: string
  full_name?: string
  is_active?: boolean
}): Promise<UserResponse> {
  const response = await api.post('/users', data)
  return response.data
}

export async function updateUser(id: number, data: Partial<UserResponse>): Promise<UserResponse> {
  const response = await api.put(`/users/${id}`, data)
  return response.data
}

export async function deleteUser(id: number): Promise<void> {
  await api.delete(`/users/${id}`)
}
