export interface Site {
  id: number
  name: string
  location: string
  city: string
  room: string
  contact: string
  contactPhone: string
  status: 'online' | 'alert' | 'offline'
  alertCount: number
}

export interface Circuit {
  id: string
  name: string
  provider: string
  type: string
  siteId: number
  bandwidth: number
  monthlyCost: number
  contractStart: string
  contractEnd: string
  circuitNo: string
  supportPhone: string
  publicIp: string
  status: string
  note: string
  updatedBy: string
  updatedAt: string
}

export interface Aggregate {
  id: number
  network: string
  name: string
}

export interface Prefix {
  id: number
  aggregateId: number | null
  network: string
  siteId: number | null
  vlan: string
  usage: string
  customScanPorts?: string | null
  autoScanEnabled?: boolean
  scanCron?: string
  ipCount?: number
}

export interface IPAddress {
  id: string | number
  address: string
  prefixId: number | null
  deviceId: number | null
  usage: string
  owner: string
  status: string
  expireAt?: string
  isOnline?: boolean
  lastSeenAt?: string
  scanMethod?: string
  openPorts?: number[]
  macAddress?: string
  lastScannedAt?: string
}

export interface Device {
  id: number
  name: string
  type: string
  vendor: string
  model: string
  sn: string
  assetTag: string
  siteId: number | null
  location: string
  mgmtIpId: number | null
  rackId: number | null
  uPosition: number | null
  uSize: number
  status: string
  purchaseDate: string
  warrantyEnd: string
  purchaseAmount: number
  owner: string
  note: string
}

export interface Rack {
  id: number
  name: string
  siteId: number | null
  room: string | null
  rowPosition: number
  totalU: number
  status: string
  description: string | null
  usedU?: number
  utilization?: number
  deviceCount?: number
}

export interface RackStats {
  totalU: number
  usedU: number
  freeU: number
  utilization: number
  deviceCount: number
}

export interface RackDevice {
  id: number
  name: string
  type: string | null
  vendor: string | null
  model: string | null
  sn: string | null
  uPosition: number | null
  uSize: number
  status: string
  mgmtIp?: string | null
}

export interface Credential {
  id: string
  name: string
  deviceId?: number
  protocol: string
  port: number
  username: string
  password?: string
  enablePassword?: string
  authType: string
  privateKey?: string
  jumpHost?: string
  jumpPort: number
  jumpUsername?: string
  jumpPassword?: string
  description?: string
  usedByCount?: number
  usedByTasks?: Array<{ id: number; name: string }>
  lastTestedAt?: string
  lastTestStatus?: 'success' | 'failed'
}

export interface Backup {
  id: string
  deviceId: number
  deviceName?: string
  version: number
  content?: string
  contentHash?: string
  filePath?: string
  trigger: string
  operator?: string
  status: string
  errorMessage?: string
  hasChange: boolean
  changeSummary?: string
  tag?: string
  durationMs?: number
  size?: number
  note?: string
  created_at: string
  createdAt: string
}

export interface BackupTask {
  id: string
  name: string
  isEnabled: boolean
  cronExpr: string
  deviceIds?: string
  siteId?: number
  vendor?: string
  credentialId: number | string
  credentialName?: string
  siteName?: string
  retentionCount: number
  retentionDays: number
  notifyOnChange: boolean
  notifyOnFail: boolean
  last_run_at?: string
  lastRunAt?: string
  lastRunStatus?: string
  scopeType?: 'devices' | 'site' | 'all'
  credentialMissing?: boolean
  credentialProtocol?: 'ssh' | 'telnet' | null
  deviceMissingIds?: number[]
  nextRunAt?: string | null
  isRunning?: boolean
  deviceCount?: number
  created_at?: string
  createdAt?: string
}

export interface User {
  id: string
  username: string
  email: string
  role: string
  role_display_name: string
  isActive: boolean
  is_superuser: boolean
  permissions: string[]
  display_name: string
  is_sso_user: boolean
  last_login_at?: string
  last_login_ip?: string
  avatar?: string
  created_at?: string
  updated_at?: string
}

export interface AuditLog {
  id: string | number
  user: string
  action: string
  resource: string
  detail: string
  ipAddress: string | null
  createdAt: string
  success: string
}

export interface VlanGroup {
  id: number
  name: string
  siteId?: number
  description?: string
}

export interface Vlan {
  id: number
  vid: number
  name?: string
  groupId?: number
  siteId?: number
  status: string
  description?: string
}

export interface AppState {
  sites: Site[]
  circuits: Circuit[]
  aggregates: Aggregate[]
  prefixes: Prefix[]
  ipAddresses: IPAddress[]
  devices: Device[]
  racks: Rack[]
  credentials: Credential[]
  backups: Backup[]
  users: User[]
  auditLogs: AuditLog[]
  vlanGroups: VlanGroup[]
  vlans: Vlan[]
}
