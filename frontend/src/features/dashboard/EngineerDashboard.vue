<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/store/auth'

import { getDashboardStats, getPrefixesUsage, getRecentLogs, getDeviceTypes, getCircuitTypes, type DashboardStats, type PrefixUsage, type AuditLogItem, type DeviceTypeItem, type CircuitTypeItem } from '@/api/dashboard'
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

// 快捷操作列表
const quickActions = computed(() => {
  const actions = []
  
  if (isAdmin.value || isEngineer.value) {
    actions.push({
      icon: 'Plus',
      label: '添加设备',
      path: '/devices',
      color: '#409EFF',
      description: '快速添加网络设备'
    })
    actions.push({
      icon: 'Globe',
      label: '添加专线',
      path: '/circuits',
      color: '#67C23A',
      description: '管理网络专线'
    })
    actions.push({
      icon: 'Network',
      label: '分配IP',
      path: '/ipam',
      color: '#E6A23C',
      description: 'IP地址管理'
    })
    actions.push({
      icon: 'Clock',
      label: '创建巡检',
      path: '/inspection',
      color: '#909399',
      description: '设备巡检任务'
    })
    actions.push({
      icon: 'Database',
      label: '备份配置',
      path: '/backups',
      color: '#F56C6C',
      description: '配置备份管理'
    })
  }
  
  actions.push({
    icon: 'FolderOpened',
    label: '查看站点',
    path: '/sites',
    color: '#9C27B0',
    description: '站点资源管理'
  })
  
  return actions
})

function navigateTo(path: string) {
  router.push(path)
}

// 用户权限判断
const isAdmin = computed(() => authStore.user?.role === 'super_admin')
const isEngineer = computed(() => authStore.user?.role === 'engineer')

// 根据角色确定可见的概览卡片
const visibleCards = computed(() => {
  const cards = []
  // 所有角色都能看到站点统计
  cards.push('sites', 'devices', 'bandwidth')
  // 工程师和管理员能看到 IP 统计
  if (isAdmin.value || isEngineer.value) cards.push('ipam')
  // 工程师和管理员能看到备份统计
  if (isAdmin.value || isEngineer.value) cards.push('backups')
  // 管理员能看到系统健康状态
  if (isAdmin.value) cards.push('health')
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

const timeRangeOptions = [
  { label: t('dashboard.allTime'), value: 'all' },
  { label: t('dashboard.last24h'), value: '24h' },
  { label: t('dashboard.last7d'), value: '7d' },
  { label: t('dashboard.last15d'), value: '15d' },
  { label: t('dashboard.last30d'), value: '30d' }
]

// 设备类型颜色映射
const deviceTypeColors: Record<string, string> = {
  'router': '#409EFF',
  'switch': '#67C23A',
  'firewall': '#E6A23C',
  'server': '#909399',
  'other': '#F56C6C',
  'unknown': '#909399'
}



const filteredLogs = computed(() => {
  if (!searchQuery.value) return recentLogs.value
  return recentLogs.value.filter(log => 
    log.action.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
    log.resource.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
    log.detail.toLowerCase().includes(searchQuery.value.toLowerCase())
  )
})

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
  const actionMap: Record<string, string> = {
    '用户登录': t('common.userLogin'),
    '登录成功': t('common.loginSuccess'),
    '登录失败': t('common.loginFailed')
  }
  return actionMap[action] || action
}

// 资源类型翻译映射
function getResourceTranslation(resource: string): string {
  const resourceMap: Record<string, string> = {
    '认证': t('common.auth'),
    '系统': t('common.system')
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
    <div class="overview-cards">
      <div v-if="visibleCards.includes('sites')" class="overview-card" @click="navigateTo('/sites')">
        <div class="overview-card-label">站点</div>
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
        <div class="overview-card-arrow">›</div>
      </div>
      <div v-if="visibleCards.includes('health')" class="overview-card" :style="{ borderLeftColor: dashboardStats?.alerts.pending ? '#F56C6C' : '#67C23A' }" @click="navigateTo('/alerts?status=pending')">
        <div class="overview-card-label">未处理告警</div>
        <div class="overview-card-value" :style="{ color: dashboardStats?.alerts.pending ? '#F56C6C' : '#67C23A' }">{{ dashboardStats?.alerts.pending || 0 }}</div>
        <div class="overview-card-trend" :style="{ color: dashboardStats?.alerts.pending ? '#F56C6C' : '#67C23A' }">
          {{ dashboardStats?.alerts.pending ? '有待处理告警' : '一切正常' }}
        </div>
        <div class="overview-card-arrow">›</div>
      </div>
    </div>

    <div class="main-content">
      <div class="side-panel">
        <div class="quick-actions-panel">
          <div class="panel-header">
            <el-icon><Lightning /></el-icon>
            <span>快捷操作</span>
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
      <el-card v-if="isAdmin || isEngineer" class="table-card" shadow="never">
        <template #header>
          <div class="card-title">
            <el-icon><Monitor /></el-icon>
            子网使用率
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
            设备类型分布
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

      <el-card v-if="isAdmin || isEngineer" class="table-card" shadow="never">
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
              <div class="activity-time">{{ log.created_at ? formatTime(log.created_at) : '-' }}</div>
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

.overview-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}

.overview-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid #8c8c8c;
  transition: all 0.2s ease;
  position: relative;
  cursor: pointer;
  overflow: hidden;
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.overview-card-success { border-left-color: #52c41a; }
.overview-card-warning { border-left-color: #faad14; }
.overview-card-blue { border-left-color: #1890ff; }
.overview-card-purple { border-left-color: #722ed1; }

.overview-card-label {
  font-size: 13px;
  color: #8c8c8c;
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
  color: #262626;
  line-height: 1.2;
  margin-bottom: 4px;
}

.overview-card-trend {
  font-size: 12px;
  color: #bfbfbf;
}

.overview-card-sub-trend {
  font-size: 11px;
  color: #bfbfbf;
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
  color: #1890ff;
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
  background: #fff;
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
  background: #fafafa;
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
  color: #262626;
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
  color: #8c8c8c;
}

.circuit-stat-value {
  font-size: 13px;
  font-weight: 600;
  color: #262626;
}

.table-card {
  border-radius: 8px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #262626;
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
  color: #8c8c8c;
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
  background: #f5f5f5;
  border-radius: 5px;
  overflow: hidden;
}

.usage-fill {
  height: 100%;
  background: #67C23A;
  transition: width 0.3s ease;
}

.usage-fill.danger {
  background: #F56C6C;
}

.usage-percent {
  font-size: 12px;
  color: #8c8c8c;
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
  border-bottom: 1px solid #f0f0f0;
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
  color: #262626;
}

.device-type-count {
  font-size: 14px;
  font-weight: 600;
  color: #262626;
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
  background: #fafafa;
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
  color: #262626;
}

.activity-resource {
  font-size: 12px;
  color: #8c8c8c;
}

.activity-detail {
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
}

.activity-time {
  font-size: 12px;
  color: #bfbfbf;
}

.quick-actions-panel {
  background: #fff;
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
  color: #262626;
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
  background: #fafafa;
  cursor: pointer;
  transition: all 0.2s ease;
  gap: 8px;
}

.quick-action-item:hover {
  background: #f5f5f5;
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
  color: #262626;
  font-weight: 500;
}
</style>
