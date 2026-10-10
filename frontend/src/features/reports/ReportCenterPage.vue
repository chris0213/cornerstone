<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Document, TrendCharts } from '@element-plus/icons-vue'
import InspectionPage from '../inspection/InspectionPage.vue'
import ReportsPage from './ReportsPage.vue'

const { t } = useI18n()
const activeTab = ref('inspection')

onMounted(() => {
  // 页面加载时默认显示巡检标签
})
</script>

<template>
  <div class="report-center-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('nav.reports') }}</h2>
      <p class="page-desc">{{ t('reports.centerDescription') }}</p>
    </div>

    <el-tabs v-model="activeTab" type="border-card" class="report-tabs">
      <el-tab-pane name="inspection">
        <template #label>
          <div class="tab-label">
            <el-icon><TrendCharts /></el-icon>
            <span>{{ t('inspection.title') }}</span>
          </div>
        </template>
        <InspectionPage />
      </el-tab-pane>

      <el-tab-pane name="monthly">
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
  color: #303133;
  margin: 0 0 8px 0;
}

.page-desc {
  font-size: 14px;
  color: #909399;
  margin: 0;
}

.report-tabs {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.report-tabs :deep(.el-tabs__header) {
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
}

.report-tabs :deep(.el-tabs__item) {
  font-size: 15px;
  font-weight: 500;
  padding: 0 20px;
}

.report-tabs :deep(.el-tabs__item.is-active) {
  background: #fff;
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
