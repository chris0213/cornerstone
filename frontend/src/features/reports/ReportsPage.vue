<template>
  <div class="reports-page">
    <div class="page-desc" style="margin-bottom: 16px; color: var(--el-text-color-secondary); font-size: 14px;">
      {{ t('reports.description') }}
    </div>

    <div class="report-toolbar">
      <el-button type="primary" @click="handleGenerate" :loading="generating">
        <el-icon><Document /></el-icon>
        {{ t('reports.generateCurrent') }}
      </el-button>
      <el-button @click="fetchReports" :loading="loading">
        <el-icon><Refresh /></el-icon>
        {{ t('common.refresh') }}
      </el-button>
    </div>

    <!-- 定时推送设置 -->
    <el-card class="schedule-card">
      <template #header>
        <div class="card-header">
          <span class="schedule-title">
            <el-icon><Timer /></el-icon>
            {{ t('reports.scheduleTitle') }}
          </span>
          <el-switch
            v-model="schedule.enabled"
            :disabled="savingSchedule"
            @change="saveSchedule"
          />
        </div>
      </template>
      <div class="schedule-form">
        <span class="schedule-label">{{ t('reports.scheduleRunAt') }}</span>
        <span class="schedule-fixed">{{ t('reports.scheduleEveryMonth') }}</span>
        <el-select v-model="schedule.day" style="width: 74px">
          <el-option v-for="d in 28" :key="d" :label="`${d}`" :value="d" />
        </el-select>
        <span class="schedule-fixed">{{ t('reports.scheduleDayUnit') }}</span>
        <el-select v-model="schedule.hour" style="width: 74px">
          <el-option v-for="h in 24" :key="h - 1" :label="`${h - 1}`" :value="h - 1" />
        </el-select>
        <span class="schedule-colon">:</span>
        <el-select v-model="schedule.minute" style="width: 74px">
          <el-option v-for="m in 60" :key="m - 1" :label="`${m - 1}`" :value="m - 1" />
        </el-select>
        <span class="schedule-label schedule-email-label" v-if="hasEmailChannel">{{ t('reports.scheduleEmailTo') }}</span>
        <el-input
          v-if="hasEmailChannel"
          v-model="schedule.email_to"
          :placeholder="t('reports.scheduleEmailPlaceholder')"
          style="width: 250px"
          clearable
        />
        <el-button type="primary" @click="saveSchedule" :loading="savingSchedule">
          {{ t('common.save') }}
        </el-button>
      </div>
      <!-- 推送渠道选择 -->
      <div class="schedule-channels">
        <span class="schedule-label">{{ t('reports.scheduleChannels') }}</span>
        <el-checkbox-group v-model="schedule.channels" @change="saveSchedule">
          <el-checkbox label="email">{{ t('reports.channelEmail') }}</el-checkbox>
          <el-checkbox label="dingtalk">{{ t('reports.channelDingtalk') }}</el-checkbox>
          <el-checkbox label="wechat">{{ t('reports.channelWechat') }}</el-checkbox>
          <el-checkbox label="feishu">{{ t('reports.channelFeishu') }}</el-checkbox>
        </el-checkbox-group>
      </div>
      <!-- 聊天软件消息内容配置 -->
      <div class="schedule-chat-config" v-if="hasChatChannel">
        <span class="schedule-label">{{ t('reports.scheduleBaseUrl') }}</span>
        <el-input
          v-model="schedule.link_base_url"
          :placeholder="t('reports.scheduleBaseUrlPlaceholder')"
          style="width: 250px"
          clearable
        />
        <el-checkbox v-model="schedule.include_summary">{{ t('reports.scheduleIncludeSummary') }}</el-checkbox>
        <el-checkbox v-model="schedule.include_link">{{ t('reports.scheduleIncludeLink') }}</el-checkbox>
        <el-button @click="saveSchedule" :loading="savingSchedule" size="small">
          {{ t('common.save') }}
        </el-button>
      </div>
      <div class="schedule-hint">{{ t('reports.scheduleHint') }}</div>
    </el-card>

    <el-card class="report-card" v-loading="loading">
      <template #header>
        <div class="card-header">
          <span>{{ t('reports.reportList') }}</span>
          <span class="report-count">{{ reports.length }} {{ t('reports.items') }}</span>
        </div>
      </template>

      <div v-if="reports.length === 0 && !loading" class="empty-state">
        <el-icon class="empty-icon"><Document /></el-icon>
        <p>{{ t('reports.empty') }}</p>
      </div>

      <div v-else class="report-list">
        <div class="report-item" v-for="item in reports" :key="item.id">
          <el-icon class="report-icon"><Document /></el-icon>
          <div class="report-info">
            <span class="report-name">{{ item.year }}{{ t('reports.year') }}{{ item.month }}{{ t('reports.month') }}{{ t('reports.monthlyReport') }}</span>
            <span class="report-meta">{{ formatFileSize(item.file_size) }} · {{ formatTime(item.generated_at) }} · {{ t('reports.generatedBy') }}: {{ item.generated_by }}</span>
          </div>
          <div class="report-actions">
            <el-button type="primary" plain size="small" @click="handleDownload(item)">
              <el-icon><Download /></el-icon>
              {{ t('reports.download') }}
            </el-button>
            <el-button type="danger" plain size="small" @click="handleDelete(item)">
              <el-icon><Delete /></el-icon>
              {{ t('common.delete') }}
            </el-button>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Refresh, Download, Delete, Timer } from '@element-plus/icons-vue'
import { formatFileSize } from '@/lib/utils'
import {
  listMonthlyReports,
  generateMonthlyReport,
  downloadMonthlyReport,
  deleteMonthlyReport,
  getReportSchedule,
  updateReportSchedule,
  type ReportItem,
  type ReportSchedule
} from '@/api/reports'

const { t } = useI18n()

const reports = ref<ReportItem[]>([])
const loading = ref(false)
const generating = ref(false)

async function fetchReports() {
  loading.value = true
  try {
    reports.value = await listMonthlyReports()
  } catch (error) {
    console.error('Failed to load reports:', error)
    ElMessage.error(t('reports.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function handleGenerate() {
  generating.value = true
  try {
    const now = new Date()
    await generateMonthlyReport(now.getFullYear(), now.getMonth() + 1)
    ElMessage.success(t('reports.generateSuccess'))
    await fetchReports()
  } catch (error: any) {
    console.error('Failed to generate report:', error)
    ElMessage.error(error.response?.data?.detail || t('reports.generateFailed'))
  } finally {
    generating.value = false
  }
}

async function handleDownload(item: ReportItem) {
  try {
    const blob = await downloadMonthlyReport(item.year, item.month)
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = item.filename || `report_${item.year}_${item.month}.pdf`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (error: any) {
    console.error('Failed to download report:', error)
    ElMessage.error(error.response?.data?.detail || t('reports.downloadFailed'))
  }
}

async function handleDelete(item: ReportItem) {
  try {
    await ElMessageBox.confirm(
      t('reports.confirmDelete', { name: `${item.year}${t('reports.year')}${item.month}${t('reports.month')}${t('reports.monthlyReport')}` }),
      t('common.confirmDelete'),
      { type: 'warning' }
    )
    await deleteMonthlyReport(item.year, item.month)
    ElMessage.success(t('reports.deleteSuccess'))
    await fetchReports()
  } catch (error: any) {
    if (error === 'cancel') return
    console.error('Failed to delete report:', error)
    ElMessage.error(error.response?.data?.detail || t('reports.deleteFailed'))
  }
}

function formatTime(time: string): string {
  // 后端已输出 "YYYY-MM-DD HH:MM" 北京时间文本，直接展示，避免二次时区解析偏移
  return time || ''
}

onMounted(() => {
  fetchReports()
  loadSchedule()
})

// ===== 定时推送设置 =====
const schedule = ref<ReportSchedule>({
  enabled: false,
  day: 1,
  hour: 9,
  minute: 0,
  email_to: '',
  channels: ['email'],
  include_link: true,
  include_summary: true,
  link_base_url: ''
})
const savingSchedule = ref(false)

// 是否勾选了聊天软件渠道（钉钉/企业微信/飞书）
const hasChatChannel = computed(() =>
  schedule.value.channels.some(c => ['dingtalk', 'wechat', 'feishu'].includes(c))
)
const hasEmailChannel = computed(() => schedule.value.channels.includes('email'))

async function loadSchedule() {
  try {
    schedule.value = await getReportSchedule()
  } catch (error) {
    console.error('Failed to load report schedule:', error)
  }
}

async function saveSchedule() {
  savingSchedule.value = true
  try {
    schedule.value = await updateReportSchedule(schedule.value)
    ElMessage.success(t('reports.scheduleSaved'))
  } catch (error: any) {
    console.error('Failed to save report schedule:', error)
    ElMessage.error(error.response?.data?.detail || t('reports.scheduleSaveFailed'))
  } finally {
    savingSchedule.value = false
  }
}
</script>

<style scoped>
.reports-page {
  padding: 0;
}

/* 定时推送设置 */
.schedule-card {
  margin-bottom: 16px;
}

.schedule-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.schedule-form {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.schedule-label {
  color: var(--el-text-color-regular);
  font-size: 14px;
}

.schedule-email-label {
  margin-left: 12px;
}

.schedule-fixed {
  color: var(--el-text-color-primary);
  font-size: 14px;
}

.schedule-colon {
  font-size: 16px;
  font-weight: 600;
}

.schedule-channels {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.schedule-chat-config {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}

.schedule-hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h2 {
  margin: 0 0 8px 0;
  font-size: 20px;
}

.page-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.report-toolbar {
  margin-bottom: 16px;
  display: flex;
  gap: 12px;
}

.report-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.report-count {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.empty-state {
  text-align: center;
  padding: 60px 0;
  color: var(--el-text-color-secondary);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.report-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.report-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  transition: background-color 0.2s;
}

.report-item:hover {
  background-color: var(--el-fill-color-light);
}

.report-icon {
  font-size: 24px;
  color: var(--el-color-primary);
}

.report-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.report-name {
  font-size: 14px;
  font-weight: 500;
}

.report-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.report-actions {
  display: flex;
  gap: 8px;
}
</style>
