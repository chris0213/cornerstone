<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../store'
import { useAuthStore } from '../../store/auth'
import { storeToRefs } from 'pinia'
import { ElMessage, ElDialog, ElButton, ElDatePicker, ElTabPane, ElTabs, ElMessageBox } from 'element-plus'
import { confirmAndRun } from '@/lib/confirm'
import { Bell, Refresh, CircleClose, Warning, DataLine, Connection, View, InfoFilled, Calendar, Monitor, DocumentCopy, SetUp, BellFilled, WarningFilled } from '@element-plus/icons-vue'
import AIPrediction from '../../components/AIPrediction.vue'
import AnomalyCard, { type Anomaly } from './AnomalyCard.vue'
import { onNewAlert } from '@/lib/alertSocket'
import {
  getAlertRecords,
  getAlertFullSummary,
  acknowledgeAlert,
  batchAcknowledgeAlerts,
  resolveAlert,
  muteAlertRule,
  type AlertRecord
} from '../../api/alerts'
import type { UserResponse } from '../../api/users'
import { getUsers } from '../../api/users'
import { getLocale } from '@/i18n'
import { useI18n } from 'vue-i18n'

const { locale, t } = useI18n()
const authStore = useAuthStore()
const isViewer = computed(() => authStore.isReadOnly())
const canWrite = computed(() => authStore.hasPermission('alerts', 'write'))
interface Alert {
  type: string
  title: string
  due: string
  days: number
  level: 'danger' | 'warn' | 'ok'
  detail?: string
  ipId?: string | number
  deviceId?: string | number
  circuitId?: string | number
  backupId?: string
  suggestion?: string
}

interface ExpiringIP {
  id: string | number
  address: string
  prefixId: string | number | null
  usage: string
  owner: string
  expireAt: string
  remainingDays: number
}

const router = useRouter()
const store = useAppStore()
const { circuits, devices, backups, prefixes, ipAddresses } = storeToRefs(store)
const { prefixNetwork, updateIPAddress } = store

const today = new Date()
today.setHours(0, 0, 0, 0)

const activeTab = ref('realtime')
const showRenewDialog = ref(false)
const editingIP = ref<ExpiringIP | null>(null)
const renewForm = ref({
  expireAt: ''
})

// ==================== 告警记录：筛选/分页/批量 ====================
// 注意：搜索与筛选仅作用于「告警记录」卡片（统一列表），
// 各预警 Tab（实时/到期/容量）为按现状数据实时计算的预警，不受筛选影响。
const filterSeverity = ref<'all' | 'info' | 'warning' | 'critical'>('all')
const filterStatus = ref<'all' | 'active' | 'acknowledged' | 'resolved'>('all')
const filterType = ref<'all' | 'latency' | 'packet_loss' | 'status' | 'circuit_expire' | 'inspection_offline' | 'inspection_new_device' | 'inspection_fingerprint_change'>('all')
const filterTimeRange = ref<[Date, Date] | null>(null)

const records = ref<AlertRecord[]>([])
const recordsTotal = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loadingRecords = ref(false)

// ID → 用户名映射（展示认领人/处理人）
const userNameMap = ref<Record<number, string>>({})

function formatRelativeTime(dateText: string): string {
  const now = new Date()
  const createdAt = new Date(dateText)
  const diffMinutes = Math.floor((now.getTime() - createdAt.getTime()) / 60000)
  if (diffMinutes < 1) return t('alerts.justNow')
  if (diffMinutes < 60) return t('alerts.minutesAgo', { count: diffMinutes })
  if (diffMinutes < 1440) return t('alerts.hoursAgo', { count: Math.floor(diffMinutes / 60) })
  return t('alerts.daysAgo', { count: Math.floor(diffMinutes / 1440) })
}

function formatDateTime(dateText?: string): string {
  if (!dateText) return '-'
  return new Date(dateText).toLocaleString(getLocale() || 'zh-CN')
}

// 告警标题：优先规则名，无规则时按类型映射
const ruleNameMap = ref<Record<number, string>>({})

async function loadRuleNameMap() {
  try {
    const { getAlertRules } = await import('../../api/alerts')
    const rules = await getAlertRules()
    const map: Record<number, string> = {}
    rules.forEach((rule) => {
      map[rule.id] = rule.name
    })
    ruleNameMap.value = map
  } catch {
    // 兜底走类型名
  }
}

function alertTitle(record: AlertRecord): string {
  if (record.rule_id && ruleNameMap.value[record.rule_id]) return ruleNameMap.value[record.rule_id]
  const typeMap: Record<string, string> = {
    latency: t('alerts.highLatency'),
    packet_loss: t('alerts.highPacketLoss'),
    status: t('alerts.statusAbnormal'),
    circuit_expire: t('alerts.circuitContractAlerts'),
    inspection_offline: t('alerts.offlineAlert'),
    inspection_new_device: t('alerts.newDevice'),
    inspection_fingerprint_change: t('alerts.fingerprintChange')
  }
  return typeMap[record.alert_type] || t('alerts.alertTriggered')
}

// 对象跳转：circuit 类告警跳专线，其余跳设备
function goToRecordTarget(record: AlertRecord) {
  if (record.object_type === 'circuit') {
    router.push(`/circuits?id=${record.device_id}`)
  } else if (record.device_id) {
    router.push(`/devices?id=${record.device_id}`)
  }
}

async function loadUserNameMap() {
  try {
    const users = await getUsers()
    const map: Record<number, string> = {}
    users.forEach((u: UserResponse) => {
      map[u.id] = u.full_name || u.username
    })
    userNameMap.value = map
  } catch {
    // 权限不足或接口异常时兜底显示 ID
  }
}

function displayName(userId?: number): string {
  if (!userId) return '-'
  return userNameMap.value[userId] || `#${userId}`
}

async function loadRecords() {
  loadingRecords.value = true
  try {
    const params: Record<string, unknown> = {
      page: currentPage.value,
      page_size: pageSize.value
    }
    if (filterSeverity.value !== 'all') params.severity = filterSeverity.value
    if (filterStatus.value !== 'all') params.status = filterStatus.value
    if (filterType.value !== 'all') params.alert_type = filterType.value
    if (filterTimeRange.value) {
      params.start_time = filterTimeRange.value[0].toISOString()
      params.end_time = filterTimeRange.value[1].toISOString()
    }
    const data = await getAlertRecords(params)
    records.value = data.items
    recordsTotal.value = data.total
  } catch (error) {
    console.error('加载告警记录失败:', error)
  } finally {
    loadingRecords.value = false
  }
}

// ==================== 统一统计（与列表同源，后端 /summary/full） ====================
const fullSummary = ref<{
  by_status: { total: number; active: number; acknowledged: number; resolved: number }
  by_severity: { info: number; warning: number; critical: number }
  open_by_severity: { info: number; warning: number; critical: number }
} | null>(null)

async function loadFullSummary() {
  try {
    fullSummary.value = await getAlertFullSummary()
  } catch (error) {
    console.error('加载告警统计失败:', error)
  }
}

const statTotal = computed(() => fullSummary.value?.by_status.total ?? 0)
const statUnacknowledged = computed(() => fullSummary.value?.by_status.active ?? 0)
const statAcknowledged = computed(() => fullSummary.value?.by_status.acknowledged ?? 0)
const statResolved = computed(() => fullSummary.value?.by_status.resolved ?? 0)
const statCriticalOpen = computed(() => fullSummary.value?.open_by_severity.critical ?? 0)
const statWarningOpen = computed(() => fullSummary.value?.open_by_severity.warning ?? 0)

// 卡片 → 记录列表联动筛选
function applyStatusFilter(status: 'all' | 'active' | 'acknowledged' | 'resolved') {
  filterStatus.value = status
  currentPage.value = 1
  loadRecords()
}
function applySeverityFilter(severity: 'all' | 'critical' | 'warning') {
  filterSeverity.value = severity
  currentPage.value = 1
  loadRecords()
}

// ==================== 处置动作：认领 / 批量认领 / 处理 / 静默 ====================
const selectedRecords = ref<AlertRecord[]>([])

async function handleAcknowledge(record: AlertRecord) {
  try {
    await acknowledgeAlert(record.id)
    ElMessage.success(t('alerts.acknowledgeSuccess'))
    await Promise.all([loadRecords(), loadFullSummary()])
  } catch (error) {
    console.error('认领告警失败:', error)
    ElMessage.error(t('alerts.acknowledgeFailed'))
  }
}

async function handleBatchAcknowledge() {
  const ids = selectedRecords.value.filter(r => r.status === 'active').map(r => r.id)
  if (ids.length === 0) return
  try {
    await ElMessageBox.confirm(
      t('alerts.batchAcknowledgeConfirm', { count: ids.length }),
      t('common.confirm'),
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const res = await batchAcknowledgeAlerts(ids)
    ElMessage.success(t('alerts.batchAcknowledgeSuccess', { count: res.acknowledged, skipped: res.skipped }))
    selectedRecords.value = []
    await Promise.all([loadRecords(), loadFullSummary()])
  } catch (error) {
    console.error('批量认领失败:', error)
    ElMessage.error(t('alerts.acknowledgeFailed'))
  }
}

// 处理弹窗：必填备注
const showResolveDialog = ref(false)
const resolvingRecord = ref<AlertRecord | null>(null)
const resolveNote = ref('')
const resolveSubmitting = ref(false)

function openResolveDialog(record: AlertRecord) {
  resolvingRecord.value = record
  resolveNote.value = ''
  showResolveDialog.value = true
}

async function confirmResolve() {
  const note = resolveNote.value.trim()
  if (!note) {
    ElMessage.warning(t('alerts.resolveNoteRequired'))
    return
  }
  if (!resolvingRecord.value) return
  try {
    await ElMessageBox.confirm(t('alerts.resolveConfirm'), t('common.confirm'), { type: 'warning' })
  } catch {
    return
  }
  resolveSubmitting.value = true
  try {
    await resolveAlert(resolvingRecord.value.id, note)
    ElMessage.success(t('alerts.resolveSuccess'))
    showResolveDialog.value = false
    resolvingRecord.value = null
    await Promise.all([loadRecords(), loadFullSummary()])
  } catch (error) {
    console.error('处理告警失败:', error)
    ElMessage.error(t('alerts.resolveFailed'))
  } finally {
    resolveSubmitting.value = false
  }
}

async function handleMute(record: AlertRecord, hours: number) {
  if (!record.rule_id) return
  try {
    await muteAlertRule(record.rule_id, hours)
    ElMessage.success(t('alerts.muteSuccess', { hours }))
    await loadRecords()
  } catch (error: any) {
    console.error('静默规则失败:', error)
    ElMessage.error(error.response?.data?.detail || t('alerts.muteFailed'))
  }
}

function handleSelectionChange(rows: AlertRecord[]) {
  selectedRecords.value = rows
}

const hasActiveSelection = computed(() => selectedRecords.value.some(r => r.status === 'active'))

// 严重未处理置顶排序（同页内）：active+critical → 其他 active → 已认领 → 已处理
function recordSortWeight(r: AlertRecord): number {
  if (r.status === 'resolved') return 3
  if (r.status === 'acknowledged') return 2
  return r.severity === 'critical' ? 0 : 1
}
const sortedRecords = computed(() => {
  // 默认后端按时间倒序；这里仅做严重置顶的稳定分组，不破坏同组内时间序
  const map = new Map<number, AlertRecord[]>()
  records.value.forEach(r => {
    const w = recordSortWeight(r)
    if (!map.has(w)) map.set(w, [])
    map.get(w)!.push(r)
  })
  return [...map.keys()].sort((a, b) => a - b).flatMap(w => map.get(w)!)
})

const hasCriticalUnacknowledged = computed(() =>
  records.value.some(r => r.status === 'active' && r.severity === 'critical')
)

// ==================== 展示辅助：重置/级别徽标/状态文案/对象文案/行样式 ====================
function resetFilters() {
  filterSeverity.value = 'all'
  filterStatus.value = 'all'
  filterType.value = 'all'
  filterTimeRange.value = null
  currentPage.value = 1
  loadRecords()
}

function severityTagType(severity: string) {
  const map: Record<string, 'danger' | 'warning' | 'info'> = {
    critical: 'danger',
    warning: 'warning',
    info: 'info'
  }
  return map[severity] || 'info'
}

function severityLabel(severity: string): string {
  const map: Record<string, string> = {
    critical: t('alerts.critical'),
    warning: t('alerts.warning'),
    info: t('alerts.info')
  }
  return map[severity] || severity
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    active: t('alerts.unacknowledged'),
    acknowledged: t('alerts.acknowledged'),
    resolved: t('alerts.resolved')
  }
  return map[status] || status
}

function recordTargetLabel(record: AlertRecord): string {
  if (record.object_type === 'circuit') return t('alerts.circuit')
  if (record.device_id) return t('alerts.device')
  return ''
}

function recordRowClass({ row }: { row: AlertRecord }): string {
  return row.status === 'active' && row.severity === 'critical' ? 'row-critical-open' : ''
}

// ==================== 实时推送 ====================
let unsubscribeRealtimeAlert: (() => void) | null = null

onMounted(() => {
  loadRecords()
  loadFullSummary()
  loadUserNameMap()
  loadRuleNameMap()
  // 实时推送到达时刷新记录与统计
  unsubscribeRealtimeAlert = onNewAlert(() => {
    loadRecords()
    loadFullSummary()
  })
})

onUnmounted(() => {
  unsubscribeRealtimeAlert?.()
  unsubscribeRealtimeAlert = null
})

function daysUntilDate(dateText: string): number {
  const date = new Date(`${dateText}T00:00:00+08:00`)
  const diff = date.getTime() - today.getTime()
  return Math.ceil(diff / 86400000)
}

// IP到期预警数据
const expiringIPs = computed((): ExpiringIP[] => {
  const result: ExpiringIP[] = []
  ipAddresses.value.forEach((ip) => {
    if (ip.expireAt && ip.status !== 'available') {
      const days = daysUntilDate(ip.expireAt)
      if (days >= 0 && days <= 30) {
        result.push({
          id: ip.id,
          address: ip.address,
          prefixId: ip.prefixId,
          usage: ip.usage || '-',
          owner: ip.owner || '-',
          expireAt: ip.expireAt,
          remainingDays: days
        })
      }
    }
  })
  return result.sort((a, b) => a.remainingDays - b.remainingDays)
})

// 专线合同预警
const circuitAlerts = computed((): Alert[] => {
  const result: Alert[] = []
  circuits.value.forEach((circuit) => {
    const days = daysUntilDate(circuit.contractEnd)
    if (days >= 0 && days <= 30) {
      result.push({
        type: t('alerts.circuitContract'),
        title: circuit.name,
        due: circuit.contractEnd,
        days,
        level: days <= 7 ? 'danger' : 'warn',
        detail: circuit.circuitNo,
        circuitId: circuit.id
      })
    }
  })
  return result.sort((a, b) => a.days - b.days)
})

// 设备保修预警
const deviceAlerts = computed((): Alert[] => {
  const result: Alert[] = []
  devices.value.forEach((device) => {
    const days = daysUntilDate(device.warrantyEnd)
    if (days >= 0 && days <= 30) {
      result.push({
        type: t('alerts.deviceWarranty'),
        title: device.name,
        due: device.warrantyEnd,
        days,
        level: days <= 7 ? 'danger' : 'warn',
        detail: device.sn,
        deviceId: device.id
      })
    }
  })
  return result.sort((a, b) => a.days - b.days)
})

// 备份失败预警（status 数据值为英文枚举：success/failed/pending）
const backupAlerts = computed((): Alert[] => {
  const result: Alert[] = []
  backups.value
    .filter((backup) => backup.status === 'failed')
    .forEach((backup) => {
      const device = devices.value.find((d) => d.id === backup.deviceId)
      result.push({
        type: t('alerts.backupFailed'),
        title: device?.name || '-',
        due: backup.createdAt,
        days: 0,
        level: 'danger',
        detail: backup.size ? `${(backup.size / 1024).toFixed(1)} KB` : '-',
        deviceId: backup.deviceId,
        backupId: backup.id
      })
    })
  return result
})

// 子网容量预警
const prefixAlerts = computed((): Alert[] => {
  const result: Alert[] = []
  prefixes.value.forEach((prefix) => {
    const used = ipAddresses.value.filter((ip) => ip.prefixId === prefix.id).length
    const percent = used / 254
    if (percent >= 0.8) {
      result.push({
        type: t('alerts.subnetCapacity'),
        title: prefix.network,
        due: `${Math.round(percent * 100)}%`,
        days: 0,
        level: 'danger',
        detail: `${used}/254`
      })
    }
  })
  return result
})

// ==================== AI异常行为检测 ====================

// AI异常检测 - 设备状态异常
const deviceAnomalies = computed((): Anomaly[] => {
  const anomalies: Anomaly[] = []

  devices.value.forEach((device) => {
    if (device.status === 'offline') {
      anomalies.push({
        id: `status-offline-${device.id}`,
        type: t('alerts.statusAbnormal'),
        title: t('alerts.deviceOffline', { name: device.name }),
        description: t('alerts.deviceOfflineDesc'),
        level: 'danger',
        target: t('alerts.device'),
        targetId: String(device.id),
        metric: t('alerts.status'),
        currentValue: t('alerts.offline'),
        threshold: t('alerts.online'),
        suggestion: t('alerts.deviceOfflineSuggestion'),
        detectedAt: new Date().toLocaleString(getLocale() || 'zh-CN')
      })
    } else if (device.status === 'repair') {
      anomalies.push({
        id: `status-repair-${device.id}`,
        type: t('alerts.statusAbnormal'),
        title: t('alerts.deviceRepairing', { name: device.name }),
        description: t('alerts.deviceRepairingDesc'),
        level: 'warn',
        target: t('alerts.device'),
        targetId: String(device.id),
        metric: t('alerts.status'),
        currentValue: t('alerts.repairing'),
        threshold: t('alerts.online'),
        suggestion: t('alerts.deviceRepairingSuggestion'),
        detectedAt: new Date().toLocaleString(locale.value || getLocale() || 'zh-CN')
      })
    }
  })

  return anomalies
})

// AI异常检测 - 专线质量异常
const circuitAnomalies = computed((): Anomaly[] => {
  const anomalies: Anomaly[] = []

  circuits.value.forEach((circuit) => {
    if (circuit.status === 'down') {
      anomalies.push({
        id: `circuit-down-${circuit.id}`,
        type: t('alerts.connectionAbnormal'),
        title: t('alerts.circuitDown', { name: circuit.name }),
        description: t('alerts.circuitDownDesc'),
        level: 'danger',
        target: t('alerts.circuit'),
        targetId: String(circuit.id),
        metric: t('alerts.status'),
        currentValue: t('alerts.down'),
        threshold: t('alerts.normal'),
        suggestion: t('alerts.circuitDownSuggestion'),
        detectedAt: new Date().toLocaleString(locale.value || getLocale() || 'zh-CN')
      })
    } else if (circuit.status === 'unstable') {
      anomalies.push({
        id: `circuit-unstable-${circuit.id}`,
        type: t('alerts.connectionAbnormal'),
        title: t('alerts.circuitUnstable', { name: circuit.name }),
        description: t('alerts.circuitUnstableDesc'),
        level: 'warn',
        target: t('alerts.circuit'),
        targetId: String(circuit.id),
        metric: t('alerts.status'),
        currentValue: t('alerts.unstable'),
        threshold: t('alerts.normal'),
        suggestion: t('alerts.circuitUnstableSuggestion'),
        detectedAt: new Date().toLocaleString(locale.value || getLocale() || 'zh-CN')
      })
    }
  })

  return anomalies
})

// AI异常检测 - 备份成功率异常
const backupAnomaly = computed((): Anomaly | null => {
  const sevenDaysAgo = new Date()
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)

  const recentBackups = backups.value.filter((backup) => {
    const backupDate = new Date(backup.createdAt)
    return backupDate >= sevenDaysAgo
  })

  if (recentBackups.length === 0) return null

  const failedCount = recentBackups.filter((b) => b.status === 'failed').length
  const successRate = ((recentBackups.length - failedCount) / recentBackups.length) * 100

  if (successRate < 80) {
    return {
      id: 'backup-success-rate',
      type: t('alerts.backupAbnormal'),
      title: t('alerts.backupSuccessRateLow'),
      description: t('alerts.backupSuccessRateDesc', { total: recentBackups.length, success: recentBackups.length - failedCount, rate: successRate.toFixed(1) }),
      level: successRate < 50 ? 'danger' : 'warn',
      target: t('alerts.system'),
      targetId: '',
      metric: t('alerts.backupSuccessRate'),
      currentValue: `${successRate.toFixed(1)}%`,
      threshold: '80%',
      suggestion: t('alerts.backupSuccessRateSuggestion'),
      detectedAt: new Date().toLocaleString(locale.value || getLocale() || 'zh-CN')
    }
  }

  return null
})

// AI异常检测 - IP池耗尽预测
const ipPoolAnomaly = computed((): Anomaly | null => {
  const anomalies: Anomaly[] = []

  prefixes.value.forEach((prefix) => {
    const used = ipAddresses.value.filter((ip) => ip.prefixId === prefix.id && ip.status !== 'available').length
    const percent = (used / 254) * 100

    if (percent >= 70) {
      const daysToExhaust = Math.ceil((254 - used) / Math.max(1, used / 30))

      anomalies.push({
        id: `ip-pool-${prefix.id}`,
        type: t('alerts.ipPoolWarning'),
        title: t('alerts.ipPoolExhausting', { network: prefix.network }),
        description: t('alerts.ipPoolExhaustingDesc', { used, percent: percent.toFixed(1), days: daysToExhaust }),
        level: percent >= 90 ? 'danger' : 'warn',
        target: t('alerts.subnet'),
        targetId: String(prefix.id),
        metric: t('alerts.ipUsage'),
        currentValue: `${percent.toFixed(1)}%`,
        threshold: '70%',
        suggestion: t('alerts.ipPoolSuggestion', { days: daysToExhaust }),
        detectedAt: new Date().toLocaleString(locale?.value || getLocale() || 'zh-CN')
      })
    }
  })

  return anomalies.sort((a, b) => (b.level === 'danger' ? 1 : 0) - (a.level === 'danger' ? 1 : 0))[0] || null
})

// 合并所有AI异常检测
const aiAnomalies = computed((): Anomaly[] => {
  const all: Anomaly[] = [
    ...deviceAnomalies.value,
    ...circuitAnomalies.value
  ]

  if (backupAnomaly.value) all.push(backupAnomaly.value)
  if (ipPoolAnomaly.value) all.push(ipPoolAnomaly.value)

  return all
})

function getLevelType(level: string) {
  const map: Record<string, string> = {
    'danger': 'danger',
    'warn': 'warning',
    'ok': 'success'
  }
  return map[level] || 'info'
}

function openRenewDialog(ip: ExpiringIP) {
  editingIP.value = ip
  renewForm.value = {
    expireAt: ''
  }
  showRenewDialog.value = true
}

function handleRenew() {
  if (!renewForm.value.expireAt) {
    ElMessage.warning(t('alerts.selectNewExpireDate'))
    return
  }
  if (!editingIP.value) return

  updateIPAddress(String(editingIP.value.id), { expireAt: renewForm.value.expireAt })
  ElMessage.success(t('alerts.ipRenewed'))
  showRenewDialog.value = false
  editingIP.value = null
}

function closeRenewDialog() {
  showRenewDialog.value = false
  editingIP.value = null
}

const handleReleaseIP = async (ip: ExpiringIP) => {
  // 失败静默与原行为一致：不传 errorMessage
  await confirmAndRun({
    message: t('alerts.confirmReleaseIP', { address: ip.address }),
    title: t('common.confirm'),
    confirmText: t('alerts.release'),
    cancelText: t('common.cancel'),
    action: () => {
      updateIPAddress(String(ip.id), {
        deviceId: null,
        usage: '',
        owner: '',
        status: 'available',
        expireAt: ''
      })
    },
    successMessage: t('alerts.ipReleased'),
  })
}

const handleViewDevice = (deviceId: string | number | undefined) => {
  if (deviceId) {
    router.push(`/devices?id=${deviceId}`)
  }
}

const handleViewCircuit = (circuitId: string | number | undefined) => {
  if (circuitId) {
    router.push(`/circuits?id=${circuitId}`)
  }
}

const handleViewAnomalyTarget = (anomaly: Anomaly) => {
  if (anomaly.target === t('alerts.device')) {
    router.push(`/devices?id=${anomaly.targetId}`)
  } else if (anomaly.target === t('alerts.circuit')) {
    router.push(`/circuits?id=${anomaly.targetId}`)
  } else if (anomaly.target === t('alerts.subnet')) {
    router.push('/ipam?tab=prefixes')
  }
}

function goToAISettings() {
  router.push('/system/ai-settings')
}
</script>

<template>
  <div class="alerts-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <p class="description">{{ t('alerts.pageDescription') }}</p>
        <el-alert
          v-if="isViewer"
          type="info"
          :closable="false"
          show-icon
          style="margin-top: 12px;"
        >
          <span>{{ t('alerts.viewerHint') }}</span>
        </el-alert>
      </div>
      <div class="header-right">
        <el-button text @click="goToAISettings">
          <el-icon><SetUp /></el-icon>
          {{ t('alerts.aiSettings') }}
        </el-button>
      </div>
    </div>

    <!-- 统计概览卡片：与告警记录同源（/summary/full），点击联动筛选 -->
    <div class="overview-cards">
      <div class="overview-card overview-card-clickable" :class="{ 'is-active': filterStatus === 'all' }" @click="applyStatusFilter('all')">
        <div class="overview-card-icon"><BellFilled /></div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('alerts.totalAlerts') }}</div>
          <div class="overview-card-value">{{ statTotal }}</div>
        </div>
      </div>
      <div class="overview-card overview-card-clickable overview-card-danger" :class="{ 'is-active': filterStatus === 'active' }" @click="applyStatusFilter('active')">
        <div class="overview-card-icon"><WarningFilled /></div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('alerts.unackedCount') }}</div>
          <div class="overview-card-value">{{ statUnacknowledged }}</div>
        </div>
      </div>
      <div class="overview-card overview-card-clickable" :class="{ 'is-active': filterStatus === 'acknowledged' }" @click="applyStatusFilter('acknowledged')">
        <div class="overview-card-icon"><Bell /></div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('alerts.ackCount') }}</div>
          <div class="overview-card-value">{{ statAcknowledged }}</div>
        </div>
      </div>
      <div class="overview-card overview-card-clickable overview-card-success" :class="{ 'is-active': filterStatus === 'resolved' }" @click="applyStatusFilter('resolved')">
        <div class="overview-card-icon"><DataLine /></div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('alerts.resolvedCount') }}</div>
          <div class="overview-card-value">{{ statResolved }}</div>
        </div>
      </div>
      <div class="overview-card overview-card-clickable overview-card-warning" :class="{ 'is-active': filterSeverity === 'critical' }" @click="applySeverityFilter(filterSeverity === 'critical' ? 'all' : 'critical')">
        <div class="overview-card-icon"><Warning /></div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('alerts.criticalAlerts') }} · {{ t('alerts.unresolved') }}</div>
          <div class="overview-card-value" :class="{ 'zero-muted': statCriticalOpen === 0 }">{{ statCriticalOpen }}</div>
        </div>
      </div>
      <div class="overview-card overview-card-clickable" :class="{ 'is-active': filterSeverity === 'warning' }" @click="applySeverityFilter(filterSeverity === 'warning' ? 'all' : 'warning')">
        <div class="overview-card-icon"><Warning /></div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('alerts.warningAlerts') }} · {{ t('alerts.unresolved') }}</div>
          <div class="overview-card-value" :class="{ 'zero-muted': statWarningOpen === 0 }">{{ statWarningOpen }}</div>
        </div>
      </div>
    </div>

    <!-- 告警记录（统一列表：合并原「通知面板」，支持认领/处理/批量/静默） -->
    <el-card class="records-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="card-title">
            <el-icon><Bell /></el-icon>
            {{ t('alerts.alertNotifications') }}
            <el-badge v-if="statUnacknowledged > 0" :value="statUnacknowledged" class="notification-badge" />
          </div>
          <div class="header-ops">
            <span v-if="selectedRecords.length > 0" class="selected-count">{{ t('alerts.selectedCount', { count: selectedRecords.length }) }}</span>
            <el-button
              v-if="canWrite && hasActiveSelection"
              type="primary"
              plain
              size="small"
              @click="handleBatchAcknowledge"
            >
              {{ t('alerts.batchAcknowledge') }}
            </el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="hasCriticalUnacknowledged"
        type="error"
        :title="t('alerts.escalatedWarning')"
        show-icon
        :closable="false"
        class="critical-banner"
      />

      <!-- 级别/状态/类型/时间四维筛选（仅作用于本列表；后端 records 不支持关键字搜索） -->
      <div class="search-bar">
        <el-select v-model="filterSeverity" class="filter-select" :placeholder="t('alerts.levelAll')" @change="currentPage = 1; loadRecords()">
          <el-option :label="t('alerts.levelAll')" value="all" />
          <el-option :label="t('alerts.critical')" value="critical" />
          <el-option :label="t('alerts.warning')" value="warning" />
          <el-option :label="t('alerts.info')" value="info" />
        </el-select>
        <el-select v-model="filterStatus" class="filter-select" :placeholder="t('alerts.statusAll')" @change="currentPage = 1; loadRecords()">
          <el-option :label="t('alerts.statusAll')" value="all" />
          <el-option :label="t('alerts.unacknowledged')" value="active" />
          <el-option :label="t('alerts.acknowledged')" value="acknowledged" />
          <el-option :label="t('alerts.resolved')" value="resolved" />
        </el-select>
        <el-select v-model="filterType" class="filter-select filter-select-type" :placeholder="t('alerts.typeAll')" @change="currentPage = 1; loadRecords()">
          <el-option :label="t('alerts.typeAll')" value="all" />
          <el-option :label="t('alerts.highLatency')" value="latency" />
          <el-option :label="t('alerts.highPacketLoss')" value="packet_loss" />
          <el-option :label="t('alerts.statusAbnormal')" value="status" />
          <el-option :label="t('alerts.circuitContractAlerts')" value="circuit_expire" />
          <el-option :label="t('alerts.offlineAlert')" value="inspection_offline" />
          <el-option :label="t('alerts.newDevice')" value="inspection_new_device" />
          <el-option :label="t('alerts.fingerprintChange')" value="inspection_fingerprint_change" />
        </el-select>
        <el-date-picker
          v-model="filterTimeRange"
          type="datetimerange"
          :start-placeholder="t('alerts.timeRangePlaceholder')"
          :end-placeholder="t('alerts.timeRangePlaceholder')"
          class="time-range"
          @change="currentPage = 1; loadRecords()"
        />
        <el-button
          v-if="filterSeverity !== 'all' || filterStatus !== 'all' || filterType !== 'all' || filterTimeRange"
          text
          @click="resetFilters"
        >
          {{ t('alerts.resetFilter') }}
        </el-button>
      </div>
      <div class="filter-scope-hint">{{ t('alerts.filterScopeHint') }}</div>

      <el-table
        :data="sortedRecords"
        v-loading="loadingRecords"
        class="records-table"
        style="width: 100%"
        stripe
        border
        @selection-change="handleSelectionChange"
        :row-class-name="recordRowClass"
      >
        <el-table-column v-if="canWrite" type="selection" width="42" :selectable="(row: AlertRecord) => row.status === 'active'" />
        <el-table-column :label="t('alerts.alertLevel')" width="86" align="center">
          <template #default="{ row }">
            <el-tag :type="severityTagType(row.severity)" size="small" effect="dark">
              {{ severityLabel(row.severity) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('alerts.alertMessage')" min-width="150">
          <template #default="{ row }">
            <div class="record-title">
              <span class="record-name">{{ alertTitle(row) }}</span>
              <el-tag v-if="row.escalated_at" type="danger" size="small" effect="plain">{{ t('alerts.escalatedWarning') }}</el-tag>
            </div>
            <div class="record-message">{{ row.message }}</div>
          </template>
        </el-table-column>
        <el-table-column :label="t('alerts.object')" width="130">
          <template #default="{ row }">
            <el-button
              v-if="recordTargetLabel(row)"
              link
              type="primary"
              size="small"
              @click="goToRecordTarget(row)"
            >
              {{ recordTargetLabel(row) }}
              <el-icon><View /></el-icon>
            </el-button>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('alerts.status')" width="96" align="center">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'resolved' ? 'success' : row.status === 'acknowledged' ? 'primary' : 'warning'"
              size="small"
              effect="plain"
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('alerts.alertTime')" width="160">
          <template #default="{ row }">
            <div>{{ formatDateTime(row.created_at) }}</div>
            <div class="record-time-relative">{{ formatRelativeTime(row.created_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column :label="t('alerts.acknowledgedBy')" width="150">
          <template #default="{ row }">
            <span v-if="row.acknowledged_by">{{ displayName(row.acknowledged_by) }}</span>
            <span v-if="row.acknowledged_at" class="record-time-sub">{{ formatDateTime(row.acknowledged_at) }}</span>
            <span v-if="!row.acknowledged_by && !row.acknowledged_at">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('alerts.resolvedBy')" width="150">
          <template #default="{ row }">
            <template v-if="row.resolved_by || row.resolve_note">
              <span v-if="row.resolved_by">{{ displayName(row.resolved_by) }}</span>
              <span v-if="row.resolved_at" class="record-time-sub">{{ formatDateTime(row.resolved_at) }}</span>
              <el-tooltip v-if="row.resolve_note" :content="row.resolve_note" placement="top">
                <div class="record-note">{{ row.resolve_note }}</div>
              </el-tooltip>
            </template>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="canWrite" :label="t('common.actions')" width="210" align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'active'"
              size="small"
              type="primary"
              plain
              @click="handleAcknowledge(row)"
            >
              {{ t('alerts.acknowledge') }}
            </el-button>
            <el-button
              v-if="row.status === 'acknowledged'"
              size="small"
              type="success"
              plain
              @click="openResolveDialog(row)"
            >
              {{ t('alerts.resolve') }}
            </el-button>
            <el-dropdown
              v-if="row.status !== 'resolved' && row.rule_id"
              trigger="click"
              @command="(cmd: number) => handleMute(row, cmd)"
            >
              <el-button size="small" plain>
                {{ t('alerts.mute') }}
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item :command="1">{{ t('alerts.mute1h') }}</el-dropdown-item>
                  <el-dropdown-item :command="8">{{ t('alerts.mute8h') }}</el-dropdown-item>
                  <el-dropdown-item :command="24">{{ t('alerts.mute24h') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="t('alerts.noRecords')" />
        </template>
      </el-table>

      <div class="pagination-bar">
        <span class="total-text">{{ t('alerts.totalItems', { total: recordsTotal }) }}</span>
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="recordsTotal"
          :page-sizes="[10, 20, 50, 100]"
          layout="sizes, prev, pager, next, jumper"
          @current-change="loadRecords"
          @size-change="currentPage = 1; loadRecords()"
        />
      </div>
    </el-card>

    <!-- Tab页签内容 -->
    <el-tabs v-model="activeTab" type="card" class="alerts-tabs">
      <!-- 实时告警 -->
      <el-tab-pane :label="t('alerts.realtimeAlerts')" name="realtime">
        <!-- AI异常检测 -->
        <el-card v-if="aiAnomalies.length > 0" class="table-card" shadow="never">
          <template #header>
            <div class="table-header">
              <div class="card-title">
                <el-icon><Warning /></el-icon>
                {{ t('alerts.aiAnomalyDetection') }}
              </div>
              <el-tag type="warning" effect="light">
                {{ aiAnomalies.length }} {{ t('alerts.anomalies') }}
              </el-tag>
            </div>
          </template>

          <AnomalyCard :anomalies="aiAnomalies" @view-target="handleViewAnomalyTarget" />
        </el-card>

        <!-- 备份失败告警 -->
        <el-card class="table-card" shadow="never">
          <template #header>
            <div class="table-header">
              <div class="card-title">
                <el-icon><DocumentCopy /></el-icon>
                {{ t('alerts.backupFailedAlerts') }}
              </div>
              <el-tag :type="backupAlerts.length > 0 ? 'danger' : 'success'" effect="light">
                {{ backupAlerts.length }} {{ t('alerts.failures') }}
              </el-tag>
            </div>
          </template>

          <div v-if="backupAlerts.length === 0" class="empty-state">
            <el-empty :description="t('alerts.noBackupFailures')" />
          </div>

          <el-table v-else class="alerts-backup-table" :data="backupAlerts" style="width: 100%" stripe border>
            <el-table-column :label="t('alerts.alertType')" min-width="100">
              <template #default="{ row }">
                <el-tag :type="getLevelType(row.level)" effect="dark" size="small">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('alerts.device')" min-width="150">
              <template #default="{ row }">{{ row.title }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.backupSize')" min-width="100">
              <template #default="{ row }">{{ row.detail || '-' }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.failureTime')" min-width="130">
              <template #default="{ row }">{{ row.due }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.severity')" min-width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="getLevelType(row.level)" effect="light" size="small">
                  {{ row.level === 'danger' ? t('alerts.critical') : t('alerts.warning') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" min-width="100" align="center">
              <template #default="{ row }">
                <el-button v-if="row.deviceId" type="primary" link size="small" @click="handleViewDevice(row.deviceId)">
                  <el-icon><View /></el-icon>
                  {{ t('common.viewDetail') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 到期预警 -->
      <el-tab-pane :label="t('alerts.expiringAlerts')" name="expiring">
        <!-- 专线合同预警 -->
        <el-card class="table-card" shadow="never">
          <template #header>
            <div class="table-header">
              <div class="card-title">
                <el-icon><Connection /></el-icon>
                {{ t('alerts.circuitContractAlerts') }}
              </div>
              <el-tag :type="circuitAlerts.length > 0 ? 'warning' : 'success'" effect="light">
                {{ circuitAlerts.length }} {{ t('alerts.alerts') }}
              </el-tag>
            </div>
          </template>

          <div v-if="circuitAlerts.length === 0" class="empty-state">
            <el-empty :description="t('alerts.noCircuitContractAlerts')" />
          </div>

          <el-table v-else class="alerts-circuit-table" :data="circuitAlerts" style="width: 100%" stripe border>
            <el-table-column :label="t('alerts.alertType')" min-width="100">
              <template #default="{ row }">
                <el-tag :type="getLevelType(row.level)" effect="dark" size="small">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('alerts.circuit')" min-width="150">
              <template #default="{ row }">{{ row.title }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.circuitNo')" min-width="100">
              <template #default="{ row }">{{ row.detail || '-' }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.contractExpire')" min-width="110">
              <template #default="{ row }">{{ row.due }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.daysRemaining')" min-width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="getLevelType(row.level)" effect="light" size="small">
                  {{ row.days > 0 ? `${row.days} ${t('alerts.days')}` : t('alerts.expired') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" min-width="100" align="center">
              <template #default="{ row }">
                <el-button v-if="row.circuitId" type="primary" link size="small" @click="handleViewCircuit(row.circuitId)">
                  <el-icon><View /></el-icon>
                  {{ t('common.viewDetail') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 设备保修预警 -->
        <el-card class="table-card" shadow="never">
          <template #header>
            <div class="table-header">
              <div class="card-title">
                <el-icon><Monitor /></el-icon>
                {{ t('alerts.deviceWarrantyAlerts') }}
              </div>
              <el-tag :type="deviceAlerts.length > 0 ? 'warning' : 'success'" effect="light">
                {{ deviceAlerts.length }} {{ t('alerts.alerts') }}
              </el-tag>
            </div>
          </template>

          <div v-if="deviceAlerts.length === 0" class="empty-state">
            <el-empty :description="t('alerts.noDeviceWarrantyAlerts')" />
          </div>

          <el-table v-else class="alerts-device-table" :data="deviceAlerts" style="width: 100%" stripe border>
            <el-table-column :label="t('alerts.alertType')" min-width="100">
              <template #default="{ row }">
                <el-tag :type="getLevelType(row.level)" effect="dark" size="small">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('alerts.device')" min-width="150">
              <template #default="{ row }">{{ row.title }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.serialNumber')" min-width="100">
              <template #default="{ row }">{{ row.detail || '-' }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.warrantyExpire')" min-width="110">
              <template #default="{ row }">{{ row.due }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.daysRemaining')" min-width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="getLevelType(row.level)" effect="light" size="small">
                  {{ row.days > 0 ? `${row.days} ${t('alerts.days')}` : t('alerts.expired') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" min-width="100" align="center">
              <template #default="{ row }">
                <el-button v-if="row.deviceId" type="primary" link size="small" @click="handleViewDevice(row.deviceId)">
                  <el-icon><View /></el-icon>
                  {{ t('common.viewDetail') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- IP到期预警 -->
        <el-card v-if="!isViewer" class="table-card" shadow="never">
          <template #header>
            <div class="table-header">
              <div class="card-title">
                <el-icon><Calendar /></el-icon>
                {{ t('alerts.ipExpiringAlerts') }}
              </div>
              <el-tag :type="expiringIPs.length > 0 ? 'warning' : 'success'" effect="light">
                {{ expiringIPs.length }} {{ t('alerts.alerts') }}
              </el-tag>
            </div>
          </template>

          <div v-if="expiringIPs.length === 0" class="empty-state">
            <el-empty :description="t('alerts.noExpiringIPs')" />
          </div>

          <el-table
            v-else
            class="alerts-ip-expire-table"
            :data="expiringIPs"
            style="width: 100%"
            stripe
            border
          >
            <el-table-column prop="address" :label="t('alerts.ipAddress')" min-width="120">
              <template #default="{ row }">
                <code class="ip-address">{{ row.address }}</code>
              </template>
            </el-table-column>
            <el-table-column prop="prefixId" :label="t('alerts.subnet')" min-width="140">
              <template #default="{ row }">{{ prefixNetwork(row.prefixId) }}</template>
            </el-table-column>
            <el-table-column prop="usage" :label="t('alerts.usage')" min-width="100" />
            <el-table-column prop="owner" :label="t('alerts.owner')" min-width="80" />
            <el-table-column prop="expireAt" :label="t('alerts.expireDate')" min-width="110" />
            <el-table-column :label="t('alerts.daysRemaining')" min-width="100" align="center">
              <template #default="{ row }">
                <el-tag
                  :type="row.remainingDays <= 7 ? 'danger' : 'warning'"
                  effect="light"
                  :class="{ 'bold': row.remainingDays <= 7 }"
                >
                  {{ row.remainingDays }} {{ t('alerts.days') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" min-width="140" align="center">
              <template #default="{ row }">
                <el-button
                  link
                  type="primary"
                  size="small"
                  @click="openRenewDialog(row)"
                >
                  <el-icon><Refresh /></el-icon>
                  {{ t('alerts.renew') }}
                </el-button>
                <el-button
                  link
                  type="danger"
                  size="small"
                  @click="handleReleaseIP(row)"
                >
                  <el-icon><CircleClose /></el-icon>
                  {{ t('alerts.release') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 容量预警 -->
      <el-tab-pane v-if="!isViewer" :label="t('alerts.capacityAlerts')" name="capacity">
        <!-- 子网容量预警 -->
        <el-card class="table-card" shadow="never">
          <template #header>
            <div class="table-header">
              <div class="card-title">
                <el-icon><SetUp /></el-icon>
                {{ t('alerts.subnetCapacityAlerts') }}
              </div>
              <el-tag :type="prefixAlerts.length > 0 ? 'danger' : 'success'" effect="light">
                {{ prefixAlerts.length }} {{ t('alerts.alerts') }}
              </el-tag>
            </div>
          </template>

          <div v-if="prefixAlerts.length === 0" class="empty-state">
            <el-empty :description="t('alerts.noSubnetCapacityAlerts')" />
          </div>

          <el-table v-else class="alerts-prefix-table" :data="prefixAlerts" style="width: 100%" stripe border>
            <el-table-column :label="t('alerts.alertType')" min-width="100">
              <template #default="{ row }">
                <el-tag :type="getLevelType(row.level)" effect="dark" size="small">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('alerts.subnet')" min-width="150">
              <template #default="{ row }">{{ row.title }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.ipUsage')" min-width="100">
              <template #default="{ row }">{{ row.detail || '-' }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.currentUsage')" min-width="100">
              <template #default="{ row }">{{ row.due }}</template>
            </el-table-column>
            <el-table-column :label="t('alerts.severity')" min-width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="getLevelType(row.level)" effect="light" size="small">
                  {{ row.level === 'danger' ? t('alerts.critical') : t('alerts.warning') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" min-width="100" align="center">
              <template #default>
                <el-button type="primary" link size="small" @click="router.push('/ipam?tab=prefixes')">
                  <el-icon><View /></el-icon>
                  {{ t('alerts.manageSubnet') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- IP池耗尽预测 -->
        <el-card v-if="ipPoolAnomaly" class="table-card" shadow="never">
          <template #header>
            <div class="table-header">
              <div class="card-title">
                <el-icon><DataLine /></el-icon>
                {{ t('alerts.ipPoolWarning') }}
              </div>
              <el-tag :type="ipPoolAnomaly.level === 'danger' ? 'danger' : 'warning'" effect="light">
                {{ t('alerts.aiPrediction') }}
              </el-tag>
            </div>
          </template>

          <AnomalyCard v-if="ipPoolAnomaly" :anomalies="[ipPoolAnomaly]" @view-target="handleViewAnomalyTarget" />
        </el-card>
      </el-tab-pane>

      <!-- 概览（保留用于向后兼容，但默认不显示） -->
      <el-tab-pane :label="t('alerts.overview')" name="overview" v-if="false">
        <!-- AI智能预测中心 -->
        <el-card class="table-card" shadow="never">
          <template #header>
            <div class="table-header">
              <div class="card-title">
                <el-icon><InfoFilled /></el-icon>
                {{ t('alerts.aiPredictionCenter') }}
              </div>
              <el-tag type="primary" effect="light">
                <InfoFilled style="width: 16px; height: 16px; margin-right: 4px;" />
                {{ t('alerts.llmPowered') }}
              </el-tag>
            </div>
          </template>
          <AIPrediction />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 处理告警对话框（必填备注 + 二次确认） -->
    <ElDialog
      v-model="showResolveDialog"
      :title="t('alerts.resolveAlert')"
      width="520px"
      :close-on-click-modal="false"
    >
      <div v-if="resolvingRecord" class="resolve-form">
        <div class="form-row">
          <label>{{ t('alerts.alertName') }}</label>
          <span>{{ alertTitle(resolvingRecord) }}</span>
        </div>
        <div class="form-row form-row-top">
          <label>{{ t('alerts.alertMessage') }}</label>
          <span class="resolve-message">{{ resolvingRecord.message }}</span>
        </div>
        <div class="form-row form-row-top">
          <label>{{ t('alerts.resolveNoteLabel') }} *</label>
          <el-input
            v-model="resolveNote"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            :placeholder="t('alerts.resolveNotePlaceholder')"
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="showResolveDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="resolveSubmitting" @click="confirmResolve">{{ t('alerts.resolve') }}</el-button>
      </template>
    </ElDialog>

    <!-- IP续期对话框 -->
    <ElDialog
      v-model="showRenewDialog"
      :title="t('alerts.ipRenewal')"
      width="480px"
      :close-on-click-modal="false"
    >
      <div v-if="editingIP" class="renew-form">
        <div class="form-row">
          <label>{{ t('alerts.ipAddress') }}</label>
          <code>{{ editingIP.address }}</code>
        </div>
        <div class="form-row">
          <label>{{ t('alerts.originalExpireDate') }}</label>
          <span>{{ editingIP.expireAt }}</span>
        </div>
        <div class="form-row">
          <label>{{ t('alerts.newExpireDate') }} *</label>
          <el-date-picker
            v-model="renewForm.expireAt"
            type="date"
            :placeholder="t('alerts.selectNewExpireDate')"
            style="width: 100%"
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="closeRenewDialog">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleRenew">{{ t('alerts.confirmRenew') }}</el-button>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.alerts-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.header-left .description {
  font-size: 14px;
  color: var(--el-text-color-secondary);
  margin: 0;
}

.header-ops {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* ==================== 统计概览卡片 ==================== */
.overview-cards {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
}

.overview-card {
  background: var(--el-bg-color);
  border-radius: 12px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  border: 1px solid var(--el-border-color);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.overview-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--el-border-color), transparent);
}

.overview-card-clickable {
  cursor: pointer;
}

.overview-card-clickable:hover {
  transform: translateY(-4px);
  box-shadow: var(--el-box-shadow-light);
}

.overview-card.is-active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
}

.overview-card.is-active::before {
  background: linear-gradient(90deg, var(--el-color-primary), transparent);
}

.overview-card-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--el-fill-color-light);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: var(--el-color-primary);
  transition: transform 0.3s ease;
  flex-shrink: 0;
}

.overview-card:hover .overview-card-icon {
  transform: scale(1.1);
}

.overview-card-danger {
  border-color: var(--el-color-danger-light-7);
}

.overview-card-danger::before {
  background: linear-gradient(90deg, var(--el-color-danger), transparent);
}

.overview-card-danger .overview-card-icon {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
}

.overview-card-danger .overview-card-value {
  color: var(--el-color-danger);
}

.overview-card-warning {
  border-color: var(--el-color-warning-light-7);
}

.overview-card-warning::before {
  background: linear-gradient(90deg, var(--el-color-warning), transparent);
}

.overview-card-warning .overview-card-icon {
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning);
}

.overview-card-warning .overview-card-value {
  color: var(--el-color-warning);
}

.overview-card-success {
  border-color: var(--el-color-success-light-7);
}

.overview-card-success::before {
  background: linear-gradient(90deg, var(--el-color-success), transparent);
}

.overview-card-success .overview-card-icon {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
}

.overview-card-success .overview-card-value {
  color: var(--el-color-success);
}

.overview-card-content {
  flex: 1;
  min-width: 0;
}

.overview-card-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.overview-card-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
}

.zero-muted {
  color: var(--el-text-color-placeholder);
}

/* ==================== 告警记录卡片 ==================== */
.records-card {
  border-radius: 8px;
}

.records-card :deep(.el-card__header) {
  padding: 14px 20px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.card-title .el-icon {
  color: var(--el-color-primary);
}

.notification-badge {
  margin-left: 8px;
}

.selected-count {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.critical-banner {
  margin-bottom: 12px;
}

/* ==================== 筛选栏 ==================== */
.search-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-select {
  width: 140px;
}

.filter-select-type {
  width: 170px;
}

.time-range {
  width: 340px;
}

.filter-scope-hint {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 8px;
}

/* ==================== 记录表格 ==================== */
.records-table {
  margin-top: 12px;
}

.records-table :deep(.row-critical-open) {
  background: var(--el-color-danger-light-9);
}

.records-table :deep(.row-critical-open:hover > td) {
  background: var(--el-color-danger-light-8);
}

.record-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.record-name {
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.record-message {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.record-time-relative {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 2px;
}

.record-time-sub {
  display: block;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.record-note {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  max-width: 130px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.total-text {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

/* ==================== 处理弹窗 ==================== */
.resolve-form {
  padding: 4px 0;
}

.form-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.form-row-top {
  align-items: flex-start;
}

.form-row label {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-regular);
  flex-shrink: 0;
}

.form-row code {
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 14px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  padding: 4px 8px;
  border-radius: 4px;
}

.form-row span {
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.resolve-message {
  text-align: right;
  color: var(--el-text-color-secondary) !important;
  max-width: 320px;
}

.resolve-form .el-textarea {
  margin-top: 8px;
}

/* ==================== 预警 Tab ==================== */
.alerts-tabs {
  background: transparent;
}

.alerts-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
  background: var(--el-bg-color);
  padding: 0 16px;
  border-radius: 8px 8px 0 0;
  border: 1px solid var(--el-border-color);
}

.alerts-tabs :deep(.el-tabs__content) {
  padding: 0;
}

.table-card {
  border-radius: 8px;
  margin-bottom: 16px;
}

.empty-state {
  padding: 40px;
  text-align: center;
}

.ip-address {
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 14px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  padding: 4px 8px;
  border-radius: 4px;
}

.bold {
  font-weight: bold;
}

.renew-form {
  padding: 16px 0;
}

@media (max-width: 1400px) {
  .overview-cards {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 1200px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .time-range {
    width: 100%;
  }
}

@media (max-width: 768px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .page-header {
    flex-direction: column;
    gap: 16px;
  }

  .filter-select,
  .filter-select-type,
  .time-range {
    width: 100%;
  }
}

.alerts-ip-expire-table :deep(.cell),
.alerts-device-table :deep(.cell),
.alerts-circuit-table :deep(.cell),
.alerts-backup-table :deep(.cell),
.alerts-prefix-table :deep(.cell) {
  line-height: 1.5;
}

.alerts-ip-expire-table :deep(.el-table__cell),
.alerts-device-table :deep(.el-table__cell),
.alerts-circuit-table :deep(.el-table__cell),
.alerts-backup-table :deep(.el-table__cell),
.alerts-prefix-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>
