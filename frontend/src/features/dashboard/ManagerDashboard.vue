<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  getManagerStats,
  getRisks,
  getCircuitCostTrend,
  getDeviceLifecycle,
  getMonthlyIncidents,
  type ManagerStats,
  type RisksResponse,
  type CircuitCostTrend,
  type DeviceLifecycle,
  type MonthlyIncidents,
  type RiskItem
} from '@/api/dashboard'
import {
  listMonthlyReports,
  generateMonthlyReport,
  downloadMonthlyReport,
  type ReportItem
} from '@/api/reports'
import {
  TrendCharts,
  Warning,
  Money,
  Clock,
  CircleCheck,
  Document,
  Download
} from '@element-plus/icons-vue'
// echarts 按需引入：只注册用到的图表与组件，避免全量打包（全量约 1MB）
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, AxisPointerComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage } from 'element-plus'
import { formatFileSize } from '@/lib/utils'

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, AxisPointerComponent, CanvasRenderer])

const router = useRouter()
const { t } = useI18n()

const loading = ref(true)
const managerStats = ref<ManagerStats | null>(null)
const risksData = ref<RisksResponse | null>(null)
const costTrendData = ref<CircuitCostTrend | null>(null)
const lifecycleData = ref<DeviceLifecycle | null>(null)
const monthlyIncidents = ref<MonthlyIncidents | null>(null)
const showExpiringDialog = ref(false)
// 数据更新时间（每次加载刷新）
const lastUpdated = ref('')

function formatMoney(amount: number): string {
  if (amount >= 10000) {
    return `¥${(amount / 10000).toFixed(1)}万`
  }
  return `¥${amount.toLocaleString()}`
}

// ==================== 可用性卡片（消费 all_failed / last_month_available 标记） ====================

const availabilityValueText = computed(() => {
  const a = managerStats.value?.availability
  if (!a || a.current == null) return t('manager.notDetected')
  return `${a.current}%`
})

const availabilityTrendText = computed(() => {
  const a = managerStats.value?.availability
  if (!a) return ''
  if (a.current == null) return t('manager.noProbeData')
  if (a.all_failed) return t('manager.allProbeFailed')
  if (a.trend === 'up') return t('manager.vsLastMonthUp')
  if (a.trend === 'down') return t('manager.vsLastMonthDown')
  if (a.trend === 'stable') return t('manager.vsLastMonthStable')
  // trend=null：上月无探测数据时明确提示，避免误读为"持平"
  return a.last_month_available ? '—' : t('manager.lastMonthNoData')
})

const availabilityTrendColor = computed(() => {
  const a = managerStats.value?.availability
  if (!a) return 'var(--text-muted)'
  if (a.all_failed) return 'var(--accent-danger)'
  if (a.trend === 'up') return 'var(--accent-success)'
  if (a.trend === 'down') return 'var(--accent-danger)'
  return 'var(--text-muted)'
})

const availabilityValueColor = computed(() => {
  const a = managerStats.value?.availability
  if (a?.all_failed) return 'var(--accent-danger)'
  return 'var(--text-primary)'
})

// ==================== 费用卡片（消费 in_contract / expired_unrenewed 拆分） ====================

const costMainText = computed(() => formatMoney(managerStats.value?.circuit_cost.in_contract ?? 0))

const costExpiredText = computed(() => {
  const expired = managerStats.value?.circuit_cost.expired_unrenewed ?? 0
  return expired > 0 ? `${t('manager.costExpiredUnrenewed')} ${formatMoney(expired)}` : ''
})

const costTrendText = computed(() => {
  const trend = managerStats.value?.circuit_cost.trend
  if (trend === 'up') return t('manager.costTrendUp')
  if (trend === 'down') return t('manager.costTrendDown')
  // 无月租历史：不显示假同比
  return t('manager.costTrendNoData')
})

function getCircuitTypeColor(type: string): string {
  // 已知类型固定颜色
  const fixedColorMap: Record<string, string> = {
    '互联网专线': '#67C23A',    // 绿色
    'MPLS': '#E6A23C',         // 橙色
    'SD-WAN': '#409EFF',       // 蓝色
    '裸光纤': '#F56C6C',       // 红色
    '云专线': '#909399',       // 灰色
  }
  if (fixedColorMap[type]) {
    return fixedColorMap[type]
  }
  
  // 预设颜色数组，新增类型自动从中选择
  const presetColors = [
    '#606266', '#409EFF', '#67C23A', '#E6A23C', '#F56C6C',
    '#722ED1', '#36BFFA', '#F7BA1E', '#909399', '#00CED1',
    '#FF6347', '#4682B4', '#32CD32', '#FFD700', '#9932CC',
  ]
  
  // 简单 hash 算法，同一个类型总是得到同一个颜色
  let hash = 0
  for (let i = 0; i < type.length; i++) {
    hash = ((hash << 5) - hash) + type.charCodeAt(i)
    hash = hash & hash
  }
  const index = Math.abs(hash) % presetColors.length
  return presetColors[index]
}

function getSeverityBorderColor(severity: string): string {
  switch (severity) {
    case 'high': return 'var(--accent-danger)'
    case 'medium': return 'var(--accent-warning)'
    case 'low': return 'var(--accent-success)'
    default: return 'var(--text-muted)'
  }
}

function navigateTo(url: string) {
  router.push(url)
}

// 趋势图中实际有数据的类型（图与下方 breakdown 共用，保证两者一致）
const costByType = computed(() => (costTrendData.value?.by_type ?? {}) as Record<string, number[]>)

const chartTypes = computed(() => {
  const byType = costByType.value
  return Object.keys(byType).filter(typeKey => (byType[typeKey] || []).some(v => v > 0))
})

function costLastValue(type: string): number {
  const arr = costByType.value[type] || []
  return arr[arr.length - 1] || 0
}

function initCostChart() {
  if (!costTrendData.value) return

  const chartDom = document.getElementById('cost-trend-chart')
  if (!chartDom) return

  const myChart = echarts.init(chartDom)

  const months = costTrendData.value.months.map(m => m.slice(5) + '月')

  const series = [
    {
      name: t('manager.costTotal'),
      type: 'line',
      data: costTrendData.value.total_costs,
      smooth: true,
      lineStyle: { width: 3 },
      itemStyle: { color: '#409EFF' }
    }
  ]

  // 类型线用虚线细线：与总费用实线在视觉上区分（构成 vs 总量）
  // 注：echarts 为 canvas 绘制，不支持 CSS 变量，色值保留硬编码
  chartTypes.value.forEach(typeKey => {
    const typeData = (costTrendData.value?.by_type as Record<string, number[]>)?.[typeKey]
    if (typeData) {
      const color = getCircuitTypeColor(typeKey)
      series.push({
        name: typeKey,
        type: 'line',
        data: typeData,
        smooth: true,
        lineStyle: { width: 2, type: 'dashed' } as any,
        itemStyle: { color }
      })
    }
  })

  const option = {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        let result = params[0].name + '<br/>'
        params.forEach((p: any) => {
          result += `${p.seriesName}: ¥${p.value.toLocaleString()}<br/>`
        })
        return result
      }
    },
    legend: {
      data: (series || []).map(s => s.name),
      bottom: 10,
      type: 'scroll'
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '25%',
      top: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: months
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        formatter: (value: number) => {
          if (value >= 10000) return `${value / 10000}万`
          return value.toString()
        }
      }
    },
    series: series
  }
  
  myChart.setOption(option)
}

function initLifecycleChart() {
  if (!lifecycleData.value || !lifecycleData.value.age_distribution) return
  
  const chartDom = document.getElementById('lifecycle-chart')
  if (!chartDom) return
  
  // 确保DOM存在再初始化图表
  const myChart = echarts.init(chartDom);
  
  // 添加窗口大小变化监听，自动适配图表大小
  window.addEventListener('resize', () => myChart.resize());
  
  const raw = lifecycleData.value.age_distribution || []
  // 从数据中剔除未设置项用于绘图
  const unsetEntry = raw.find(d => d.range && d.range.includes('未设置'))
  const unsetCount = unsetEntry?.count || 0
  const full = raw.filter(d => !(d.range && d.range.includes('未设置')))
  // 仅展示 count > 0 的段，不显示为 0 的项
  const data = full.filter(d => (d.count || 0) > 0)
  const maxCount = data.length > 0 ? Math.max(1, ...data.map(d => d.count || 0)) : 1

  // 在图表下方显示未设置提示（如果有）
  const noteContainer = document.querySelector('.lifecycle-content')
  if (noteContainer) {
    const existing = document.getElementById('lifecycle-unset-note')
    if (existing) existing.remove()
    if (unsetCount > 0) {
      const noteEl = document.createElement('div')
      noteEl.id = 'lifecycle-unset-note'
      noteEl.style.color = '#909399'
      noteEl.style.fontSize = '12px'
      noteEl.style.marginTop = '8px'
      noteEl.innerText = t('manager.uncountedNote', { n: unsetCount })
      noteContainer.appendChild(noteEl)
    }
  }
  
  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any[]) => {
        // 只显示“台”计数，未设置段统一灰色说明
        const p = params[0]
        const name = p && p.name ? p.name : ''
        const value = p && p.value != null ? p.value : 0
        const color = name === '未设置' ? '#909399' : (name.includes('5年以上') || name.includes('> 5年') ? '#E24B4A' : name.includes('3-5') ? '#EF9F27' : '#1D9E75')
        return `<span style="display:inline-block;width:10px;height:10px;background:${color};margin-right:6px;border-radius:2px"></span>${name}：${value}台`
      }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: Math.max(3, maxCount),
      interval: 1,
      axisLabel: { formatter: (val: number) => Math.round(val) }
    },
    yAxis: {
      type: 'category',
      data: (data || []).map(d => d.range),
      axisLabel: { fontSize: 12 }
    },
    series: [
      {
        type: 'bar',
        data: (data || []).map(d => ({
          value: d.count,
          itemStyle: {
            color: getAgeColor(d.range)
          }
        })),
        barWidth: 30,
        label: {
          show: true,
          position: 'right',
          formatter: '{c}台'
        }
      }
    ]
  }
  
  myChart.setOption(option)
}

async function loadData() {
  loading.value = true
  try {
    // 独立容错：任一接口失败只影响对应卡片，不拖垮整个看板
    const settled = await Promise.allSettled([
      getManagerStats(),
      getRisks(),
      getCircuitCostTrend(),
      getDeviceLifecycle(),
      getMonthlyIncidents()
    ])
    const pick = <T>(r: PromiseSettledResult<T>): T | null => {
      if (r.status === 'fulfilled') return r.value
      console.error('Failed to load manager dashboard data:', r.reason)
      return null
    }

    const stats = pick(settled[0])
    const risks = pick(settled[1])
    const costTrend = pick(settled[2])
    const lifecycle = pick(settled[3])
    const incidents = pick(settled[4])

    if (stats) managerStats.value = stats
    if (risks) risksData.value = risks
    if (costTrend) costTrendData.value = costTrend
    if (lifecycle) lifecycleData.value = lifecycle
    if (incidents) monthlyIncidents.value = incidents

    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

    setTimeout(() => {
      initCostChart()
      initLifecycleChart()
    }, 100)
    fetchReports()
  } catch (error) {
    console.error('Failed to load manager dashboard data:', error)
  } finally {
    loading.value = false
  }
}

const reports = ref<ReportItem[]>([])
const generatingReport = ref(false)

async function fetchReports() {
  try {
    reports.value = await listMonthlyReports()
  } catch (error) {
    console.error('Failed to load reports:', error)
  }
}

async function handleGenerateReport() {
  generatingReport.value = true
  try {
    const now = new Date()
    await generateMonthlyReport(now.getFullYear(), now.getMonth() + 1)
    ElMessage.success(t('manager.reportGenerated'))
    await fetchReports()
  } catch (error: any) {
    console.error('Failed to generate report:', error)
    ElMessage.error(error.response?.data?.detail || t('manager.reportGenerateFailed'))
  } finally {
    generatingReport.value = false
  }
}

async function handleDownloadReport(item: ReportItem) {
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
  } catch (error) {
    console.error('Failed to download report:', error)
    ElMessage.error(t('manager.downloadFailed'))
  }
}

function getSeverityRisks(severity: string): RiskItem[] {
  if (!risksData.value) return []
  return risksData.value.risks.filter(r => r.severity === severity)
}

function getAgeColor(range: string): string {
  if (!range) return '#909399'
  if (range.includes('未设置')) return '#909399' // 数据缺失灰色
  if (range.includes('5年以上') || range.includes('> 5年')) return '#E24B4A' // 高风险
  if (range.includes('3-5')) return '#EF9F27' // 需关注
  return '#1D9E75' // 正常
}

function getOldDevicesWarning(): string | null {
  if (!lifecycleData.value) return null
  const oldCount = lifecycleData.value.age_distribution.find(d => (d.range && (d.range.includes('5年以上') || d.range.includes('> 5年'))))?.count || 0
  if (oldCount > 0) {
    return t('manager.oldDevicesWarning', { n: oldCount })
  }
  return null
}

function getExpiringDisplayCount(): number {
  const stats = managerStats.value?.expiring_soon
  if (!stats) return 0
  return stats.urgent_count > 0 ? stats.urgent_count : stats.warning_count
}

function getExpiringIconStyle(): Record<string, string> {
  const stats = managerStats.value?.expiring_soon
  if (!stats || stats.total_count === 0) {
    return { background: '#f6ffed', color: 'var(--accent-success)' }
  }
  if (stats.urgent_count > 0) {
    return { background: '#fff2f0', color: 'var(--accent-danger)' }
  }
  return { background: '#fff7e6', color: 'var(--accent-warning)' }
}

function getExpiringTrendColor(): string {
  const stats = managerStats.value?.expiring_soon
  if (!stats || stats.total_count === 0) return 'var(--accent-success)'
  if (stats.urgent_count > 0) return 'var(--accent-danger)'
  return 'var(--accent-warning)'
}

function getExpiringTrendText(): string {
  const stats = managerStats.value?.expiring_soon
  if (!stats || stats.total_count === 0) return t('manager.noExpiring')
  const parts = []
  if (stats.urgent_count > 0) parts.push(`🔴${t('manager.urgentItems', { n: stats.urgent_count })}`)
  if (stats.warning_count > 0) parts.push(`🟡${t('manager.warningItems', { n: stats.warning_count })}`)
  return parts.join(' ')
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="manager-dashboard" v-loading="loading">
    <div class="page-header">
      <h1>{{ t('manager.title') }}</h1>
      <span v-if="lastUpdated" class="data-updated">{{ t('dashboard.updatedAt', { time: lastUpdated }) }}</span>
    </div>

    <!-- 第一行：四个核心指标卡片 -->
    <div class="overview-cards">
      <!-- 本月网络可用性 -->
      <div class="overview-card" @click="navigateTo('/circuits')">
        <div class="card-icon" style="background: #e6f7ff; color: var(--accent-primary)">
          <el-icon><TrendCharts /></el-icon>
        </div>
        <div class="card-content">
          <div class="card-label">{{ t('manager.availability') }}</div>
          <div class="card-value" :style="{ color: availabilityValueColor }">
            {{ availabilityValueText }}
          </div>
          <div class="card-trend" :style="{ color: availabilityTrendColor }">
            {{ availabilityTrendText }}
          </div>
        </div>
      </div>

      <!-- 专线月租费用（合同内为主值，已到期未续约为副行） -->
      <div class="overview-card" @click="navigateTo('/circuits')">
        <div class="card-icon" style="background: #f6ffed; color: var(--accent-success)">
          <el-icon><Money /></el-icon>
        </div>
        <div class="card-content">
          <div class="card-label">{{ t('manager.circuitCost') }}</div>
          <div class="card-value">{{ costMainText }}</div>
          <div class="card-trend" :style="{ color: 'var(--text-muted)' }">
            <template v-if="costExpiredText">{{ costExpiredText }} · </template>{{ costTrendText }}
          </div>
        </div>
      </div>

      <!-- 未解决故障 -->
      <div class="overview-card" :class="{ 'has-alert': (managerStats?.open_incidents.count || 0) > 0 }" @click="navigateTo('/alerts?tab=circuit')">
        <div class="card-icon" :style="{ background: (managerStats?.open_incidents.count || 0) > 0 ? '#fff2f0' : '#f6ffed', color: (managerStats?.open_incidents.count || 0) > 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
          <el-icon><Warning /></el-icon>
        </div>
        <div class="card-content">
          <div class="card-label">{{ t('manager.openIncidents') }}</div>
          <div class="card-value" :style="{ color: (managerStats?.open_incidents.count || 0) > 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
            {{ managerStats?.open_incidents.count || 0 }}
            <span class="unit">{{ t('common.countUnit') }}</span>
          </div>
          <div class="card-trend">
            {{ (managerStats?.open_incidents.count || 0) > 0 ? `${t('manager.maxDuration', { h: managerStats?.open_incidents.max_duration_hours })}` : t('manager.noIncident') }}
          </div>
        </div>
      </div>

      <!-- 即将到期事项（两级预警） -->
      <div class="overview-card" :class="{ 'has-alert': (managerStats?.expiring_soon.urgent_count || 0) > 0, 'has-warning': (managerStats?.expiring_soon.urgent_count || 0) === 0 && (managerStats?.expiring_soon.warning_count || 0) > 0 }" @click="showExpiringDialog = true">
        <div class="card-icon" :style="getExpiringIconStyle()">
          <el-icon><Clock /></el-icon>
        </div>
        <div class="card-content">
          <div class="card-label">{{ t('manager.expiringItems') }}</div>
          <div class="card-value" :style="{ color: (managerStats?.expiring_soon.urgent_count || 0) > 0 ? 'var(--accent-danger)' : (managerStats?.expiring_soon.warning_count || 0) > 0 ? 'var(--accent-warning)' : 'var(--accent-success)' }">
            {{ getExpiringDisplayCount() }}
            <span class="unit">{{ t('common.itemUnit') }}</span>
          </div>
          <div class="card-trend" :style="{ color: getExpiringTrendColor() }">
            {{ getExpiringTrendText() }}
          </div>
        </div>
      </div>
    </div>

    <!-- 🔴🟡 到期预警详情弹窗 -->
    <el-dialog v-model="showExpiringDialog" :title="t('manager.expiringDialogTitle')" width="600px" :close-on-click-modal="false">
      <div class="expiring-dialog-body">
        <!-- 🔴 紧急 -->
        <div v-if="(managerStats?.expiring_soon.urgent_items?.length || 0) > 0" class="expiring-section">
          <div class="expiring-section-title urgent">
            🔴 {{ t('manager.urgent30') }}
          </div>
          <div v-for="item in managerStats?.expiring_soon.urgent_items" :key="item.name" class="expiring-item urgent-item">
            <div class="expiring-item-main">
              <span class="expiring-item-name">{{ item.name }}</span>
              <span class="expiring-item-type">{{ item.type }}</span>
            </div>
            <div class="expiring-item-meta">
              <span class="expiring-item-date">{{ t('manager.expireAt', { date: item.expire_date }) }}</span>
              <span class="expiring-item-days">{{ t('manager.daysLeft', { n: item.days_left }) }}</span>
            </div>
          </div>
        </div>
        <!-- 🟡 即将到期 -->
        <div v-if="(managerStats?.expiring_soon.warning_items?.length || 0) > 0" class="expiring-section">
          <div class="expiring-section-title warning">
            🟡 {{ t('manager.warning3160') }}
          </div>
          <div v-for="item in managerStats?.expiring_soon.warning_items" :key="item.name" class="expiring-item warning-item">
            <div class="expiring-item-main">
              <span class="expiring-item-name">{{ item.name }}</span>
              <span class="expiring-item-type">{{ item.type }}</span>
            </div>
            <div class="expiring-item-meta">
              <span class="expiring-item-date">{{ t('manager.expireAt', { date: item.expire_date }) }}</span>
              <span class="expiring-item-days">{{ t('manager.daysLeft', { n: item.days_left }) }}</span>
            </div>
          </div>
        </div>
        <div v-if="(managerStats?.expiring_soon.total_count || 0) === 0" class="expiring-empty">
          <el-icon><CircleCheck /></el-icon>
          <span>{{ t('manager.expiringEmpty') }}</span>
        </div>
      </div>
    </el-dialog>

    <!-- 第二行：IT风险看板 + 专线费用趋势 -->
    <div class="main-grid">
      <!-- 左侧：IT风险看板 -->
      <div class="panel risk-panel">
        <div class="panel-header">
          <h3>{{ t('manager.riskBoard') }}</h3>
          <el-button link type="primary" @click="navigateTo('/alerts')">{{ t('manager.viewAll') }}</el-button>
        </div>
        <div class="risk-content">
          <!-- 高风险 -->
          <div v-if="getSeverityRisks('high').length > 0" class="risk-section">
            <div class="risk-header">
              <span class="risk-dot high"></span>
              <span class="risk-title">{{ t('manager.riskHigh') }}</span>
              <span class="risk-count">{{ risksData?.high_count }}</span>
            </div>
            <div v-for="risk in getSeverityRisks('high')" :key="risk.title" class="risk-item clickable" :style="{ borderLeftColor: getSeverityBorderColor('high') }" @click="navigateTo(risk.action_url)" :title="t('manager.riskClickHint')">
              <div class="risk-item-title">{{ risk.title }}</div>
              <div class="risk-item-desc">{{ risk.description }}</div>
            </div>
          </div>

          <!-- 中风险 -->
          <div v-if="getSeverityRisks('medium').length > 0" class="risk-section">
            <div class="risk-header">
              <span class="risk-dot medium"></span>
              <span class="risk-title">{{ t('manager.riskMedium') }}</span>
              <span class="risk-count">{{ risksData?.medium_count }}</span>
            </div>
            <div v-for="risk in getSeverityRisks('medium')" :key="risk.title" class="risk-item clickable" :style="{ borderLeftColor: getSeverityBorderColor('medium') }" @click="navigateTo(risk.action_url)" :title="t('manager.riskClickHint')">
              <div class="risk-item-title">{{ risk.title }}</div>
              <div class="risk-item-desc">{{ risk.description }}</div>
            </div>
          </div>

          <!-- 低风险 -->
          <div v-if="getSeverityRisks('low').length > 0" class="risk-section">
            <div class="risk-header">
              <span class="risk-dot low"></span>
              <span class="risk-title">{{ t('manager.riskLow') }}</span>
              <span class="risk-count">{{ risksData?.low_count }}</span>
            </div>
            <div v-for="risk in getSeverityRisks('low')" :key="risk.title" class="risk-item clickable" :style="{ borderLeftColor: getSeverityBorderColor('low') }" @click="navigateTo(risk.action_url)" :title="t('manager.riskClickHint')">
              <div class="risk-item-title">{{ risk.title }}</div>
              <div class="risk-item-desc">{{ risk.description }}</div>
            </div>
          </div>

          <!-- 无风险 -->
          <div v-if="!risksData || risksData.risks.length === 0" class="no-risk">
            <el-icon><CircleCheck /></el-icon>
            <span>{{ t('manager.noRisk') }}</span>
          </div>
        </div>
      </div>

      <!-- 右侧：专线费用趋势 -->
      <div class="panel chart-panel">
        <div class="panel-header">
          <h3>{{ t('manager.costTrendTitle') }}</h3>
        </div>
        <div id="cost-trend-chart" class="chart-container"></div>
        <div class="cost-breakdown">
          <div v-for="type in chartTypes" :key="type" class="cost-item">
            <span class="cost-label" :style="{ color: getCircuitTypeColor(type) }">{{ type }}</span>
            <span class="cost-value" :style="{ color: getCircuitTypeColor(type) }">{{ formatMoney(costLastValue(type)) }}</span>
          </div>
        </div>
        <div class="cost-note">{{ t('manager.costBreakdownNote') }}</div>
      </div>
    </div>

    <!-- 第三行：本月故障汇总 + 设备生命周期 -->
    <div class="main-grid">
      <!-- 左侧：本月故障汇总 -->
      <div class="panel">
        <div class="panel-header">
          <h3>{{ t('manager.incidentTitle') }}</h3>
          <span class="incident-summary" v-if="monthlyIncidents">
            {{ t('manager.incidentTotal', { n: monthlyIncidents.total }) }}
            <template v-if="monthlyIncidents.avg_recovery_hours > 0">
              | {{ t('manager.avgRecovery', { h: monthlyIncidents.avg_recovery_hours }) }}
            </template>
          </span>
        </div>
        <div class="incident-content">
          <el-table class="dashboard-incidents-table" :data="monthlyIncidents?.incidents || []" style="width: 100%">
            <el-table-column prop="title" :label="t('manager.incidentColTitle')" min-width="100" />
            <el-table-column prop="circuit_name" :label="t('manager.incidentColCircuit')" min-width="70" />
            <el-table-column prop="severity" :label="t('manager.incidentColSeverity')" min-width="60">
              <template #default="{ row }">
                <el-tag :type="row.severity === 'critical' ? 'danger' : row.severity === 'major' ? 'warning' : 'info'" size="small">
                  {{ row.severity }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="started_at" :label="t('manager.incidentColStart')" min-width="90" />
            <el-table-column prop="duration_hours" :label="t('manager.incidentColDuration')" min-width="60">
              <template #default="{ row }">{{ row.duration_hours }}h</template>
            </el-table-column>
            <el-table-column prop="status" :label="t('manager.incidentColStatus')" min-width="55">
              <template #default="{ row }">
                <el-tag :type="row.status === 'open' ? 'danger' : 'success'" size="small">
                  {{ row.status === 'open' ? t('manager.statusOpen') : t('manager.statusResolved') }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="!monthlyIncidents?.incidents?.length" class="empty-table">
            <span>{{ t('manager.incidentEmpty') }}</span>
          </div>
          <div v-if="monthlyIncidents && monthlyIncidents.total > 5" class="view-more">
            <el-button link type="primary" @click="navigateTo('/circuits')">{{ t('manager.viewAllIncidents', { n: monthlyIncidents.total }) }}</el-button>
          </div>
          <div v-if="monthlyIncidents?.max_duration" class="incident-footer">
            <span>{{ t('manager.maxIncident', { h: monthlyIncidents.max_duration.hours, circuit: monthlyIncidents.max_duration.circuit, date: monthlyIncidents.max_duration.date }) }}</span>
          </div>
        </div>
      </div>

      <!-- 右侧：设备生命周期 -->
      <div class="panel">
        <div class="panel-header">
          <h3>{{ t('manager.ageTitle') }}</h3>
        </div>
        <div class="lifecycle-content">
          <div id="lifecycle-chart" class="lifecycle-chart"></div>
          <div class="lifecycle-warning" v-if="getOldDevicesWarning()">
            <el-icon><Warning /></el-icon>
            {{ getOldDevicesWarning() }}
          </div>
        </div>
      </div>
    </div>

    <!-- 第四行：月报下载（待审批面板为静态占位已移除） -->
    <div class="main-grid single">
      <!-- 月报下载 -->
      <div class="panel">
        <div class="panel-header">
          <h3>{{ t('manager.reportTitle') }}</h3>
        </div>
        <div class="report-content">
          <div class="report-list">
            <div class="report-item" v-for="item in reports" :key="item.id">
              <el-icon><Document /></el-icon>
              <span class="report-name">{{ t('manager.reportName', { year: item.year, month: item.month }) }}</span>
              <span class="report-meta">{{ formatFileSize(item.file_size) }} · {{ item.generated_at }}</span>
              <el-button type="primary" plain size="small" @click="handleDownloadReport(item)">
                <el-icon><Download /></el-icon>
                {{ t('manager.downloadPdf') }}
              </el-button>
            </div>
            <div v-if="reports.length === 0" class="report-empty">
              {{ t('manager.reportEmpty') }}
            </div>
          </div>
          <div class="report-actions">
            <el-button type="primary" @click="handleGenerateReport" :loading="generatingReport">
              <el-icon><Document /></el-icon>
              {{ t('manager.generateReport') }}
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.manager-dashboard {
  padding: 20px;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h1 {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.overview-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 20px;
}

@media (max-width: 1200px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .main-grid {
    grid-template-columns: 1fr;
  }

  .cost-note {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 8px;
  text-align: right;
}

.cost-breakdown {
    flex-wrap: wrap;
    gap: 12px;
  }

  .cost-item {
    min-width: 80px;
  }

  .chart-container {
    height: 200px;
    width: 100%;
    max-width: 100%;
    overflow: hidden;
  }

  .lifecycle-chart {
    height: 200px;
    width: 100%;
    max-width: 100%;
    overflow: hidden;
  }

  .dashboard-incidents-table {
    width: 100%;
    max-width: 100%;
  }

  .dashboard-incidents-table :deep(.el-table__header th) {
    white-space: nowrap;
    font-size: 11px;
    padding: 4px 2px;
  }

  .dashboard-incidents-table :deep(.el-table__body td) {
    font-size: 11px;
    padding: 4px 2px;
  }

  .dashboard-incidents-table :deep(.el-table__cell) {
    padding: 4px 2px;
  }

  .panel {
    padding: 12px;
  }

  .risk-item {
    padding: 8px 10px;
  }

  .risk-item-title {
    font-size: 12px;
  }

  .risk-item-desc {
    font-size: 11px;
  }

  :deep(.el-table) {
    font-size: 12px;
    overflow-x: auto;
  }

  :deep(.el-table__cell) {
    padding: 6px 4px;
  }

  :deep(.el-table__header th) {
    white-space: nowrap;
  }

  .dashboard-incidents-table {
    display: block;
    overflow-x: auto;
  }

  .expiring-item {
    padding: 10px 12px;
  }

  .expiring-item-title {
    font-size: 13px;
  }

  .expiring-item-desc {
    font-size: 12px;
  }
}

.overview-card {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 20px;
  display: flex;
  gap: 16px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.card-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;
}

.card-content {
  flex: 1;
  min-width: 0;
}

.card-label {
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.card-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.card-value .unit {
  font-size: 16px;
  font-weight: normal;
  color: var(--text-secondary);
}

.card-trend {
  font-size: 12px;
  color: var(--text-muted);
}

.main-grid {
  display: grid;
  grid-template-columns: 2fr 3fr;
  gap: 20px;
  margin-bottom: 20px;
}

.main-grid.single {
  grid-template-columns: 1fr;
}

@media (max-width: 1200px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
}

.panel {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  overflow-x: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.panel-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.data-updated {
  font-size: 12px;
  color: var(--text-muted);
}

.incident-summary {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 风险看板 */
.risk-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.risk-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.risk-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.risk-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.risk-dot.high { background: var(--accent-danger); }
.risk-dot.medium { background: var(--accent-warning); }
.risk-dot.low { background: var(--accent-success); }

.risk-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.risk-count {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  padding: 2px 8px;
  border-radius: 10px;
}

.risk-item.clickable {
  cursor: pointer;
  transition: background 0.15s;
}

.risk-item.clickable:hover {
  background: var(--bg-hover);
}

.risk-item {
  padding: 10px 14px;
  background: var(--bg-secondary);
  border-radius: 6px;
  border-left: 3px solid;
}

.risk-item-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.risk-item-desc {
  font-size: 12px;
  color: var(--text-secondary);
}

.no-risk {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--accent-success);
  font-size: 14px;
  gap: 8px;
}

/* 图表 */
.chart-container {
  height: 250px;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
}

.cost-breakdown {
  display: flex;
  justify-content: space-around;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
  margin-top: 16px;
}

.cost-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.cost-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.cost-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 故障表格 */
.incident-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.empty-table {
  text-align: center;
  padding: 40px;
  color: var(--accent-success);
  font-size: 14px;
}

.view-more {
  text-align: center;
}

.incident-footer {
  font-size: 12px;
  color: var(--text-secondary);
  padding-top: 12px;
  border-top: 1px solid var(--border-light);
}

/* 到期预警弹窗 */
.expiring-dialog-body {
  max-height: 60vh;
  overflow-y: auto;
}

.expiring-section {
  margin-bottom: 20px;
}

.expiring-section:last-child {
  margin-bottom: 0;
}

.expiring-section-title {
  font-size: 15px;
  font-weight: 600;
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 8px;
}

.expiring-section-title.urgent {
  background: #fff2f0;
  color: var(--accent-danger);
}

.expiring-section-title.warning {
  background: #fff7e6;
  color: var(--accent-warning);
}

.expiring-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 16px;
  border-radius: 6px;
  margin-bottom: 8px;
}

.expiring-item:last-child {
  margin-bottom: 0;
}

.urgent-item {
  background: #fff2f0;
  border-left: 3px solid var(--accent-danger);
}

.warning-item {
  background: #fffbe6;
  border-left: 3px solid var(--accent-warning);
}

.expiring-item-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.expiring-item-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.expiring-item-type {
  font-size: 11px;
  color: var(--text-secondary);
  background: rgba(0,0,0,0.04);
  padding: 2px 8px;
  border-radius: 4px;
}

.expiring-item-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.expiring-item-date {
  font-size: 13px;
  color: #595959;
}

.expiring-item-days {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.expiring-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 8px;
  color: var(--accent-success);
  font-size: 14px;
}

/* 生命周期图表 */
.lifecycle-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-x: hidden;
}

.lifecycle-chart {
  height: 200px;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
}

.lifecycle-warning {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fff2f0;
  border-radius: 6px;
  color: var(--accent-danger);
  font-size: 13px;
}

/* 月报下载 */
.report-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.report-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.report-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-secondary);
  border-radius: 6px;
}

.report-item .el-icon {
  font-size: 20px;
  color: #409EFF;
}

.report-name {
  flex: 1;
  font-size: 14px;
  color: var(--text-primary);
}

.report-meta {
  font-size: 12px;
  color: var(--text-secondary);
  margin-right: 16px;
}

.report-empty {
  text-align: center;
  padding: 32px;
  color: var(--text-secondary);
  font-size: 13px;
}

.report-actions {
  display: flex;
  gap: 12px;
}

/* 待审批 */
.approval-content {
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.no-approval {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--accent-success);
  font-size: 14px;
}

.dashboard-incidents-table :deep(.cell) {
  line-height: 1.5;
}

.dashboard-incidents-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>
