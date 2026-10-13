<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Monitor, Connection, Box, MapLocation } from '@element-plus/icons-vue'
import { getBackups, getBackupContent, getBackupDiff, updateBackupTag, deleteBackup, restoreBackup } from '@/api/backups'
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
    'manual': '手动',
    'scheduled': '定时',
    'pre_change': '变更前',
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
const tagInput = ref('')
const showTagPopover = ref(false)
const taggingBackupId = ref<number | null>(null)

// 筛选
const searchQuery = ref('')
const filterStatus = ref('')
const filterTrigger = ref('')
const filterHasChange = ref<boolean | ''>('')

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
  
  return result
})

function canCompare() {
  return selectedBackups.value.length === 2
}

async function handleCompare() {
  if (!canCompare()) {
    ElMessage.warning('请选择恰好2条备份记录进行对比')
    return
  }
  
  const [a, b] = selectedBackups.value.sort((x, y) => x.version - y.version)
  
  try {
    diffResult.value = await getBackupDiff(parseInt(a.id), parseInt(b.id))
    showDiffDialog.value = true
  } catch (error) {
    console.error('Failed to compare backups:', error)
    ElMessage.error('获取差异失败')
  }
}

function handleSelectionChange(rows: Backup[]) {
  selectedBackups.value = rows
}

async function viewBackup(backup: Backup) {
  try {
    viewingBackup.value = backup
    const result = await getBackupContent(parseInt(backup.id))
    viewingContent.value = result.content || '暂无配置内容'
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
  await confirmAndRun({
    message: `确定要删除该备份记录吗？此操作不可撤销。`,
    title: '确认删除',
    confirmText: '删除',
    cancelText: '取消',
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
    successMessage: '备份记录删除成功',
    errorMessage: '删除备份失败',
  })
}

function showTagInput(backup: Backup) {
  taggingBackupId.value = parseInt(backup.id)
  tagInput.value = backup.tag || ''
  showTagPopover.value = true
}

async function saveTag() {
  if (!taggingBackupId.value) return
  
  try {
    const backup = backups.value.find(b => parseInt(b.id) === taggingBackupId.value)
    await updateBackupTag(taggingBackupId.value, tagInput.value)
    
    // 添加操作日志
    store.addAuditLog({
      user: authStore.user?.username || 'system',
      action: '更新备份标签',
      resource: '配置备份',
      detail: `更新设备 ${backup?.deviceId} 备份 (v${backup?.version}) 的标签为: ${tagInput.value}`,
      ipAddress: null,
      createdAt: new Date().toISOString(),
      success: 'true'
    })
    
    ElMessage.success('标签保存成功')
    showTagPopover.value = false
    await loadBackups()
  } catch (error) {
    console.error('Failed to save tag:', error)
    ElMessage.error('保存标签失败')
  }
}

function downloadBackup(backup: Backup) {
  if (!backup.content) {
    ElMessage.warning('该备份无配置内容')
    return
  }
  const blob = new Blob([backup.content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  
  // 使用设备名称（如果有）或设备ID，加上版本号生成文件名
  const deviceName = backup.deviceName || `device_${backup.deviceId}`
  const safeDeviceName = deviceName.replace(/[^a-zA-Z0-9_\u4e00-\u9fa5]/g, '_')
  a.download = `${safeDeviceName}_v${backup.version}_${backup.created_at.replace(/[:\s]/g, '-')}.cfg`
  
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
  if (!backup.content) {
    ElMessage.warning('该备份无配置内容，无法还原')
    return
  }
  
  try {
    await ElMessageBox.confirm(
      `确定要将此配置还原到设备吗？\n\n设备: ${backup.deviceId}\n版本: v${backup.version}\n备份时间: ${formatDateTime(backup.created_at)}\n\n⚠️ 警告：此操作将覆盖设备当前配置，请确保已备份最新配置！`,
      '确认还原配置',
      { 
        confirmButtonText: '确认还原', 
        cancelButtonText: '取消', 
        type: 'warning',
        dangerouslyUseHTMLString: true
      }
    )
    
    const result = await restoreBackup(parseInt(backup.id))
    
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
      
      ElMessage.success('配置还原成功')
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
      
      ElMessage.error(`还原失败: ${result.message}`)
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
      
      ElMessage.error('还原配置失败')
    }
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
        <div class="overview-card-label">{{ t('backups.title') }}</div>
        <div class="overview-card-value">{{ backups.length }}</div>
        <div class="overview-card-trend">{{ t('backups.allRecords') }}</div>
      </div>
      <div class="overview-card overview-card-success">
        <div class="overview-card-label">成功备份</div>
        <div class="overview-card-value">{{ backups.filter(b => b.status === 'success').length }}</div>
        <div class="overview-card-trend">备份成功率</div>
      </div>
      <div class="overview-card overview-card-danger">
        <div class="overview-card-label">失败备份</div>
        <div class="overview-card-value">{{ backups.filter(b => b.status === 'failed').length }}</div>
        <div class="overview-card-trend">备份失败数</div>
      </div>
      <div class="overview-card overview-card-warning">
        <div class="overview-card-label">{{ t('backups.changeCount') }}</div>
        <div class="overview-card-value">{{ backups.filter(b => b.hasChange).length }}</div>
        <div class="overview-card-trend">近7天发现变更</div>
      </div>
    </div>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="card-title">
              <el-icon><DocumentCopy /></el-icon>
              {{ t('backups.title') }}
            </div>
          <div class="table-actions" v-if="canCompare()">
            <el-button type="warning" @click="handleCompare">
              <el-icon><Connection /></el-icon>
              对比选中版本
            </el-button>
          </div>
        </div>
      </template>

      <div class="table-filters">
        <el-input
          v-model="searchQuery"
          placeholder="搜索设备、标签..."
          prefix-icon="Search"
          clearable
          style="width: 200px"
        />
        <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 120px">
          <el-option value="success" label="成功" />
          <el-option value="failed" label="失败" />
        </el-select>
        <el-select v-model="filterTrigger" placeholder="触发方式" clearable style="width: 120px">
          <el-option value="manual" label="手动" />
          <el-option value="scheduled" label="定时" />
        </el-select>
        <el-select v-model="filterHasChange" placeholder="变更状态" clearable style="width: 120px">
          <el-option :value="true" label="有变更" />
          <el-option :value="false" label="无变更" />
        </el-select>
      </div>

      <el-table
        :data="filteredBackups"
        style="width: 100%"
        stripe
        border
        v-loading="loading"
        max-height="calc(100vh - 420px)"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="50" />
        <el-table-column prop="version" label="版本" min-width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small">v{{ row.version }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="deviceId" label="设备" min-width="200">
          <template #default="{ row }">
            <div class="device-info">
              <el-icon class="device-icon">
                <component :is="getDeviceIcon(getDeviceInfo(row.deviceId)?.type || '')" />
              </el-icon>
              <div class="device-detail">
                <div class="device-name">{{ getDeviceInfo(row.deviceId)?.name || `设备${row.deviceId}` }}</div>
                <div class="device-meta">
                  <span class="device-vendor">{{ getDeviceInfo(row.deviceId)?.vendor || '-' }}</span>
                  <span class="device-model">{{ getDeviceInfo(row.deviceId)?.model || '-' }}</span>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="siteId" label="站点" min-width="100">
          <template #default="{ row }">
            <div class="site-info">
              <el-icon class="site-icon" size="14"><MapLocation /></el-icon>
              <span>{{ getSiteName(getDeviceInfo(row.deviceId)?.site_id) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="deviceIp" label="管理IP" min-width="110">
          <template #default="{ row }">
            {{ getIpAddress(getDeviceInfo(row.deviceId)?.mgmt_ip_id) }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="备份时间" min-width="140">
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="trigger" label="触发" min-width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="getTriggerType(row.trigger)" effect="light" size="small">
              {{ getTriggerLabel(row.trigger) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="hasChange" label="变更" min-width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.hasChange" type="warning" size="small">
              {{ row.changeSummary || '有变更' }}
            </el-tag>
            <el-tag v-else type="info" size="small">无变更</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="tag" label="标签" min-width="100">
          <template #default="{ row }">
            <span v-if="row.tag" class="tag-text">{{ row.tag }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="durationMs" label="耗时" min-width="80" align="center">
          <template #default="{ row }">{{ formatDuration(row.durationMs) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" min-width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" effect="light" size="small">
              {{ row.status === 'success' ? '成功' : row.status === 'failed' ? '失败' : '等待' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="viewBackup(row)">
              <el-icon><View /></el-icon>
              查看
            </el-button>
            <el-popover
              placement="top"
              :width="200"
              trigger="click"
              v-model:visible="showTagPopover"
            >
              <template #reference>
                <el-button link type="primary" size="small" @click="showTagInput(row)">
                  <el-icon><PriceTag /></el-icon>
                  标签
                </el-button>
              </template>
              <div class="tag-popover">
                <el-input v-model="tagInput" placeholder="输入标签" />
                <el-button type="primary" size="small" @click="saveTag">保存</el-button>
              </div>
            </el-popover>
            <el-button link type="success" size="small" @click="downloadBackup(row)" :disabled="!row.content">
  <el-icon><Download /></el-icon>
</el-button>
<el-button link type="warning" size="small" @click="handleRestore(row)" :disabled="!row.content || row.status !== 'success'">
  <el-icon><RefreshLeft /></el-icon>
  还原
</el-button>
<el-button link type="danger" size="small" @click="handleDelete(row)">
  <el-icon><Delete /></el-icon>
</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="filteredBackups.length === 0 && !loading" description="暂无备份记录" />
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
            <span class="meta-value">{{ formatDateTime(viewingBackup.created_at) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">状态：</span>
            <el-tag :type="getStatusType(viewingBackup.status)" size="small">
              {{ viewingBackup.status === 'success' ? '成功' : '失败' }}
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
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid #8c8c8c;
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
}

.overview-card-trend {
  font-size: 12px;
  color: #bfbfbf;
  margin-top: 4px;
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

.table-filters {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.device-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.device-icon {
  color: #1890ff;
  font-size: 18px;
}

.device-detail {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.device-name {
  font-weight: 500;
  color: #262626;
}

.device-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #8c8c8c;
}

.device-vendor {
  padding: 2px 6px;
  background: #f5f5f5;
  border-radius: 4px;
}

.device-model {
  padding: 2px 6px;
  background: #f5f5f5;
  border-radius: 4px;
}

.site-info {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #595959;
}

.site-icon {
  color: #52c41a;
}

.tag-text {
  color: #1890ff;
}

.text-muted {
  color: #bfbfbf;
}

.tag-popover {
  display: flex;
  gap: 8px;
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
  background: #fafafa;
  border-radius: 8px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.meta-label {
  font-weight: 600;
  color: #595959;
}

.meta-value {
  color: #262626;
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
  background: #fafafa;
  border-radius: 8px;
}

.summary-text {
  color: #262626;
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
  color: #1890ff;
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
