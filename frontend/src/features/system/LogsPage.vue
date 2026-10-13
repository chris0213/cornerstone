<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAppStore } from '../../store'
import { useAuthStore } from '../../store/auth'
import { storeToRefs } from 'pinia'
import { applyKeywordFilter } from '@/lib/filters'
import { Files, User, Clock, Warning, Check, Edit } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { getLocale } from '@/i18n'

const { t, locale } = useI18n()
const store = useAppStore()
const authStore = useAuthStore()
const { auditLogs } = storeToRefs(store)

onMounted(() => {
  authStore.fetchAuditLogs()
})

const isViewer = computed(() => authStore.isReadOnly())

// 高危操作关键词列表
const DANGEROUS_ACTIONS = ['delete', '创建用户', '修改角色', '删除用户', '回滚']

const activeTab = ref<'login' | 'dangerous' | 'all'>('login')
const searchQuery = ref('')

const tabs = computed(() => {
  const allTabs = [
    { key: 'login', label: t('logs.loginLogs') },
    { key: 'dangerous', label: '高危操作' },
  ]
  if (!isViewer.value) {
    allTabs.push({ key: 'all', label: t('logs.operationLogs') })
  }
  return allTabs
})

const filteredLogs = computed(() => {
  let logs = auditLogs.value

  // 按标签页过滤
  if (activeTab.value === 'login') {
    logs = logs.filter(log => log.action.includes(t('logs.login')))
  } else if (activeTab.value === 'dangerous') {
    logs = logs.filter(log => {
      if (log.action.includes(t('logs.login'))) return false
      return DANGEROUS_ACTIONS.some(keyword => 
        log.action.includes(keyword) || log.detail.includes(keyword)
      )
    })
  } else {
    logs = logs.filter(log => !log.action.includes(t('logs.login')))
  }

  // 搜索过滤
  logs = applyKeywordFilter(logs, searchQuery.value, ['action', 'resource', 'user', 'detail'])

  return logs
})

const getActionType = (action: string) => {
  if (action.includes(t('logs.update'))) return { label: t('logs.update'), type: 'primary', icon: Edit }
  if (action.includes(t('logs.create'))) return { label: t('logs.create'), type: 'success', icon: Check }
  if (action.includes(t('common.delete'))) return { label: t('common.delete'), type: 'danger', icon: Warning }
  if (action.includes(t('logs.backup'))) return { label: t('logs.backup'), type: 'info', icon: Files }
  if (action.includes(t('logs.login'))) return { label: t('logs.login'), type: action.includes(t('logs.failed')) ? 'danger' : 'success', icon: User }
  return { label: t('logs.operation'), type: 'info', icon: Files }
}

const getStatusText = (log: any) => {
  if (log.success === 'true') return { text: t('common.success'), type: 'success' }
  return { text: t('common.failed'), type: 'danger' }
}

const formatDateTime = (dateString: string) => {
  const date = new Date(dateString)
  if (isNaN(date.getTime())) {
    return dateString
  }
  return date.toLocaleString(locale.value || 'zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}
</script>

<template>
  <div class="logs-page">
    <div class="overview-cards">
      <div class="overview-card overview-card-info">
        <div class="overview-card-label">{{ t('logs.totalLogs') }}</div>
        <div class="overview-card-value">{{ auditLogs.length }}</div>
        <div class="overview-card-trend">{{ t('logs.auditRecords') }}</div>
      </div>
      <div class="overview-card overview-card-success">
        <div class="overview-card-label">{{ t('logs.loginLogs') }}</div>
        <div class="overview-card-value">{{ auditLogs.filter(l => l.action.includes(t('logs.login'))).length }}</div>
        <div class="overview-card-trend">{{ t('logs.loginRecords') }}</div>
      </div>
      <div class="overview-card" :class="isViewer ? 'overview-card-danger' : 'overview-card-primary'">
        <div class="overview-card-label">{{ isViewer ? '高危操作' : t('logs.operationLogs') }}</div>
        <div class="overview-card-value">{{ isViewer ? auditLogs.filter(l => !l.action.includes(t('logs.login')) && DANGEROUS_ACTIONS.some(k => l.action.includes(k) || l.detail.includes(k))).length : auditLogs.filter(l => !l.action.includes(t('logs.login'))).length }}</div>
        <div class="overview-card-trend">{{ isViewer ? '高风险记录' : t('logs.operationRecords') }}</div>
      </div>
    </div>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="card-title">
            <el-icon><Files /></el-icon>
            {{ t('logs.logAudit') }}
          </div>
        </div>
      </template>

      <!-- 标签页 -->
      <div class="tabs-container">
        <el-tabs v-model="activeTab" type="card" class="logs-tabs">
          <el-tab-pane
            v-for="tab in tabs"
            :key="tab.key"
            :label="tab.label"
            :name="tab.key"
          />
        </el-tabs>
      </div>

      <!-- 搜索框 -->
      <div class="search-container">
        <el-input
          v-model="searchQuery"
          :placeholder="t('common.search')"
          prefix-icon="Search"
          clearable
          style="width: 360px"
        />
        <div class="search-label">{{ t('logs.operationTime') }}</div>
        <div class="search-date">{{ new Date().toLocaleDateString(getLocale() || 'zh-CN') }}</div>
      </div>

      <el-table
        class="logs-table"
        :data="filteredLogs"
        style="width: 100%"
        stripe
        border
        max-height="calc(100vh - 400px)"
      >
        <el-table-column :label="t('logs.operationTime')" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="time-cell">
              <el-icon class="time-icon"><Clock /></el-icon>
              <span>{{ formatDateTime(row.createdAt) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.operationType')" min-width="100" align="center" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag :type="getActionType(row.action).type">
              {{ getActionType(row.action).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.operationDescription')" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.action }}
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.operationTarget')" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="target-text">{{ row.resource }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.operator')" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="user-cell">
              <el-icon class="user-icon"><User /></el-icon>
              <span>{{ row.user }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.sourceIP')" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="ip-text">{{ row.ipAddress || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.detailInfo')" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="detail-text">{{ row.detail }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.result')" min-width="100" align="center" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag :type="getStatusText(row).type">
              {{ getStatusText(row).text }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="filteredLogs.length === 0"
        :description="t('logs.noLogs')"
      />
    </el-card>
  </div>
</template>

<style scoped>
.logs-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.overview-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
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

.overview-card-info { 
  border-left-color: #1890ff; 
}

.overview-card-success { 
  border-left-color: #52c41a; 
}

.overview-card-primary { 
  border-left-color: #722ed1; 
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

.tabs-container {
  margin-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
}

.logs-tabs {
  margin-bottom: -1px;
}

.search-container {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
}

.search-label {
  font-size: 14px;
  color: #8c8c8c;
}

.search-date {
  font-size: 14px;
  color: #262626;
  font-weight: 500;
}

.time-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #666;
  font-size: 13px;
}

.time-icon {
  color: #1890ff;
  font-size: 14px;
}

.target-text {
  color: #262626;
  font-weight: 500;
}

.detail-text {
  color: #8c8c8c;
  font-size: 13px;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #262626;
}

.user-icon {
  color: #52c41a;
  font-size: 14px;
}

.ip-text {
  color: #8c8c8c;
  font-size: 13px;
  font-family: monospace;
}

@media (max-width: 1200px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

.logs-table :deep(.cell) {
  line-height: 1.5;
}

.logs-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>
