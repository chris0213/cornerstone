<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getBackupTasks, createBackupTask, updateBackupTask, deleteBackupTask, toggleBackupTask, runBackupTaskNow, getBackupTaskHistory, getCredentials } from '@/api/backups'
import { formatDateTime } from '@/lib/utils'
import { getDevices, type DeviceResponse } from '@/api/devices'
import { getSites, type SiteResponse } from '@/api/sites'
import type { BackupTask, Credential, Device, Site } from '@/types/domain'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()

const tasks = ref<BackupTask[]>([])
const credentials = ref<Credential[]>([])
const devices = ref<Device[]>([])
const sites = ref<Site[]>([])
const loading = ref(false)
const showDialog = ref(false)
const showHistoryDialog = ref(false)
const editingTask = ref<BackupTask | null>(null)
const taskHistory = ref<any[]>([])
const historyLoading = ref(false)
const selectedTaskIds = ref<number[]>([])

// 用于跟踪是否使用自定义Cron表达式
const useCustomCron = ref(false)

const form = ref<{
  name: string
  cronExpr: string
  customCronExpr: string
  credentialId: string | number
  backupScope: 'devices' | 'site'
  deviceIds: number[]
  siteId: string | number
  vendor: string
  retentionCount: number
  retentionDays: number
  notifyOnChange: boolean
  notifyOnFail: boolean
  isEnabled: boolean
}>({
  name: '',
  cronExpr: '0 2 * * *',
  customCronExpr: '',
  credentialId: '',
  backupScope: 'devices',
  deviceIds: [],
  siteId: '',
  vendor: '',
  retentionCount: 30,
  retentionDays: 90,
  notifyOnChange: true,
  notifyOnFail: true,
  isEnabled: true,
})

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

function resetForm() {
  form.value = {
    name: '',
    cronExpr: '0 2 * * *',
    customCronExpr: '',
    credentialId: '',
    backupScope: 'devices',
    deviceIds: [],
    siteId: '',
    vendor: '',
    retentionCount: 30,
    retentionDays: 90,
    notifyOnChange: true,
    notifyOnFail: true,
    isEnabled: true,
  }
  editingTask.value = null
}

function openCreateDialog() {
  resetForm()
  showDialog.value = true
}

function openEditDialog(task: BackupTask) {
  editingTask.value = task
  const deviceIds = task.deviceIds ? JSON.parse(task.deviceIds) : []
  form.value = {
    name: task.name,
    cronExpr: task.cronExpr,
    customCronExpr: '',
    credentialId: task.credentialId,
    backupScope: task.siteId ? 'site' : 'devices',
    deviceIds: deviceIds,
    siteId: task.siteId || '',
    vendor: task.vendor || '',
    retentionCount: task.retentionCount,
    retentionDays: task.retentionDays,
    notifyOnChange: task.notifyOnChange,
    notifyOnFail: task.notifyOnFail,
    isEnabled: task.isEnabled,
  }
  showDialog.value = true
}

function closeDialog() {
  showDialog.value = false
  resetForm()
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
    console.error('Failed to save task:', error)
    ElMessage.error(t('backups.saveFailed'))
  }
}

async function handleDelete(task: BackupTask) {
  try {
    await ElMessageBox.confirm(
      t('backups.confirmDelete', { name: task.name }),
      t('common.confirm'),
      { confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'), type: 'warning' }
    )
    await deleteBackupTask(parseInt(task.id))
    ElMessage.success(t('backups.taskDeleted'))
    await loadTasks()
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('Failed to delete task:', error)
      ElMessage.error(t('backups.deleteFailed'))
    }
  }
}

// 处理选择变化
const handleSelectionChange = (val: any[]) => {
  selectedTaskIds.value = val.map(item => parseInt(item.id))
}

// 批量删除
async function handleBatchDelete() {
  try {
    await ElMessageBox.confirm(
      t('backups.confirmBatchDelete', { count: selectedTaskIds.value.length }),
      t('common.confirm'),
      { confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'), type: 'warning' }
    )
    // 逐个删除（可以优化为批量API）
    for (const id of selectedTaskIds.value) {
      await deleteBackupTask(id)
    }
    ElMessage.success(t('backups.batchDeleted', { count: selectedTaskIds.value.length }))
    selectedTaskIds.value = []
    await loadTasks()
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('Failed to batch delete tasks:', error)
      ElMessage.error(t('backups.batchDeleteFailed'))
    }
  }
}

async function handleToggle(task: BackupTask) {
  try {
    const result = await toggleBackupTask(parseInt(task.id))
    task.isEnabled = result.isEnabled
    ElMessage.success(result.isEnabled ? t('backups.taskEnabled') : t('backups.taskDisabled'))
    await loadTasks()
  } catch (error) {
    console.error('Failed to toggle task:', error)
    ElMessage.error(t('backups.toggleFailed'))
  }
}

async function handleRunNow(task: BackupTask) {
  try {
    await runBackupTaskNow(parseInt(task.id))
    ElMessage.success(t('backups.taskStarted'))
  } catch (error: any) {
    console.error('Failed to run task:', error)
    // 提取具体的错误信息
    const errorMsg = error.response?.data?.detail || error.message || t('backups.runFailed')
    ElMessage.error(errorMsg)
  }
}

async function openHistoryDialog(task: BackupTask) {
  editingTask.value = task
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
      deviceCount: task.device_count || task.deviceCount,
      cronExpr: task.cron_expr || task.cronExpr,
      retentionCount: task.retention_count || task.retentionCount,
      retentionDays: task.retention_days || task.retentionDays,
      notifyOnChange: task.notify_on_change || task.notifyOnChange,
      notifyOnFail: task.notify_on_fail || task.notifyOnFail,
      isEnabled: task.is_enabled || task.isEnabled,
      createdAt: task.created_at || task.createdAt,
    }))
  } catch (error) {
    console.error('Failed to load tasks:', error)
    ElMessage.error(t('backups.loadTasksFailed'))
  } finally {
    loading.value = false
  }
}

async function loadCredentials() {
  try {
    credentials.value = await getCredentials()
  } catch (error) {
    console.error('Failed to load credentials:', error)
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

function getCronLabel(cron: string) {
  const preset = cronPresets.find(p => p.value === cron)
  return preset ? preset.label : cron
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
    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="card-title">
            <el-icon><Timer /></el-icon>
            {{ t('backups.tasks') }}
          </div>
          <div class="table-actions">
            <el-button 
              v-if="selectedTaskIds.length > 0" 
              type="danger" 
              @click="handleBatchDelete"
            >
              <el-icon><Delete /></el-icon>
              {{ t('backups.batchDelete', { count: selectedTaskIds.length }) }}
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
        :data="tasks"
        style="width: 100%"
        stripe
        border
        v-loading="loading"
        height="calc(100vh - 220px)"
        :selectable="(row: BackupTask) => !row.isEnabled"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column prop="name" :label="t('backups.taskName')" min-width="180">
          <template #default="{ row }">
            <div class="task-name">
              <el-icon class="task-icon"><Timer /></el-icon>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="deviceCount" :label="t('backups.deviceCount')" min-width="80" align="center">
          <template #default="{ row }">{{ row.deviceCount || 0 }}</template>
        </el-table-column>
        <el-table-column prop="credentialName" :label="t('backups.credentialName')" min-width="150">
          <template #default="{ row }">{{ row.credentialName || '-' }}</template>
        </el-table-column>
        <el-table-column prop="cronExpr" :label="t('backups.cronExpr')" min-width="150">
          <template #default="{ row }">
            <el-tag size="small">{{ getCronLabel(row.cronExpr) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="lastRunAt" :label="t('backups.lastRunAt')" min-width="160">
          <template #default="{ row }">
            <span v-if="row.lastRunAt">{{ formatDateTime(row.lastRunAt) }}</span>
            <span v-else class="text-muted">{{ t('backups.neverRun') }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="lastRunStatus" :label="t('backups.lastRunStatus')" min-width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.lastRunStatus" :type="getStatusType(row.lastRunStatus)" size="small">
              {{ row.lastRunStatus === 'success' ? t('backups.success') : row.lastRunStatus === 'partial_fail' ? t('backups.partialFail') : t('backups.failed') }}
            </el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="isEnabled" :label="t('common.status')" min-width="80" align="center">
          <template #default="{ row }">
            <el-switch
              v-model="row.isEnabled"
              @change="handleToggle(row)"
              size="small"
            />
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="280" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="handleRunNow(row)">
              <el-icon><VideoPlay /></el-icon>
              {{ t('backups.runNow') }}
            </el-button>
            <el-button link type="primary" size="small" @click="openHistoryDialog(row)">
              <el-icon><Clock /></el-icon>
              {{ t('common.history') || 'History' }}
            </el-button>
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

      <el-empty v-if="tasks.length === 0 && !loading" :description="t('backups.noTasks')" />
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
          <el-select v-model="form.deviceIds" 
            style="width: 100%" 
            multiple 
            :placeholder="t('backups.selectDevices')"
            collapse-tags
          >
            <el-option v-for="device in devices" :key="device.id" :label="device.name" :value="device.id" />
          </el-select>
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

    <!-- 执行历史对话框 -->
    <el-dialog
      v-model="showHistoryDialog"
      :title="t('backups.history')"
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
  </div>
</template>

<style scoped>
.backup-task-list-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.table-card {
  border-radius: 8px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #262626;
}

.card-title .el-icon {
  color: #1890ff;
}

.task-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-icon {
  color: #1890ff;
}

.text-muted {
  color: #bfbfbf;
}

.cron-hint {
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 4px;
}

.success-text {
  color: #52c41a;
}

.fail-text {
  color: #ff4d4f;
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
</style>
