<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Monitor, Connection, DocumentChecked, DataLine, Clock, View } from '@element-plus/icons-vue'

export interface Anomaly {
  id: string
  type: string
  title: string
  description: string
  level: 'danger' | 'warn' | 'info'
  target: string
  targetId: string
  metric: string
  currentValue: string
  threshold: string
  suggestion: string
  detectedAt: string
}

const props = defineProps<{ anomalies: Anomaly[] }>()
const emit = defineEmits<{ (e: 'view-target', anomaly: Anomaly): void }>()
const { t } = useI18n()

function iconFor(a: Anomaly) {
  if (a.type.includes(t('alerts.device'))) return Monitor
  if (a.type.includes(t('alerts.circuit'))) return Connection
  if (a.type.includes(t('alerts.backup'))) return DocumentChecked
  return DataLine
}
</script>

<template>
  <div class="anomaly-list">
    <div
      v-for="anomaly in props.anomalies"
      :key="anomaly.id"
      class="anomaly-item"
      :class="`anomaly-${anomaly.level}`"
    >
      <div class="anomaly-icon">
        <el-icon><component :is="iconFor(anomaly)" /></el-icon>
      </div>
      <div class="anomaly-content">
        <div class="anomaly-header">
          <el-tag :type="anomaly.level === 'danger' ? 'danger' : 'warning'" effect="dark" size="small">
            {{ anomaly.type }}
          </el-tag>
          <span class="anomaly-title">{{ anomaly.title }}</span>
        </div>
        <div class="anomaly-description">{{ anomaly.description }}</div>
        <div class="anomaly-metrics">
          <span class="metric-item">
            <span class="metric-label">{{ t('alerts.currentValue') }}：</span>
            <span class="metric-value">{{ anomaly.currentValue }}</span>
          </span>
          <span class="metric-item">
            <span class="metric-label">{{ t('alerts.threshold') }}：</span>
            <span class="metric-value">{{ anomaly.threshold }}</span>
          </span>
        </div>
        <div class="anomaly-suggestion">
          <el-icon><Clock /></el-icon>
          {{ anomaly.suggestion }}
        </div>
        <div class="anomaly-footer">
          <span class="anomaly-detected-at">
            <el-icon><Clock /></el-icon>
            {{ t('alerts.detectedAt') }}：{{ anomaly.detectedAt }}
          </span>
        </div>
      </div>
      <div class="anomaly-action">
        <el-button type="primary" link @click="emit('view-target', anomaly)">
          <el-icon><View /></el-icon>
          {{ t('common.viewDetail') }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.anomaly-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.anomaly-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 20px;
  background: linear-gradient(135deg, #fffbe6 0%, #fff7e6 100%);
  border-radius: 12px;
  border: 1px solid #ffe58f;
  transition: all 0.2s ease;
}

.anomaly-item:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.anomaly-item.anomaly-danger {
  background: linear-gradient(135deg, #fff2f0 0%, #fff0f0 100%);
  border-color: #ffccc7;
}

.anomaly-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #faad14;
  flex-shrink: 0;
}

.anomaly-danger .anomaly-icon {
  color: #ff4d4f;
}

.anomaly-content {
  flex: 1;
  min-width: 0;
}

.anomaly-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.anomaly-title {
  font-size: 15px;
  font-weight: 600;
  color: #262626;
}

.anomaly-description {
  font-size: 14px;
  color: #595959;
  margin-bottom: 12px;
  line-height: 1.5;
}

.anomaly-metrics {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
}

.metric-item {
  font-size: 13px;
}

.metric-label {
  color: #8c8c8c;
}

.metric-value {
  color: #262626;
  font-weight: 500;
}

.anomaly-suggestion {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
  color: #52c41a;
  padding: 10px 14px;
  background: #f6ffed;
  border-radius: 6px;
  margin-bottom: 12px;
}

.anomaly-suggestion .el-icon {
  color: #52c41a;
  font-size: 14px;
  margin-top: 1px;
}

.anomaly-footer {
  display: flex;
  justify-content: flex-end;
}

.anomaly-detected-at {
  font-size: 12px;
  color: #bfbfbf;
}

.anomaly-action {
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .anomaly-item {
    flex-direction: column;
  }

  .anomaly-action {
    width: 100%;
    margin-top: 12px;
  }
}
</style>
