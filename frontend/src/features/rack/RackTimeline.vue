<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Rack, RackDevice } from '../../types/domain'
import { getAlertRecords, type AlertRecord } from '../../api/alerts'

const props = defineProps<{
  rack: Rack | null
  devices: RackDevice[]
}>()

const { t } = useI18n()
const tab = ref<'realtime' | 'history'>('realtime')

interface TimelineEvent {
  id: string
  kind: 'alert' | 'mount' | 'online' | 'offline'
  title: string
  detail: string
  time: string
  dotColor: string
}

// 真实告警记录（从后端加载）
const alertRecords = ref<AlertRecord[]>([])
const loadingAlerts = ref(false)

async function loadAlerts() {
  if (!props.devices.length) {
    alertRecords.value = []
    return
  }
  loadingAlerts.value = true
  try {
    const deviceIds = new Set(props.devices.map(d => d.id))
    // 拉取最近 100 条告警，前端过滤出当前机柜内设备的
    const page = await getAlertRecords({ page: 1, page_size: 100 })
    alertRecords.value = page.items.filter((r: AlertRecord) => deviceIds.has(r.device_id))
  } catch (error) {
    console.error('Failed to load rack alerts:', error)
    alertRecords.value = []
  } finally {
    loadingAlerts.value = false
  }
}

watch(() => [props.rack?.id, props.devices.length], () => {
  loadAlerts()
}, { immediate: true })

// severity 用主题变量着色（与全局告警语义一致）
const severityColor: Record<string, string> = {
  critical: 'var(--el-color-danger, #f56c6c)',
  warning: 'var(--el-color-warning, #e6a23c)',
  info: 'var(--el-color-primary, #409eff)',
}

const realtimeEvents = computed<TimelineEvent[]>(() => {
  return alertRecords.value
    .slice()
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 10)
    .map(r => {
      const device = props.devices.find(d => d.id === r.device_id)
      return {
        id: `alert-${r.id}`,
        kind: 'alert' as const,
        title: `${device?.name || `设备${r.device_id}`} ${r.severity === 'critical' ? '严重告警' : r.severity === 'warning' ? '警告' : '提示'}`,
        detail: r.message + (r.target_ip ? `（IP: ${r.target_ip}）` : ''),
        time: r.created_at,
        dotColor: severityColor[r.severity] || '#6b7280',
      }
    })
})

// 历史标签：展示机柜内设备清单（真实上架信息，不造时间）
const historyEvents = computed<TimelineEvent[]>(() => {
  if (!props.rack || !props.devices.length) return []
  return props.devices
    .filter(d => d.uPosition != null)
    .sort((a, b) => (b.uPosition || 0) - (a.uPosition || 0))
    .map(d => ({
      id: `dev-${d.id}`,
      kind: 'mount' as const,
      title: `${d.name} 占用 U位`,
      detail: `机柜:${props.rack!.name} U位:${d.uPosition}-${(d.uPosition || 0) + (d.uSize || 1) - 1}U 型号:${d.model || 'N/A'} 序列号:${d.sn || 'N/A'} 状态:${d.status}`,
      time: '',
      dotColor: '#3f83f8',
    }))
})

const visible = computed<TimelineEvent[]>(() =>
  tab.value === 'realtime' ? realtimeEvents.value : historyEvents.value
)

const fmt = (iso: string) => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
</script>

<template>
  <div class="rack-timeline-panel">
    <h4 class="panel-title">{{ t('rack.eventsTimeline') }}</h4>
    <el-tabs v-model="tab" size="small" class="timeline-tabs">
      <el-tab-pane :label="t('rack.realTimeEvents')" name="realtime" />
      <el-tab-pane :label="t('rack.historyEvents')" name="history" />
    </el-tabs>

    <div v-if="!rack" class="timeline-empty">
      <el-empty :description="t('rack.noRackSelected')" :image-size="40" />
    </div>
    <div v-else-if="tab === 'realtime' && loadingAlerts" class="timeline-empty">
      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
    </div>
    <div v-else-if="visible.length === 0" class="timeline-empty">
      <el-empty :description="t('rack.noEvents')" :image-size="40" />
    </div>
    <el-timeline v-else class="rack-timeline">
      <el-timeline-item
        v-for="ev in visible"
        :key="ev.id"
        :timestamp="fmt(ev.time)"
        :color="ev.dotColor"
        placement="top"
        size="large"
      >
        <div class="evt-item">
          <div class="evt-title">{{ ev.title }}</div>
          <div class="evt-detail">{{ ev.detail }}</div>
        </div>
      </el-timeline-item>
    </el-timeline>
  </div>
</template>

<style scoped>
.rack-timeline-panel {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--border-color, #eef0f3);
}
.panel-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}
.timeline-tabs { margin-bottom: 8px; }

.evt-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #1f2937);
  margin-bottom: 2px;
}
.evt-detail {
  font-size: 12px;
  color: var(--text-secondary, #6b7280);
  line-height: 1.5;
  word-break: break-all;
}

.timeline-empty { padding: 16px 0 4px; text-align: center; }
.rack-timeline { padding: 8px 0 4px; }
:deep(.el-timeline-item__timestamp) {
  color: var(--text-secondary, #6b7280);
  font-size: 11px;
}
:deep(.el-timeline-item__wrapper) { padding-left: 16px; }
</style>
