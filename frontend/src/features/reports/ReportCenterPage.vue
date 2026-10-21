<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Document, TrendCharts } from '@element-plus/icons-vue'
import InspectionPage from '../inspection/InspectionPage.vue'
import ReportsPage from './ReportsPage.vue'
import { useAuthStore } from '@/store/auth'

const { t } = useI18n()
const authStore = useAuthStore()

// 两个 tab 分别按权限显隐；两个都无权限时显示空态
const showInspectionTab = computed(() => authStore.hasPermission('inspection', 'read'))
const showMonthlyTab = computed(() => authStore.hasPermission('reports', 'read'))
const activeTab = ref('inspection')
const defaultTab = computed(() => showInspectionTab.value ? 'inspection' : (showMonthlyTab.value ? 'monthly' : ''))

onMounted(() => {
  if (defaultTab.value) activeTab.value = defaultTab.value
})
</script>

<template>
  <div class="report-center-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('nav.reports') }}</h2>
      <p class="page-desc">{{ t('reports.centerDescription') }}</p>
    </div>

    <div v-if="!showInspectionTab && !showMonthlyTab" class="empty-state">
      <el-icon :size="48" color="var(--el-text-color-placeholder)"><Document /></el-icon>
      <p>{{ t('common.noPermission') }}</p>
    </div>

    <el-tabs v-else v-model="activeTab" type="border-card" class="report-tabs">
      <el-tab-pane v-if="showInspectionTab" name="inspection">
        <template #label>
          <div class="tab-label">
            <el-icon><TrendCharts /></el-icon>
            <span>{{ t('inspection.title') }}</span>
          </div>
        </template>
        <InspectionPage />
      </el-tab-pane>

      <el-tab-pane v-if="showMonthlyTab" name="monthly">
        <template #label>
          <div class="tab-label">
            <el-icon><Document /></el-icon>
            <span>{{ t('reports.monthlyReport') }}</span>
          </div>
        </template>
        <ReportsPage />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.report-center-page {
  padding: 20px;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 0 0 8px 0;
}

.page-desc {
  font-size: 14px;
  color: var(--el-text-color-secondary);
  margin: 0;
}

.empty-state {
  text-align: center;
  padding: 60px 0;
  color: var(--el-text-color-secondary);
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.empty-state p {
  margin: 12px 0 0;
}

.report-tabs {
  background: var(--el-bg-color);
  border-radius: 8px;
  box-shadow: var(--el-box-shadow-light);
}

.report-tabs :deep(.el-tabs__header) {
  background: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.report-tabs :deep(.el-tabs__item) {
  font-size: 15px;
  font-weight: 500;
  padding: 0 20px;
}

.report-tabs :deep(.el-tabs__item.is-active) {
  background: var(--el-bg-color);
  font-weight: 600;
}

.report-tabs :deep(.el-tabs__content) {
  padding: 0;
}

.tab-label {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tab-label .el-icon {
  font-size: 16px;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .report-center-page {
    padding: 12px;
  }

  .page-title {
    font-size: 20px;
  }

  .page-desc {
    font-size: 13px;
  }

  .report-tabs :deep(.el-tabs__item) {
    font-size: 14px;
    padding: 0 12px;
  }

  .tab-label {
    gap: 4px;
  }

  .tab-label .el-icon {
    font-size: 14px;
  }
}
</style>
