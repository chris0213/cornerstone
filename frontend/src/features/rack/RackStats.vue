<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Rack, RackStats as StatsType, RackDevice } from '../../types/domain'
import { deviceTypeText } from './deviceTypes'

const props = defineProps<{
  stats: StatsType | null
  rack: Rack | null
  devices: RackDevice[]
}>()

const { t } = useI18n()

const stats = computed(() => props.stats || {
  totalU: props.rack?.totalU || 42,
  usedU: 0,
  freeU: props.rack?.totalU || 42,
  utilization: 0,
  deviceCount: props.devices.length,
})

const typeBuckets = computed(() => {
  const m = new Map<string, number>()
  for (const d of props.devices) {
    const k = d.type || 'other'
    m.set(k, (m.get(k) || 0) + 1)
  }
  return Array.from(m.entries()).sort((a, b) => b[1] - a[1]).slice(0, 5)
})

const circumference = 2 * Math.PI * 50
const usedArc = computed(() => {
  const pct = Math.max(0, Math.min(100, stats.value.utilization)) / 100
  return circumference * pct
})

// 与侧边栏 / IP 管理页阈值保持一致：>90 红、70–90 橙、<70 蓝
const ringColor = computed(() => {
  const p = stats.value.utilization
  if (p > 90) return 'var(--el-color-danger, #f56c6c)'
  if (p >= 70) return 'var(--el-color-warning, #e6a23c)'
  return 'var(--el-color-primary, #409eff)'
})
</script>

<template>
  <div class="rack-stats-panel">
    <h4 class="panel-title">{{ t('rack.capacityOverview') }}</h4>

    <div class="stats-grid">
      <div class="stat-card">
        <span class="stat-label">{{ t('rack.totalU') }}</span>
        <span class="stat-value">{{ stats.totalU }}</span>
      </div>
      <div class="stat-card used">
        <span class="stat-label">{{ t('rack.usedU') }}</span>
        <span class="stat-value">{{ stats.usedU }}</span>
      </div>
      <div class="stat-card free">
        <span class="stat-label">{{ t('rack.freeU') }}</span>
        <span class="stat-value">{{ stats.freeU }}</span>
      </div>
      <div class="stat-card util">
        <span class="stat-label">{{ t('rack.deviceCount') }}</span>
        <span class="stat-value">{{ stats.deviceCount }}</span>
      </div>
    </div>

    <div class="util-ring-row">
      <svg width="140" height="140" viewBox="0 0 120 120" class="util-ring">
        <circle cx="60" cy="60" r="50" fill="none" stroke="#eef0f3" stroke-width="10" />
        <circle
          cx="60" cy="60" r="50" fill="none"
          :style="{ stroke: ringColor }"
          stroke-width="10"
          stroke-linecap="round"
          :stroke-dasharray="`${usedArc} ${circumference}`"
          stroke-dashoffset="0"
          transform="rotate(-90 60 60)"
        />
        <text x="60" y="58" text-anchor="middle" class="ring-pct">{{ stats.utilization }}%</text>
        <text x="60" y="74" text-anchor="middle" class="ring-label">{{ t('rack.utilization') }}</text>
      </svg>

      <div class="legend">
        <div class="legend-row">
          <span class="dot used"></span>
          <span>{{ t('rack.usedU') }}</span>
          <strong>{{ stats.usedU }} U</strong>
        </div>
        <div class="legend-row">
          <span class="dot free"></span>
          <span>{{ t('rack.freeU') }}</span>
          <strong>{{ stats.freeU }} U</strong>
        </div>
      </div>
    </div>

    <h4 class="panel-title mt">{{ t('rack.deviceType') }}</h4>
    <div v-if="typeBuckets.length === 0" class="no-types">
      <el-empty :description="t('rack.noDevicesInRack')" :image-size="40" />
    </div>
    <div v-else class="type-bars">
      <div v-for="[name, count] in typeBuckets" :key="name" class="type-row">
        <div class="type-row-head">
          <span class="type-name">{{ deviceTypeText(t, name) }}</span>
          <span class="type-count">{{ count }}</span>
        </div>
        <div class="type-bar-bg">
          <div
            class="type-bar-fill"
            :style="{ width: `${(count / Math.max(1, ...typeBuckets.map(x => x[1]))) * 100}%` }"
          ></div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rack-stats-panel {
  padding: 4px 2px;
}
.panel-title {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
  letter-spacing: 0.3px;
}
.panel-title.mt { margin-top: 16px; }

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 14px;
}
.stat-card {
  border-radius: 6px;
  padding: 10px 12px;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 3px;
  border: 1px solid var(--border-color, #eef0f3);
}
.stat-label { font-size: 11px; color: var(--text-secondary, #6b7280); }
.stat-value { font-size: 18px; font-weight: 600; color: var(--text-primary, #1f2937); }
.stat-card.used .stat-value { color: #3f83f8; }
.stat-card.free .stat-value { color: #10b981; }
.stat-card.util .stat-value { color: #6366f1; }

.util-ring-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 4px 0 8px;
}
.ring-pct { font-size: 18px; font-weight: 700; fill: var(--text-primary, #1f2937); }
.ring-label { font-size: 10px; fill: var(--text-secondary, #6b7280); }

.legend { flex: 1; display: flex; flex-direction: column; gap: 6px; font-size: 12px; }
.legend-row {
  display: grid;
  grid-template-columns: 12px 1fr auto;
  gap: 8px;
  align-items: center;
}
.legend-row strong { font-weight: 600; }
.dot {
  width: 10px; height: 10px; border-radius: 50%;
  align-self: center;
}
.dot.used { background: #3f83f8; }
.dot.free { background: #10b981; }

.type-bars { display: flex; flex-direction: column; gap: 8px; }
.type-row-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 4px;
}
.type-name { color: var(--text-primary, #1f2937); }
.type-count { color: var(--text-secondary, #6b7280); font-weight: 600; }
.type-bar-bg {
  width: 100%;
  height: 6px;
  background: #eef0f3;
  border-radius: 3px;
  overflow: hidden;
}
.type-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #3f83f8);
  border-radius: 3px;
  transition: width .3s;
}
.no-types { padding: 8px 0; }
</style>
