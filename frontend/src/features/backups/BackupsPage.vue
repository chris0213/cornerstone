<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Monitor, Connection, Box, MapLocation } from '@element-plus/icons-vue'
import { getBackups, getBackupContent, getBackupDiff, updateBackupTag, deleteBackup, restoreBackup, triggerBackup, triggerBatchBackup } from '@/api/backups'
import { formatDateTime } from '@/lib/utils'
import { applyKeywordFilter } from '@/lib/filters'
import { confirmAndRun } from '@/lib/confirm'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
import { getDevices, type DeviceResponse } from '@/api/devices'
import { getSites, type SiteResponse } from '@/api/sites'
import { getIPAddresses } from '@/api/ipam'
import type { IPAddress } from '@/types/domain'
import type { Backup } from '@/types/domain'
import { useAppStore } from '@/store'
import { useAuthStore } from '@/store/auth'

const store = useAppStore()
const authStore = useAuthStore()
const backups = ref<Backup[]>([])
const loading = ref(false)
const showViewDialog = ref(false)
const devices = ref<DeviceResponse[]>([])
const sites = ref<SiteResponse[]>([])
const ipAddresses = ref<IPAddress[]>([])

const deviceMap = computed(() => {
  const map = new Map<number, DeviceResponse>()
  devices.value.forEach(d => map.set(d.id, d))
  return map
})

const siteMap = computed(() => {
  const map = new Map<number, SiteResponse>()
  sites.value.forEach(s => map.set(s.id, s))
  return map
})

const ipMap = computed(() => {
  const map = new Map<number, IPAddress>()
  ipAddresses.value.forEach((ip: IPAddress) => {
    if (typeof ip.id === 'number') {
      map.set(ip.id, ip)
    }
  })
  return map
})

function getIpAddress(ipId?: number | null | undefined) {
  if (!ipId) return '-'
  return ipMap.value.get(ipId)?.address || '-'
}

function getDeviceIcon(type: string) {
  const iconMap: Record<string, any> = {
    'switch': Monitor,
    'router': Connection,
    'firewall': Box,
  }
  return iconMap[type?.toLowerCase()] || Monitor
}

function getTriggerLabel(trigger: string): string {
  const labelMap: Record<string, string> = {
    'manual': t('backups.triggerManual'),
    'scheduled': t('backups.triggerScheduled'),
    'pre_change': t('backups.triggerPreChange'),
  }
  return labelMap[trigger] || trigger
}

function getTriggerType(trigger: string): string {
  const typeMap: Record<string, string> = {
    'manual': 'primary',
    'scheduled': 'info',
    'pre_change': 'warning',
  }
  return typeMap[trigger] || 'default'
}

function getDeviceInfo(deviceId: number) {
  return deviceMap.value.get(deviceId)
}

function getSiteName(siteId?: number | null | undefined) {
  if (!siteId) return '-'
  return siteMap.value.get(siteId)?.name || '-'
}
const showDiffDialog = ref(false)
const viewingBackup = ref<Backup | null>(null)
const viewingContent = ref('')
const selectedBackups = ref<Backup[]>([])
const diffResult = ref<{
  hasChange: boolean
  addedLines: number
  removedLines: number
  diffText: string
  changeSummary: string
} | null>(null)

// ==================== 筛选 / 分页 / 列设置 ====================
const searchQuery = ref('')
const filterStatus = ref('')
const filterTrigger = ref('')
const filterHasChange = ref<boolean | ''>('')
const filterSiteId = ref<number | ''>('')
const filterDeviceId = ref<number | ''>('')

const currentPage = ref(1)
const pageSize = ref(20)
const pageSizes = [10, 20, 50, 100]

// 列设置（localStorage 持久化），耗时列数据大多为空，默认隐藏
const COLUMN_STORAGE_KEY = 'backups_column_settings_v1'
const columnDefs = [
  { key: 'tag', labelKey: 'backups.tagColumn' },
  { key: 'duration', labelKey: 'backups.durationColumn' },
] as const
type ColumnKey = (typeof columnDefs)[number]['key']

const loadColumnSettings = (): Record<ColumnKey, boolean> => {
  const defaults = Object.fromEntries(columnDefs.map(c => [c.key, true])) as Record<ColumnKey, boolean>
  defaults.duration = false
  try {
    const saved = localStorage.getItem(COLUMN_STORAGE_KEY)
    return saved ? { ...defaults, ...JSON.parse(saved) } : defaults
  } catch {
    return defaults
  }
}
const columnVisible = ref<Record<ColumnKey, boolean>>(loadColumnSettings())
const showColumnSettings = ref(false)

watch(columnVisible, (val) => {
  localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(val))
}, { deep: true })

// ==================== 立即备份弹窗 ====================
const showBackupNowDialog = ref(false)
const backupNowSubmitting = ref(false)
const backupNowDeviceIds = ref<number[]>([])

const filteredBackups = computed(() => {
  let result = backups.value

  if (searchQuery.value) {
    result = applyKeywordFilter(result, searchQuery.value, [
      (b) => b.deviceId,
      'operator',
      'tag',
      (b) => getDeviceInfo(b.deviceId)?.name,
      (b) => getDeviceInfo(b.deviceId)?.type,
      (b) => getDeviceInfo(b.deviceId)?.vendor,
      (b) => getDeviceInfo(b.deviceId)?.model,
      (b) => getSiteName(getDeviceInfo(b.deviceId)?.site_id),
      (b) => getIpAddress(getDeviceInfo(b.deviceId)?.mgmt_ip_id ?? undefined),
    ])
  }

  if (filterStatus.value) {
    result = result.filter(b => b.status === filterStatus.value)
  }

  if (filterTrigger.value) {
    result = result.filter(b => b.trigger === filterTrigger.value)
  }

  if (filterHasChange.value !== '') {
    result = result.filter(b => b.hasChange === filterHasChange.value)
  }

  if (filterSiteId.value !== '') {
    result = result.filter(b => getDeviceInfo(b.deviceId)?.site_id === filterSiteId.value)
  }

  if (filterDeviceId.value !== '') {
    result = result.filter(b => b.deviceId === filterDeviceId.value)
  }

  return result
})

// 前端分页
const pagedBackups = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredBackups.value.slice(start, start + pageSize.value)
})

// 筛选条件变化时回到第一页
watch([searchQuery, filterStatus, filterTrigger, filterHasChange, filterSiteId, filterDeviceId], () => {
  currentPage.value = 1
})

function canCompare() {
  return selectedBackups.value.length === 2
}

async function handleCompare() {
  if (!canCompare()) {
    ElMessage.warning(t('backups.compareNeedTwo'))
    return
  }

  const [a, b] = selectedBackups.value.sort((x, y) => x.version - y.version)

  try {
    diffResult.value = await getBackupDiff(parseInt(a.id), parseInt(b.id))
    showDiffDialog.value = true
  } catch (error) {
    console.error('Failed to compare backups:', error)
    ElMessage.error(t('backups.diffLoadFailed'))
  }
}

function handleSelectionChange(rows: Backup[]) {
  selectedBackups.value = rows
}

async function viewBackup(backup: Backup) {
  try {
    viewingBackup.value = backup
    const result = await getBackupContent(parseInt(backup.id))
    viewingContent.value = result.content || t('backups.loadContentEmpty')
    showViewDialog.value = true
  } catch (error) {
    console.error('Failed to load backup content:', error)
    ElMessage.error('加载配置内容失败')
  }
}

function closeViewDialog() {
  showViewDialog.value = false
  viewingBackup.value = null
  viewingContent.value = ''
}

function closeDiffDialog() {
  showDiffDialog.value = false
  diffResult.value = null
}

async function handleDelete(backup: Backup) {
  const deviceName = getDeviceInfo(backup.deviceId)?.name || `#${backup.deviceId}`
  await confirmAndRun({
    message: t('backups.confirmDeleteMessage', { device: deviceName, version: backup.version }),
    title: t('backups.confirmDeleteTitle'),
    confirmText: t('backups.confirmDeleteText'),
    cancelText: t('common.cancel'),
    danger: true,
    action: async () => {
      await deleteBackup(parseInt(backup.id))

      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: '删除备份记录',
        resource: '配置备份',
        detail: `删除设备 ${backup.deviceId} 的备份记录 (v${backup.version})`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'true'
      })

      await loadBackups()
    },
    successMessage: t('backups.deleteSuccessText'),
    errorMessage: t('backups.deleteFailedText'),
  })
}

// 「更多」菜单里的标签编辑：prompt 弹窗替代原行内 popover
async function handleEditTag(backup: Backup) {
  try {
    const { value } = await ElMessageBox.prompt(
      t('backups.tagPrompt'),
      t('backups.tagColumn'),
      {
        inputValue: backup.tag || '',
        confirmButtonText: t('common.save'),
        cancelButtonText: t('common.cancel'),
        inputPattern: /^.{0,50}$/,
        inputErrorMessage: t('backups.tagPrompt'),
      }
    )
    await updateBackupTag(parseInt(backup.id), value.trim())

    // 添加操作日志
    store.addAuditLog({
      user: authStore.user?.username || 'system',
      action: '更新备份标签',
      resource: '配置备份',
      detail: `更新设备 ${backup.deviceId} 备份 (v${backup.version}) 的标签为: ${value.trim()}`,
      ipAddress: null,
      createdAt: new Date().toISOString(),
      success: 'true'
    })

    ElMessage.success(t('backups.tagSaveSuccess'))
    await loadBackups()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('Failed to save tag:', error)
      ElMessage.error(t('backups.tagSaveFailed'))
    }
  }
}

// ==================== 失败重试 / 立即备份 ====================
// 对单台设备重新发起备份（失败行「重试」与「更多」菜单共用）
async function triggerDeviceBackup(backup: Backup) {
  try {
    const result = await triggerBackup(backup.deviceId)
    if (result.success) {
      ElMessage.success(t('backups.retryStarted'))
    } else {
      ElMessage.warning(result.message || t('backups.retryFailed'))
    }
    await loadBackups()
  } catch (error: any) {
    console.error('Failed to trigger backup:', error)
    ElMessage.error(error.response?.data?.detail || t('backups.retryFailed'))
  }
}

function openBackupNowDialog() {
  backupNowDeviceIds.value = []
  showBackupNowDialog.value = true
}

// 立即备份：单台走 /trigger，多台走 /trigger-batch
async function handleBackupNow() {
  if (backupNowDeviceIds.value.length === 0) {
    ElMessage.warning(t('backups.backupNowNoDevice'))
    return
  }
  backupNowSubmitting.value = true
  try {
    if (backupNowDeviceIds.value.length === 1) {
      await triggerBackup(backupNowDeviceIds.value[0])
    } else {
      await triggerBatchBackup(backupNowDeviceIds.value)
    }

    // 添加操作日志
    store.addAuditLog({
      user: authStore.user?.username || 'system',
      action: '立即备份',
      resource: '配置备份',
      detail: `手动触发 ${backupNowDeviceIds.value.length} 台设备的配置备份`,
      ipAddress: null,
      createdAt: new Date().toISOString(),
      success: 'true'
    })

    ElMessage.success(t('backups.backupNowStarted'))
    showBackupNowDialog.value = false
    await loadBackups()
  } catch (error: any) {
    console.error('Failed to trigger backup:', error)
    ElMessage.error(error.response?.data?.detail || t('backups.backupNowFailed'))
  } finally {
    backupNowSubmitting.value = false
  }
}

async function downloadBackup(backup: Backup) {
  if (!hasContent(backup)) {
    ElMessage.warning(t('backups.noContent'))
    return
  }
  // 小配置直接用记录内 content；大配置（content 为空、存文件）走后端 content 接口
  let content = backup.content
  if (!content) {
    try {
      const result = await getBackupContent(parseInt(backup.id))
      content = result.content
    } catch (error) {
      console.error('Failed to load backup content:', error)
      ElMessage.error(t('backups.loadFailed'))
      return
    }
  }
  if (!content) {
    ElMessage.warning(t('backups.loadContentEmpty'))
    return
  }
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  
  // 使用设备名称（如果有）或设备ID，加上版本号生成文件名
  const deviceName = backup.deviceName || `device_${backup.deviceId}`
  const safeDeviceName = deviceName.replace(/[^a-zA-Z0-9_\u4e00-\u9fa5]/g, '_')
  a.download = `${safeDeviceName}_v${backup.version}_${backup.createdAt.replace(/[:\s]/g, '-')}.cfg`
  
  a.click()
  URL.revokeObjectURL(url)
  
  // 添加操作日志
  store.addAuditLog({
    user: authStore.user?.username || 'system',
    action: '下载配置备份',
    resource: '配置备份',
    detail: `下载设备 ${backup.deviceId} 的备份配置文件 (v${backup.version})`,
    ipAddress: null,
    createdAt: new Date().toISOString(),
    success: 'true'
  })
  
  ElMessage.success('配置下载成功')
}

async function handleRestore(backup: Backup) {
  if (!hasContent(backup)) {
    ElMessage.warning(t('backups.noContent'))
    return
  }
  // 还原目标 IP：设备主 IP（后端 restore 接口必填 ip_address）
  const ipAddress = getDeviceIpAddress(backup.deviceId)
  if (!ipAddress) {
    ElMessage.warning(t('backups.restoreNoDeviceIp'))
    return
  }

  try {
    await ElMessageBox.confirm(
      `${t('backups.restoreConfirm')}<br><br>设备: ${getDeviceInfo(backup.deviceId)?.name || backup.deviceId}<br>版本: v${backup.version}<br>${t('backups.backupTime')}: ${formatDateTime(backup.createdAt)}<br><br>⚠️ ${t('backups.restoreWarning')}`,
      t('backups.confirmRestoreTitle'),
      {
        confirmButtonText: t('backups.confirmRestoreText'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
        dangerouslyUseHTMLString: true
      }
    )

    const result = await restoreBackup(parseInt(backup.id), ipAddress)

    if (result.success) {
      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: '还原设备配置',
        resource: '配置备份',
        detail: `还原设备 ${backup.deviceId} 的配置到版本 v${backup.version}`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'true'
      })

      ElMessage.success(t('backups.restoreSuccessText'))
    } else {
      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: '还原设备配置',
        resource: '配置备份',
        detail: `还原设备 ${backup.deviceId} 的配置失败: ${result.message}`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'false'
      })

      ElMessage.error(t('backups.restoreFailedText', { msg: result.message }))
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('Failed to restore backup:', error)

      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: '还原设备配置',
        resource: '配置备份',
        detail: `还原设备 ${backup.deviceId} 的配置失败: ${error.message || '未知错误'}`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'false'
      })

      ElMessage.error(t('backups.restoreErrorText'))
    }
  }
}

// 「更多」下拉命令分发
function handleRowCommand(command: string, row: Backup) {
  if (command === 'retry') {
    triggerDeviceBackup(row)
  } else if (command === 'tag') {
    handleEditTag(row)
  } else if (command === 'restore') {
    handleRestore(row)
  } else if (command === 'delete') {
    handleDelete(row)
  }
}

function downloadDiff() {
  if (!diffResult.value?.diffText) return
  
  const blob = new Blob([diffResult.value.diffText], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `diff_${Date.now()}.diff`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('Diff文件下载成功')
}

async function loadBackups() {
  loading.value = true
  try {
    const [backupList, deviceList, siteList, ipList] = await Promise.all([
      getBackups({ limit: 200 }),
      getDevices(),
      getSites(),
      getIPAddresses()
    ])
    backups.value = backupList
    devices.value = deviceList
    sites.value = siteList
    ipAddresses.value = ipList
  } catch (error) {
    console.error('Failed to load backups:', error)
    ElMessage.error('加载备份列表失败')
  } finally {
    loading.value = false
  }
}

function getStatusType(status: string) {
  const map: Record<string, string> = {
    'success': 'success',
    'failed': 'danger',
    'pending': 'info',
  }
  return map[status] || 'info'
}

function getStatusText(status: string): string {
  const map: Record<string, string> = {
    'success': t('backups.statusSuccess'),
    'failed': t('backups.statusFailed'),
    'pending': t('backups.statusPending'),
  }
  return map[status] || status
}

// 配置内容是否存在：小配置存 content，大配置存 file_path（content 为空但文件在）
function hasContent(backup: Backup): boolean {
  return !!(backup.content || backup.filePath)
}

// 还原目标 IP：设备管理 IP（与备份采集目标一致）
function getDeviceIpAddress(deviceId: number): string | undefined {
  const mgmtIpId = deviceMap.value.get(deviceId)?.mgmt_ip_id
  if (!mgmtIpId) return undefined
  const address = ipMap.value.get(mgmtIpId)?.address
  return address && address !== '-' ? address : undefined
}

// ==================== 卡片统计口径 ====================
// 对账规则：成功 + 失败 + 进行中(pending) = 总记录数
const successCount = computed(() => backups.value.filter(b => b.status === 'success').length)
const failedCount = computed(() => backups.value.filter(b => b.status === 'failed').length)
// 终态记录数（成功+失败），作为成功率分母，排除进行中
const terminalCount = computed(() => successCount.value + failedCount.value)
const successRateText = computed(() => {
  if (terminalCount.value === 0) return '—'
  return `${Math.round((successCount.value / terminalCount.value) * 100)}%`
})
// 近 7 天发现的变更（createdAt 在 7 天内且有变更）
const recent7dChanges = computed(() => {
  const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000
  return backups.value.filter(b => {
    if (!b.hasChange || !b.createdAt) return false
    const ts = new Date(b.createdAt.replace(' ', 'T')).getTime()
    return !Number.isNaN(ts) && ts >= cutoff
  }).length
})

function formatDuration(ms?: number) {
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function parseDiffLine(line: string) {
  if (line.startsWith('+')) return { type: 'added', text: line }
  if (line.startsWith('-')) return { type: 'removed', text: line }
  if (line.startsWith('@@')) return { type: 'header', text: line }
  return { type: 'context', text: line }
}

onMounted(() => {
  loadBackups()
})
</script>

<template>
  <div class="backups-page">
    <div class="overview-cards">
      <div class="overview-card">
        <div class="overview-card-label">{{ t('backups.cardTotal') }}</div>
        <div class="overview-card-value">{{ backups.length }}</div>
        <div class="overview-card-trend">{{ t('backups.allRecords') }}</div>
      </div>
      <div class="overview-card overview-card-success">
        <div class="overview-card-label">{{ t('backups.cardSuccess') }}</div>
        <div class="overview-card-value">{{ successCount }}</div>
        <div class="overview-card-trend">{{ t('backups.subSuccessRate', { rate: successRateText }) }}</div>
      </div>
      <div class="overview-card overview-card-danger">
        <div class="overview-card-label">{{ t('backups.cardFailed') }}</div>
        <div class="overview-card-value">{{ failedCount }}</div>
        <div class="overview-card-trend">{{ t('backups.subFailedHint') }}</div>
      </div>
      <div class="overview-card overview-card-warning">
        <div class="overview-card-label">{{ t('backups.cardRecentChanges') }}</div>
        <div class="overview-card-value">{{ recent7dChanges }}</div>
        <div class="overview-card-trend">{{ t('backups.subChangeHint') }}</div>
      </div>
    </div>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="table-filters-wrapper">
            <div class="table-filters">
              <el-input
                v-model="searchQuery"
                :placeholder="t('backups.searchPlaceholder')"
                prefix-icon="Search"
                clearable
                style="width: 200px"
              />
              <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 110px">
                <el-option value="success" :label="t('backups.statusSuccess')" />
                <el-option value="failed" :label="t('backups.statusFailed')" />
                <el-option value="pending" :label="t('backups.statusPending')" />
              </el-select>
              <el-select v-model="filterTrigger" placeholder="触发方式" clearable style="width: 110px">
                <el-option value="manual" :label="t('backups.triggerManual')" />
                <el-option value="scheduled" :label="t('backups.triggerScheduled')" />
                <el-option value="pre_change" :label="t('backups.triggerPreChange')" />
              </el-select>
              <el-select v-model="filterHasChange" placeholder="变更状态" clearable style="width: 110px">
                <el-option :value="true" :label="t('backups.changeYes')" />
                <el-option :value="false" :label="t('backups.changeNo')" />
              </el-select>
              <el-select v-model="filterSiteId" :placeholder="t('backups.filterSite')" clearable style="width: 120px">
                <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
              </el-select>
              <el-select v-model="filterDeviceId" :placeholder="t('backups.filterDevice')" clearable style="width: 130px">
                <el-option v-for="device in devices" :key="device.id" :label="device.name" :value="device.id" />
              </el-select>
            </div>
          </div>
          <div class="table-actions">
            <el-button v-if="canCompare()" type="warning" @click="handleCompare">
              <el-icon><Connection /></el-icon>
              {{ t('backups.compareSelected') }}
            </el-button>
            <el-popover v-model:visible="showColumnSettings" placement="bottom-end" :width="160" trigger="click">
              <template #reference>
                <el-button plain>
                  <el-icon><Setting /></el-icon> {{ t('circuits.columnSettings') }}
                </el-button>
              </template>
              <div class="column-settings">
                <el-checkbox
                  v-for="col in columnDefs"
                  :key="col.key"
                  v-model="columnVisible[col.key]"
                >
                  {{ t(col.labelKey) }}
                </el-checkbox>
              </div>
            </el-popover>
            <el-button type="primary" @click="openBackupNowDialog">
              <el-icon><Refresh /></el-icon>
              {{ t('backups.backupNow') }}
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="pagedBackups"
        style="width: 100%"
        stripe
        border
        v-loading="loading"
        max-height="calc(100vh - 420px)"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="50" />
        <el-table-column prop="version" :label="t('backups.versionColumn')" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small">v{{ row.version }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="deviceId" :label="t('backups.deviceColumn')" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="device-info">
              <el-icon class="device-icon">
                <component :is="getDeviceIcon(getDeviceInfo(row.deviceId)?.type || '')" />
              </el-icon>
              <div class="device-detail">
                <div class="device-name">{{ getDeviceInfo(row.deviceId)?.name || `#${row.deviceId}` }}</div>
                <el-tooltip
                  :content="`${getDeviceInfo(row.deviceId)?.model || '—'} · ${getDeviceInfo(row.deviceId)?.vendor || '—'}`"
                  placement="top"
                  :show-after="150"
                  :disabled="!getDeviceInfo(row.deviceId)?.model && !getDeviceInfo(row.deviceId)?.vendor"
                >
                  <div class="device-meta nowrap-ellipsis">{{ getDeviceInfo(row.deviceId)?.model || '—' }} · {{ getDeviceInfo(row.deviceId)?.vendor || '—' }}</div>
                </el-tooltip>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="siteId" :label="t('backups.siteColumn')" width="110">
          <template #default="{ row }">
            <div class="site-info nowrap">
              <el-icon class="site-icon" size="14"><MapLocation /></el-icon>
              <span v-if="getSiteName(getDeviceInfo(row.deviceId)?.site_id) !== '-'" class="nowrap-ellipsis">{{ getSiteName(getDeviceInfo(row.deviceId)?.site_id) }}</span>
              <span v-else class="empty-placeholder">—</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="deviceIp" :label="t('backups.mgmtIpColumn')" width="140">
          <template #default="{ row }">
            <span v-if="getIpAddress(getDeviceInfo(row.deviceId)?.mgmt_ip_id) !== '-'" class="ip-text nowrap">{{ getIpAddress(getDeviceInfo(row.deviceId)?.mgmt_ip_id) }}</span>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="createdAt" :label="t('backups.timeColumn')" width="160">
          <template #default="{ row }">
            <span class="nowrap">{{ formatDateTime(row.createdAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="trigger" :label="t('backups.triggerColumn')" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="getTriggerType(row.trigger)" effect="light" size="small">
              {{ getTriggerLabel(row.trigger) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="hasChange" :label="t('backups.changeColumn')" width="100" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.hasChange && row.changeSummary" :content="row.changeSummary" placement="top" :show-after="150">
              <el-tag type="warning" size="small" class="nowrap">{{ t('backups.changeYes') }}</el-tag>
            </el-tooltip>
            <el-tag v-else-if="row.hasChange" type="warning" size="small">{{ t('backups.changeYes') }}</el-tag>
            <el-tag v-else type="info" size="small">{{ t('backups.changeNo') }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column
          v-if="columnVisible.tag"
          prop="tag"
          :label="t('backups.tagColumn')"
          min-width="100"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <span v-if="row.tag" class="tag-text">{{ row.tag }}</span>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.duration" prop="durationMs" :label="t('backups.durationColumn')" width="80" align="center">
          <template #default="{ row }">
            <span v-if="formatDuration(row.durationMs) !== '-'" class="nowrap">{{ formatDuration(row.durationMs) }}</span>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" :label="t('backups.statusColumn')" width="90" align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.status === 'failed' && row.errorMessage"
              :content="`${t('backups.failReason')}：${row.errorMessage}`"
              placement="top"
              :show-after="150"
            >
              <el-tag :type="getStatusType(row.status)" effect="light" size="small" class="status-help">
                {{ getStatusText(row.status) }}
              </el-tag>
            </el-tooltip>
            <el-tag v-else :type="getStatusType(row.status)" effect="light" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('backups.actionColumn')" width="170" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="viewBackup(row)">
              <el-icon><View /></el-icon>
              {{ t('common.view') }}
            </el-button>
            <el-tooltip :content="t('backups.downloadDisabledTip')" :disabled="hasContent(row)" placement="top">
              <span class="action-wrap">
                <el-button link type="primary" size="small" @click="downloadBackup(row)" :disabled="!hasContent(row)">
                  <el-icon><Download /></el-icon>
                  {{ t('common.download') }}
                </el-button>
              </span>
            </el-tooltip>
            <el-dropdown trigger="click" @command="(cmd: string) => handleRowCommand(cmd, row)">
              <span class="more-trigger" @click.stop>
                {{ t('backups.moreActions') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="row.status === 'failed'" command="retry">
                    <el-icon><RefreshRight /></el-icon>
                    {{ t('backups.retryBackup') }}
                  </el-dropdown-item>
                  <el-dropdown-item command="tag">
                    <el-icon><PriceTag /></el-icon>
                    {{ t('backups.tagColumn') }}
                  </el-dropdown-item>
                  <el-dropdown-item command="restore" :disabled="!hasContent(row) || row.status !== 'success'">
                    <el-icon><RefreshLeft /></el-icon>
                    {{ t('backups.restore') }}
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" divided class="danger-item">
                    <el-icon><Delete /></el-icon>
                    <span class="danger-text">{{ t('common.delete') }}</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <span class="table-total">{{ t('backups.totalRecordsText', { total: filteredBackups.length }) }}</span>
        <div class="table-pager">
          <el-select
            :model-value="pageSize"
            class="page-size-select"
            :validate-event="false"
            @change="(val: number) => { pageSize = val; currentPage = 1 }"
          >
            <el-option
              v-for="size in pageSizes"
              :key="size"
              :value="size"
              :label="t('backups.perPage', { size })"
            />
          </el-select>
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="pageSizes"
            :total="filteredBackups.length"
            layout="prev, pager, next, jumper"
            background
          />
        </div>
      </div>

      <el-empty v-if="filteredBackups.length === 0 && !loading" :description="t('backups.noBackupRecords')" />
    </el-card>

    <!-- 查看配置对话框 -->
    <el-dialog
      v-model="showViewDialog"
      title="查看配置"
      width="900px"
      :close-on-click-modal="false"
    >
      <div class="config-view" v-if="viewingBackup">
        <div class="config-meta">
          <div class="meta-item">
            <span class="meta-label">设备：</span>
            <span class="meta-value">设备{{ viewingBackup.deviceId }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">版本：</span>
            <span class="meta-value">v{{ viewingBackup.version }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">时间：</span>
            <span class="meta-value">{{ formatDateTime(viewingBackup.createdAt) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">状态：</span>
            <el-tag :type="getStatusType(viewingBackup.status)" size="small">
              {{ getStatusText(viewingBackup.status) }}
            </el-tag>
          </div>
          <div class="meta-item">
            <span class="meta-label">耗时：</span>
            <span class="meta-value">{{ formatDuration(viewingBackup.durationMs) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">触发方式：</span>
            <el-tag :type="getTriggerType(viewingBackup.trigger)" size="small">
              {{ getTriggerLabel(viewingBackup.trigger) }}
            </el-tag>
          </div>
          <div class="meta-item">
            <span class="meta-label">变更状态：</span>
            <template v-if="viewingBackup.hasChange">
              <el-tag type="warning" size="small">有变更</el-tag>
              <span class="change-summary">{{ viewingBackup.changeSummary }}</span>
            </template>
            <el-tag v-else type="success" size="small">无变更</el-tag>
          </div>
        </div>
        <pre class="config-content">{{ viewingContent }}</pre>
      </div>

      <template #footer>
        <el-button @click="closeViewDialog">关闭</el-button>
        <el-button v-if="viewingBackup?.content" type="primary" @click="downloadBackup(viewingBackup)">
          <el-icon><Download /></el-icon>
          下载配置
        </el-button>
      </template>
    </el-dialog>

    <!-- Diff对比对话框 -->
    <el-dialog
      v-model="showDiffDialog"
      title="配置差异对比"
      width="1000px"
      :close-on-click-modal="false"
    >
      <div class="diff-view" v-if="diffResult">
        <div class="diff-summary">
          <span class="summary-text">{{ diffResult.changeSummary }}</span>
          <el-tag v-if="diffResult.hasChange" type="warning" size="small">有变更</el-tag>
          <el-tag v-else type="success" size="small">无变更</el-tag>
          <el-button type="primary" size="small" @click="downloadDiff">
            <el-icon><Download /></el-icon>
            下载Diff
          </el-button>
        </div>
        <pre class="diff-content" v-if="diffResult.diffText">
          <div
            v-for="(line, index) in diffResult.diffText.split('\n').filter(l => l)"
            :key="index"
            class="diff-line"
            :class="parseDiffLine(line).type"
          >
            <span class="line-prefix">{{ line.startsWith('+') ? '+' : line.startsWith('-') ? '-' : ' ' }}</span>
            <span class="line-text">{{ line }}</span>
          </div>
        </pre>
        <el-empty v-else description="两个版本完全相同，无差异" />
      </div>

      <template #footer>
        <el-button @click="closeDiffDialog">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 立即备份对话框 -->
    <el-dialog
      v-model="showBackupNowDialog"
      :title="t('backups.backupNowTitle')"
      width="520px"
      :close-on-click-modal="false"
    >
      <div class="backup-now-form">
        <div class="backup-now-tip">{{ t('backups.backupNowTip') }}</div>
        <el-select
          v-model="backupNowDeviceIds"
          multiple
          filterable
          :placeholder="t('backups.backupNowDevice')"
          style="width: 100%"
        >
          <el-option
            v-for="device in devices"
            :key="device.id"
            :label="device.name"
            :value="device.id"
          >
            <span>{{ device.name }}</span>
            <span v-if="getIpAddress(device.mgmt_ip_id) !== '-'" class="device-option-ip">{{ getIpAddress(device.mgmt_ip_id) }}</span>
          </el-option>
        </el-select>
      </div>
      <template #footer>
        <el-button @click="showBackupNowDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="backupNowSubmitting" @click="handleBackupNow">
          {{ t('backups.backupNowTitle') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.backups-page {
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
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid var(--el-color-info);
}

.overview-card-success { border-left-color: var(--el-color-success); }
.overview-card-warning { border-left-color: var(--el-color-warning); }
.overview-card-danger { border-left-color: var(--el-color-danger); }

.overview-card-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}

.overview-card-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
}

.overview-card-trend {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
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

.table-filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.table-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.device-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.device-icon {
  color: var(--el-color-primary);
  font-size: 18px;
}

.device-detail {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.device-name {
  font-weight: 500;
  color: var(--el-text-color-primary);
}

/* 设备副行：型号 · 平台，灰色小字一行，超出省略（tooltip 由外层 el-tooltip 提供） */
.device-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.nowrap {
  white-space: nowrap;
}

.nowrap-ellipsis {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 空值占位：灰色 em dash（对齐专线页） */
.empty-placeholder {
  color: var(--el-text-color-placeholder);
}

/* 管理 IP 等宽，便于对齐阅读 */
.ip-text {
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
}

.site-info {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.site-icon {
  color: var(--el-color-success);
  flex-shrink: 0;
}

.tag-text {
  color: var(--el-color-primary);
}

/* 禁用按钮外包一层 span 才能触发 tooltip */
.action-wrap {
  display: inline-flex;
}

/* 失败记录可 hover 查看失败原因 */
.status-help {
  cursor: help;
}

/* 操作列「更多」触发器（el-dropdown 内原生 span） */
.more-trigger {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  color: var(--el-color-primary);
  cursor: pointer;
  outline: none;
}

.more-trigger:hover {
  color: var(--el-color-primary-light-3);
}

/* 下拉菜单危险项标红（scoped 外的 popper 需全局类配合，见 style 后段） */

/* 列设置面板 */
.column-settings {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 分页底栏 */
.table-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
}

.table-total {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.page-size-select {
  width: 110px;
}

.table-pager {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 立即备份弹窗 */
.backup-now-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.backup-now-tip {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.device-option-ip {
  float: right;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
}

.config-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.config-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  padding: 16px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.meta-label {
  font-weight: 600;
  color: var(--el-text-color-regular);
}

.meta-value {
  color: var(--el-text-color-primary);
}

.config-content {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 20px;
  border-radius: 8px;
  overflow-x: auto;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  max-height: 500px;
  overflow-y: auto;
}

.diff-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.diff-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.summary-text {
  color: var(--el-text-color-primary);
  font-weight: 500;
}

.diff-content {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.5;
  max-height: 500px;
  overflow-y: auto;
}

.diff-line {
  display: flex;
  padding: 2px 8px;
  margin: 0 -8px;
}

.diff-line.added {
  background: rgba(82, 196, 26, 0.15);
  color: #7cb305;
}

.diff-line.removed {
  background: rgba(255, 77, 79, 0.15);
  color: #ff7875;
}

.diff-line.header {
  color: var(--el-color-primary);
  font-weight: 600;
}

.line-prefix {
  width: 20px;
  text-align: center;
  flex-shrink: 0;
}

.line-text {
  white-space: pre;
}

@media (max-width: 1200px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>

<!-- 下拉菜单渲染在 body 的 popper 中，scoped 样式作用不到，需非 scoped 块 -->
<style>
.el-dropdown-menu__item.danger-item .danger-text,
.el-dropdown-menu__item.danger-item .el-icon {
  color: var(--el-color-danger);
}

.el-dropdown-menu__item.danger-item:not(.is-disabled):hover {
  background-color: var(--el-color-danger-light-9);
}

.el-dropdown-menu__item.danger-item:not(.is-disabled):hover .danger-text,
.el-dropdown-menu__item.danger-item:not(.is-disabled):hover .el-icon {
  color: var(--el-color-danger);
}
</style>
