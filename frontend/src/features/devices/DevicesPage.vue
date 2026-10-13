<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Download, Upload, Edit, Delete, MagicStick } from '@element-plus/icons-vue'
import { formatDate } from '../../lib/utils'
import { applyKeywordFilter } from '../../lib/filters'
import { confirmAndRun } from '../../lib/confirm'
import { useCrudForm } from '../../lib/useCrudForm'
import type { Device, IPAddress, Site } from '../../types/domain'
import { getIPAddresses, createIPAddress } from '../../api/ipam'
import { getDevices, createDevice, updateDevice, deleteDevice, type DeviceResponse } from '../../api/devices'
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

const statusText: Record<string, string> = {
  online: t('devices.online'),
  offline: t('devices.offline'),
  active: t('devices.active'),
  inactive: t('devices.inactive'),
}

const isViewer = computed(() => authStore.isReadOnly())
const highlightedDeviceId = ref<number | null>(null)

// 从后端获取的站点数据
const sites = ref<Site[]>([])

// 获取站点名称
const siteName = (id: number): string => {
  return sites.value.find((site) => site.id === id)?.name || '-'
}

// 从后端获取的设备数据
const devices = ref<Device[]>([])
// 从后端获取的IP地址数据
const ipAddresses = ref<IPAddress[]>([])

const searchQuery = ref('')
const selectedSiteId = ref<number | null>(null)
const showQuickAddWizard = ref(false)
const loading = ref(false)

// 表单弹窗状态（新建/编辑/关闭）
const defaultDeviceForm = () => ({
  name: '',
  type: t('devices.typeSwitch'),
  vendor: '',
  model: '',
  sn: '',
  siteId: null as number | null,
  location: '',
  mgmtIpId: null as number | null,
  mgmtIpAddress: '',
  status: t('devices.statusOnline'),
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

const filteredDevices = computed(() => {
  let result = devices.value
  
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

function getWarrantyStatus(endDate: string) {
  const days = getWarrantyDays(endDate)
  if (days === null) return { type: 'info', text: t('warrantyStatus.notSet') }
  if (days <= 0) return { type: 'danger', text: t('warrantyStatus.expired') }
  if (days <= 90) return { type: 'warning', text: t('warrantyStatus.daysRemaining', { days }) }
  return { type: 'success', text: t('warrantyStatus.daysRemaining', { days }) }
}

function getDeviceTypeConfigKey(type: string | undefined): string {
  const typeMap: Record<string, string> = {
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

function getStatusType(status: string): string {
  switch (status) {
    case 'normal':
    case 'online':
      return 'success'
    case 'warning':
      return 'warning'
    case 'offline':
    case 'critical':
    case 'error':
      return 'danger'
    default:
      return 'info'
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
      
      // 检查IP是否已存在
      const existingIp = ipAddresses.value.find(ip => ip.address === inputIp)
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

const handleDelete = async (device: Device) => {
  await confirmAndRun({
    message: `${t('common.confirm')} ${t('common.delete')} ${t('devices.device')} "${device.name}"?`,
    title: t('common.confirm'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
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
  } catch (error) {
    console.error(t('devices.loadFailed'), error)
    ElMessage.error(t('devices.loadFailed'))
  } finally {
    loading.value = false
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
  loadDevices()
  try {
    ipAddresses.value = await getIPAddresses()
  } catch (error) {
    console.error('Failed to load IP addresses:', error)
  }
  
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
        <div class="overview-card-value">{{ devices.filter(d => d.status === t('devices.statusOnline')).length }}</div>
        <div class="overview-card-trend">{{ t('devices.onlineCount') }}</div>
      </div>
      <div class="overview-card overview-card-warning">
        <div class="overview-card-label">{{ t('devices.offline') }}</div>
        <div class="overview-card-value">{{ devices.filter(d => d.status === t('devices.statusOffline')).length }}</div>
        <div class="overview-card-trend">{{ t('devices.offlineCount') }}</div>
      </div>
      <div class="overview-card overview-card-danger">
        <div class="overview-card-label">{{ t('devices.warrantyExpired') }}</div>
        <div class="overview-card-value">{{ devices.filter(d => getWarrantyDays(d.warrantyEnd) !== null && getWarrantyDays(d.warrantyEnd)! <= 0).length }}</div>
        <div class="overview-card-trend">{{ t('devices.expiredCount') }}</div>
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
            <el-button v-if="!isViewer" type="info" @click="$router.push('/devices/links')">
              <el-icon><Connection /></el-icon>
              {{ t('devices.connections') }}
            </el-button>
            <el-button v-if="!isViewer" type="primary" @click="openCreateDialog">
              <el-icon><Plus /></el-icon>
              {{ t('devices.create') }}
            </el-button>
            <el-button v-if="!isViewer" type="success" @click="showQuickAddWizard = true">
              <el-icon><MagicStick /></el-icon>
              快速添加
            </el-button>
            <el-button v-if="!isViewer" type="success" @click="handleImportClick">
              <el-icon><Upload /></el-icon>
              {{ t('devices.import') }}
            </el-button>
            <el-button v-if="!isViewer" type="info" @click="handleExport">
              <el-icon><Download /></el-icon>
              {{ t('devices.export') }}
            </el-button>
          </div>
        </div>
      </template>

      <div class="table-filters">
        <el-select
          v-model="selectedSiteId"
          :placeholder="t('sites.filter')"
          clearable
          style="width: 180px; margin-right: 16px"
        >
          <el-option :value="null" :label="t('sites.all')" />
          <el-option
            v-for="site in sites"
            :key="site.id"
            :label="`${site.name} (${siteDeviceCount[site.id] || 0} ${t('devices.units')})`"
            :value="site.id"
          />
        </el-select>
        <el-input
          v-model="searchQuery"
          :placeholder="t('devices.searchPlaceholder')"
          prefix-icon="Search"
          clearable
          style="width: 420px"
        />
      </div>

      <el-table
        :data="filteredDevices"
        style="width: 100%"
        stripe
        border
        max-height="calc(100vh - 420px)"
        :row-class-name="tableRowClassName"
      >
        <el-table-column prop="name" :label="t('devices.device')" min-width="200">
          <template #default="{ row }">
            <div class="device-cell">
              <div class="device-icon" :style="getDeviceIconStyle(row.type)">
                <i :class="getDeviceIconClass(row.type)" :style="{ fontSize: '18px' }" aria-hidden="true" />
              </div>
              <div class="device-info">
                <div class="device-name">{{ row.name }}</div>
                <div class="device-spec">{{ row.brand }} {{ row.model }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="type" :label="t('common.type')" min-width="100" />
        <el-table-column prop="vendor" :label="t('devices.vendor')" min-width="100">
          <template #default="{ row }">
            <el-tag v-if="row.vendor" type="info" size="small">
              {{ vendorOptions.find(v => v.value === row.vendor)?.label || row.vendor }}
            </el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer" prop="sn" :label="t('devices.serial')" min-width="140">
          <template #default="{ row }">
            <code class="serial-number">{{ row.sn || '-' }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="siteId" :label="t('sites.title')" min-width="120">
          <template #default="{ row }">
            <span class="site-badge">{{ siteName(row.siteId) || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer" prop="location" :label="t('devices.location')" min-width="120">
          <template #default="{ row }">{{ row.location || '-' }}</template>
        </el-table-column>
        <el-table-column v-if="!isViewer" prop="mgmtIpId" :label="t('devices.mgmtIp')" min-width="120">
          <template #default="{ row }">
            <code v-if="getIpAddress(row.mgmtIpId)" class="mgmt-ip">{{ getIpAddress(row.mgmtIpId) }}</code>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" :label="t('common.status')" min-width="80">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" effect="light" size="small">
              {{ statusText[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="warrantyEnd" :label="t('devices.warranty')" min-width="120">
          <template #default="{ row }">
            <div class="warranty-cell">
              <div class="warranty-date">{{ formatDate(row.warrantyEnd) }}</div>
              <div v-if="row.warrantyEnd" class="warranty-status">
                <el-tag :type="getWarrantyStatus(row.warrantyEnd).type" effect="dark" size="small">
                  {{ getWarrantyStatus(row.warrantyEnd).text }}
                </el-tag>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer" :label="t('common.actions')" width="140" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEditDialog(row)">
              <el-icon><Edit /></el-icon>
              {{ t('common.edit') }}
            </el-button>
            <el-button link type="danger" size="small" @click="handleDelete(row)">
              <el-icon><Delete /></el-icon>
              {{ t('common.delete') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

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
                <el-option :value="t('devices.typeSwitch')">{{ t('devices.typeSwitch') }}</el-option>
                <el-option :value="t('devices.typeRouter')">{{ t('devices.typeRouter') }}</el-option>
                <el-option :value="t('devices.typeFirewall')">{{ t('devices.typeFirewall') }}</el-option>
                <el-option :value="t('devices.typeServer')">{{ t('devices.typeServer') }}</el-option>
                <el-option value="AP">{{ t('devices.typeAP') }}</el-option>
                <el-option :value="t('devices.typeOther')">{{ t('devices.typeOther') }}</el-option>
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
            <el-form-item :label="t('sites.title')">
              <el-select v-model="form.siteId" style="width: 100%" :placeholder="t('sites.select')">
                <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
              </el-select>
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
            <el-form-item :label="t('common.status')">
              <el-select v-model="form.status" style="width: 100%">
                <el-option :value="t('devices.statusOnline')">{{ t('devices.statusOnline') }}</el-option>
                <el-option :value="t('devices.statusOffline')">{{ t('devices.statusOffline') }}</el-option>
                <el-option :value="t('devices.statusMaintenance')">{{ t('devices.statusMaintenance') }}</el-option>
                <el-option :value="t('devices.statusScrapped')">{{ t('devices.statusScrapped') }}</el-option>
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
  grid-template-columns: repeat(4, 1fr);
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
}

.device-name {
  font-weight: 500;
  color: #262626;
  font-size: 14px;
}

.device-spec {
  font-size: 12px;
  color: #8c8c8c;
}

.serial-number,
.mgmt-ip {
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  color: #595959;
  background: #fafafa;
  padding: 3px 8px;
  border-radius: 4px;
}

.mgmt-ip {
  color: #1890ff;
  background: #e6f7ff;
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

@media (max-width: 1200px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .overview-cards {
    grid-template-columns: 1fr;
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
