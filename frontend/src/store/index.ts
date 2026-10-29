import { defineStore } from 'pinia'
import type { AppState, Circuit, Site, Device, Prefix, IPAddress, Backup, User, AuditLog, VlanGroup, Vlan, Credential } from '../types/domain'
import { seedState, STORE_KEY } from './seed'
import { uid } from '../lib/utils'

function getEmptyState(): AppState {
  return {
    sites: [],
    circuits: [],
    aggregates: [],
    prefixes: [],
    ipAddresses: [],
    devices: [],
    credentials: [],
    backups: [],
    users: [],
    auditLogs: [],
    vlanGroups: [],
    vlans: [],
    racks: [],
  }
}

function loadState(): AppState {
  const saved = localStorage.getItem(STORE_KEY)
  if (!saved) return getEmptyState()
  try {
    const parsed = JSON.parse(saved) as AppState
    // 兜底：旧数据可能缺字段，合并空态保证结构完整
    return { ...getEmptyState(), ...parsed }
  } catch (e) {
    // 脏数据致 JSON.parse 抛错：清除坏 key 回空态，避免全站白屏不可恢复
    console.warn('[store] loadState failed, resetting to empty state:', e)
    localStorage.removeItem(STORE_KEY)
    return getEmptyState()
  }
}

// 凭证敏感字段永不落盘（一次 XSS 即可全网设备口令+私钥泄露）
const CREDENTIAL_SENSITIVE_KEYS: (keyof Credential)[] = [
  'password',
  'enablePassword',
  'privateKey',
  'jumpPassword',
]

function stripSensitiveCredentials(state: AppState): AppState {
  return {
    ...state,
    credentials: state.credentials.map((c) => {
      const safe: Credential = { ...c }
      for (const key of CREDENTIAL_SENSITIVE_KEYS) {
        delete safe[key]
      }
      return safe
    }),
  }
}

function saveState(state: AppState): void {
  localStorage.setItem(STORE_KEY, JSON.stringify(stripSensitiveCredentials(state)))
}

export const useAppStore = defineStore('app', {
  state: (): AppState => ({
    ...loadState(),
  }),

  getters: {
    siteById: (state) => (id: number): Site | undefined => {
      return state.sites.find((site) => site.id === id)
    },

    siteName: (state) => (id: number): string => {
      return state.sites.find((site) => site.id === id)?.name || '-'
    },

    deviceById: (state) => (id: number): Device | undefined => {
      return state.devices.find((device) => device.id === id)
    },

    deviceName: (state) => (id: number): string => {
      return state.devices.find((device) => device.id === id)?.name || '-'
    },

    ipAddressById: (state) => (id: string | number): IPAddress | undefined => {
      return state.ipAddresses.find((ip) => String(ip.id) === String(id))
    },

    ipAddress: (state) => (id: string | number): string => {
      return state.ipAddresses.find((ip) => String(ip.id) === String(id))?.address || '-'
    },

    prefixById: (state) => (id: number): Prefix | undefined => {
      return state.prefixes.find((prefix) => prefix.id === id)
    },

    prefixNetwork: (state) => (id: number): string => {
      return state.prefixes.find((prefix) => prefix.id === id)?.network || '-'
    },

    normalCircuitsCount: (state): number => {
      return state.circuits.filter((c) => c.status === '正常').length
    },

    todaySuccessfulBackups: (state): number => {
      const today = new Date().toISOString().split('T')[0]
      return state.backups.filter((b) => b.createdAt.startsWith(today) && b.status === '成功').length
    },

    todayFailedBackups: (state): number => {
      const today = new Date().toISOString().split('T')[0]
      return state.backups.filter((b) => b.createdAt.startsWith(today) && b.status === '失败').length
    },

    ipTotal: (state): number => {
      return state.prefixes.length * 254
    },

    ipUsed: (state): number => {
      return state.ipAddresses.filter((ip) => ip.status === '已分配').length
    },

    ipUsagePercent: (state): number => {
      const total = state.prefixes.length * 254
      const used = state.ipAddresses.filter((ip) => ip.status === '已分配').length
      return total > 0 ? Math.round((used / total) * 100) : 0
    },
  },

  actions: {
    save() {
      saveState(this.$state)
    },

    reset() {
      this.$patch(JSON.parse(JSON.stringify(seedState)))
      this.save()
    },

    // Circuit actions
    addCircuit(circuit: Omit<Circuit, 'id' | 'updatedBy' | 'updatedAt'>) {
      const now = new Date()
      const newCircuit: Circuit = {
        ...circuit,
        id: uid('cir'),
        updatedBy: 'admin',
        updatedAt: `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`,
      }
      this.circuits.push(newCircuit)
      this.save()
      return newCircuit
    },

    updateCircuit(id: string, updates: Partial<Circuit>) {
      const index = this.circuits.findIndex((c) => c.id === id)
      if (index !== -1) {
        const now = new Date()
        this.circuits[index] = {
          ...this.circuits[index],
          ...updates,
          updatedBy: 'admin',
          updatedAt: `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`,
        }
        this.save()
      }
    },

    deleteCircuit(id: string) {
      const index = this.circuits.findIndex((c) => c.id === id)
      if (index !== -1) {
        this.circuits.splice(index, 1)
        this.save()
      }
    },

    deleteCircuits(ids: string[]) {
      this.circuits = this.circuits.filter((c) => !ids.includes(c.id))
      this.save()
    },

    setCircuits(circuits: Circuit[]) {
      this.circuits = circuits
      this.save()
    },

    // Site actions
    addSite(site: Omit<Site, 'id'>) {
      const newSite: Site = {
        ...site,
        id: Date.now(),
      }
      this.sites.push(newSite)
      this.save()
      return newSite
    },

    updateSite(site: Site) {
      const index = this.sites.findIndex((s) => s.id === site.id)
      if (index !== -1) {
        this.sites[index] = site
        this.save()
      }
    },

    deleteSite(id: number) {
      const index = this.sites.findIndex((s) => s.id === id)
      if (index !== -1) {
        this.sites.splice(index, 1)
        this.save()
      }
    },

    // Device actions
    addDevice(device: Omit<Device, 'id'>) {
      const newDevice: Device = {
        ...device,
        id: Date.now(),
      }
      this.devices.push(newDevice)
      this.save()
      return newDevice
    },

    updateDevice(id: number, updates: Partial<Device>) {
      const index = this.devices.findIndex((d) => d.id === id)
      if (index !== -1) {
        this.devices[index] = { ...this.devices[index], ...updates }
        this.save()
      }
    },

    deleteDevice(id: number) {
      const index = this.devices.findIndex((d) => d.id === id)
      if (index !== -1) {
        this.devices.splice(index, 1)
        this.save()
      }
    },

    // Prefix actions
    addPrefix(prefix: Omit<Prefix, 'id'>) {
      const newPrefix: Prefix = {
        ...prefix,
        id: Date.now(),
      }
      this.prefixes.push(newPrefix)
      this.save()
      return newPrefix
    },

    updatePrefix(id: number, updates: Partial<Prefix>) {
      const index = this.prefixes.findIndex((p) => p.id === id)
      if (index !== -1) {
        this.prefixes[index] = { ...this.prefixes[index], ...updates }
        this.save()
      }
    },

    deletePrefix(id: number) {
      const index = this.prefixes.findIndex((p) => p.id === id)
      if (index !== -1) {
        this.prefixes.splice(index, 1)
        this.save()
      }
    },

    // IP Address actions
    addIPAddress(ipAddress: Omit<IPAddress, 'id'>) {
      const newIP: IPAddress = {
        ...ipAddress,
        id: uid('ip'),
      }
      this.ipAddresses.push(newIP)
      this.save()
      return newIP
    },

    updateIPAddress(id: string, updates: Partial<IPAddress>) {
      const index = this.ipAddresses.findIndex((ip) => ip.id === id)
      if (index !== -1) {
        this.ipAddresses[index] = { ...this.ipAddresses[index], ...updates }
        this.save()
      }
    },

    deleteIPAddress(id: string) {
      const index = this.ipAddresses.findIndex((ip) => ip.id === id)
      if (index !== -1) {
        this.ipAddresses.splice(index, 1)
        this.save()
      }
    },

    // Backup actions
    addBackup(backup: Omit<Backup, 'id'>) {
      const newBackup: Backup = {
        ...backup,
        id: uid('bak'),
      }
      this.backups.push(newBackup)
      this.save()
      return newBackup
    },

    updateBackup(id: string, updates: Partial<Backup>) {
      const index = this.backups.findIndex((b) => b.id === id)
      if (index !== -1) {
        this.backups[index] = { ...this.backups[index], ...updates }
        this.save()
      }
    },

    deleteBackup(id: string) {
      const index = this.backups.findIndex((b) => b.id === id)
      if (index !== -1) {
        this.backups.splice(index, 1)
        this.save()
      }
    },

    // User actions
    addUser(user: Omit<User, 'id'>) {
      const newUser: User = {
        ...user,
        id: uid('user'),
      }
      this.users.push(newUser)
      this.save()
      return newUser
    },

    updateUser(id: string, updates: Partial<User>) {
      const index = this.users.findIndex((u) => u.id === id)
      if (index !== -1) {
        this.users[index] = { ...this.users[index], ...updates }
        this.save()
      }
    },

    deleteUser(id: string) {
      const index = this.users.findIndex((u) => u.id === id)
      if (index !== -1) {
        this.users.splice(index, 1)
        this.save()
      }
    },

    // Audit log actions
    addAuditLog(log: Omit<AuditLog, 'id'>) {
      const newLog: AuditLog = {
        ...log,
        id: uid('log'),
      }
      this.auditLogs.unshift(newLog)
      this.save()
      return newLog
    },

    // VLAN Group actions
    addVlanGroup(group: Omit<VlanGroup, 'id'>) {
      const newGroup: VlanGroup = {
        ...group,
        id: Date.now(),
      }
      this.vlanGroups.push(newGroup)
      this.save()
      return newGroup
    },

    updateVlanGroup(id: number, updates: Partial<VlanGroup>) {
      const index = this.vlanGroups.findIndex((g) => g.id === id)
      if (index !== -1) {
        this.vlanGroups[index] = { ...this.vlanGroups[index], ...updates }
        this.save()
      }
    },

    deleteVlanGroup(id: number) {
      const index = this.vlanGroups.findIndex((g) => g.id === id)
      if (index !== -1) {
        this.vlanGroups.splice(index, 1)
        this.save()
      }
    },

    // VLAN actions
    addVlan(vlan: Omit<Vlan, 'id'>) {
      const newVlan: Vlan = {
        ...vlan,
        id: Date.now(),
      }
      this.vlans.push(newVlan)
      this.save()
      return newVlan
    },

    updateVlan(id: number, updates: Partial<Vlan>) {
      const index = this.vlans.findIndex((v) => v.id === id)
      if (index !== -1) {
        this.vlans[index] = { ...this.vlans[index], ...updates }
        this.save()
      }
    },

    deleteVlan(id: number) {
      const index = this.vlans.findIndex((v) => v.id === id)
      if (index !== -1) {
        this.vlans.splice(index, 1)
        this.save()
      }
    },
  },
})
