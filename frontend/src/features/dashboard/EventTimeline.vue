<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { getTimelineEvents, type TimelineEvent } from '@/api/timeline'

const router = useRouter()
const { t } = useI18n()

const events = ref<TimelineEvent[]>([])
const loading = ref(true)
const timeRange = ref('7days')
const selectedTypes = ref<string[]>(['device_offline', 'device_online', 'config_change', 'backup_success', 'backup_fail', 'system'])
const hasReadAll = ref(false)

const eventTypeOptions = [
  { value: 'device_offline', label: '设备离线', color: '#F56C6C' },
  { value: 'device_online', label: '设备恢复', color: '#67C23A' },
  { value: 'config_change', label: '配置变更', color: '#E6A23C' },
  { value: 'backup_success', label: '备份成功', color: '#409EFF' },
  { value: 'backup_fail', label: '备份失败', color: '#F56C6C' },
  { value: 'system', label: '系统操作', color: '#909399' }
]

const eventTypeColors: Record<string, string> = {
  device_offline: '#F56C6C',
  device_online: '#67C23A',
  config_change: '#E6A23C',
  backup_success: '#409EFF',
  backup_fail: '#F56C6C',
  system: '#909399'
}

const timeRangeOptions = [
  { value: 'today', label: '今天', sub: '00:00 ～ 当前' },
  { value: 'yesterday', label: '昨天', sub: '昨日 00:00 ～ 23:59' },
  { value: '7days', label: '最近7天', sub: '最近7天' }
]

const timeRangeLabel = computed(() => {
  const opt = timeRangeOptions.find(o => o.value === timeRange.value)
  return opt ? opt.sub : ''
})

const filteredEvents = computed(() => {
  return events.value.filter(e => selectedTypes.value.includes(e.event_type))
})

function formatTime(dateString: string | null): string {
  if (!dateString) return '-'
  const date = new Date(dateString)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatDate(dateString: string | null): string {
  if (!dateString) return '-'
  const date = new Date(dateString)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  
  if (date.toDateString() === today.toDateString()) {
    return '今天'
  } else if (date.toDateString() === yesterday.toDateString()) {
    return '昨天'
  }
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function toggleType(type: string) {
  const index = selectedTypes.value.indexOf(type)
  if (index > -1) {
    selectedTypes.value.splice(index, 1)
  } else {
    selectedTypes.value.push(type)
  }
}

function handleMarkAllRead() {
  hasReadAll.value = true
  ElMessage.success('已标记全部为已读')
}

function handleNavigate(url: string | null) {
  if (url) {
    router.push(url)
  }
}

// 本地挂钟格式（无时区后缀）：与后端「naive 北京挂钟」口径一致，
// 不再用 toISOString（UTC）避免跨日偏移
function formatLocalDT(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function loadEvents() {
  loading.value = true
  try {
    // 用 Date(y, m, d) 构造器生成边界（自动跨月/跨年），不 mutate 共享的 now
    const now = new Date()
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const yestStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1)
    const weekAgoStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7)

    let start_time: string | undefined
    let end_time: string | undefined

    if (timeRange.value === 'today') {
      start_time = formatLocalDT(todayStart)
      end_time = formatLocalDT(now)
    } else if (timeRange.value === 'yesterday') {
      start_time = formatLocalDT(yestStart)
      end_time = formatLocalDT(new Date(yestStart.getFullYear(), yestStart.getMonth(), yestStart.getDate(), 23, 59, 59))
    } else if (timeRange.value === '7days') {
      start_time = formatLocalDT(weekAgoStart)
      end_time = formatLocalDT(now)
    }

    const result = await getTimelineEvents(start_time, end_time, selectedTypes.value.join(','))
    events.value = result.events
  } catch (error) {
    console.error('Failed to load timeline events:', error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadEvents()
})
</script>

<template>
  <el-card class="timeline-card" shadow="never">
    <template #header>
      <div class="card-header">
        <div class="card-title">
          <el-icon><Clock /></el-icon>
          事件时间线
        </div>
        <div class="card-actions">
          <el-select v-model="timeRange" size="small" @change="loadEvents">
            <el-option v-for="opt in timeRangeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <el-button size="small" :disabled="hasReadAll" @click="handleMarkAllRead">
            {{ hasReadAll ? '已全部标记' : '标记全部已读' }}
          </el-button>
        </div>
      </div>
    </template>

    <div class="type-filter">
      <el-tag
        v-for="type in eventTypeOptions"
        :key="type.value"
        :type="selectedTypes.includes(type.value) ? 'primary' : 'info'"
        :style="{ borderColor: type.color, color: selectedTypes.includes(type.value) ? type.color : undefined }"
        @click="toggleType(type.value)"
        class="filter-tag"
      >
        {{ type.label }}
      </el-tag>
    </div>
    
    <div class="time-range-bar">
      <el-icon><Clock /></el-icon>
      <span>显示范围：<strong>{{ timeRangeLabel }}</strong></span>
      <span class="event-count">共 {{ filteredEvents.length }} 条事件</span>
    </div>
    
    <div class="timeline-content" v-loading="loading">
      <div v-if="filteredEvents.length === 0 && !loading" class="empty-state">
        <el-icon class="empty-icon"><Clock /></el-icon>
        <div class="empty-text">{{ t('dashboard.timelineNoEvents') }}</div>
        <div class="empty-sub">{{ timeRangeLabel }} · {{ t('dashboard.timelineNoEventsSub') }}</div>
      </div>
      
      <div v-for="event in filteredEvents" :key="event.id" class="timeline-item" @click="handleNavigate(event.detail_url)">
        <div class="timeline-time">
          <div class="time-hour">{{ formatTime(event.occurred_at) }}</div>
          <div class="time-date">{{ formatDate(event.occurred_at) }}</div>
        </div>
        <div class="timeline-dot" :style="{ backgroundColor: eventTypeColors[event.event_type] }"></div>
        <div class="timeline-body">
          <div class="event-title">{{ event.title }}</div>
          <div class="event-description">{{ event.description }}</div>
          <div class="event-meta">
            <span class="source-tag">{{ event.source }}</span>
            <span v-if="event.detail_url" class="link-hint">点击查看详情</span>
          </div>
        </div>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.timeline-card {
  border-radius: 8px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--text-primary);
}

.card-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.type-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.filter-tag {
  cursor: pointer;
  transition: all 0.2s;
}

.filter-tag:hover {
  opacity: 0.8;
}

.timeline-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 120px;
  color: var(--accent-success);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.empty-text {
  font-size: 16px;
  font-weight: 500;
}

.empty-sub {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 4px;
}

.time-range-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 13px;
  color: #595959;
}

.time-range-bar .el-icon {
  font-size: 14px;
  color: var(--accent-primary);
}

.time-range-bar strong {
  color: var(--text-primary);
}

.event-count {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
}

.timeline-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  background: var(--bg-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.timeline-item:hover {
  background: var(--border-light);
}

.timeline-time {
  width: 80px;
  text-align: right;
  flex-shrink: 0;
}

.time-hour {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: 'SF Mono', monospace;
}

.time-date {
  font-size: 12px;
  color: var(--text-muted);
}

.timeline-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  margin-top: 4px;
  flex-shrink: 0;
}

.timeline-body {
  flex: 1;
  min-width: 0;
}

.event-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.event-description {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.event-meta {
  display: flex;
  gap: 12px;
  align-items: center;
}

.source-tag {
  font-size: 12px;
  color: var(--accent-primary);
  background: #e6f7ff;
  padding: 2px 8px;
  border-radius: 4px;
}

.link-hint {
  font-size: 12px;
  color: var(--text-muted);
}
</style>