<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, Upload, Edit, Delete, MagicStick } from '@element-plus/icons-vue'
import { formatDate } from '../../lib/utils'
import { applyKeywordFilter } from '../../lib/filters'
import { confirmAndRun } from '../../lib/confirm'
import { useCrudForm } from '../../lib/useCrudForm'
import type { Device, IPAddress, Site } from '../../types/domain'
import { getIPAddresses, getIPAddressesByIds, findIPAddressByAddress, createIPAddress } from '../../api/ipam'
import { getDevices, createDevice, updateDevice, deleteDevice, type DeviceResponse } from '../../api/devices'
import { getDeviceLinks } from '../../api/topology'
import { getSites, type SiteResponse } from '../../api/sites'
import { useAppStore } from '../../store'
import { useAuthStore } from '../../store/auth'
import api from '../../api/axios'
import { DEVICE_TYPE_CONFIG } from '../../constants/deviceIcons'
import QuickAddDeviceWizard from './QuickAddDeviceWizard.vue'

const { t } = useI18n()
const store = useAppStore()
const authStore = useAuthStore()
const route = useRoute()

// 在线三态口径：管理 IP 的最近探测结果（设备表无探测字段）
// online = 管理 IP 探测在线；offline = 管理 IP 探测离线；notProbed = 无管理 IP 或未探测
type OnlineState = 'online' | 'offline' | 'notProbed'

function getOnlineState(device: Pick<Device, 'mgmtIpId'>): OnlineState {
  if (!device.mgmtIpId) return 'notProbed'
  const ip = ipAddresses.value.find(addr => String(addr.id) === String(device.mgmtIpId))
  if (!ip || ip.isOnline === undefined || ip.isOnline === null) return 'notProbed'
  return ip.isOnline ? 'online' : 'offline'
}

const onlineCount = computed(() => devices.value.filter(d => getOnlineState(d) === 'online').length)
const offlineCount = computed(() => devices.value.filter(d => getOnlineState(d) === 'offline').length)
const notProbedCount = computed(() => devices.value.filter(d => getOnlineState(d) === 'notProbed').length)

// 生命周期状态：显示映射（含中文存量值回退，不修改存量数据）
const lifecycleText: Record<string, string> = {
  active: t('devices.active'),
  inactive: t('devices.inactive'),
  maintenance: t('devices.maintenance'),
  scrapped: t('devices.scrapped'),
  alert: t('devices.alert'),
  online: t('devices.onlineState'),
  offline: t('devices.offline'),
  '在线': t('devices.onlineState'),
  '离线': t('devices.offline'),
  '维修': t('devices.maintenance'),
  '报废': t('devices.scrapped'),
}

function lifecycleLabel(status: string): string {
  return lifecycleText[status] || status
}

function lifecycleTagType(status: string): string {
  switch (status) {
    case 'active':
    case '在线':
      return 'success'
    case 'maintenance':
    case 'alert':
    case '维修':
      return 'warning'
    case 'inactive':
    case 'offline':
    case 'scrapped':
    case '离线':
    case '报废':
      return 'info'
    default:
      return 'info'
  }
}

const isViewer = computed(() => authStore.isReadOnly())
const highlightedDeviceId = ref<number | null>(null)

// 从后端获取的站点数据
const sites = ref<Site[]>([])

// 获取站点名称
const siteName = (id: number): string => {
  return sites.value.find((site) => site.id === id)?.name || '—'
}

// 从后端获取的设备数据
const devices = ref<Device[]>([])
// 从后端获取的IP地址数据
const ipAddresses = ref<IPAddress[]>([])

const searchQuery = ref('')
const selectedSiteId = ref<number | null>(null)
const showQuickAddWizard = ref(false)
const loading = ref(false)

// 新增设备分体下拉：主体点击=新增，下拉项=快速添加
function handleCreateCommand(command: string) {
  if (command === 'quick') showQuickAddWizard.value = true
}

// 表单弹窗状态（新建/编辑/关闭）
const defaultDeviceForm = () => ({
  name: '',
  type: 'switch',
  vendor: '',
  model: '',
  sn: '',
  assetTag: '',
  siteId: null as number | null,
  location: '',
  mgmtIpId: null as number | null,
  mgmtIpAddress: '',
  status: 'active',
  purchaseDate: '',
  warrantyEnd: '',
  purchaseAmount: 0,
  owner: '',
  note: '',
})
type DeviceForm = ReturnType<typeof defaultDeviceForm>

const {
  showDialog,
  editing: editingDevice,
  form,
  openCreate: openCreateDialog,
  openEdit: openEditDialog,
  closeDialog,
} = useCrudForm<Device, DeviceForm>({
  createDefaults: defaultDeviceForm,
  toForm: (device) => ({
    name: device.name,
    type: device.type,
    vendor: device.vendor,
    model: device.model,
    sn: device.sn,
    assetTag: device.assetTag || '',
    siteId: device.siteId,
    location: device.location,
    mgmtIpId: device.mgmtIpId,
    mgmtIpAddress: getIpAddress(device.mgmtIpId || 0) !== '-' ? getIpAddress(device.mgmtIpId || 0) : '',
    status: device.status,
    purchaseDate: device.purchaseDate,
    warrantyEnd: device.warrantyEnd,
    purchaseAmount: device.purchaseAmount,
    owner: device.owner,
    note: device.note,
  }),
})

// 厂商选项
const vendorOptions = computed(() => [
  { value: '', label: t('devices.vendorPlaceholder') },
  { value: 'cisco_ios', label: 'Cisco IOS' },
  { value: 'cisco_nxos', label: 'Cisco NX-OS' },
  { value: 'huawei_vrp', label: 'Huawei' },
  { value: 'h3c', label: 'H3C' },
  { value: 'juniper', label: 'Juniper' },
  { value: 'fortinet', label: 'Fortinet' },
  { value: 'ruijie', label: 'Ruijie' },
  { value: 'hillstone', label: 'Hillstone' },
  { value: 'aruba', label: 'Aruba' },
])

// 列设置（localStorage 持久化，序列号/位置默认隐藏）
type ColumnKey = 'name' | 'type' | 'vendor' | 'sn' | 'site' | 'location' | 'mgmtIp' | 'online' | 'lifecycle' | 'warranty'
const COLUMN_DEFS: { key: ColumnKey; labelKey: string }[] = [
  { key: 'name', labelKey: 'devices.device' },
  { key: 'type', labelKey: 'common.type' },
  { key: 'vendor', labelKey: 'devices.vendor' },
  { key: 'sn', labelKey: 'devices.serial' },
  { key: 'site', labelKey: 'devices.siteField' },
  { key: 'location', labelKey: 'devices.location' },
  { key: 'mgmtIp', labelKey: 'devices.mgmtIp' },
  { key: 'online', labelKey: 'devices.onlineState' },
  { key: 'lifecycle', labelKey: 'devices.lifecycle' },
  { key: 'warranty', labelKey: 'devices.warranty' },
]
const COLUMN_SETTINGS_KEY = 'devices_column_settings_v1'
const DEFAULT_COLUMN_VISIBLE: Record<ColumnKey, boolean> = {
  name: true, type: true, vendor: true, sn: false, site: true, location: false, mgmtIp: true, online: true, lifecycle: true, warranty: true,
}

function loadColumnSettings(): Record<ColumnKey, boolean> {
  try {
    const raw = localStorage.getItem(COLUMN_SETTINGS_KEY)
    if (raw) return { ...DEFAULT_COLUMN_VISIBLE, ...JSON.parse(raw) }
  } catch { /* 忽略解析失败，使用默认值 */ }
  return { ...DEFAULT_COLUMN_VISIBLE }
}

const columnVisible = ref<Record<ColumnKey, boolean>>(loadColumnSettings())
watch(columnVisible, (val) => {
  localStorage.setItem(COLUMN_SETTINGS_KEY, JSON.stringify(val))
}, { deep: true })

// 筛选：类型 / 站点 / 生命周期 / 保修状态
// type 已枚举化（switch/router/...），与后端 constants/device_type.py 对齐
const filterType = ref('')
const filterLifecycle = ref('')

// 保修联动筛选（卡片与筛选下拉共用，0 时卡片不可点击）
const warrantyFilter = ref<'' | 'expired' | 'expiring90' | 'notSet' | 'valid'>('')

function toggleWarrantyFilter(key: 'expired' | 'expiring90') {
  warrantyFilter.value = warrantyFilter.value === key ? '' : key
}

const deviceTypeOptions = [
  { value: 'switch', labelKey: 'devices.typeSwitch' },
  { value: 'router', labelKey: 'devices.typeRouter' },
  { value: 'firewall', labelKey: 'devices.typeFirewall' },
  { value: 'server', labelKey: 'devices.typeServer' },
  { value: 'ap', labelKey: 'devices.typeAP' },
  { value: 'wireless-controller', labelKey: 'devices.typeWirelessController' },
  { value: 'load-balancer', labelKey: 'devices.typeLoadBalancer' },
  { value: 'ids-ips', labelKey: 'devices.typeIdsIps' },
  { value: 'waf', labelKey: 'devices.typeWaf' },
  { value: 'vpn', labelKey: 'devices.typeVpn' },
  { value: 'storage', labelKey: 'devices.typeStorage' },
  { value: 'other', labelKey: 'devices.typeOther' },
]

// 类型显示映射：枚举 → i18n 文案，未知值原样回退
const typeTextMap: Record<string, string> = Object.fromEntries(
  deviceTypeOptions.map(o => [o.value, t(o.labelKey)])
)

function typeText(type: string | null | undefined): string {
  if (!type) return '—'
  return typeTextMap[type] || type
}

// 分页
const currentPage = ref(1)
const pageSize = ref(20)
const pagedDevices = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredDevices.value.slice(start, start + pageSize.value)
})

const filteredDevices = computed(() => {
  let result = devices.value

  // 保修筛选（卡片联动与下拉共用同一状态）
  if (warrantyFilter.value === 'expired') {
    result = result.filter(d => getWarrantyState(d.warrantyEnd).state === 'expired')
  } else if (warrantyFilter.value === 'expiring90') {
    result = result.filter(d => ['expiring30', 'expiring90'].includes(getWarrantyState(d.warrantyEnd).state))
  } else if (warrantyFilter.value === 'notSet') {
    result = result.filter(d => getWarrantyState(d.warrantyEnd).state === 'notSet')
  } else if (warrantyFilter.value === 'valid') {
    result = result.filter(d => getWarrantyState(d.warrantyEnd).state === 'valid')
  }

  // 按类型筛选
  if (filterType.value) {
    result = result.filter(d => d.type === filterType.value)
  }

  // 按生命周期筛选
  if (filterLifecycle.value) {
    result = result.filter(d => d.status === filterLifecycle.value)
  }

  // 按站点筛选
  if (selectedSiteId.value !== null) {
    result = result.filter(d => d.siteId === selectedSiteId.value)
  }

  // 按搜索关键词筛选
  result = applyKeywordFilter(result, searchQuery.value, [
    'name', 'type', 'vendor', 'model', 'sn',
    (d) => siteName(d.siteId || 0),
    (d) => getIpAddress(d.mgmtIpId || 0),
  ])

  return result
})

// 筛选条件变化时回到第一页
watch([searchQuery, selectedSiteId, filterType, filterLifecycle, warrantyFilter], () => {
  currentPage.value = 1
})

const siteDeviceCount = computed(() => {
  const count: Record<number, number> = {}
  devices.value.forEach(d => {
    if (d.siteId) {
      count[d.siteId] = (count[d.siteId] || 0) + 1
    }
  })
  return count
})

function getIpAddress(id: string | number | null | undefined): string {
  if (!id) return '-'
  return ipAddresses.value.find(ip => String(ip.id) === String(id))?.address || '-'
}

onMounted(async () => {
  try {
    ipAddresses.value = await getIPAddresses()
  } catch (error) {
    console.error('Failed to load IP addresses:', error)
  }
})

function getWarrantyDays(endDate: string) {
  if (!endDate) return null
  const today = new Date()
  const end = new Date(endDate)
  const diff = end.getTime() - today.getTime()
  return Math.ceil(diff / (1000 * 60 * 60 * 24))
}

// 保修状态统一判断（全页唯一口径，规则与专线页 getContractState 同构）
// expired = 已过保；expiring30 = 30 天内到期；expiring90 = 90 天内到期；valid = 其余；notSet = 未设置
type WarrantyState = 'notSet' | 'expired' | 'expiring30' | 'expiring90' | 'valid'

function getWarrantyState(endDate: string): { state: WarrantyState; days: number | null } {
  const days = getWarrantyDays(endDate)
  if (days === null) return { state: 'notSet', days: null }
  if (days <= 0) return { state: 'expired', days }
  if (days <= 30) return { state: 'expiring30', days }
  if (days <= 90) return { state: 'expiring90', days }
  return { state: 'valid', days }
}

function getWarrantyDisplay(endDate: string): { type: string; text: string } {
  const { state, days } = getWarrantyState(endDate)
  switch (state) {
    case 'notSet':
      return { type: 'info', text: t('warrantyStatus.notSet') }
    case 'expired':
      return { type: 'danger', text: t('warrantyStatus.expiredDays', { days: -(days as number) }) }
    case 'expiring30':
      return { type: 'warning', text: t('warrantyStatus.daysRemaining', { days }) }
    case 'expiring90':
      return { type: 'info', text: t('warrantyStatus.daysRemaining', { days }) }
    default:
      return { type: 'success', text: t('warrantyStatus.daysRemaining', { days }) }
  }
}

const expiredWarrantyDevices = computed(() => devices.value.filter(d => getWarrantyState(d.warrantyEnd).state === 'expired'))
const expiring90WarrantyDevices = computed(() =>
  devices.value.filter(d => ['expiring30', 'expiring90'].includes(getWarrantyState(d.warrantyEnd).state))
)

function getDeviceTypeConfigKey(type: string | undefined): string {
  // 枚举值 → 图标配置 key；保留中文映射回退（防御未迁移数据）
  const typeMap: Record<string, string> = {
    'switch': 'core-switch',
    'router': 'router',
    'firewall': 'firewall',
    'server': 'server',
    'ap': 'ap',
    'wireless-controller': 'ac',
    'load-balancer': 'load-balancer',
    'ids-ips': 'ids-ips',
    'waf': 'waf',
    'vpn': 'vpn',
    'storage': 'nas',
    'other': 'unknown',
    // 历史中文值回退
    '交换机': 'core-switch',
    '路由器': 'router',
    '防火墙': 'firewall',
    '服务器': 'server',
    'AP': 'ap',
    '其他': 'unknown'
  }
  return typeMap[type || ''] || 'unknown'
}

function getDeviceIconClass(type: string | undefined): string {
  const configKey = getDeviceTypeConfigKey(type)
  return DEVICE_TYPE_CONFIG[configKey]?.iconClass || DEVICE_TYPE_CONFIG['unknown'].iconClass
}

function getDeviceIconStyle(type: string | undefined) {
  const configKey = getDeviceTypeConfigKey(type)
  const config = DEVICE_TYPE_CONFIG[configKey]
  return {
    background: config.bgColor,
    color: config.color,
    border: `1px solid ${config.borderColor}`
  }
}

async function handleSave() {
  if (!form.value.name.trim()) {
    ElMessage.error(t('validation.required'))
    return
  }

  try {
    let mgmtIpId: number | null = form.value.mgmtIpId || null
    
    // 如果用户手动输入了IP地址
    if (form.value.mgmtIpAddress.trim() && !mgmtIpId) {
      const inputIp = form.value.mgmtIpAddress.trim()

      // 检查IP是否已存在：本地缓存未命中时再查后端（本地只加载了分页首页，
      // 已有 IP 可能不在其中，误判会导致重复创建）
      let existingIp = ipAddresses.value.find(ip => ip.address === inputIp)
      if (!existingIp) {
        try {
          existingIp = await findIPAddressByAddress(inputIp)
          if (existingIp) ipAddresses.value.push(existingIp)
        } catch (lookupError) {
          console.error(`Failed to lookup IP ${inputIp}:`, lookupError)
        }
      }
      if (existingIp) {
        mgmtIpId = typeof existingIp.id === 'number' ? existingIp.id : null
      } else {
        // 自动创建新的IP地址
        try {
          const newIp = await createIPAddress({
            address: inputIp,
            status: 'active',
            usage: `${t('common.auto')} - ${form.value.name} ${t('devices.mgmtIp')}`,
            owner: '',
            prefixId: null,
            deviceId: null,
          })
          mgmtIpId = typeof newIp.id === 'number' ? newIp.id : null
          ipAddresses.value.push(newIp)
          ElMessage.success(`${t('common.created')} IP: ${inputIp}`)
        } catch (createError) {
          console.error(`Failed to create IP ${inputIp}:`, createError)
          ElMessage.warning(`${t('common.createFailed')} IP: ${inputIp}. ${t('validation.ipAddress')}`)
        }
      }
    }

    const deviceData = {
      name: form.value.name,
      type: form.value.type,
      vendor: form.value.vendor,
      model: form.value.model,
      sn: form.value.sn,
      asset_tag: form.value.assetTag?.trim() || null,
      site_id: form.value.siteId,
      location: form.value.location || null,
      mgmt_ip_id: mgmtIpId,
      status: form.value.status,
      purchase_date: form.value.purchaseDate || null,
      warranty_end: form.value.warrantyEnd || null,
      purchase_amount: form.value.purchaseAmount || null,
      owner: form.value.owner || null,
      note: form.value.note || null,
    }

    if (editingDevice.value) {
      const response = await updateDevice(editingDevice.value.id as number, deviceData)
      const index = devices.value.findIndex(d => d.id === response.id)
      if (index !== -1) {
        devices.value[index] = convertToDevice(response)
      }
      
      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: t('auditActions.updateDevice'),
        resource: t('auditResources.deviceManagement'),
        detail: `${t('auditActions.updateDevice')}: ${form.value.name}`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'true'
      })
      
      ElMessage.success(t('common.success'))
    } else {
      const response = await createDevice(deviceData)
      devices.value.push(convertToDevice(response))
      
      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: t('auditActions.createDevice'),
        resource: t('auditResources.deviceManagement'),
        detail: `${t('auditActions.createDevice')}: ${form.value.name}`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'true'
      })
      
      ElMessage.success(t('common.success'))
    }
    closeDialog()
  } catch (error) {
    console.error('Failed to save device:', error)
    ElMessage.error(t('common.error'))
  }
}

// 删除影响统计：IP 记录本地可算；连接关系需请求一次（后端无按设备过滤参数）
async function getDeleteImpact(device: Device): Promise<{ ips: number; links: number | null }> {
  const ips = ipAddresses.value.filter(ip => String(ip.deviceId) === String(device.id)).length
  let links: number | null = null
  try {
    const allLinks = await getDeviceLinks(0, 1000)
    links = allLinks.filter(l => l.source_device_id === device.id || l.target_device_id === device.id).length
  } catch {
    links = null
  }
  return { ips, links }
}

const handleDelete = async (device: Device) => {
  const impact = await getDeleteImpact(device)
  let message: string
  if (impact.links === null) {
    message = t('devices.deleteImpactUnknown')
  } else {
    const parts: string[] = []
    if (impact.ips > 0) parts.push(t('devices.deleteImpactIps', { count: impact.ips }))
    if (impact.links > 0) parts.push(t('devices.deleteImpactLinks', { count: impact.links }))
    parts.push(t('devices.deleteImpactGeneral'))
    message = parts.join('；')
  }
  await confirmAndRun({
    message,
    title: t('devices.confirmDelete'),
    confirmText: t('common.confirmDelete'),
    cancelText: t('common.cancel'),
    danger: true,
    action: async () => {
      await deleteDevice(device.id as number)
      devices.value = devices.value.filter(d => d.id !== device.id)

      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: t('auditActions.deleteDevice'),
        resource: t('auditResources.deviceManagement'),
        detail: `${t('auditActions.deleteDevice')}: ${device.name}`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'true'
      })
    },
    successMessage: t('common.success'),
    errorMessage: t('common.error'),
  })
}

// 将后端响应转换为前端Device类型
const convertToDevice = (response: DeviceResponse): Device => ({
  id: response.id,
  name: response.name,
  type: response.type,
  vendor: response.vendor || '',
  model: response.model,
  sn: response.sn,
  assetTag: response.asset_tag || '',
  siteId: response.site_id,
  location: response.location || '',
  mgmtIpId: response.mgmt_ip_id,
  rackId: response.rack_id ?? null,
  uPosition: response.u_position ?? null,
  uSize: response.u_size ?? 1,
  status: response.status,
  purchaseDate: response.purchase_date || '',
  warrantyEnd: response.warranty_end || '',
  purchaseAmount: response.purchase_amount || 0,
  owner: response.owner || '',
  note: response.note || '',
})

// 将后端响应转换为前端Site类型
const convertToSite = (response: SiteResponse): Site => ({
  id: response.id,
  name: response.name,
  location: response.location || '',
  city: response.city || '',
  room: response.room || '',
  contact: response.contact || '',
  contactPhone: response.contact_phone || '',
  status: (['online', 'alert', 'offline'].includes(response.status) ? response.status : 'online') as 'online' | 'alert' | 'offline',
  alertCount: response.alert_count,
})

// 加载站点数据
const loadSites = async () => {
  try {
    const response = await getSites()
    sites.value = response.map(convertToSite)
  } catch (error) {
    console.error('Failed to load sites:', error)
  }
}

// 高亮表格行
function tableRowClassName({ row }: { row: Device }) {
  if (highlightedDeviceId.value === row.id) {
    return 'highlighted-row'
  }
  return ''
}

// 加载设备数据
const loadDevices = async () => {
  loading.value = true
  try {
    const response = await getDevices()
    devices.value = response.map(convertToDevice)
    // IP 列表接口是分页的（默认 100 条），扫描入库几千条后设备引用的管理 IP
    // 大概率不在首页，导致下拉回显裸 id、列表/在线状态解析失败——按 id 补拉
    await ensureMgmtIpsLoaded()
  } catch (error) {
    console.error(t('devices.loadFailed'), error)
    ElMessage.error(t('devices.loadFailed'))
  } finally {
    loading.value = false
  }
}

// 补拉被设备引用但不在已加载集合中的管理 IP（一次请求，按 id 精确查询）
async function ensureMgmtIpsLoaded() {
  const known = new Set(ipAddresses.value.map(ip => String(ip.id)))
  const missing = [...new Set(devices.value.map(d => d.mgmtIpId).filter(Boolean))] as number[]
  const need = missing.filter(id => !known.has(String(id)))
  if (need.length === 0) return
  try {
    const extra = await getIPAddressesByIds(need)
    ipAddresses.value.push(...extra)
  } catch (error) {
    console.error('Failed to load referenced management IPs:', error)
  }
}

// 导出设备数据
async function handleExport() {
  if (devices.value.length === 0) {
    ElMessage.warning(t('common.noData'))
    return
  }

  try {
    const response = await api.get('/import-export/devices/export', {
      params: { format: 'excel' },
      responseType: 'blob'
    })

    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `devices_${new Date().toISOString().split('T')[0]}.xlsx`
    link.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success(t('common.success'))
  } catch (error) {
    ElMessage.error(t('common.error'))
  }
}

// 导入相关
const showImportDialog = ref(false)
const importFile = ref<File | null>(null)
const importLoading = ref(false)
const importResult = ref<any>(null)

function handleImportClick() {
  showImportDialog.value = true
  importFile.value = null
  importResult.value = null
}

function handleFileSelect(event: any) {
  const file = event.target.files[0]
  if (file) {
    if (file.name.endsWith('.xlsx') || file.name.endsWith('.xls') || file.name.endsWith('.csv')) {
      importFile.value = file
      importResult.value = null
    } else {
      ElMessage.error(t('validation.pattern'))
      event.target.value = ''
    }
  }
}

async function handleImport() {
  if (!importFile.value) {
    ElMessage.error(t('validation.required'))
    return
  }

  importLoading.value = true
  importResult.value = null

  try {
    const formData = new FormData()
    formData.append('file', importFile.value)

    const response = await api.post('/import-export/devices/import', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })

    importResult.value = response.data

    if (response.data.success_count > 0) {
      ElMessage.success(`${t('common.success')} ${response.data.success_count} ${t('devices.device')}`)
      // 重新加载设备列表
      await loadDevices()
    }

    if (response.data.failed_count > 0) {
      ElMessage.warning(`${response.data.failed_count} ${t('devices.device')} ${t('common.failed')}`)
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || t('common.error'))
  } finally {
    importLoading.value = false
  }
}

function downloadTemplate() {
  window.open('/api/v1/import-export/devices/template', '_blank')
}

onMounted(async () => {
  await loadSites()
  // 先加载 IP 基础列表（分页首页），再加载设备并按 id 补拉被引用的管理 IP；
  // 顺序不能反：getIPAddresses 是整体赋值，会冲掉 ensureMgmtIpsLoaded 的补拉结果
  try {
    ipAddresses.value = await getIPAddresses()
  } catch (error) {
    console.error('Failed to load IP addresses:', error)
  }
  await loadDevices()

  // 如果有 ?id= 参数，高亮并滚动到对应设备
  const targetId = route.query.id
  if (targetId) {
    highlightedDeviceId.value = Number(targetId)
    await nextTick()
    setTimeout(() => {
      const el = document.querySelector('.highlighted-row')
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 500)
  }
})
</script>

<template>
  <div class="devices-page">
    <div class="overview-cards">
      <div class="overview-card">
        <div class="overview-card-label">{{ t('devices.total') }}</div>
        <div class="overview-card-value">{{ devices.length }}</div>
        <div class="overview-card-trend">{{ t('devices.allDevices') }}</div>
      </div>
      <div class="overview-card overview-card-success">
        <div class="overview-card-label">{{ t('devices.online') }}</div>
        <div class="overview-card-value">{{ onlineCount }}</div>
        <div class="overview-card-trend">{{ t('devices.probeBasis') }}</div>
      </div>
      <div class="overview-card overview-card-warning">
        <div class="overview-card-label">{{ t('devices.offline') }}</div>
        <div class="overview-card-value">{{ offlineCount }}</div>
        <div class="overview-card-trend">{{ t('devices.offlineOfTotal', { offline: offlineCount, total: devices.length }) }}</div>
      </div>
      <div class="overview-card overview-card-info">
        <div class="overview-card-label">{{ t('devices.notProbed') }}</div>
        <div class="overview-card-value">{{ notProbedCount }}</div>
        <div class="overview-card-trend">{{ t('devices.notProbedOfTotal', { notProbed: notProbedCount, total: devices.length }) }}</div>
      </div>
      <div
        class="overview-card overview-card-danger"
        :class="{ 'overview-card-clickable': expiredWarrantyDevices.length > 0, 'is-active': warrantyFilter === 'expired' }"
        @click="expiredWarrantyDevices.length > 0 && toggleWarrantyFilter('expired')"
      >
        <div class="overview-card-label">{{ t('devices.warrantyExpired') }}</div>
        <div class="overview-card-value">{{ expiredWarrantyDevices.length }}</div>
        <div class="overview-card-trend">{{ t('devices.expiredCount') }}</div>
      </div>
      <div
        class="overview-card overview-card-blue"
        :class="{ 'overview-card-clickable': expiring90WarrantyDevices.length > 0, 'is-active': warrantyFilter === 'expiring90' }"
        @click="expiring90WarrantyDevices.length > 0 && toggleWarrantyFilter('expiring90')"
      >
        <div class="overview-card-label">{{ t('devices.warrantyExpiring90') }}</div>
        <div class="overview-card-value">{{ expiring90WarrantyDevices.length }}</div>
        <div class="overview-card-trend">{{ t('devices.expiring90Count') }}</div>
      </div>
    </div>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="card-title">
            <el-icon><Monitor /></el-icon>
            {{ t('devices.title') }}
          </div>
          <div class="table-actions">
            <el-popover placement="bottom-end" :width="180" trigger="click">
              <template #reference>
                <el-button plain>
                  <el-icon><Setting /></el-icon>
                  {{ t('devices.columnSettings') }}
                </el-button>
              </template>
              <div class="column-settings">
                <el-checkbox
                  :model-value="COLUMN_DEFS.every(c => columnVisible[c.key])"
                  :indeterminate="COLUMN_DEFS.some(c => columnVisible[c.key]) && !COLUMN_DEFS.every(c => columnVisible[c.key])"
                  @change="(val: boolean) => COLUMN_DEFS.forEach(c => columnVisible[c.key] = val)"
                >
                  {{ t('devices.selectAll') }}
                </el-checkbox>
                <el-checkbox
                  v-for="col in COLUMN_DEFS"
                  :key="col.key"
                  v-model="columnVisible[col.key]"
                >
                  {{ t(col.labelKey) }}
                </el-checkbox>
              </div>
            </el-popover>
            <el-button v-if="!isViewer" plain @click="handleExport">
              <el-icon><Download /></el-icon>
              {{ t('common.export') }}
            </el-button>
            <el-button v-if="!isViewer" plain @click="handleImportClick">
              <el-icon><Upload /></el-icon>
              {{ t('common.import') }}
            </el-button>
            <el-dropdown
              v-if="!isViewer"
              split-button
              type="primary"
              class="create-dropdown"
              @click="openCreateDialog"
              @command="handleCreateCommand"
            >
              {{ t('devices.create') }}
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="quick">
                    <el-icon><MagicStick /></el-icon>
                    {{ t('devices.quickAdd') }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </template>

      <div class="table-filters">
        <el-select
          v-model="filterType"
          :placeholder="t('common.type')"
          clearable
          style="width: 120px"
        >
          <el-option
            v-for="opt in deviceTypeOptions"
            :key="opt.value"
            :label="t(opt.labelKey)"
            :value="opt.value"
          />
        </el-select>
        <el-select
          v-model="selectedSiteId"
          :placeholder="t('sites.filter')"
          clearable
          style="width: 180px"
        >
          <el-option :value="null" :label="t('sites.all')" />
          <el-option
            v-for="site in sites"
            :key="site.id"
            :label="`${site.name} (${siteDeviceCount[site.id] || 0} ${t('devices.units')})`"
            :value="site.id"
          />
        </el-select>
        <el-select
          v-model="filterLifecycle"
          :placeholder="t('devices.filterLifecycle')"
          clearable
          style="width: 120px"
        >
          <el-option value="active" :label="t('devices.active')" />
          <el-option value="inactive" :label="t('devices.inactive')" />
          <el-option value="maintenance" :label="t('devices.maintenance')" />
          <el-option value="scrapped" :label="t('devices.scrapped')" />
        </el-select>
        <el-select
          v-model="warrantyFilter"
          :placeholder="t('devices.filterWarranty')"
          clearable
          style="width: 140px"
        >
          <el-option value="expired" :label="t('warrantyStatus.expired')" />
          <el-option value="expiring90" :label="t('devices.warrantyExpiring90')" />
          <el-option value="notSet" :label="t('warrantyStatus.notSet')" />
          <el-option value="valid" :label="t('warrantyStatus.valid')" />
        </el-select>
        <el-input
          v-model="searchQuery"
          :placeholder="t('devices.searchPlaceholder')"
          prefix-icon="Search"
          clearable
          style="width: 300px"
        />
        <el-button plain class="links-entry" @click="$router.push('/devices/links')">
          <el-icon><Connection /></el-icon>
          {{ t('devices.connections') }}
        </el-button>
      </div>

      <el-table
        :data="pagedDevices"
        style="width: 100%"
        border
        max-height="calc(100vh - 460px)"
        :row-class-name="tableRowClassName"
      >
        <el-table-column v-if="columnVisible.name" prop="name" :label="t('devices.device')" min-width="200">
          <template #default="{ row }">
            <div class="device-cell">
              <div class="device-icon" :style="getDeviceIconStyle(row.type)">
                <i :class="getDeviceIconClass(row.type)" :style="{ fontSize: '18px' }" aria-hidden="true" />
              </div>
              <div class="device-info">
                <el-tooltip :content="row.name" placement="top" :disabled="!row.name">
                  <div class="device-name">{{ row.name }}</div>
                </el-tooltip>
                <div class="device-spec">{{ row.model || '—' }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.type" prop="type" :label="t('common.type')" min-width="100">
          <template #default="{ row }">{{ typeText(row.type) }}</template>
        </el-table-column>
        <el-table-column v-if="columnVisible.vendor" prop="vendor" :label="t('devices.vendor')" min-width="100">
          <template #default="{ row }">
            <el-tag v-if="row.vendor" type="info" size="small">
              {{ vendorOptions.find(v => v.value === row.vendor)?.label || row.vendor }}
            </el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer && columnVisible.sn" prop="sn" :label="t('devices.serial')" min-width="140">
          <template #default="{ row }">
            <code v-if="row.sn" class="serial-number">{{ row.sn }}</code>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.site" prop="siteId" :label="t('devices.siteField')" min-width="120">
          <template #default="{ row }">
            <span class="site-badge">{{ siteName(row.siteId) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer && columnVisible.location" prop="location" :label="t('devices.location')" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.location || '—' }}</template>
        </el-table-column>
        <el-table-column v-if="!isViewer && columnVisible.mgmtIp" prop="mgmtIpId" :label="t('devices.mgmtIp')" width="130" class-name="nowrap-col">
          <template #default="{ row }">
            <code v-if="row.mgmtIpId && getIpAddress(row.mgmtIpId) !== '-'" class="mgmt-ip">{{ getIpAddress(row.mgmtIpId) }}</code>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.online" prop="onlineState" :label="t('devices.onlineState')" width="90" align="center" class-name="nowrap-col">
          <template #default="{ row }">
            <span v-if="getOnlineState(row) === 'online'" class="online-dot online-dot-on"></span>
            <span v-else-if="getOnlineState(row) === 'offline'" class="online-dot online-dot-off"></span>
            <span v-else class="muted">{{ t('devices.notProbed') }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.lifecycle" prop="status" :label="t('devices.lifecycle')" width="110" class-name="nowrap-col">
          <template #default="{ row }">
            <el-tag :type="lifecycleTagType(row.status)" effect="light" size="small">
              {{ lifecycleLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.warranty" prop="warrantyEnd" :label="t('devices.warranty')" width="150" class-name="nowrap-col">
          <template #default="{ row }">
            <div class="warranty-cell">
              <div class="warranty-date">{{ formatDate(row.warrantyEnd) }}</div>
              <div v-if="row.warrantyEnd" class="warranty-status">
                <el-tag :type="getWarrantyDisplay(row.warrantyEnd).type" effect="light" size="small">
                  {{ getWarrantyDisplay(row.warrantyEnd).text }}
                </el-tag>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer" :label="t('common.actions')" width="120" fixed="right" align="center">
          <template #default="{ row }">
            <div class="action-cell">
              <el-button link type="primary" size="small" @click="openEditDialog(row)">
                <el-icon><Edit /></el-icon>
                {{ t('common.edit') }}
              </el-button>
              <el-dropdown trigger="click">
                <el-button link type="primary" size="small">
                  {{ t('common.more') }}
                  <el-icon><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item class="danger-item" @click="handleDelete(row)">
                      <el-icon><Delete /></el-icon>
                      {{ t('common.delete') }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="filteredDevices.length"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          background
        />
      </div>

      <el-empty v-if="filteredDevices.length === 0" :description="t('common.noData')" />
    </el-card>

    <el-dialog
      v-model="showDialog"
      :title="editingDevice ? t('devices.edit') : t('devices.create')"
      width="840px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item>
              <template #label>
                <span>{{ t('devices.name') }}</span>
                <span class="required">*</span>
              </template>
              <el-input v-model="form.name" :placeholder="t('devices.namePlaceholder')" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('devices.type')">
              <el-select v-model="form.type" style="width: 100%">
                <el-option
                  v-for="opt in deviceTypeOptions"
                  :key="opt.value"
                  :label="t(opt.labelKey)"
                  :value="opt.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('devices.vendor')">
              <el-select v-model="form.vendor" style="width: 100%" :placeholder="t('devices.vendorPlaceholder')">
                <el-option v-for="vendor in vendorOptions" :key="vendor.value" :label="vendor.label" :value="vendor.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('devices.model')">
              <el-input v-model="form.model" :placeholder="t('devices.modelPlaceholder')" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('devices.serial')">
              <el-input v-model="form.sn" :placeholder="t('devices.serialPlaceholder')" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('devices.siteField')">
              <el-select v-model="form.siteId" style="width: 100%" :placeholder="t('sites.select')">
                <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('devices.assetTag')">
              <el-input v-model="form.assetTag" :placeholder="t('devices.assetTagPlaceholder')" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('devices.location')">
              <el-input v-model="form.location" :placeholder="t('devices.locationPlaceholder')" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('devices.mgmtIp')">
              <div class="mgmt-ip-input-wrapper">
                <el-input 
                  v-model="form.mgmtIpAddress" 
                  :placeholder="t('devices.mgmtIpPlaceholder')"
                  style="width: 100%"
                  @input="form.mgmtIpId = null"
                />
                <el-select 
                  v-model="form.mgmtIpId" 
                  style="width: 100%; margin-top: 8px" 
                  :placeholder="t('devices.selectIp')"
                  @change="form.mgmtIpAddress = getIpAddress(form.mgmtIpId) || ''"
                >
                  <el-option v-for="ip in ipAddresses" :key="ip.id" :label="ip.address" :value="ip.id" />
                </el-select>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('devices.lifecycle')">
              <el-select v-model="form.status" style="width: 100%">
                <!-- 选中回显取 label 属性（插槽文本不参与回显），必须用 :label -->
                <el-option :label="t('devices.active')" value="active" />
                <el-option :label="t('devices.inactive')" value="inactive" />
                <el-option :label="t('devices.maintenance')" value="maintenance" />
                <el-option :label="t('devices.scrapped')" value="scrapped" />
                <!-- 测试数据混有探测/告警状态，保留兼容选项 -->
                <el-option :label="t('devices.alert')" value="alert" />
                <el-option :label="t('devices.onlineState')" value="online" />
                <el-option :label="t('devices.offline')" value="offline" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('devices.owner')">
              <el-input v-model="form.owner" :placeholder="t('devices.ownerPlaceholder')" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item :label="t('devices.purchaseDate')">
              <el-date-picker v-model="form.purchaseDate" type="date" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="t('devices.warrantyEnd')">
              <el-date-picker v-model="form.warrantyEnd" type="date" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="t('devices.purchaseAmount')">
              <el-input-number v-model="form.purchaseAmount" style="width: 100%" :min="0" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="24">
            <el-form-item :label="t('devices.note')">
              <el-input v-model="form.note" type="textarea" :rows="3" :placeholder="t('devices.notePlaceholder')" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <template #footer>
        <el-button @click="closeDialog">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleSave">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- 导入设备对话框 -->
    <el-dialog :title="t('devices.import')" v-model="showImportDialog" width="600px">
      <div class="import-content">
        <!-- 说明 -->
        <el-alert
          :title="t('devices.importGuide')"
          type="info"
          :closable="false"
          style="margin-bottom: 20px;"
        >
          <template #default>
            <p>{{ t('devices.importStep1') }}</p>
            <p>{{ t('devices.importStep2') }}</p>
            <p>{{ t('devices.importStep3') }}</p>
          </template>
        </el-alert>

        <!-- 下载模板按钮 -->
        <div style="margin-bottom: 20px;">
          <el-button type="primary" plain @click="downloadTemplate">
            <el-icon><Download /></el-icon>
            {{ t('devices.downloadTemplate') }}
          </el-button>
        </div>

        <!-- 文件上传 -->
        <div class="import-upload">
          <input
            type="file"
            class="import-file-input"
            accept=".xlsx,.xls,.csv"
            @change="handleFileSelect"
            hidden
          />
          <el-button type="info" @click="($el.querySelector('.import-file-input') as HTMLInputElement).click()">
            <el-icon><Upload /></el-icon>
            {{ t('devices.selectFile') }}
          </el-button>
          <span v-if="importFile" class="import-file-name">{{ importFile.name }}</span>
        </div>

        <!-- 导入结果 -->
        <div v-if="importResult" style="margin-top: 20px;">
          <el-divider />
          <h4>{{ t('devices.importResult') }}</h4>
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="t('devices.successCount')">
              <el-tag type="success">{{ importResult.success_count }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item :label="t('devices.failedCount')">
              <el-tag type="danger">{{ importResult.failed_count }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <div v-if="importResult.errors && importResult.errors.length > 0" style="margin-top: 16px;">
            <h5>{{ t('devices.errorDetails') }}</h5>
            <el-alert
              v-for="(error, index) in importResult.errors"
              :key="index"
              :title="error"
              type="error"
              :closable="false"
              style="margin-bottom: 8px;"
            />
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="showImportDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleImport" :disabled="!importFile" :loading="importLoading">
          <el-icon><Upload /></el-icon>
          {{ t('devices.startImport') }}
        </el-button>
      </template>
    </el-dialog>
    
    <QuickAddDeviceWizard v-model:visible="showQuickAddWizard" />
  </div>
</template>

<style scoped>
.devices-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.overview-cards {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
}

.overview-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid #8c8c8c;
  transition: all 0.2s ease;
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.overview-card-success { border-left-color: #52c41a; }
.overview-card-warning { border-left-color: #faad14; }
.overview-card-danger { border-left-color: #ff4d4f; }
.overview-card-info { border-left-color: #bfbfbf; }
.overview-card-blue { border-left-color: #1890ff; }

/* 可点击保修卡片（联动筛选，与 IPAM 页一致） */
.overview-card-clickable {
  cursor: pointer;
}

.overview-card-clickable:hover {
  border-left-width: 3px;
  outline: 1px solid #1890ff;
}

.overview-card.is-active {
  outline: 2px solid #1890ff;
  outline-offset: -2px;
}

.overview-card-label {
  font-size: 13px;
  color: #8c8c8c;
  margin-bottom: 6px;
}

.overview-card-value {
  font-size: 28px;
  font-weight: 700;
  color: #262626;
  line-height: 1.2;
  margin-bottom: 4px;
}

.overview-card-trend {
  font-size: 12px;
  color: #bfbfbf;
}

.table-card {
  border-radius: 8px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
}

.import-container {
  padding: 16px 0;
}

.import-info {
  margin-bottom: 20px;
}

.import-info p {
  margin: 8px 0;
  color: #666;
}

.import-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  border-radius: 4px;
  color: #52c41a !important;
}

.import-actions {
  margin-bottom: 16px;
}

.import-divider {
  text-align: center;
  color: #ccc;
  margin: 16px 0;
  position: relative;
}

.import-divider::before,
.import-divider::after {
  content: '';
  position: absolute;
  top: 50%;
  width: 35%;
  height: 1px;
  background: #eee;
}

.import-divider::before {
  left: 0;
}

.import-divider::after {
  right: 0;
}

.import-upload {
  display: flex;
  align-items: center;
  gap: 12px;
}

.import-file-name {
  font-size: 14px;
  color: #666;
}

.card-title .el-icon {
  color: #1890ff;
}

.table-filters {
  margin-bottom: 16px;
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
}

.device-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.device-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.device-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.device-name {
  font-weight: 500;
  color: #262626;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
}

.device-spec {
  font-size: 12px;
  color: #8c8c8c;
}

.serial-number {
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  color: #595959;
  background: #fafafa;
  padding: 3px 8px;
  border-radius: 4px;
}

/* 管理 IP：无底色等宽，不可点击 */
.mgmt-ip {
  font-family: var(--el-font-family-mono, 'SF Mono', 'Monaco', 'Consolas', monospace);
  font-size: 13px;
  color: var(--el-text-color-primary);
  background: none;
  padding: 0;
}

.warranty-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.warranty-date {
  font-size: 13px;
  color: #262626;
}

/* 固定宽列不换行 */
:deep(.nowrap-col .cell) {
  white-space: nowrap;
}

/* 在线状态圆点 */
.online-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.online-dot-on {
  background: #52c41a;
  box-shadow: 0 0 0 3px rgba(82, 196, 26, 0.15);
}

.online-dot-off {
  background: #bfbfbf;
  box-shadow: 0 0 0 3px rgba(191, 191, 191, 0.15);
}

.muted {
  color: #bfbfbf;
}

.site-badge {
  display: inline-block;
  background: #e6f7ff;
  color: #1890ff;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 13px;
}

.required {
  color: #ff4d4f;
}

/* 操作列：编辑 + 更多 */
.action-cell {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

/* 分页 */
.table-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

/* 连接关系入口：筛选行末尾 */
.links-entry {
  margin-left: auto;
}

/* 列设置面板 */
.column-settings {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 320px;
  overflow-y: auto;
}

/* 更多菜单删除项（红色） */
:global(.el-dropdown-menu__item.danger-item) {
  color: var(--el-color-danger);
}
:global(.el-dropdown-menu__item.danger-item .el-icon) {
  color: var(--el-color-danger);
}
:global(.el-dropdown-menu__item.danger-item:hover) {
  color: var(--el-color-danger);
  background-color: var(--el-color-danger-light-9);
}

@media (max-width: 1024px) {
  .overview-cards {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .table-header {
    flex-direction: column;
    align-items: stretch;
  }
  
  .card-title {
    justify-content: center;
  }
  
  .table-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  
  .table-filters {
    flex-direction: column;
    align-items: stretch;
  }
}

/* 高亮从事件时间线跳转过来的设备行 */
.highlighted-row {
  animation: row-highlight 3s ease-out;
}

@keyframes row-highlight {
  0% { background-color: #e6f7ff; }
  100% { background-color: transparent; }
}
</style>
