<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/store/auth'

import { getDashboardStats, getPrefixesUsage, getRecentLogs, getDeviceTypes, getCircuitTypes, type DashboardStats, type PrefixUsage, type AuditLogItem, type DeviceTypeItem, type CircuitTypeItem } from '@/api/dashboard'
import { applyKeywordFilter } from '@/lib/filters'
import EventTimeline from './EventTimeline.vue'
import { useRouter } from 'vue-router'
import { Plus, MapLocation, Connection, Clock, DataBoard, FolderOpened, Lightning } from '@element-plus/icons-vue'

function getOnlineDevicesColor(online: number, total: number): string {
  if (online === 0) return '#F56C6C' // 全部离线，红色
  if (online > 0 && online < total) return '#E6A23C' // 部分在线，橙色
  return '#67C23A' // 全部在线，绿色
}

const { t, locale } = useI18n()
const authStore = useAuthStore()
const router = useRouter()

// 快捷操作：按权限点显隐（hasPermission 对 super_admin 直通）
const quickActions = computed(() => {
  const actions = []
  const can = (perm: string) => authStore.hasPermission(perm)

  if (can('devices:write')) {
    actions.push({
      icon: 'Plus',
      label: t('dashboard.actAddDevice'),
      path: '/devices',
      color: '#409EFF',
      description: t('dashboard.actAddDeviceDesc')
    })
  }
  if (can('circuits:write')) {
    actions.push({
      icon: 'Globe',
      label: t('dashboard.actAddCircuit'),
      path: '/circuits',
      color: '#67C23A',
      description: t('dashboard.actAddCircuitDesc')
    })
  }
  if (can('ipam:write')) {
    actions.push({
      icon: 'Network',
      label: t('dashboard.actAllocIp'),
      path: '/ipam',
      color: '#E6A23C',
      description: t('dashboard.actAllocIpDesc')
    })
  }
  // 智能巡检入口在报告中心（/inspection 已 redirect 到 /reports）
  if (can('inspection:write')) {
    actions.push({
      icon: 'Clock',
      label: t('dashboard.actInspection'),
      path: '/reports',
      color: '#909399',
      description: t('dashboard.actInspectionDesc')
    })
  }
  if (can('backups:read')) {
    actions.push({
      icon: 'Database',
      label: t('dashboard.actBackup'),
      path: '/backups',
      color: '#F56C6C',
      description: t('dashboard.actBackupDesc')
    })
  }
  if (can('sites:read')) {
    actions.push({
      icon: 'FolderOpened',
      label: t('dashboard.actViewSites'),
      path: '/sites',
      color: '#9C27B0',
      description: t('dashboard.actViewSitesDesc')
    })
  }

  return actions
})

function navigateTo(path: string) {
  router.push(path)
}

// 用户权限判断
const isAdmin = computed(() => authStore.user?.role === 'super_admin')
const isEngineer = computed(() => authStore.user?.role === 'engineer')

// 根据权限点确定可见的概览卡片
const visibleCards = computed(() => {
  const cards = []
  // 站点/设备/带宽基础统计对所有登录用户可见
  cards.push('sites', 'devices', 'bandwidth')
  // IP 统计、备份统计需要对应读权限
  if (authStore.hasPermission('ipam:read')) cards.push('ipam')
  if (authStore.hasPermission('backups:read')) cards.push('backups')
  // 系统健康状态需要告警读权限
  if (authStore.hasPermission('alerts:read')) cards.push('health')
  return cards
})

// 真实数据状态
const dashboardStats = ref<DashboardStats | null>(null)
const prefixesUsage = ref<PrefixUsage[]>([])
const recentLogs = ref<AuditLogItem[]>([])
const deviceTypes = ref<DeviceTypeItem[]>([])
const circuitTypes = ref<CircuitTypeItem[]>([])
const loading = ref(true)
const searchQuery = ref('')
const backupTimeRange = ref('all')
// 数据更新时间（每次加载刷新）
const lastUpdated = ref('')

const timeRangeOptions = [
  { label: t('dashboard.allTime'), value: 'all' },
  { label: t('dashboard.last24h'), value: '24h' },
  { label: t('dashboard.last7d'), value: '7d' },
  { label: t('dashboard.last15d'), value: '15d' },
  { label: t('dashboard.last30d'), value: '30d' }
]

// 设备品牌颜色映射（后端 /dashboard/device-types 按品牌分组，key 为品牌英文标识）
const deviceTypeColors: Record<string, string> = {
  'huawei': '#E6A23C',
  'cisco': '#409EFF',
  'ruijie': '#F56C6C',
  'h3c': '#67C23A',
  'juniper': '#722ED1',
  'fortinet': '#36BFFA',
  'paloalto': '#FF6347',
  'arista': '#00CED1',
  'mikrotik': '#F7BA1E',
  'dell': '#4682B4',
  'hp': '#9932CC',
  'linux': '#909399',
  'other': '#C0C4CC',
  'unknown': '#909399'
}



const filteredLogs = computed(() =>
  applyKeywordFilter(recentLogs.value, searchQuery.value, ['action', 'resource', 'detail'])
)

// 格式化时间
function formatTime(dateString: string) {
  const date = new Date(dateString)
  return date.toLocaleString(locale.value || t('common.locale'), {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
}

// 操作日志翻译映射
function getActionTranslation(action: string): string {
  // 数据库 action 值中英文混杂（用户登录/删除用户 为中文，delete/create 为英文枚举），统一映射
  const actionMap: Record<string, string> = {
    '用户登录': t('common.userLogin'),
    '登录成功': t('common.loginSuccess'),
    '登录失败': t('common.loginFailed'),
    'delete': t('dashboard.actDelete'),
    'create': t('dashboard.actCreate'),
    'update': t('dashboard.actUpdate'),
    'test': t('dashboard.actTest'),
    'import': t('dashboard.actImport'),
    'notification_update': t('dashboard.actNotificationUpdate'),
    'notification_test': t('dashboard.actNotificationTest'),
    'brand_update': t('dashboard.actBrandUpdate'),
    'brand_reset': t('dashboard.actBrandReset'),
    'logo_upload': t('dashboard.actLogoUpload'),
    'logo_delete': t('dashboard.actLogoDelete')
  }
  return actionMap[action] || action
}

// 资源类型翻译映射
function getResourceTranslation(resource: string): string {
  const resourceMap: Record<string, string> = {
    '认证': t('common.auth'),
    '系统': t('common.system'),
    'system_settings': t('dashboard.resSystemSettings'),
    '用户': t('dashboard.resUser'),
    '设备': t('dashboard.resDevice'),
    '专线': t('dashboard.resCircuit'),
    'IP地址': t('dashboard.resIp'),
    '报告': t('dashboard.resReport')
  }
  return resourceMap[resource] || resource
}

// 详情翻译映射
function getDetailTranslation(detail: string): string {
  if (detail.includes('用户 ') && detail.includes(' 登录系统')) {
    const username = detail.replace('用户 ', '').replace(' 登录系统', '')
    return t('common.userLogin') + ' - ' + username
  }
  return detail
}



// 获取设备类型颜色
function getDeviceTypeColor(type: string): string {
  return deviceTypeColors[type] || '#909399'
}

// 带宽格式化
function formatBandwidth(mbps: number): string {
  if (mbps >= 1000) {
    return `${(mbps / 1000).toFixed(1)} Gbps`
  }
  return `${mbps} Mbps`
}

async function loadDashboardData() {
  loading.value = true
  try {
    const [stats, prefixes, logs, deviceTypesData, circuitTypesData] = await Promise.all([
      getDashboardStats(backupTimeRange.value),
      getPrefixesUsage(),
      getRecentLogs(8),
      getDeviceTypes(),
      getCircuitTypes()
    ])
    dashboardStats.value = stats
    prefixesUsage.value = prefixes
    recentLogs.value = logs
    deviceTypes.value = deviceTypesData
    circuitTypes.value = circuitTypesData
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch (error) {
    console.error('Failed to load dashboard data:', error)
  } finally {
    loading.value = false
  }
}

function handleTimeRangeChange() {
  loadDashboardData()
}

onMounted(() => {
  loadDashboardData()
})
</script>

<template>
  <div class="engineer-dashboard" v-loading="loading">
    <div class="data-updated-bar" v-if="lastUpdated">{{ t('dashboard.updatedAt', { time: lastUpdated }) }}</div>
    <div class="overview-cards">
      <div v-if="visibleCards.includes('sites')" class="overview-card" @click="navigateTo('/sites')">
        <div class="overview-card-label">{{ t('sites.title') }}</div>
        <div class="overview-card-value">{{ dashboardStats?.sites.total || 0 }}</div>
        <div class="overview-card-trend">{{ t('topology.deviceCount') }}</div>
        <div class="overview-card-arrow">›</div>
      </div>
      <div v-if="visibleCards.includes('devices')" class="overview-card overview-card-purple" @click="navigateTo('/devices')">
        <div class="overview-card-label">{{ t('devices.title') }}</div>
        <div class="overview-card-value">{{ dashboardStats?.devices.total || 0 }}</div>
        <div class="overview-card-trend" :style="{ color: getOnlineDevicesColor(dashboardStats?.devices.online || 0, dashboardStats?.devices.total || 0) }">
          {{ dashboardStats?.devices.online || 0 }} {{ t('dashboard.onlineDevices') }}
        </div>
        <div class="overview-card-arrow">›</div>
      </div>
      <div v-if="visibleCards.includes('bandwidth')" class="overview-card overview-card-success" @click="navigateTo('/circuits')">
        <div class="overview-card-label">{{ t('circuits.bandwidth') }}</div>
        <div class="overview-card-value">{{ formatBandwidth(dashboardStats?.circuits.bandwidth || 0) }}</div>
        <div class="overview-card-trend">总专线带宽</div>
        <div class="overview-card-sub-trend">共 {{ dashboardStats?.circuits.total || 0 }} 条专线</div>
        <div class="overview-card-arrow">›</div>
      </div>
      <div v-if="visibleCards.includes('ipam')" class="overview-card overview-card-blue" @click="navigateTo('/ipam')">
        <div class="overview-card-label">IP使用率</div>
        <div class="overview-card-value">{{ dashboardStats?.ip.percent || 0 }}%</div>
        <div class="overview-card-trend">{{ dashboardStats?.ip.used || 0 }}/{{ dashboardStats?.ip.total || 0 }} 已分配</div>
        <div class="overview-card-arrow">›</div>
      </div>
      <div v-if="visibleCards.includes('backups')" class="overview-card overview-card-warning" @click="navigateTo('/backups')">
        <div class="overview-card-header">
          <div class="overview-card-label">{{ t('backups.title') }}</div>
          <el-select 
            v-model="backupTimeRange" 
            @change="handleTimeRangeChange"
            size="small" 
            class="time-range-select"
            :placeholder="t('dashboard.selectTimeRange')"
          >
            <el-option 
              v-for="option in timeRangeOptions" 
              :key="option.value" 
              :label="option.label" 
              :value="option.value" 
            />
          </el-select>
        </div>
        <div class="overview-card-value">{{ dashboardStats?.backups.successful || 0 }}/{{ dashboardStats?.backups.failed || 0 }}</div>
        <div class="overview-card-trend">{{ t('backups.backupSuccess') }} / {{ t('backups.backupFailed') }}</div>
        <div class="overview-card-hint">{{ t('dashboard.backupRangeHint') }}</div>
        <div class="overview-card-arrow">›</div>
      </div>
      <div v-if="visibleCards.includes('health')" class="overview-card" :style="{ borderLeftColor: dashboardStats?.alerts.pending ? 'var(--accent-danger)' : 'var(--accent-success)' }" @click="navigateTo('/alerts?status=pending')">
        <div class="overview-card-label">{{ t('dashboard.pendingAlerts') }}</div>
        <div class="overview-card-value" :style="{ color: dashboardStats?.alerts.pending ? 'var(--accent-danger)' : 'var(--accent-success)' }">{{ dashboardStats?.alerts.pending || 0 }}</div>
        <div class="overview-card-trend" :style="{ color: dashboardStats?.alerts.pending ? 'var(--accent-danger)' : 'var(--accent-success)' }">
          {{ dashboardStats?.alerts.pending ? t('dashboard.hasPendingAlerts') : t('dashboard.noPendingAlerts') }}
        </div>
        <div class="overview-card-arrow">›</div>
      </div>
    </div>

    <div class="main-content">
      <div class="side-panel">
        <div class="quick-actions-panel">
          <div class="panel-header">
            <el-icon><Lightning /></el-icon>
            <span>{{ t('dashboard.quickActions') }}</span>
          </div>
          <div class="quick-actions-grid">
            <div 
              v-for="action in quickActions" 
              :key="action.path" 
              class="quick-action-item"
              @click="navigateTo(action.path)"
              :title="action.description"
            >
              <div class="action-icon" :style="{ backgroundColor: action.color + '15', color: action.color }">
                <el-icon><component :is="action.icon === 'Plus' ? Plus : action.icon === 'Globe' ? MapLocation : action.icon === 'Network' ? Connection : action.icon === 'Clock' ? Clock : action.icon === 'Database' ? DataBoard : FolderOpened" /></el-icon>
              </div>
              <span class="action-label">{{ action.label }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="center-panel">
        <EventTimeline />
      </div>

      <div class="side-panel">
        <div v-if="isAdmin || isEngineer" class="circuit-types-card">
          <div class="card-title">
            <el-icon><Connection /></el-icon>
            {{ t('circuits.type') }}{{ t('common.distribution') }}
          </div>
          <div class="circuit-types-section">
            <div v-for="circuitType in circuitTypes" :key="circuitType.type" class="circuit-type-item" :style="{ borderLeftColor: circuitType.color }">
              <div class="circuit-type-header">
                <span class="circuit-type-dot" :style="{ backgroundColor: circuitType.color }"></span>
                <span class="circuit-type-name">{{ circuitType.name }}</span>
              </div>
              <div class="circuit-type-stats">
                <div class="circuit-stat">
                  <span class="circuit-stat-label">{{ t('common.total') }}</span>
                  <span class="circuit-stat-value">{{ circuitType.value }}</span>
                </div>
                <div class="circuit-stat">
                  <span class="circuit-stat-label">{{ t('circuits.bandwidth') }}</span>
                  <span class="circuit-stat-value">{{ formatBandwidth(circuitType.bandwidth) }}</span>
                </div>
              </div>
            </div>
            <el-empty v-if="circuitTypes.length === 0" :description="t('common.noData')" />
          </div>
        </div>
      </div>
    </div>

    <div class="bottom-grid">
      <el-card v-if="authStore.hasPermission('logs:read')" class="table-card" shadow="never">
        <template #header>
          <div class="card-title">
            <el-icon><Monitor /></el-icon>
            {{ t('dashboard.subnetUsage') }}
          </div>
        </template>
        <div class="usage-section">
          <div v-for="prefix in prefixesUsage" :key="prefix.id" class="usage-row">
            <div class="usage-name">
              <strong>{{ prefix.network }}</strong>
              <span class="usage-tag">{{ prefix.usage }}</span>
            </div>
            <div class="usage-bar-wrapper">
              <div class="usage-bar">
                <div 
                  class="usage-fill" 
                  :class="{ 'danger': prefix.usage_percent > 80 }"
                  :style="{ width: `${prefix.usage_percent}%` }"
                ></div>
              </div>
              <span class="usage-percent">{{ prefix.usage_percent }}%</span>
            </div>
          </div>
          <el-empty v-if="prefixesUsage.length === 0" :description="t('common.noData')" />
        </div>
      </el-card>

      <el-card class="table-card" shadow="never">
        <template #header>
          <div class="card-title">
            <el-icon><Cpu /></el-icon>
            {{ t('dashboard.brandDistribution') }}
          </div>
        </template>
        <div class="device-types-section">
          <div v-for="deviceType in deviceTypes" :key="deviceType.type" class="device-type-row">
            <div class="device-type-info">
              <span class="device-type-dot" :style="{ backgroundColor: getDeviceTypeColor(deviceType.type) }"></span>
              <span class="device-type-name">{{ deviceType.name }}</span>
            </div>
            <div class="device-type-count">{{ deviceType.value }}</div>
          </div>
          <el-empty v-if="deviceTypes.length === 0" :description="t('common.noData')" />
        </div>
      </el-card>

      <el-card v-if="authStore.hasPermission('logs:read')" class="table-card" shadow="never">
        <template #header>
          <div class="card-title">
            <el-icon><Clock /></el-icon>
            {{ t('dashboard.recentActivity') }}
          </div>
        </template>
        <el-input
          v-model="searchQuery"
          :placeholder="t('common.search') + '...'"
          prefix-icon="Search"
          clearable
          style="margin-bottom: 16px"
        />
        <div class="activity-list">
          <div v-for="log in filteredLogs" :key="log.id" class="activity-item">
            <div class="activity-icon">
              <el-icon>
                <Document />
              </el-icon>
            </div>
            <div class="activity-content">
              <div class="activity-header">
                <strong>{{ getActionTranslation(log.action) }}</strong>
                <span class="activity-resource">· {{ getResourceTranslation(log.resource) }}</span>
              </div>
              <div class="activity-detail">{{ getDetailTranslation(log.detail) }}</div>
              <div class="activity-meta">
                <span v-if="log.user" class="activity-user">{{ log.user }}</span>
                <span v-if="log.ip_address" class="activity-ip">{{ log.ip_address }}</span>
                <span class="activity-time">{{ log.created_at ? formatTime(log.created_at) : '-' }}</span>
              </div>
            </div>
          </div>
          <el-empty v-if="filteredLogs.length === 0" :description="t('common.noData')" />
        </div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.engineer-dashboard {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.data-updated-bar {
  font-size: 12px;
  color: var(--text-muted);
  text-align: right;
}

.overview-card-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}


.overview-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}

.overview-card {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid var(--text-secondary);
  transition: all 0.2s ease;
  position: relative;
  cursor: pointer;
  overflow: hidden;
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.overview-card-success { border-left-color: var(--accent-success); }
.overview-card-warning { border-left-color: #faad14; }
.overview-card-blue { border-left-color: var(--accent-primary); }
.overview-card-purple { border-left-color: #722ed1; }

.overview-card-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.overview-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.time-range-select {
  width: 110px;
}

.overview-card-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
  margin-bottom: 4px;
}

.overview-card-trend {
  font-size: 12px;
  color: var(--text-muted);
}

.overview-card-sub-trend {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.overview-card-arrow {
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 24px;
  color: #e8e8e8;
  transition: all 0.2s ease;
}

.overview-card:hover .overview-card-arrow {
  color: var(--accent-primary);
  right: 12px;
}

.main-content {
  display: grid;
  grid-template-columns: 280px 1fr 280px;
  gap: 20px;
}

@media (max-width: 1200px) {
  .main-content {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .bottom-grid {
    grid-template-columns: 1fr;
  }

  .quick-actions-grid {
    grid-template-columns: repeat(2, 1fr) !important;
  }
}

.side-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.center-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.bottom-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
}

.circuit-types-card {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.circuit-types-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}

.circuit-type-item {
  border-radius: 6px;
  padding: 12px 14px;
  border-left: 3px solid #e8e8e8;
  background: var(--bg-secondary);
  transition: all 0.2s ease;
}

.circuit-type-item:hover {
  background: #f5f7fa;
}

.circuit-type-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.circuit-type-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.circuit-type-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}

.circuit-type-stats {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.circuit-stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.circuit-stat-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.circuit-stat-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.table-card {
  border-radius: 8px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--text-primary);
  font-size: 15px;
}

.usage-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.usage-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.usage-name {
  display: flex;
  align-items: center;
  gap: 10px;
}

.usage-tag {
  font-size: 12px;
  color: var(--text-secondary);
  background: #f5f7fa;
  padding: 2px 8px;
  border-radius: 4px;
}

.usage-bar-wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
}

.usage-bar {
  flex: 1;
  height: 10px;
  background: var(--bg-tertiary);
  border-radius: 5px;
  overflow: hidden;
}

.usage-fill {
  height: 100%;
  background: var(--accent-success);
  transition: width 0.3s ease;
}

.usage-fill.danger {
  background: var(--accent-danger);
}

.usage-percent {
  font-size: 12px;
  color: var(--text-secondary);
  width: 40px;
  text-align: right;
}

.device-types-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.device-type-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-light);
}

.device-type-row:last-child {
  border-bottom: none;
}

.device-type-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.device-type-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.device-type-name {
  font-size: 14px;
  color: var(--text-primary);
}

.device-type-count {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.activity-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.activity-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 6px;
}

.activity-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e6f7ff;
  border-radius: 6px;
  color: #409EFF;
  flex-shrink: 0;
}

.activity-content {
  flex: 1;
  min-width: 0;
}

.activity-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.activity-header strong {
  font-size: 14px;
  color: var(--text-primary);
}

.activity-resource {
  font-size: 12px;
  color: var(--text-secondary);
}

.activity-detail {
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
}

.activity-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.activity-user {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  padding: 1px 8px;
  border-radius: 8px;
}

.activity-ip {
  font-size: 12px;
  color: var(--text-muted);
  font-family: var(--font-mono, monospace);
}

.activity-time {
  font-size: 12px;
  color: var(--text-muted);
}

.quick-actions-panel {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.quick-actions-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.quick-action-item {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  height: 60px;
  border-radius: 8px;
  background: var(--bg-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  gap: 8px;
}

.quick-action-item:hover {
  background: var(--bg-tertiary);
  transform: translateY(-1px);
}

.action-icon {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.action-label {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
}
</style>
