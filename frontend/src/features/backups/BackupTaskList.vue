<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getBackupTasks, createBackupTask, updateBackupTask, deleteBackupTask, toggleBackupTask, runBackupTaskNow, getBackupTaskHistory, getCredentials } from '@/api/backups'
import { formatDateTime } from '@/lib/utils'
import { confirmAndRun } from '@/lib/confirm'
import { resolveErrorMessage } from '@/lib/apiError'
import { useCrudForm } from '@/lib/useCrudForm'
import { getDevices, type DeviceResponse } from '@/api/devices'
import { getSites, type SiteResponse } from '@/api/sites'
import cronstrue from 'cronstrue'
import 'cronstrue/locales/zh_CN'
import type { BackupTask, Credential, Device, Site } from '@/types/domain'
import { useI18n } from 'vue-i18n'
const { t, locale } = useI18n()

const tasks = ref<BackupTask[]>([])
const credentials = ref<Credential[]>([])
const devices = ref<Device[]>([])
const sites = ref<Site[]>([])
const loading = ref(false)
const showHistoryDialog = ref(false)
const taskHistory = ref<any[]>([])
const historyLoading = ref(false)
const historyTaskName = ref('')
const selectedRows = ref<BackupTask[]>([])
const batchDeleting = ref(false)
const runningTaskIds = ref<number[]>([])
const taskTableRef = ref()

// ==================== 统计卡片 / 搜索 / 筛选 / 前端分页 ====================
type StatFilter = '' | 'enabled' | 'disabled' | 'failed'
const statFilter = ref<StatFilter>('')
const searchQuery = ref('')
const filterStatus = ref<'' | 'enabled' | 'disabled'>('')
const currentPage = ref(1)
const pageSize = ref(20)
const pageSizes = [10, 20, 50, 100]

const totalCount = computed(() => tasks.value.length)
const enabledCount = computed(() => tasks.value.filter(task => task.isEnabled).length)
const disabledCount = computed(() => tasks.value.filter(task => !task.isEnabled).length)
// 近期失败：以上次执行结果为准（failed 或 partial_fail）
const failedCount = computed(() => tasks.value.filter(task => task.lastRunStatus === 'failed' || task.lastRunStatus === 'partial_fail').length)

const statCards = computed(() => [
  { key: '' as StatFilter, label: t('backups.statTotal'), value: totalCount.value, clickable: false },
  { key: 'enabled' as StatFilter, label: t('backups.statEnabled'), value: enabledCount.value, clickable: enabledCount.value > 0 },
  { key: 'disabled' as StatFilter, label: t('backups.statDisabled'), value: disabledCount.value, clickable: disabledCount.value > 0 },
  { key: 'failed' as StatFilter, label: t('backups.statRecentFailed'), value: failedCount.value, clickable: failedCount.value > 0 },
])

function toggleStatFilter(key: StatFilter) {
  if (!key) return
  statFilter.value = statFilter.value === key ? '' : key
  filterStatus.value = statFilter.value === 'enabled' || statFilter.value === 'disabled' ? statFilter.value : ''
  currentPage.value = 1
}

const statFilterLabel = computed(() => {
  const card = statCards.value.find(c => c.key === statFilter.value)
  return card ? card.label : ''
})

const filteredTasks = computed(() => {
  let result = tasks.value
  if (searchQuery.value) {
    const kw = searchQuery.value.toLowerCase()
    result = result.filter(task => task.name.toLowerCase().includes(kw))
  }
  if (statFilter.value === 'failed') {
    result = result.filter(task => task.lastRunStatus === 'failed' || task.lastRunStatus === 'partial_fail')
  } else if (statFilter.value === 'enabled' || statFilter.value === 'disabled') {
    result = result.filter(task => statFilter.value === 'enabled' ? task.isEnabled : !task.isEnabled)
  }
  return result
})

const pagedTasks = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredTasks.value.slice(start, start + pageSize.value)
})

// 用于跟踪是否使用自定义Cron表达式
const useCustomCron = ref(false)

// 表单弹窗状态（新建/编辑/关闭）
const defaultTaskForm = () => ({
  name: '',
  cronExpr: '0 2 * * *',
  customCronExpr: '',
  credentialId: '' as string | number,
  backupScope: 'devices' as 'devices' | 'site',
  deviceIds: [] as number[],
  siteId: '' as string | number,
  vendor: '',
  retentionCount: 30,
  retentionDays: 90,
  notifyOnChange: true,
  notifyOnFail: true,
  isEnabled: true,
})
type TaskForm = ReturnType<typeof defaultTaskForm>

const {
  showDialog,
  editing: editingTask,
  form,
  openCreate: openCreateDialog,
  openEdit: baseOpenEditDialog,
  closeDialog,
} = useCrudForm<BackupTask, TaskForm>({
  createDefaults: defaultTaskForm,
  toForm: (task) => ({
    name: task.name,
    cronExpr: task.cronExpr,
    customCronExpr: '',
    credentialId: task.credentialId,
    backupScope: task.siteId ? 'site' : 'devices',
    deviceIds: task.deviceIds ? JSON.parse(task.deviceIds) : [],
    siteId: task.siteId || '',
    vendor: task.vendor || '',
    retentionCount: task.retentionCount,
    retentionDays: task.retentionDays,
    notifyOnChange: task.notifyOnChange,
    notifyOnFail: task.notifyOnFail,
    isEnabled: task.isEnabled,
  }),
})

// 编辑 scope 为空的存量任务（scope_type = all）：打开弹窗先提示「请先指定设备或站点」
function openEditDialog(task: BackupTask) {
  baseOpenEditDialog(task)
  if (task.scopeType === 'all') {
    ElMessage.warning(t('backups.scopeRequiredPrompt'))
  }
}

// 厂商选项
const vendorOptions = [
  { value: '', label: t('backups.useDeviceVendor') },
  { value: 'cisco_ios', label: 'Cisco IOS' },
  { value: 'cisco_nxos', label: 'Cisco NX-OS' },
  { value: 'huawei_vrp', label: t('backups.huawei') },
  { value: 'h3c', label: 'H3C' },
  { value: 'juniper', label: 'Juniper' },
  { value: 'fortinet', label: 'Fortinet' },
  { value: 'ruijie', label: t('backups.ruijie') },
  { value: 'hillstone', label: t('backups.hillstone') },
  { value: 'aruba', label: 'Aruba' },
]

// 设备多选轻量增强：按站点分组 + 全选/清空 + 按站点快速添加
const deviceOptions = computed(() =>
  [...devices.value].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN')),
)

const deviceGroups = computed(() => {
  const groupName = new Map<number | null, string>()
  for (const site of sites.value) groupName.set(site.id, site.name)
  const unknownSiteLabel = t('backups.siteNotAssigned')
  const groups = new Map<string, typeof deviceOptions.value>()
  for (const d of deviceOptions.value) {
    const label = groupName.get(d.siteId) ?? unknownSiteLabel
    if (!groups.has(label)) groups.set(label, [])
    groups.get(label)!.push(d)
  }
  return [...groups.entries()]
    .map(([label, items]) => ({ label, items }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
})

const selectedSiteForAdd = ref<string | number>('')
const siteOptionsForAdd = computed(() => sites.value.map(s => ({ id: s.id, name: s.name })))

function addDevicesBySite(siteId: string | number) {
  if (!siteId) return
  const ids = devices.value.filter(d => d.siteId === siteId).map(d => d.id)
  const merged = [...new Set([...form.value.deviceIds, ...ids])]
  form.value.deviceIds = merged
  selectedSiteForAdd.value = ''
  ElMessage.success(t('backups.addedDevicesBySite', { count: ids.length }))
}

function selectAllDevices() {
  form.value.deviceIds = deviceOptions.value.map(d => d.id)
}

function clearDevices() {
  form.value.deviceIds = []
}

// 监听cronExpr变化，判断是否选择了自定义
const handleCronChange = (value: string) => {
  if (value === 'custom') {
    useCustomCron.value = true
    // 如果之前有自定义值，恢复它
    if (form.value.customCronExpr) {
      form.value.cronExpr = form.value.customCronExpr
    } else {
      form.value.cronExpr = ''
    }
  } else {
    useCustomCron.value = false
  }
}

// 将后端响应转换为前端Device类型
const convertToDevice = (response: DeviceResponse): Device => ({
  id: response.id,
  name: response.name,
  type: response.type,
  vendor: response.vendor || '',
  model: response.model || '',
  sn: response.sn || '',
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
  alertCount: response.alert_count || 0,
})

// 加载设备数据
async function loadDevices() {
  try {
    const response = await getDevices()
    devices.value = response.map(convertToDevice)
  } catch (error) {
    console.error('Failed to load devices:', error)
  }
}

// 加载站点数据
async function loadSites() {
  try {
    const response = await getSites()
    sites.value = response.map(convertToSite)
  } catch (error) {
    console.error('Failed to load sites:', error)
  }
}

const cronPresets = [
  { value: '0 2 * * *', label: t('backups.cronDaily2am') },
  { value: '0 4 * * *', label: t('backups.cronDaily4am') },
  { value: '0 */6 * * *', label: t('backups.cronEvery6h') },
  { value: '0 2 * * 1', label: t('backups.cronWeeklyMon2am') },
  { value: 'custom', label: t('backups.cronCustom') },
]

// cronstrue 人话文案：zh 环境输出中文，其余输出英文；解析失败回退原始表达式
function getCronDescription(cron: string): string {
  try {
    return cronstrue.toString(cron, {
      locale: locale.value.startsWith('zh') ? 'zh_CN' : 'en',
      use24HourTimeFormat: true,
    })
  } catch {
    return cron
  }
}

async function handleSave() {
  if (!form.value.name) {
    ElMessage.error(t('backups.enterTaskName'))
    return
  }
  if (!form.value.credentialId) {
    ElMessage.error(t('backups.selectCredential'))
    return
  }
  if (form.value.backupScope === 'devices' && form.value.deviceIds.length === 0) {
    ElMessage.error(t('backups.selectDevicesToBackup'))
    return
  }
  if (form.value.backupScope === 'site' && !form.value.siteId) {
    ElMessage.error(t('backups.selectSite'))
    return
  }

  try {
    const data: any = {
      name: form.value.name,
      cron_expr: form.value.cronExpr,
      credential_id: typeof form.value.credentialId === 'string' ? parseInt(form.value.credentialId) : form.value.credentialId,
      retention_count: form.value.retentionCount,
      retention_days: form.value.retentionDays,
      notify_on_change: form.value.notifyOnChange,
      notify_on_fail: form.value.notifyOnFail,
      is_enabled: form.value.isEnabled,
    }

    if (form.value.backupScope === 'devices' && form.value.deviceIds.length > 0) {
      data.device_ids = form.value.deviceIds
    }
    if (form.value.backupScope === 'site' && form.value.siteId) {
      data.site_id = typeof form.value.siteId === 'string' ? parseInt(form.value.siteId) : form.value.siteId
    }
    if (form.value.vendor) {
      data.vendor = form.value.vendor
    }

    if (editingTask.value) {
      await updateBackupTask(parseInt(editingTask.value.id), data)
      ElMessage.success(t('backups.taskUpdated'))
    } else {
      await createBackupTask(data)
      ElMessage.success(t('backups.taskCreated'))
    }
    await loadTasks()
    closeDialog()
  } catch (error) {
    console.error('Failed to save task:', (error as Error)?.message || error)
    ElMessage.error(resolveErrorMessage(error, t('backups.saveFailed')))
  }
}

// 单个删除：二次确认（红色按钮）+ 403 走统一「无权限」文案
async function handleDelete(task: BackupTask) {
  await confirmAndRun({
    message: t('backups.confirmDeleteTaskText', { name: task.name }),
    title: t('backups.confirmDeleteTaskTitle'),
    confirmText: t('backups.confirmDeleteTaskButton'),
    cancelText: t('common.cancel'),
    danger: true,
    action: async () => {
      await deleteBackupTask(parseInt(task.id))
      await loadTasks()
    },
    successMessage: t('backups.taskDeleted'),
    errorMessage: (error) => resolveErrorMessage(error, t('backups.deleteFailed')),
  })
}

// 处理选择变化（全部行可勾选，含启用中的任务）
const handleSelectionChange = (val: BackupTask[]) => {
  selectedRows.value = val
}

// 操作列「更多」下拉命令分发
function handleRowCommand(cmd: string, row: BackupTask) {
  if (cmd === 'edit') openEditDialog(row)
  else if (cmd === 'delete') handleDelete(row)
}

// 批量删除聚合：逐个请求，遇到第一个 403 立即中止并提示「无权限」；
// 结束后按成功/失败数量分别提示。选中项含执行中任务时，确认弹窗先行提示。
async function handleBatchDelete() {
  const rows = selectedRows.value
  if (rows.length === 0) {
    ElMessage.warning(t('backups.selectTasksFirst'))
    return
  }
  const runningCount = rows.filter(row => row.isRunning).length
  let confirmed = false
  try {
    await ElMessageBox.confirm(
      runningCount > 0
        ? `${t('backups.confirmBatchDeleteText', { count: rows.length })}\n${t('backups.confirmBatchDeleteRunning', { count: runningCount })}`
        : t('backups.confirmBatchDeleteText', { count: rows.length }),
      t('backups.confirmBatchDeleteTitle'),
      {
        confirmButtonText: t('backups.confirmBatchDeleteButton'),
        cancelButtonText: t('common.cancel'),
        confirmButtonClass: 'el-button--danger',
        type: 'warning',
      },
    )
    confirmed = true
  } catch {
    confirmed = false
  }
  if (!confirmed) return

  batchDeleting.value = true
  let success = 0
  let failed = 0
  try {
    for (const row of rows) {
      try {
        await deleteBackupTask(parseInt(row.id))
        success += 1
      } catch (error: any) {
        if (error?.response?.status === 403) {
          // 无权限：立即中止剩余请求，整体提示
          ElMessage.error(t('backups.batchDeleteNoPermission'))
          return
        }
        console.error('Batch delete item failed:', error?.message || error)
        failed += 1
      }
    }
    if (failed > 0) {
      ElMessage.warning(t('backups.batchDeletePartial', { success, failed }))
    } else {
      ElMessage.success(t('backups.batchDeleteResult', { success }))
    }
  } finally {
    batchDeleting.value = false
    selectedRows.value = []
    await loadTasks()
  }
}

async function handleToggle(task: BackupTask) {
  try {
    const result = await toggleBackupTask(parseInt(task.id))
    task.isEnabled = result.isEnabled
    ElMessage.success(result.isEnabled ? t('backups.taskEnabled') : t('backups.taskDisabled'))
    await loadTasks()
  } catch (error) {
    console.error('Failed to toggle task:', (error as Error)?.message || error)
    ElMessage.error(resolveErrorMessage(error, t('backups.toggleFailed')))
  }
}

// 立即执行：确认弹窗 → 行级 loading；409（already_running）映射 i18n 文案
async function handleRunNow(task: BackupTask) {
  try {
    await ElMessageBox.confirm(
      t('backups.runNowConfirm', { name: task.name }),
      t('backups.runNow'),
      {
        confirmButtonText: t('backups.runNow'),
        cancelButtonText: t('common.cancel'),
        type: 'info',
      },
    )
  } catch {
    return
  }
  const taskId = parseInt(task.id)
  runningTaskIds.value = [...runningTaskIds.value, taskId]
  try {
    await runBackupTaskNow(taskId)
    ElMessage.success(t('backups.taskStarted'))
  } catch (error) {
    console.error('Failed to run task:', (error as Error)?.message || error)
    ElMessage.error(resolveErrorMessage(error, t('backups.runFailed')))
  } finally {
    runningTaskIds.value = runningTaskIds.value.filter(id => id !== taskId)
  }
}

async function openHistoryDialog(task: BackupTask) {
  historyTaskName.value = task.name
  showHistoryDialog.value = true
  historyLoading.value = true
  try {
    taskHistory.value = await getBackupTaskHistory(parseInt(task.id))
  } catch (error) {
    console.error('Failed to load history:', error)
    ElMessage.error(t('backups.loadHistoryFailed'))
  } finally {
    historyLoading.value = false
  }
}

async function loadTasks() {
  loading.value = true
  try {
    const rawTasks = await getBackupTasks()
    // 把下划线字段名转换成驼峰
    tasks.value = rawTasks.map((task: any) => ({
      ...task,
      lastRunAt: task.last_run_at || task.lastRunAt,
      lastRunStatus: task.last_run_status || task.lastRunStatus,
      credentialId: task.credential_id || task.credentialId,
      credentialName: task.credential_name || task.credentialName,
      siteId: task.site_id || task.siteId,
      siteName: task.site_name || task.siteName,
      deviceCount: task.device_count ?? task.deviceCount ?? 0,
      scopeType: task.scope_type || task.scopeType,
      credentialMissing: task.credential_missing ?? task.credentialMissing ?? false,
      credentialProtocol: task.credential_protocol ?? task.credentialProtocol ?? null,
      deviceMissingIds: task.device_missing_ids || task.deviceMissingIds || [],
      nextRunAt: task.next_run_at ?? task.nextRunAt ?? null,
      isRunning: task.is_running ?? task.isRunning ?? false,
      cronExpr: task.cron_expr || task.cronExpr,
      retentionCount: task.retention_count || task.retentionCount,
      retentionDays: task.retention_days || task.retentionDays,
      notifyOnChange: task.notify_on_change || task.notifyOnChange,
      notifyOnFail: task.notify_on_fail || task.notifyOnFail,
      isEnabled: task.is_enabled || task.isEnabled,
      createdAt: task.created_at || task.createdAt,
    }))
  } catch (error) {
    console.error('Failed to load tasks:', (error as Error)?.message || error)
    ElMessage.error(t('backups.loadTasksFailed'))
  } finally {
    loading.value = false
  }
}

async function loadCredentials() {
  try {
    credentials.value = await getCredentials()
  } catch (error) {
    console.error('Failed to load credentials:', (error as Error)?.message || error)
  }
}

function getStatusType(status?: string) {
  const map: Record<string, string> = {
    'success': 'success',
    'partial_fail': 'warning',
    'failed': 'danger',
  }
  return map[status || ''] || 'info'
}

// 范围列展示信息：devices=按设备(N)；site=站点名(N)；all=全部设备(N)+未指定范围标记
function getScopeInfo(task: BackupTask) {
  if (task.scopeType === 'site') {
    return { label: `${task.siteName || task.siteId || '-'} (${task.deviceCount ?? 0})`, type: 'site' as const }
  }
  if (task.scopeType === 'devices') {
    return { label: `${t('backups.scopeDevices')} (${task.deviceCount ?? 0})`, type: 'devices' as const }
  }
  return { label: `${t('backups.scopeAll')} (${task.deviceCount ?? 0})`, type: 'all' as const }
}

// 设备弹窗数据源（零新请求，复用内存数据 + device_missing_ids）：
// - devices 范围：仅设备 ID + 缺失标记（设备接口不支持按 id 批量查询，已列入需后端配合）
// - site / all 范围：内存中按 site 过滤 / 限量分页展示
const DEVICE_DIALOG_LIMIT = 200
const showDeviceDialog = ref(false)
const deviceDialogTask = ref<BackupTask | null>(null)
const deviceDialogPage = ref(1)
const deviceDialogPageSize = 10

const deviceDialogRows = computed(() => {
  const task = deviceDialogTask.value
  if (!task) return []
  if (task.scopeType === 'devices') {
    return (task.deviceIds ? (JSON.parse(task.deviceIds) as number[]) : []).map(id => ({
      id,
      name: '',
      missing: (task.deviceMissingIds || []).includes(id),
    }))
  }
  if (task.scopeType === 'site' && task.siteId) {
    return devices.value
      .filter(d => d.siteId === task.siteId)
      .map(d => ({ id: d.id, name: d.name, missing: false }))
  }
  return devices.value.slice(0, DEVICE_DIALOG_LIMIT).map(d => ({ id: d.id, name: d.name, missing: false }))
})

const deviceDialogPagedRows = computed(() => {
  const start = (deviceDialogPage.value - 1) * deviceDialogPageSize
  return deviceDialogRows.value.slice(start, start + deviceDialogPageSize)
})

function openDeviceDialog(task: BackupTask) {
  deviceDialogTask.value = task
  deviceDialogPage.value = 1
  showDeviceDialog.value = true
}

onMounted(async () => {
  await loadDevices()
  await loadSites()
  loadTasks()
  loadCredentials()
})
</script>

<template>
  <div class="backup-task-list-page">
    <!-- 统计卡片：enabled/disabled/failed 可点筛选（0 不可点），active 高亮 -->
    <div class="overview-cards">
      <div
        v-for="card in statCards"
        :key="card.key || 'total'"
        class="overview-card"
        :class="[
          card.key === 'enabled' ? 'overview-card-success' : card.key === 'disabled' ? 'overview-card-info' : card.key === 'failed' ? 'overview-card-danger' : '',
          { 'is-active': card.key && statFilter === card.key, 'is-clickable': card.clickable },
        ]"
        @click="card.clickable && toggleStatFilter(card.key)"
      >
        <div class="overview-card-label">
          {{ card.label }}
          <el-tooltip
            v-if="card.key === 'failed'"
            :content="t('backups.statRecentFailedTip')"
            placement="top"
          >
            <el-icon class="stat-tip-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>
        <div class="overview-card-value">{{ card.value }}</div>
      </div>
    </div>

    <!-- 已筛选标签 -->
    <div v-if="statFilter" class="filter-active-bar">
      <el-tag closable type="primary" @close="toggleStatFilter(statFilter)">
        {{ t('backups.filterActive', { label: statFilterLabel }) }}
      </el-tag>
    </div>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="table-filters">
            <el-input
              v-model="searchQuery"
              :placeholder="t('backups.searchTaskPlaceholder')"
              prefix-icon="Search"
              clearable
              style="width: 200px"
              @input="currentPage = 1"
            />
            <el-select v-model="filterStatus" :placeholder="t('backups.filterStatusAll')" clearable style="width: 120px" @change="currentPage = 1">
              <el-option value="enabled" :label="t('backups.filterStatusEnabled')" />
              <el-option value="disabled" :label="t('backups.filterStatusDisabled')" />
            </el-select>
          </div>
          <div class="table-actions">
            <el-button
              v-if="selectedRows.length > 0"
              type="danger"
              :loading="batchDeleting"
              @click="handleBatchDelete"
            >
              <el-icon><Delete /></el-icon>
              {{ t('backups.batchDelete', { count: selectedRows.length }) }}
            </el-button>
            <el-button type="primary" @click="openCreateDialog">
              <el-icon><Plus /></el-icon>
              {{ t('backups.newTask') }}
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        class="backup-task-table"
        ref="taskTableRef"
        :data="pagedTasks"
        style="width: 100%"
        stripe
        border
        v-loading="loading"
        max-height="calc(100vh - 430px)"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="50" />
        <el-table-column prop="name" :label="t('backups.taskName')" min-width="160">
          <template #default="{ row }">
            <div class="task-name">
              <el-icon class="task-icon"><Timer /></el-icon>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('backups.backupScope')" min-width="180">
          <template #default="{ row }">
            <div class="scope-cell">
              <el-tooltip
                v-if="getScopeInfo(row).type === 'all'"
                :content="t('backups.scopeUnspecifiedTip')"
                placement="top"
              >
                <el-tag size="small" type="warning" class="scope-unspectated-tag">{{ t('backups.scopeUnspecified') }}</el-tag>
              </el-tooltip>
              <el-link
                :underline="false"
                type="primary"
                class="scope-link"
                @click="openDeviceDialog(row)"
              >
                {{ getScopeInfo(row).label }}
              </el-link>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="credentialName" :label="t('backups.credentialName')" min-width="130">
          <template #default="{ row }">
            <div class="credential-cell">
              <span>{{ row.credentialName || '-' }}</span>
              <el-tooltip v-if="row.credentialMissing" :content="t('backups.credentialMissingTag')" placement="top">
                <el-tag size="small" type="danger">{{ t('backups.credentialMissingTag') }}</el-tag>
              </el-tooltip>
              <el-tag v-else-if="row.credentialProtocol === 'telnet'" size="small" type="warning" class="telnet-tag">
                {{ t('backups.telnetPlain') }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('backups.cronHuman')" min-width="170">
          <template #default="{ row }">
            <el-tooltip :content="row.cronExpr" placement="top">
              <span class="cron-desc">{{ getCronDescription(row.cronExpr) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column :label="t('backups.nextRunAt')" min-width="150">
          <template #default="{ row }">
            <div v-if="row.isRunning" class="running-cell">
              <el-icon class="is-loading running-icon"><Loading /></el-icon>
              <span class="running-text">{{ t('backups.running') }}</span>
            </div>
            <span v-else-if="row.nextRunAt">{{ formatDateTime(row.nextRunAt) }}</span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="lastRunAt" :label="t('backups.lastRunAt')" min-width="150">
          <template #default="{ row }">
            <span v-if="row.lastRunAt">{{ formatDateTime(row.lastRunAt) }}</span>
            <span v-else class="text-muted">{{ t('backups.neverRun') }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="lastRunStatus" :label="t('backups.lastRunStatus')" min-width="110" align="center">
          <template #default="{ row }">
            <el-tooltip :content="t('backups.lastRunViewHistoryTip')" placement="top">
              <el-tag
                v-if="row.lastRunStatus"
                :type="getStatusType(row.lastRunStatus)"
                size="small"
                class="status-tag"
                @click="openHistoryDialog(row)"
              >
                {{ row.lastRunStatus === 'success' ? t('backups.success') : row.lastRunStatus === 'partial_fail' ? t('backups.partialFail') : t('backups.failed') }}
              </el-tag>
              <span v-else class="text-muted">-</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="isEnabled" :label="t('common.status')" min-width="110" align="center">
          <template #default="{ row }">
            <div class="status-switch-cell">
              <el-switch
                v-model="row.isEnabled"
                :disabled="row.isRunning"
                @change="handleToggle(row)"
                size="small"
              />
              <span class="status-switch-text" :class="row.isEnabled ? 'is-enabled' : 'is-disabled'">
                {{ row.isEnabled ? t('backups.statusEnabledText') : t('backups.statusDisabledText') }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="220" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              :loading="runningTaskIds.includes(parseInt(row.id))"
              @click="handleRunNow(row)"
            >
              {{ t('backups.runNow') }}
            </el-button>
            <el-button link type="primary" size="small" @click="openHistoryDialog(row)">
              <el-icon><Clock /></el-icon>
              {{ t('backups.history') }}
            </el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => handleRowCommand(cmd, row)">
              <span class="more-trigger" @click.stop>
                {{ t('backups.moreMenu') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit">
                    <el-icon><Edit /></el-icon>
                    {{ t('common.edit') }}
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

      <el-empty v-if="tasks.length === 0 && !loading" :description="t('backups.noTasks')" />

      <!-- 表格 footer：共 N 条 + 每页条数 + 分页 -->
      <div v-if="filteredTasks.length > 0" class="table-footer">
        <span class="table-total">{{ t('backups.totalRecordsText', { total: filteredTasks.length }) }}</span>
        <div class="table-pager">
          <el-select
            :model-value="pageSize"
            class="page-size-select"
            :validate-event="false"
            @change="(val: number) => { pageSize = val; currentPage = 1 }"
          >
            <el-option v-for="size in pageSizes" :key="size" :label="`${size} ${t('backups.perPage')}`" :value="size" />
          </el-select>
          <el-pagination
            v-model:current-page="currentPage"
            :page-size="pageSize"
            :total="filteredTasks.length"
            layout="prev, pager, next"
            background
          />
        </div>
      </div>
    </el-card>

    <!-- 新建/编辑任务对话框 -->
    <el-dialog
      v-model="showDialog"
      :title="editingTask ? t('backups.editTask') : t('backups.newTask')"
      width="700px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item :label="t('backups.taskName')" required>
          <el-input v-model="form.name" :placeholder="t('backups.taskNamePlaceholder')" />
        </el-form-item>

        <el-form-item :label="t('backups.credentialName')" required>
          <el-select v-model="form.credentialId" style="width: 100%" :placeholder="t('backups.selectCredential')">
            <el-option v-for="cred in credentials" :key="cred.id" :label="cred.name" :value="cred.id" />
          </el-select>
        </el-form-item>

        <el-form-item :label="t('backups.backupScope')">
          <el-radio-group v-model="form.backupScope" style="width: 100%">
            <el-radio value="devices">{{ t('backups.selectDevices') }}</el-radio>
            <el-radio value="site">{{ t('backups.backupBySite') }}</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="form.backupScope === 'devices'" :label="t('backups.selectDevices')">
          <div class="device-select-block">
            <el-select
              v-model="form.deviceIds"
              style="width: 100%"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="3"
              :placeholder="t('backups.selectDevices')"
            >
              <el-option-group v-for="group in deviceGroups" :key="group.label" :label="group.label">
                <el-option v-for="device in group.items" :key="device.id" :label="device.name" :value="device.id" />
              </el-option-group>
            </el-select>
            <div class="device-select-actions">
              <el-button size="small" @click="selectAllDevices">{{ t('common.selectAll') }}</el-button>
              <el-button size="small" @click="clearDevices">{{ t('common.clear') }}</el-button>
              <el-select
                v-model="selectedSiteForAdd"
                size="small"
                :placeholder="t('backups.addBySite')"
                style="width: 180px; margin-left: auto"
                @change="addDevicesBySite"
              >
                <el-option v-for="s in siteOptionsForAdd" :key="s.id" :label="s.name" :value="s.id" />
              </el-select>
            </div>
            <div class="device-select-count">
              {{ t('backups.selectedDeviceCount', { count: form.deviceIds.length }) }}
            </div>
          </div>
        </el-form-item>

        <el-form-item v-if="form.backupScope === 'site'" :label="t('backups.selectSite')">
          <el-select v-model="form.siteId" style="width: 100%" :placeholder="t('backups.selectSite')">
            <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
          </el-select>
        </el-form-item>

        <el-form-item :label="t('backups.cronExpr')">
          <el-select v-model="form.cronExpr" style="width: 100%" @change="handleCronChange">
            <el-option v-for="preset in cronPresets" :key="preset.value" :label="preset.label" :value="preset.value" />
          </el-select>
        </el-form-item>

        <el-form-item :label="t('backups.vendor')">
          <el-select v-model="form.vendor" style="width: 100%" :placeholder="t('backups.selectVendor')">
            <el-option v-for="vendor in vendorOptions" :key="vendor.value" :label="vendor.label" :value="vendor.value" />
          </el-select>
          <div class="form-tip">{{ t('backups.vendorTip') }}</div>
        </el-form-item>

        <el-form-item v-if="useCustomCron" :label="t('backups.customCron')">
          <el-input 
            v-model="form.cronExpr" 
            placeholder="0 2 * * *" 
            @input="form.customCronExpr = $event"
          />
          <div class="cron-hint">
            {{ t('backups.cronHint') }}
          </div>
        </el-form-item>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="t('backups.retentionCount')">
              <el-input-number v-model="form.retentionCount" :min="1" :max="1000" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('backups.retentionDays')">
              <el-input-number v-model="form.retentionDays" :min="1" :max="3650" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item :label="t('backups.alertSettings')">
          <el-checkbox v-model="form.notifyOnChange">{{ t('backups.notifyOnChange') }}</el-checkbox>
          <el-checkbox v-model="form.notifyOnFail">{{ t('backups.notifyOnFail') }}</el-checkbox>
        </el-form-item>

        <el-form-item :label="t('backups.enableTask')">
          <el-switch v-model="form.isEnabled" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="closeDialog">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleSave">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- 执行历史对话框（标题带任务名） -->
    <el-dialog
      v-model="showHistoryDialog"
      :title="`${t('backups.history')} - ${historyTaskName}`"
      width="800px"
    >
      <el-table
        class="backup-history-table"
        :data="taskHistory"
        stripe
        border
        v-loading="historyLoading"
        max-height="400"
      >
        <el-table-column prop="time" :label="t('backups.execTime')" min-width="180">
          <template #default="{ row }">{{ row.time }}</template>
        </el-table-column>
        <el-table-column prop="total" :label="t('backups.totalDevices')" min-width="100" align="center">
          <template #default="{ row }">{{ row.total }}</template>
        </el-table-column>
        <el-table-column :label="t('backups.successFail')" min-width="120" align="center">
          <template #default="{ row }">
            <span class="success-text">{{ row.success }}</span>
            <span> / </span>
            <span class="fail-text">{{ row.failed }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.status')" min-width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.failed === 0" type="success" size="small">{{ t('backups.allSuccess') }}</el-tag>
            <el-tag v-else-if="row.success === 0" type="danger" size="small">{{ t('backups.allFailed') }}</el-tag>
              <el-tag v-else type="warning" size="small">{{ t('backups.partialSuccess') }}</el-tag>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="taskHistory.length === 0 && !historyLoading" :description="t('backups.noHistory')" />

      <template #footer>
        <el-button @click="showHistoryDialog = false">{{ t('common.close') }}</el-button>
      </template>
    </el-dialog>

    <!-- 任务设备列表弹窗（零新请求：devices 范围仅显示 ID+缺失标记；site/all 复用页面内存数据） -->
    <el-dialog
      v-model="showDeviceDialog"
      :title="t('backups.deviceListTitle')"
      width="560px"
    >
      <el-table :data="deviceDialogPagedRows" stripe border max-height="400" size="small">
        <el-table-column prop="id" label="ID" width="60" align="center" />
        <el-table-column :label="t('backups.taskName')" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.name" class="device-name-cell">{{ row.name }}</span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.missing" size="small" type="danger">{{ t('backups.deviceMissingMark') }}</el-tag>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="deviceDialogRows.length === 0"
        :description="t('backups.noTasks')"
        :image-size="60"
      />

      <div v-if="deviceDialogRows.length > deviceDialogPageSize" class="device-dialog-footer">
        <el-pagination
          v-model:current-page="deviceDialogPage"
          :page-size="deviceDialogPageSize"
          :total="deviceDialogRows.length"
          layout="prev, pager, next"
          background
          small
        />
      </div>

      <template #footer>
        <el-button @click="showDeviceDialog = false">{{ t('common.close') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.backup-task-list-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ==================== 统计卡片（对齐 BackupsPage 样式） ==================== */
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
.overview-card-info { border-left-color: var(--el-color-info); }
.overview-card-danger { border-left-color: var(--el-color-danger); }

.overview-card.is-clickable {
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.2s;
}

.overview-card.is-clickable:hover {
  box-shadow: var(--el-box-shadow-light);
}

.overview-card.is-active {
  box-shadow: 0 0 0 2px var(--el-color-primary-light-5);
}

.overview-card-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.stat-tip-icon {
  color: var(--el-text-color-placeholder);
  cursor: help;
}

.overview-card-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
}

/* 已筛选标签栏 */
.filter-active-bar {
  display: flex;
}

.table-card {
  border-radius: 8px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.table-filters {
  display: flex;
  gap: 8px;
  align-items: center;
}

.task-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-icon {
  color: var(--el-color-primary);
}

/* 范围列：未指定范围标记 + 可点链接 */
.scope-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.scope-link {
  font-size: 13px;

  :deep(.el-link__inner) {
    white-space: nowrap;
  }
}

/* 凭证列风险标签 */
.credential-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* 定时规则人话描述 */
.cron-desc {
  cursor: help;
}

/* 执行中标记 */
.running-cell {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.running-icon {
  color: var(--el-color-primary);
}

.running-text {
  color: var(--el-color-primary);
  font-size: 13px;
}

/* 上次状态 tag 可点 */
.status-tag {
  cursor: pointer;
}

/* 启用开关 + 文字 */
.status-switch-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.status-switch-text {
  font-size: 12px;
}

.status-switch-text.is-enabled {
  color: var(--el-color-success);
}

.status-switch-text.is-disabled {
  color: var(--el-text-color-secondary);
}

/* 操作列「更多」触发器 */
.more-trigger {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: 12px;
  font-size: 12px;
  color: var(--el-color-primary);
  cursor: pointer;
  outline: none;
}

.more-trigger:hover {
  color: var(--el-color-primary-light-3);
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

/* 设备弹窗分页 */
.device-dialog-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

/* 设备弹窗：名称单元格不换行，超长省略（配合 show-overflow-tooltip） */
.device-name-cell {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 设备多选：全选/清空/按站点快速添加 */
.device-select-block {
  width: 100%;
}

.device-select-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.device-select-count {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.text-muted {
  color: var(--el-text-color-placeholder);
}

.form-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.cron-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.success-text {
  color: var(--el-color-success);
}

.fail-text {
  color: var(--el-color-danger);
}

.backup-task-table :deep(.cell) {
  line-height: 1.5;
}

.backup-task-table :deep(.el-table__cell) {
  padding: 8px 12px;
}

.backup-history-table :deep(.cell) {
  line-height: 1.5;
}

.backup-history-table :deep(.el-table__cell) {
  padding: 8px 12px;
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
