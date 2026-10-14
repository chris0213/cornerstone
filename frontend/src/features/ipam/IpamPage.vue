<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElEmpty } from 'element-plus'
import { Search as SearchIcon, User, Edit, Plus, Delete, Connection, Download, Upload } from '@element-plus/icons-vue'
import api from '../../api/axios'
import { confirmAndRun } from '../../lib/confirm'
import type { Prefix, IPAddress } from '../../types/domain'
import IpMatrix from './components/IpMatrix.vue'
import ScanProgress from './components/ScanProgress.vue'
import { getPrefixes, createPrefix, updatePrefix, deletePrefix, getIPAddresses, createIPAddress, updateIPAddress, deleteIPAddress, scanPrefix, getNextAvailableIP } from '@/api/ipam'
import { getSites } from '../../api/sites'
import { getDevices } from '../../api/devices'
import { getVlans } from '../../api/vlans'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()

// 从后端API获取的数据
const sites = ref<any[]>([])
const devices = ref<any[]>([])
const vlans = ref<any[]>([])

function siteName(siteId: number | null | undefined): string {
  if (!siteId) return '-'
  return sites.value.find(s => s.id === siteId)?.name || '-'
}

function deviceName(deviceId: number | null | undefined): string {
  if (!deviceId) return '-'
  return devices.value.find(d => d.id === deviceId)?.name || '-'
}

function getPrefixNetwork(prefixId: string | number): string {
  return prefixes.value.find(p => String(p.id) === String(prefixId))?.network || '-'
}

// 使用本地状态存储从后端获取的数据
const prefixes = ref<Prefix[]>([])
const ipAddresses = ref<IPAddress[]>([])

// 从后端加载数据
const loadData = async () => {
  try {
    const [prefixData, ipData, sitesData, devicesData, vlansData] = await Promise.all([
      getPrefixes(),
      getIPAddresses(),
      getSites(),
      getDevices(),
      getVlans()
    ])
    prefixes.value = prefixData
    ipAddresses.value = ipData
    sites.value = sitesData
    devices.value = devicesData
    vlans.value = vlansData
    console.log('Data loaded from backend')
  } catch (error) {
    console.error('Failed to load data:', error)
    ElMessage.error(t('ipam.loadDataFailed'))
  }
}

onMounted(() => {
  loadData()
})

const activeTab = ref('prefixes')
const searchPrefixQuery = ref('')
const searchIPQuery = ref('')
const selectedSiteFilter = ref<number | null>(null)
const showPrefixDialog = ref(false)
const showIPDialog = ref(false)
const showImportDialog = ref(false)
const showPrefixImportDialog = ref(false)
const importLoading = ref(false)
const prefixImportLoading = ref(false)
const importFile = ref<File | null>(null)
const prefixImportFile = ref<File | null>(null)
const importResult = ref<any>(null)
const prefixImportResult = ref<any>(null)
const editingPrefix = ref<Prefix | null>(null)
const editingIP = ref<IPAddress | null>(null)
const selectedPrefixId = ref<string | null>(null)
const showScanDialog = ref(false)
const scanTaskId = ref('')
const scanNetwork = ref('')

const prefixForm = ref<Partial<Prefix>>({
  aggregateId: null,
  network: '',
  siteId: null,
  vlan: '',
  usage: '',
  customScanPorts: '',
  autoScanEnabled: false,
  scanCron: '0 */6 * * *',
})

const ipForm = ref<{
  address: string
  prefixId: string
  deviceId: string
  usage: string
  owner: string
  status: string
  expireAt?: string
}>({
  address: '',
  prefixId: '',
  deviceId: '',
  usage: '',
  owner: '',
  status: '已分配',
})

const currentPrefixInfo = ref<{
  total_ips: number
  used_count: number
  available_count: number
  usage_rate: number
} | null>(null)

// 选中子网的IP列表
const selectedPrefixIPs = computed(() => {
  if (!selectedPrefixId.value) return []
  const pid = Number(selectedPrefixId.value)
  return ipAddresses.value.filter(ip => Number(ip.prefixId) === pid)
})

// 选中的子网信息
const selectedPrefix = computed(() => {
  if (!selectedPrefixId.value) return null
  return prefixes.value.find(p => String(p.id) === String(selectedPrefixId.value))
})

// 触发扫描
const handleScanPrefix = async (prefixId: string | number, network: string) => {
  try {
    const data = await scanPrefix(Number(prefixId))

    if (data.task_id) {
      scanTaskId.value = data.task_id
      scanNetwork.value = network
      // 自动选中被扫描的 prefix，扫完后用户自然能在下方看到 IP 矩阵
      selectedPrefixId.value = String(prefixId)
      showScanDialog.value = true
      ElMessage.success(t('ipam.scanStarted'))
    } else {
      ElMessage.error(t('ipam.scanStartFailed') + ': ' + (data.message || t('ipam.noTaskId')))
    }
  } catch (err: any) {
    console.error('启动扫描失败:', err)
    const detail = err?.response?.data?.detail || err?.message || t('ipam.scanStartError')
    ElMessage.error(t('ipam.scanStartFailed') + ': ' + detail)
  }
}

// 扫描完成回调
const handleScanCompleted = () => {
  showScanDialog.value = false
  // 刷新IP数据
  loadData()
  ElMessage.success(t('ipam.scanCompleted'))
}

// {{ t('common.close') }}扫描对话框
const closeScanDialog = () => {
  showScanDialog.value = false
  scanTaskId.value = ''
}

// 处理IP分配
const handleQuickAssign = (ipAddress: string) => {
  if (!selectedPrefixId.value) return
  ipForm.value = {
    address: ipAddress,
    prefixId: selectedPrefixId.value,
    deviceId: '',
    usage: '',
    owner: '',
    status: '已分配',
    expireAt: '',
  }
  showIPDialog.value = true
}

// 处理查看IP详情
const handleViewIP = (ip: IPAddress) => {
  openEditIPDialog(ip)
}

const filteredPrefixes = computed(() => {
  let result = prefixes.value
  
  if (selectedSiteFilter.value !== null) {
    result = result.filter(p => p.siteId === selectedSiteFilter.value)
  }
  
  if (!searchPrefixQuery.value) return result
  return result.filter(p => 
    p.network.toLowerCase().includes(searchPrefixQuery.value.toLowerCase()) ||
    p.usage.toLowerCase().includes(searchPrefixQuery.value.toLowerCase()) ||
    siteName(p.siteId).toLowerCase().includes(searchPrefixQuery.value.toLowerCase()) ||
    (p.vlan && p.vlan.toLowerCase().includes(searchPrefixQuery.value.toLowerCase()))
  )
})

const filteredIPs = computed(() => {
  if (!searchIPQuery.value) return ipAddresses.value
  return ipAddresses.value.filter(ip => 
    ip.address.toLowerCase().includes(searchIPQuery.value.toLowerCase()) ||
    ip.usage.toLowerCase().includes(searchIPQuery.value.toLowerCase()) ||
    ip.owner.toLowerCase().includes(searchIPQuery.value.toLowerCase()) ||
    deviceName(ip.deviceId).toLowerCase().includes(searchIPQuery.value.toLowerCase())
  )
})

function getIPCount(prefixId: string | number) {
  return ipAddresses.value.filter((ip) => String(ip.prefixId) === String(prefixId)).length
}

function getUsagePercent(prefixId: string) {
  return Math.round((getIPCount(prefixId) / 254) * 100)
}

function getStatusText(status: string): string {
  const statusMap: Record<string, string> = {
    'assigned': '已分配',
    'reserved': '预留',
    'available': '未分配',
    '已分配': '已分配',
    '预留': '预留',
    '未分配': '未分配',
    'active': '已分配'
  }
  return statusMap[status] || status
}

function getStatusType(status: string): string {
  const statusTypeMap: Record<string, string> = {
    'assigned': 'success',
    'reserved': 'warning',
    'available': 'info',
    '已分配': 'success',
    '预留': 'warning',
    '未分配': 'info',
    'active': 'success'
  }
  return statusTypeMap[status] || 'info'
}

function resetPrefixForm() {
  prefixForm.value = {
    aggregateId: null,
    network: '',
    siteId: null,
    vlan: '',
    usage: '',
    customScanPorts: '',
    autoScanEnabled: false,
    scanCron: '0 */6 * * *',
  }
  editingPrefix.value = null
}

function resetIPForm() {
  ipForm.value = {
    address: '',
    prefixId: '',
    deviceId: '',
    usage: '',
    owner: '',
    status: '已分配',
  }
  editingIP.value = null
  currentPrefixInfo.value = null
}

async function loadPrefixInfo(prefixId: number) {
  try {
    const result = await getNextAvailableIP(prefixId)
    if (result.code === 0 && result.data) {
      currentPrefixInfo.value = result.data
      ipForm.value.address = result.data.ip_address
    } else {
      currentPrefixInfo.value = null
    }
  } catch (error) {
    console.error('Failed to load prefix info:', error)
    currentPrefixInfo.value = null
  }
}

function handleEditPrefix(prefix: Prefix) {
  editingPrefix.value = prefix
  prefixForm.value = {
    aggregateId: prefix.aggregateId || null,
    network: prefix.network,
    siteId: prefix.siteId,
    vlan: prefix.vlan,
    usage: prefix.usage,
    customScanPorts: prefix.customScanPorts || '',
    autoScanEnabled: !!prefix.autoScanEnabled,
    scanCron: prefix.scanCron || '0 */6 * * *',
  }
  showPrefixDialog.value = true
}

function openCreatePrefixDialog() {
  resetPrefixForm()
  showPrefixDialog.value = true
}

function closePrefixDialog() {
  showPrefixDialog.value = false
  resetPrefixForm()
}

const handleSavePrefix = async () => {
  if (!prefixForm.value.network || !prefixForm.value.network.trim()) {
    ElMessage.error(t('ipam.prefixRequired'))
    return
  }

  try {
    if (editingPrefix.value) {
      await updatePrefix(editingPrefix.value.id, prefixForm.value)
      const index = prefixes.value.findIndex(p => p.id === editingPrefix.value?.id)
      if (index !== -1) {
        prefixes.value[index] = { ...prefixes.value[index], ...prefixForm.value } as Prefix
      }
      ElMessage.success(t('ipam.updatePrefixSuccess'))
    } else {
      const newPrefix = await createPrefix({
        aggregateId: prefixForm.value.aggregateId || null,
        network: prefixForm.value.network || '',
        siteId: prefixForm.value.siteId || null,
        vlan: prefixForm.value.vlan || '',
        usage: prefixForm.value.usage || '',
        customScanPorts: prefixForm.value.customScanPorts || null,
        autoScanEnabled: !!prefixForm.value.autoScanEnabled,
        scanCron: prefixForm.value.scanCron || '0 */6 * * *',
      })
      prefixes.value.push(newPrefix)
      ElMessage.success(t('ipam.createPrefixSuccess'))
    }
    closePrefixDialog()
  } catch (error) {
    console.error('Failed to save prefix:', error)
    ElMessage.error(t('ipam.savePrefixFailed'))
  }
}

const handleDeletePrefix = async (prefix: Prefix) => {
  await confirmAndRun({
    message: `确定要删除子网「${prefix.network}」吗？此操作不可撤销。`,
    title: t('common.confirm'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    action: async () => {
      await deletePrefix(prefix.id)
      const index = prefixes.value.findIndex(p => p.id === prefix.id)
      if (index !== -1) {
        prefixes.value.splice(index, 1)
      }
    },
    successMessage: t('ipam.deletePrefixSuccess'),
    errorMessage: t('ipam.deletePrefixFailed'),
  })
}

function openCreateIPDialog() {
  resetIPForm()
  showIPDialog.value = true
}

function openEditIPDialog(ip: IPAddress) {
  editingIP.value = ip
  ipForm.value = {
    address: ip.address,
    prefixId: String(ip.prefixId || ''),
    deviceId: String(ip.deviceId || ''),
    usage: ip.usage,
    owner: ip.owner,
    status: ip.status,
    expireAt: ip.expireAt,
  }
  showIPDialog.value = true
}

// ==================== {{ t('common.import') }}导出 ====================

async function handleExportPrefixes() {
  try {
    const response = await api.get('/import-export/prefixes/export', {
      params: { format: 'excel' },
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `${t('ipam.prefixExportFilePrefix')}_${new Date().toLocaleDateString(locale?.value || 'zh-CN').replace(/\//g, '-')}.xlsx`
    link.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('子网导出成功')
  } catch (error) {
    ElMessage.error('子网导出失败')
  }
}

async function handleDownloadPrefixTemplate() {
  try {
    const response = await api.get('/import-export/prefixes/template', {
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `${t('ipam.prefixImportTemplate')}`
    link.click()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error('模板下载失败')
  }
}

function handlePrefixImportFileChange(file: any) {
  prefixImportFile.value = file.raw || file
  prefixImportResult.value = null
}

async function handleImportPrefixes() {
  if (!prefixImportFile.value) {
    ElMessage.error('请先选择文件')
    return
  }
  prefixImportLoading.value = true
  prefixImportResult.value = null
  try {
    const formData = new FormData()
    formData.append('file', prefixImportFile.value)
    const response = await api.post('/import-export/prefixes/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    prefixImportResult.value = response.data
    if (response.data.success_count > 0) {
      ElMessage.success(t('ipam.prefixImportSuccess', { count: response.data.success_count }))
      await loadData()
    }
    if (response.data.failed_count > 0) {
      ElMessage.warning(t('ipam.prefixImportFailed', { count: response.data.failed_count }))
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || t('ipam.importFailed'))
  } finally {
    prefixImportLoading.value = false
  }
}

async function handleExportIPs() {
  try {
    const response = await api.get('/import-export/ip-addresses/export', {
      params: { format: 'excel' },
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `${t('ipam.ipExportFilePrefix')}_${new Date().toLocaleDateString(locale?.value || 'zh-CN').replace(/\//g, '-')}.xlsx`
    link.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('IP导出成功')
  } catch (error) {
    ElMessage.error('IP导出失败')
  }
}

async function handleDownloadIPTemplate() {
  try {
    const response = await api.get('/import-export/ip-addresses/template', {
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `${t('ipam.ipImportTemplate')}`
    link.click()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error('模板下载失败')
  }
}

function handleImportFileChange(file: any) {
  importFile.value = file.raw || file
  importResult.value = null
}

async function handleImportIPs() {
  if (!importFile.value) {
    ElMessage.error('请先选择文件')
    return
  }
  importLoading.value = true
  importResult.value = null
  try {
    const formData = new FormData()
    formData.append('file', importFile.value)
    const response = await api.post('/import-export/ip-addresses/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    importResult.value = response.data
    if (response.data.success_count > 0) {
      ElMessage.success(`成功导入 ${response.data.success_count} 条IP`)
      await loadData()
    }
    if (response.data.failed_count > 0) {
      ElMessage.warning(`${response.data.failed_count} 条IP导入失败`)
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '导入失败')
  } finally {
    importLoading.value = false
  }
}

function closeIPDialog() {
  showIPDialog.value = false
  resetIPForm()
}

const handleSaveIP = async () => {
  if (!ipForm.value.address.trim()) {
    ElMessage.error('请输入 IP 地址')
    return
  }

  try {
    if (editingIP.value) {
      const response = await updateIPAddress(editingIP.value.id, {
        ...ipForm.value,
        prefixId: ipForm.value.prefixId ? Number(ipForm.value.prefixId) : null,
        deviceId: ipForm.value.deviceId ? Number(ipForm.value.deviceId) : null,
      })
      const index = ipAddresses.value.findIndex(ip => ip.id === editingIP.value?.id)
      if (index !== -1) {
        ipAddresses.value[index] = response
      }
      ElMessage.success('IP 更新成功')
    } else {
      const newIP = await createIPAddress({
        ...ipForm.value,
        prefixId: ipForm.value.prefixId ? Number(ipForm.value.prefixId) : null,
        deviceId: ipForm.value.deviceId ? Number(ipForm.value.deviceId) : null,
      })
      ipAddresses.value.push(newIP)
      ElMessage.success('IP 分配成功')
    }
    closeIPDialog()
  } catch (error) {
    console.error('Failed to save IP:', error)
    ElMessage.error('保存IP失败')
  }
}

const handleDeleteIP = async (ip: IPAddress) => {
  await confirmAndRun({
    message: `确定要删除 IP 地址「${ip.address}」吗？此操作不可撤销。`,
    title: '确认删除',
    confirmText: '删除',
    cancelText: '取消',
    action: async () => {
      await deleteIPAddress(ip.id)
      const index = ipAddresses.value.findIndex(ipItem => ipItem.id === ip.id)
      if (index !== -1) {
        ipAddresses.value.splice(index, 1)
      }
    },
    successMessage: 'IP 删除成功',
    errorMessage: '删除IP失败',
  })
}
</script>

<template>
  <div class="ipam-page">
    <div class="overview-cards">
      <div class="overview-card">
        <div class="overview-card-label">{{ t('ipam.prefixCountLabel') }}</div>
        <div class="overview-card-value">{{ prefixes.length }}</div>
        <div class="overview-card-trend">{{ t('ipam.allPrefixes') }}</div>
      </div>
      <div class="overview-card overview-card-blue">
        <div class="overview-card-label">{{ t('ipam.assignedIPsLabel') }}</div>
        <div class="overview-card-value">{{ ipAddresses.length }}</div>
        <div class="overview-card-trend">{{ t('ipam.ipTotal') }}</div>
      </div>
      <div class="overview-card overview-card-warning">
        <div class="overview-card-label">{{ t('ipam.avgUsageLabel') }}</div>
        <div class="overview-card-value">
          {{ prefixes.length > 0 ? Math.round((ipAddresses.length / (prefixes.length * 254)) * 100) : 0 }}%
        </div>
        <div class="overview-card-trend">{{ t('ipam.usageTrend') }}</div>
      </div>
    </div>

    <!-- IP矩阵卡片（选中子网时显示） -->
    <el-card v-if="selectedPrefix" class="matrix-card" shadow="never">
      <template #header>
        <div class="matrix-header">
          <div class="matrix-title">
            <el-icon><Connection /></el-icon>
            {{ selectedPrefix.network }} - {{ t('ipam.ipMatrixTitle') }}
          </div>
          <div class="matrix-actions">
            <el-button 
              type="primary" 
              size="small" 
              @click="handleScanPrefix(selectedPrefix.id, selectedPrefix.network)"
            >
              <el-icon><SearchIcon /></el-icon>
              {{ t('ipam.scanNow') }}
            </el-button>
            <el-button 
              type="default" 
              size="small" 
              @click="selectedPrefixId = null"
            >
              关闭
            </el-button>
          </div>
        </div>
      </template>
      <IpMatrix 
        :prefix-id="Number(selectedPrefixId)" 
        :network="selectedPrefix?.network || ''"
        :ip-list="selectedPrefixIPs"
        @assign="handleQuickAssign"
        @view="handleViewIP"
      />
    </el-card>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <el-tabs v-model="activeTab">
            <el-tab-pane :label="t('ipam.tabPrefixes')" name="prefixes" />
            <el-tab-pane :label="t('ipam.tabIPs')" name="ips" />
          </el-tabs>
          <div class="table-actions">
            <el-button
              v-if="activeTab === 'prefixes'"
              type="warning"
              plain
              @click="showPrefixImportDialog = true"
            >
              <el-icon><Upload /></el-icon>
              导入
            </el-button>
            <el-button
              v-if="activeTab === 'prefixes'"
              type="success"
              plain
              @click="handleExportPrefixes"
            >
              <el-icon><Download /></el-icon>
              导出
            </el-button>
            <el-button
              v-if="activeTab === 'ips'"
              type="success"
              plain
              @click="handleExportIPs"
            >
              <el-icon><Download /></el-icon>
              导出
            </el-button>
            <el-button
              v-if="activeTab === 'ips'"
              type="warning"
              plain
              @click="showImportDialog = true"
            >
              <el-icon><Upload /></el-icon>
              导入
            </el-button>
            <el-button
              v-if="activeTab === 'prefixes'"
              type="primary"
              @click="openCreatePrefixDialog"
            >
              <el-icon><Plus /></el-icon>
              新增子网
            </el-button>
            <el-button
              v-if="activeTab === 'ips'"
              type="primary"
              @click="openCreateIPDialog"
            >
              <el-icon><Plus /></el-icon>
              分配 IP
            </el-button>
          </div>
        </div>
      </template>

      <template v-if="activeTab === 'prefixes'">
        <div class="table-filters">
          <el-select
            v-model="selectedSiteFilter"
            placeholder="按站点筛选"
            clearable
            style="width: 200px; margin-right: 15px"
          >
            <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
          </el-select>
          <el-input
            v-model="searchPrefixQuery"
            :placeholder="t('ipam.searchPrefixesPlaceholder')"
            prefix-icon="Search"
            clearable
            style="width: 360px"
          />
        </div>
        <el-table
          class="ipam-prefix-table"
          :data="filteredPrefixes"
          style="width: 100%"
          stripe
          border
          height="calc(100vh - 420px)"
        >
          <el-table-column prop="siteId" :label="t('ipam.site')" min-width="140">
            <template #default="{ row }">{{ siteName(row.siteId) }}</template>
          </el-table-column>
          <el-table-column prop="network" :label="t('ipam.subnet')" min-width="200">
            <template #default="{ row }">
              <div class="network-cell">
                <div class="network-name">
                  <el-icon><Connection /></el-icon>
                  {{ row.network }}
                </div>
                <div class="usage-bar-wrapper">
                  <div class="usage-bar">
                    <div 
                      class="usage-fill" 
                      :class="{ 'danger': getUsagePercent(row.id) > 80 }"
                      :style="{ width: getUsagePercent(row.id) + '%' }"
                    ></div>
                  </div>
                  <span class="usage-text">{{ getIPCount(row.id) }}/254</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="vlan" :label="t('ipam.vlan')" min-width="100">
            <template #default="{ row }">{{ row.vlan || '-' }}</template>
          </el-table-column>
          <el-table-column prop="usage" :label="t('ipam.usage')" min-width="180">
            <template #default="{ row }">{{ row.usage || '-' }}</template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" width="280" fixed="right" align="center">
            <template #default="{ row }">
              <div class="action-buttons">
                <el-button 
                  link 
                  type="primary" 
                  size="small" 
                  @click="selectedPrefixId = row.id"
                >
                  <el-icon><User /></el-icon>
                  {{ t('common.view') }}
                </el-button>
                <el-button 
                  link 
                  type="warning" 
                  size="small" 
                  @click="handleEditPrefix(row)"
                >
                  <el-icon><Edit /></el-icon>
                  {{ t('common.edit') }}
                </el-button>
                <el-button 
                  link 
                  type="success" 
                  size="small" 
                  @click="handleScanPrefix(row.id, row.network)"
                >
                  <el-icon><SearchIcon /></el-icon>
                  扫描
                </el-button>
                <el-button link type="danger" size="small" @click="handleDeletePrefix(row)">
                  <el-icon><Delete /></el-icon>
                  删除
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else>
        <div class="table-filters">
          <el-input
            v-model="searchIPQuery"
            placeholder="搜索 IP 地址、用途、负责人..."
            prefix-icon="Search"
            clearable
            style="width: 360px"
          />
        </div>
        <el-table
          class="ipam-ip-table"
          :data="filteredIPs"
          style="width: 100%"
          stripe
          border
          height="calc(100vh - 420px)"
        >
          <el-table-column prop="address" label="IP 地址" min-width="160">
            <template #default="{ row }">
              <code class="ip-address">{{ row.address }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="prefixId" label="子网" min-width="160">
            <template #default="{ row }">{{ getPrefixNetwork(row.prefixId) }}</template>
          </el-table-column>
          <el-table-column prop="deviceId" label="设备" min-width="180">
            <template #default="{ row }">{{ deviceName(row.deviceId) || '-' }}</template>
          </el-table-column>
          <el-table-column prop="usage" label="用途" min-width="160">
            <template #default="{ row }">{{ row.usage || '-' }}</template>
          </el-table-column>
          <el-table-column prop="owner" label="负责人" min-width="140">
            <template #default="{ row }">{{ row.owner || '-' }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" min-width="120">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.status)" effect="light">
                {{ getStatusText(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openEditIPDialog(row)">
                <el-icon><Edit /></el-icon>
                编辑
              </el-button>
              <el-button link type="danger" size="small" @click="handleDeleteIP(row)">
                <el-icon><Delete /></el-icon>
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <el-empty v-if="(activeTab === 'prefixes' && filteredPrefixes.length === 0) || (activeTab === 'ips' && filteredIPs.length === 0)" :description="t('common.noData')" />
    </el-card>

    <el-dialog
      v-model="showPrefixDialog"
      :title="editingPrefix ? t('ipam.editPrefixTitle') : t('ipam.newPrefixTitle')"
      width="640px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('ipam.prefix')">
              <el-input v-model="prefixForm.network" :placeholder="t('ipam.prefixPlaceholder')" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="所属站点">
              <el-select v-model="prefixForm.siteId" style="width: 100%" placeholder="请选择站点">
                <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="VLAN">
              <el-select v-model="prefixForm.vlan" style="width: 100%" placeholder="请选择VLAN">
                <el-option v-for="vlan in vlans" :key="vlan.vid" :label="`${vlan.vid} - ${vlan.name || '未命名'}`" :value="vlan.vid.toString()" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="用途">
              <el-input v-model="prefixForm.usage" placeholder="如：办公网" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-divider content-position="left">自动发现扫描</el-divider>
        <el-row :gutter="20">
          <el-col :span="24">
            <el-form-item label="自定义 TCP 端口" label-width="130px">
              <el-input v-model="prefixForm.customScanPorts" placeholder="留空用默认 [22,80,443,8080,445,139,161,3389,5060]；自定义如 22,443,161" />
              <div class="form-tip">跨网段探测主要靠 TCP 端口，ARP 只在同二层有效。禁 ping 段也要能探测到。</div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="启用自动扫描" label-width="130px">
              <el-switch v-model="prefixForm.autoScanEnabled" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="扫描 Cron" label-width="90px" :disabled="!prefixForm.autoScanEnabled">
              <el-input v-model="prefixForm.scanCron" placeholder="如 0 */6 * * *（每6小时）" :disabled="!prefixForm.autoScanEnabled" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <template #footer>
        <el-button @click="closePrefixDialog">取消</el-button>
        <el-button type="primary" @click="handleSavePrefix">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showIPDialog"
      :title="editingIP ? '编辑 IP 地址' : '分配 IP 地址'"
      width="640px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="IP 地址">
              <el-input v-model="ipForm.address" placeholder="如：192.0.2.10" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="所属子网">
              <el-select 
                v-model="ipForm.prefixId" 
                style="width: 100%" 
                placeholder="请选择子网"
                @change="(val: number | string) => val && loadPrefixInfo(Number(val))"
              >
                <el-option v-for="prefix in prefixes" :key="prefix.id" :label="prefix.network" :value="prefix.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        
        <div v-if="currentPrefixInfo && !editingIP" class="prefix-info-bar">
          <el-alert
            type="info"
            :closable="false"
            style="padding: 12px;"
          >
            <div class="prefix-info-row">
              <span>子网使用情况:</span>
              <span class="usage-text">{{ currentPrefixInfo.used_count }}/{{ currentPrefixInfo.total_ips }}</span>
              <span class="usage-percent">({{ currentPrefixInfo.usage_rate }}%)</span>
            </div>
            <div class="usage-progress">
              <div 
                class="usage-bar-fill" 
                :class="{ 'warning': currentPrefixInfo.usage_rate > 80 }"
                :style="{ width: currentPrefixInfo.usage_rate + '%' }"
              ></div>
            </div>
            <div class="prefix-info-row" style="margin-top: 8px;">
              <span>可用IP:</span>
              <span class="available-count">{{ currentPrefixInfo.available_count }}个</span>
              <el-button size="small" type="primary" plain @click="loadPrefixInfo(Number(ipForm.prefixId))">
                重新选择
              </el-button>
            </div>
          </el-alert>
        </div>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="绑定设备">
              <el-select v-model="ipForm.deviceId" style="width: 100%" placeholder="无">
                <el-option v-for="device in devices" :key="device.id" :label="device.name" :value="device.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="ipForm.status" style="width: 100%">
                <el-option value="已分配">已分配</el-option>
                <el-option value="预留">预留</el-option>
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="用途">
              <el-input v-model="ipForm.usage" placeholder="如：服务器" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="负责人">
              <el-input v-model="ipForm.owner" placeholder="如：网络组" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="到期时间（可选）">
          <el-date-picker
            v-model="ipForm.expireAt"
            type="date"
            placeholder="选择到期日期"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="closeIPDialog">取消</el-button>
        <el-button type="primary" @click="handleSaveIP">保存</el-button>
      </template>
    </el-dialog>

    <!-- 扫描进度对话框 -->
    <ScanProgress
      :visible="showScanDialog"
      :network="scanNetwork"
      :task-id="scanTaskId"
      @close="closeScanDialog"
      @completed="handleScanCompleted"
    />

    <!-- 导入子网对话框 -->
    <el-dialog
      v-model="showPrefixImportDialog"
      :title="t('ipam.importPrefixesTitle')"
      width="600px"
      @close="prefixImportFile = null; prefixImportResult = null"
    >
      <el-alert
        title="导入说明"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      >
        <p>1. 请先{{ t('ipam.downloadPrefixTemplate') }}，按照模板格式填写数据</p>
        <p>2. 支持Excel (.xlsx, .xls) 和 CSV 格式</p>
        <p>3. 必填字段不能为空，否则该行数据将导入失败</p>
      </el-alert>

      <el-button
        type="primary"
        plain
        :icon="Download"
        style="margin-bottom: 16px;"
        @click="handleDownloadPrefixTemplate"
      >
        下载导入模板
      </el-button>

      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.xls,.csv"
        :on-change="handlePrefixImportFileChange"
      >
        <el-icon class="el-icon--upload"><Upload /></el-icon>
        <div class="el-upload__text">
          将文件拖到此处，或<em>点击上传</em>
        </div>
      </el-upload>

      <div v-if="prefixImportResult" style="margin-top: 16px;">
        <el-divider />
        <h4>导入结果</h4>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="成功数量">
            <el-tag type="success">{{ prefixImportResult.success_count }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="失败数量">
            <el-tag type="danger">{{ prefixImportResult.failed_count }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="prefixImportResult.errors && prefixImportResult.errors.length > 0" style="margin-top: 16px;">
          <h5>错误详情：</h5>
          <el-alert
            v-for="(error, index) in prefixImportResult.errors"
            :key="index"
            :title="error"
            type="error"
            :closable="false"
            style="margin-bottom: 8px;"
          />
        </div>
      </div>

      <template #footer>
        <el-button @click="showPrefixImportDialog = false">取消</el-button>
        <el-button
          type="primary"
          :loading="prefixImportLoading"
          :disabled="!prefixImportFile"
          @click="handleImportPrefixes"
        >
          开始导入
        </el-button>
      </template>
    </el-dialog>

    <!-- 导入IP对话框 -->
    <el-dialog
      v-model="showImportDialog"
      title="导入IP地址"
      width="600px"
      @close="importFile = null; importResult = null"
    >
      <el-alert
        title="导入说明"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      >
        <p>1. 请先下载导入模板，按照模板格式填写数据</p>
        <p>2. 支持Excel (.xlsx, .xls) 和 CSV 格式</p>
        <p>3. 必填字段不能为空，否则该行数据将导入失败</p>
      </el-alert>

      <el-button
        type="primary"
        plain
        :icon="Download"
        style="margin-bottom: 16px;"
        @click="handleDownloadIPTemplate"
      >
        下载导入模板
      </el-button>

      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.xls,.csv"
        :on-change="handleImportFileChange"
      >
        <el-icon class="el-icon--upload"><Upload /></el-icon>
        <div class="el-upload__text">
          将文件拖到此处，或<em>点击上传</em>
        </div>
      </el-upload>

      <div v-if="importResult" style="margin-top: 16px;">
        <el-divider />
        <h4>导入结果</h4>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="成功数量">
            <el-tag type="success">{{ importResult.success_count }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="失败数量">
            <el-tag type="danger">{{ importResult.failed_count }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="importResult.errors && importResult.errors.length > 0" style="margin-top: 16px;">
          <h5>错误详情：</h5>
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

      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button
          type="primary"
          :loading="importLoading"
          :disabled="!importFile"
          @click="handleImportIPs"
        >
          开始导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ipam-page {
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

.overview-card-blue { border-left-color: #1890ff; }
.overview-card-warning { border-left-color: #faad14; }

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
}

.table-filters {
  margin-bottom: 16px;
}

.network-cell {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.network-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  color: #262626;
}

.network-name .el-icon {
  color: #1890ff;
}

.usage-bar-wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
}

.usage-bar {
  flex: 1;
  height: 8px;
  background: #f0f0f0;
  border-radius: 999px;
  overflow: hidden;
}

.usage-fill {
  height: 100%;
  background: linear-gradient(90deg, #1890ff, #36cfc9);
  border-radius: inherit;
  transition: width 0.3s ease;
}

.usage-fill.danger {
  background: linear-gradient(90deg, #ff4d4f, #faad14);
}

.usage-text {
  font-size: 12px;
  color: #8c8c8c;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
}

.ip-address {
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 14px;
  color: #1890ff;
  background: #e6f7ff;
  padding: 4px 8px;
  border-radius: 4px;
}

.matrix-card {
  margin-bottom: 20px;
}

.matrix-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.matrix-title {
  font-size: 16px;
  font-weight: 600;
  color: #262626;
}

.matrix-actions {
  display: flex;
  gap: 8px;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-buttons .el-button {
  padding: 0 8px;
  margin: 0;
}

@media (max-width: 1200px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

.prefix-info-bar {
  margin-bottom: 16px;
}

.prefix-info-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.usage-text {
  font-weight: 600;
  color: #262626;
}

.usage-percent {
  color: #8c8c8c;
}

.usage-progress {
  height: 8px;
  background: #f0f0f0;
  border-radius: 4px;
  overflow: hidden;
  margin-top: 8px;
}

.usage-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #1890ff, #36cfc9);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.usage-bar-fill.warning {
  background: linear-gradient(90deg, #ff4d4f, #faad14);
}

.available-count {
  color: #67c23a;
  font-weight: 600;
}

.ipam-prefix-table :deep(.cell),
.ipam-ip-table :deep(.cell) {
  line-height: 1.5;
}

.ipam-prefix-table :deep(.el-table__cell),
.ipam-ip-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>
