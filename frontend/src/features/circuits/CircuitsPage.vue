<script setup lang="ts">
import { ref, computed, onMounted, watch, h } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '../../store'
import { storeToRefs } from 'pinia'
import { applyKeywordFilter } from '@/lib/filters'
import { useCrudForm } from '@/lib/useCrudForm'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { Plus, Download, Upload, Clock, Warning, WarningFilled, ArrowDown, View, Edit, Document, Delete, Setting } from '@element-plus/icons-vue'
import { daysUntil, money, formatDate } from '../../lib/utils'
import api from '../../api/axios'
import type { Circuit, Site } from '../../types/domain'
import { getCircuits, createCircuit, updateCircuit, deleteCircuit, type CircuitResponse } from '../../api/circuits'
import { getSites, type SiteResponse } from '../../api/sites'
import { getLocale } from '@/i18n'

const { t, locale } = useI18n()

const router = useRouter()
const route = useRoute()
const store = useAppStore()
const { circuits } = storeToRefs(store)

// 从后端获取的站点数据
const sites = ref<Site[]>([])

// 获取站点名称
const siteName = (id: number): string => {
  return sites.value.find((site) => site.id === id)?.name || '-'
}

const searchQuery = ref('')
const filterOperator = ref('')
const filterStatus = ref('')
const filterSiteId = ref('')
const filterExpiry = ref('')
const selectedRows = ref<string[]>([])
const showImportDialog = ref(false)
const importLoading = ref(false)
const importFile = ref<File | null>(null)
const importResult = ref<any>(null)
const viewMode = ref(false)

// 表单弹窗状态（新建/编辑/关闭）
const defaultCircuitForm = () => ({
  name: '',
  provider: t('circuits.providerTelecom'),
  type: t('circuits.typeInternet'),
  siteId: 0,
  bandwidth: 100,
  monthlyCost: 0,
  contractStart: '',
  contractEnd: '',
  circuitNo: '',
  supportPhone: '',
  publicIp: '',
  status: t('circuits.statusNormal'),
  note: '',
})
type CircuitForm = ReturnType<typeof defaultCircuitForm>

const {
  showDialog,
  editing: editingCircuit,
  form,
  openCreate: openCreateDialog,
  openEdit: openEditDialog,
  closeDialog: closeCircuitDialog,
} = useCrudForm<Circuit, CircuitForm>({
  createDefaults: defaultCircuitForm,
  toForm: (row) => ({ ...row }),
})

// 关闭时额外退出查看模式
const closeDialog = () => {
  viewMode.value = false
  closeCircuitDialog()
}

const totalCount = computed(() => circuits.value.length)
const onlineCount = computed(() => circuits.value.filter(c => c.status === t('circuits.statusNormal')).length)
const faultCount = computed(() => circuits.value.filter(c => c.status === t('circuits.statusFault')).length)

// 合同状态派生：全页面唯一判断入口（卡片/筛选/色条/标签/合计都复用）
// expired: 到期日 < 今天；expiring: 今天 ~ 30 天内（含今日到期）；valid: 其余或无到期日
type ContractState = 'expired' | 'expiring' | 'valid'
function getContractState(circuit: Pick<Circuit, 'contractEnd'>): ContractState {
  const days = daysUntil(circuit.contractEnd)
  if (days === -999) return 'valid' // 无到期日，视为有效
  if (days < 0) return 'expired'
  if (days <= 30) return 'expiring'
  return 'valid'
}

const expiredCircuits = computed(() => circuits.value.filter(c => getContractState(c) === 'expired'))
const expiringCircuits = computed(() => circuits.value.filter(c => getContractState(c) === 'expiring'))
const expiredCount = computed(() => expiredCircuits.value.length)
const expiryCount = computed(() => expiringCircuits.value.length)

// 月租口径：合同内 = 全部 - 已到期未续约
const expiredCost = computed(() => expiredCircuits.value.reduce((sum, c) => sum + (c.monthlyCost || 0), 0))
const totalCost = computed(() => circuits.value.reduce((sum, c) => sum + (c.monthlyCost || 0), 0))
const activeCost = computed(() => totalCost.value - expiredCost.value)
// 即将到期（0~30 天，含今日到期）这批专线的月租合计
const expiringCost = computed(() => expiringCircuits.value.reduce((sum, c) => sum + (c.monthlyCost || 0), 0))

// 卡片金额用整数显示，避免小数换行
function moneyInt(value: number): string {
  return Math.round(value).toLocaleString()
}

// 卡片联动筛选：expired / fault / expiring
const quickFilter = ref<'' | 'expired' | 'fault' | 'expiring'>('')

// 默认排序：已到期(逾期降序) → 即将到期(剩余升序) → 其余；用户列排序时覆盖
const userSort = ref<{ prop: string; order: 'ascending' | 'descending' | null } | null>(null)

const defaultContractCompare = (a: Circuit, b: Circuit): number => {
  const sa = getContractState(a)
  const sb = getContractState(b)
  if (sa !== sb) {
    const rank: Record<ContractState, number> = { expired: 0, expiring: 1, valid: 2 }
    return rank[sa] - rank[sb]
  }
  const da = daysUntil(a.contractEnd)
  const db = daysUntil(b.contractEnd)
  if (sa === 'expired') return da - db // 逾期多的在前（负值更小）
  if (sa === 'expiring') return da - db // 剩余少的在前
  return da - db
}

const filteredCircuits = computed(() => {
  let items = applyKeywordFilter([...circuits.value], searchQuery.value, ['name', 'circuitNo', 'publicIp'])

  if (filterOperator.value) {
    items = items.filter(c => c.provider === filterOperator.value)
  }

  if (filterStatus.value) {
    items = items.filter(c => c.status === filterStatus.value)
  }

  if (filterSiteId.value) {
    items = items.filter(c => String(c.siteId) === filterSiteId.value)
  }

  if (filterExpiry.value) {
    items = items.filter(c => {
      const state = getContractState(c)
      if (filterExpiry.value === 'urgent') return state === 'expiring' && daysUntil(c.contractEnd) <= 7
      if (filterExpiry.value === 'soon') return state === 'expiring'
      if (filterExpiry.value === 'expired') return state === 'expired'
      if (filterExpiry.value === 'valid') return state === 'valid'
      return true
    })
  }

  if (quickFilter.value === 'expired') {
    items = items.filter(c => getContractState(c) === 'expired')
  } else if (quickFilter.value === 'expiring') {
    items = items.filter(c => getContractState(c) === 'expiring')
  } else if (quickFilter.value === 'fault') {
    items = items.filter(c => c.status === t('circuits.statusFault'))
  }

  // 数据层排序：用户排序优先，否则默认合同风险序
  if (userSort.value && userSort.value.order) {
    const { prop, order } = userSort.value
    const dir = order === 'descending' ? -1 : 1
    items.sort((a, b) => {
      const va = (a as any)[prop]
      const vb = (b as any)[prop]
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
      return String(va).localeCompare(String(vb)) * dir
    })
  } else {
    items.sort(defaultContractCompare)
  }

  return items
})

function handleSortChange({ prop, order }: { prop: string; order: 'ascending' | 'descending' | null }) {
  userSort.value = order ? { prop, order } : null
}

function toggleQuickFilter(key: 'expired' | 'fault' | 'expiring') {
  quickFilter.value = quickFilter.value === key ? '' : key
}

function getStatusType(status: string) {
  if (status === t('circuits.statusNormal')) return 'success'
  if (status === t('circuits.statusFault')) return 'danger'
  if (status === t('circuits.statusDisabled')) return 'info'
  return 'warning'
}

function getRowClass({ row }: { row: Circuit }) {
  if (getContractState(row) === 'expired') return 'expired-row'
  if (row.status === t('circuits.statusFault')) return 'fault-row'
  if (getContractState(row) === 'expiring') return 'expiry-row'
  return ''
}

function getExpiryDisplay(date: string) {
  const days = daysUntil(date)
  if (days === -999) return { text: '', type: 'info', icon: Clock, show: false }
  if (days < 0) return { text: t('circuits.overdueDays', { days: -days }), type: 'danger', icon: Warning, show: true }
  if (days === 0) return { text: t('circuits.expireToday'), type: 'danger', icon: WarningFilled, show: true }
  if (days <= 7) return { text: t('circuits.expireRemaining', { days }), type: 'danger', icon: Clock, show: true }
  if (days <= 30) return { text: t('circuits.expireRemaining', { days }), type: 'warning', icon: Clock, show: true }
  return { text: '', type: 'info', icon: Clock, show: false } // >30 天只显示日期
}

// 状态列旁警示图标：合同已到期但专线仍在用
function isExpiredStillNormal(row: Circuit): number | null {
  if (getContractState(row) === 'expired' && row.status === t('circuits.statusNormal')) {
    return -daysUntil(row.contractEnd)
  }
  return null
}

// 续约弹窗
const renewDialog = ref(false)
const renewForm = ref({ contractStart: '', contractEnd: '', monthlyCost: 0, circuitNo: '' })
const renewTarget = ref<Circuit | null>(null)
const renewWarning = computed(() => {
  if (!renewForm.value.contractEnd) return ''
  const days = daysUntil(renewForm.value.contractEnd)
  return days < 0 ? t('circuits.renewStillExpired') : ''
})

function openRenewDialog(row: Circuit) {
  renewTarget.value = row
  const today = new Date()
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  renewForm.value = {
    contractStart: iso(today),
    contractEnd: '',
    monthlyCost: row.monthlyCost || 0,
    circuitNo: row.circuitNo || '',
  }
  renewDialog.value = true
}

async function handleRenew() {
  if (!renewTarget.value) return
  if (!renewForm.value.contractStart || !renewForm.value.contractEnd) {
    ElMessage.error(t('validation.required'))
    return
  }
  if (renewForm.value.contractEnd <= renewForm.value.contractStart) {
    ElMessage.error(t('circuits.renewDateInvalid'))
    return
  }
  try {
    const response = await updateCircuit(Number(renewTarget.value.id), {
      contract_start: renewForm.value.contractStart,
      contract_end: renewForm.value.contractEnd,
      monthly_cost: renewForm.value.monthlyCost || null,
      circuit_no: renewForm.value.circuitNo || null,
    })
    const index = circuits.value.findIndex(c => Number(c.id) === response.id)
    if (index !== -1) {
      circuits.value[index] = convertToCircuit(response)
    }
    renewDialog.value = false
    ElMessage.success(t('circuits.renewSuccess'))
  } catch (e) {
    console.error(e)
    ElMessage.error(t('circuits.renewFailed'))
  }
}

// 合计行：合同内月租 / 已到期未续约月租（口径 = 当前筛选结果）
// 返回 VNode 实现两行显示；已到期行红色、金额为 0 不显示
function summaryMethod({ columns, data }: { columns: any[]; data: Circuit[] }) {
  return columns.map((col, index) => {
    if (index === 1) return t('circuits.grandTotal')
    if (col.property === 'monthlyCost') {
      const inContract = data.filter(c => getContractState(c) !== 'expired').reduce((s, c) => s + (c.monthlyCost || 0), 0)
      const expiredPart = data.filter(c => getContractState(c) === 'expired').reduce((s, c) => s + (c.monthlyCost || 0), 0)
      const lines = [h('div', { class: 'summary-line' }, `${t('circuits.contractInTotal')} ¥${money(inContract)}`)]
      if (expiredPart > 0) {
        lines.push(h('div', { class: 'summary-line summary-line-expired' }, `${t('circuits.expiredUnrenewed')} ¥${money(expiredPart)}`))
      }
      return h('div', { class: 'summary-cost' }, lines)
    }
    return ''
  })
}

// 带宽显示：≥1000 Mbps 转换为 Gbps
function formatBandwidth(bandwidth: number | null | undefined): string {
  if (!bandwidth) return '—'
  return bandwidth >= 1000 ? `${bandwidth / 1000} Gbps` : `${bandwidth} Mbps`
}

// 公网 IP：MPLS 专线无公网概念，显示「不适用」
const isMpls = (type: string) => type === 'MPLS'

// 列设置（localStorage 持久化）；v2：旧 key 残留过 site:false 导致「所属站点」列被隐藏，升级 key 重置
const COLUMN_STORAGE_KEY = 'circuits_column_settings_v2'
const columnDefs = [
  { key: 'site', labelKey: 'circuits.siteName' },
  { key: 'provider', labelKey: 'circuits.provider' },
  { key: 'type', labelKey: 'circuits.type' },
  { key: 'bandwidth', labelKey: 'circuits.bandwidth' },
  { key: 'publicIp', labelKey: 'circuits.publicIp' },
  { key: 'contract', labelKey: 'circuits.contractTerm' },
  { key: 'status', labelKey: 'common.status' },
  { key: 'monthlyCost', labelKey: 'circuits.monthlyCost' },
] as const
type ColumnKey = (typeof columnDefs)[number]['key']

const loadColumnSettings = (): Record<ColumnKey, boolean> => {
  const defaults = Object.fromEntries(columnDefs.map(c => [c.key, true])) as Record<ColumnKey, boolean>
  try {
    const saved = localStorage.getItem(COLUMN_STORAGE_KEY)
    return saved ? { ...defaults, ...JSON.parse(saved) } : defaults
  } catch {
    return defaults
  }
}
const columnVisible = ref<Record<ColumnKey, boolean>>(loadColumnSettings())
const showColumnSettings = ref(false)
watch(columnVisible, (val) => {
  localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(val))
}, { deep: true })

async function handleSave() {
  if (!form.value.name.trim()) {
    ElMessage.error(t('validation.required'))
    return
  }
  
  try {
    const circuitData = {
      name: form.value.name,
      type: form.value.type,
      provider: form.value.provider,
      bandwidth: form.value.bandwidth || null,
      site_id: form.value.siteId || null,
      monthly_cost: form.value.monthlyCost || null,
      contract_start: form.value.contractStart || null,
      contract_end: form.value.contractEnd || null,
      circuit_no: form.value.circuitNo || null,
      support_phone: form.value.supportPhone || null,
      public_ip: form.value.publicIp || null,
      status: form.value.status,
      note: form.value.note || null
    }

    if (editingCircuit.value) {
      const response = await updateCircuit(Number(editingCircuit.value.id), circuitData)
      const index = circuits.value.findIndex(c => Number(c.id) === response.id)
      if (index !== -1) {
        circuits.value[index] = convertToCircuit(response)
        store.save()
      }
      ElMessage.success(t('common.success'))
    } else {
      const response = await createCircuit(circuitData)
      circuits.value.push(convertToCircuit(response))
      store.save()
      ElMessage.success(t('common.success'))
    }
    closeDialog()
  } catch (error) {
    console.error('Failed to save circuit:', error)
    ElMessage.error(t('common.error'))
  }
}

function handleDelete(row: Circuit) {
  ElMessageBox.confirm(
    `${t('circuits.confirmDelete')} "${row.name}"`,
    t('common.confirm'),
    {
      confirmButtonText: t('common.confirmDelete'),
      cancelButtonText: t('common.cancel'),
      confirmButtonClass: 'el-button--danger',
      type: 'warning',
    }
  )
    .then(async () => {
      try {
        await deleteCircuit(Number(row.id))
        circuits.value = circuits.value.filter(c => c.id !== row.id)
        store.save()
        ElMessage.success(t('circuits.deleteSuccess'))
      } catch (error: any) {
        console.error('Failed to delete circuit:', error)
        ElMessage.error(error?.response?.data?.detail || t('circuits.deleteFailed'))
      }
    })
    .catch(() => {
      // 用户取消，静默
    })
}

function viewDetail(row: Circuit) {
  editingCircuit.value = row
  form.value = { ...row }
  viewMode.value = true
  showDialog.value = true
}

function viewChangeRecords(row: Circuit) {
  router.push(`/circuits/${row.id}/changes`)
}

// ==================== 导入导出 ====================

async function handleExport() {
  if (circuits.value.length === 0) {
    ElMessage.warning(t('circuits.noDataToExport'))
    return
  }
  try {
    const response = await api.get('/import-export/circuits/export', {
      params: { format: 'excel' },
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `${t('circuits.circuitList')}_${new Date().toLocaleDateString((typeof locale !== 'undefined' && locale.value) ? locale.value : getLocale() || 'zh-CN').replace(/\//g, '-')}.xlsx`
    link.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success(t('circuits.exportSuccess'))
  } catch (error) {
    ElMessage.error(t('circuits.exportFailed'))
  }
}

async function handleDownloadTemplate() {
  try {
    const response = await api.get('/import-export/circuits/template', {
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `${t('circuits.circuitImportTemplate')}.xlsx`
    link.click()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(t('circuits.templateDownloadFailed'))
  }
}

function handleImportFileChange(file: any) {
  importFile.value = file.raw || file
  importResult.value = null
}

async function handleImport() {
  if (!importFile.value) {
    ElMessage.error(t('circuits.selectFileFirst'))
    return
  }
  importLoading.value = true
  importResult.value = null
  try {
    const formData = new FormData()
    formData.append('file', importFile.value)
    const response = await api.post('/import-export/circuits/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    importResult.value = response.data
    if (response.data.success_count > 0) {
      ElMessage.success(t('circuits.importSuccess', { count: response.data.success_count }))
      await loadCircuits()
    }
    if (response.data.failed_count > 0) {
      ElMessage.warning(t('circuits.importFailed', { count: response.data.failed_count }))
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || t('circuits.importFailedGeneral'))
  } finally {
    importLoading.value = false
  }
}

// 将后端响应转换为前端Circuit类型
const convertToCircuit = (response: CircuitResponse): Circuit => ({
  id: String(response.id),
  name: response.name,
  type: response.type,
  provider: response.provider,
  bandwidth: typeof response.bandwidth === 'number' ? response.bandwidth : (parseInt(String(response.bandwidth)) || 0),
  monthlyCost: typeof response.monthly_cost === 'number' ? response.monthly_cost : 0,
  siteId: typeof response.site_id === 'number' ? response.site_id : 0,
  publicIp: response.public_ip || '',
  status: response.status,
  contractStart: response.contract_start || '',
  contractEnd: response.contract_end || '',
  circuitNo: response.circuit_no || '',
  supportPhone: response.support_phone || '',
  note: response.note || '',
  updatedBy: response.updated_by || '',
  updatedAt: response.updated_at || '',
})

// 将后端响应转换为前端Site类型
const convertToSite = (response: SiteResponse): Site => ({
  id: response.id,
  name: response.name,
  location: response.location || '',
  city: response.city || '',
  room: response.room || '',
  contact: response.contact || '',
  contactPhone: response.contact_phone || '',
  status: response.status as 'online' | 'alert' | 'offline',
  alertCount: response.alert_count,
})

// 加载站点数据
const loadSites = async () => {
  try {
    const response = await getSites()
    sites.value = response.map(convertToSite)
  } catch (error) {
    console.error('Failed to load sites:', error)
  }
}

// 加载电路数据
const loadCircuits = async () => {
  try {
    const response = await getCircuits()
    const circuitList = response.map(convertToCircuit)
    store.setCircuits(circuitList)
  } catch (error) {
    console.error(t('circuits.loadFailed'), error)
    ElMessage.error(t('circuits.loadFailed'))
  }
}

onMounted(async () => {
  await loadSites()
  loadCircuits()
  // 支持 ?siteId= 查询参数：从站点管理页跳转过来时自动过滤
  // 注意：route 需在 setup 顶层 useRoute()（await 之后再调用会丢失组件实例上下文）
  const q = route.query.siteId
  if (q) filterSiteId.value = String(q)
  // 支持 ?filter= 查询参数（expired/fault/expiring）：首页风险看板跳转时自动过滤
  const f = route.query.filter
  if (f && ['expired', 'fault', 'expiring'].includes(String(f))) {
    quickFilter.value = String(f) as 'expired' | 'fault' | 'expiring'
  }
})
</script>

<template>
  <div class="circuits-page">
    <div class="overview-cards">
      <div class="overview-card">
        <div class="overview-card-label">{{ t('circuits.total') }}</div>
        <div class="overview-card-value">{{ totalCount }}</div>
        <div class="overview-card-trend">{{ t('circuits.allCircuits') }}</div>
      </div>
      <div class="overview-card overview-card-success">
        <div class="overview-card-label">{{ t('circuits.online') }}</div>
        <div class="overview-card-value">{{ onlineCount }}</div>
        <div class="overview-card-trend">{{ t('circuits.running') }}</div>
      </div>
      <div
        class="overview-card overview-card-danger"
        :class="{ 'overview-card-clickable': faultCount > 0, 'is-active': quickFilter === 'fault' }"
        @click="faultCount > 0 && toggleQuickFilter('fault')"
      >
        <div class="overview-card-label">{{ t('circuits.fault') }}</div>
        <div class="overview-card-value">{{ faultCount }}</div>
        <div class="overview-card-trend">{{ faultCount > 0 ? t('circuits.needHandle') : t('circuits.none') }}</div>
      </div>
      <div
        class="overview-card overview-card-danger"
        :class="{ 'overview-card-clickable': expiredCount > 0, 'is-active': quickFilter === 'expired' }"
        @click="expiredCount > 0 && toggleQuickFilter('expired')"
      >
        <div class="overview-card-label">{{ t('circuits.expiredUnrenewed') }}</div>
        <div class="overview-card-value">{{ expiredCount }}</div>
        <div class="overview-card-trend">{{ expiredCount > 0 ? `¥${moneyInt(expiredCost)}/月` : t('circuits.none') }}</div>
      </div>
      <div
        class="overview-card overview-card-warning"
        :class="{ 'overview-card-clickable': expiryCount > 0, 'is-active': quickFilter === 'expiring' }"
        @click="expiryCount > 0 && toggleQuickFilter('expiring')"
      >
        <div class="overview-card-label">{{ t('circuits.expiring') }}</div>
        <div class="overview-card-value">{{ expiryCount }}</div>
        <div class="overview-card-trend">{{ expiryCount > 0 ? `${t('circuits.contractInTotal')} ¥${moneyInt(expiringCost)}` : t('circuits.none') }}</div>
      </div>
      <div class="overview-card overview-card-blue">
        <div class="overview-card-label">{{ t('circuits.activeMonthlyCost') }}</div>
        <div class="overview-card-value">¥{{ moneyInt(activeCost) }}</div>
        <div class="overview-card-trend">{{ expiredCount > 0 ? t('circuits.expiredCostNote', { cost: moneyInt(expiredCost) }) : t('circuits.monthlyFee') }}</div>
      </div>
    </div>

    <div v-if="quickFilter" class="quick-filter-bar">
      <el-tag
        :type="quickFilter === 'expired' ? 'danger' : quickFilter === 'expiring' ? 'warning' : 'danger'"
        closable
        @close="quickFilter = ''"
      >
        {{ t('sites.filteredLabel') }}：{{
          quickFilter === 'expired' ? t('circuits.expiredUnrenewed')
          : quickFilter === 'expiring' ? t('circuits.expiring')
          : t('circuits.fault')
        }}
      </el-tag>
    </div>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="table-filters-wrapper">
            <div class="table-filters">
              <el-select v-model="filterOperator" :placeholder="t('circuits.provider')" clearable style="width: 120px">
                <el-option :label="t('circuits.providerTelecom')" :value="t('circuits.providerTelecom')" />
                <el-option :label="t('circuits.providerUnicom')" :value="t('circuits.providerUnicom')" />
                <el-option :label="t('circuits.providerMobile')" :value="t('circuits.providerMobile')" />
                <el-option :label="t('circuits.providerOther')" :value="t('circuits.providerOther')" />
              </el-select>
              <el-select v-model="filterStatus" :placeholder="t('common.status')" clearable style="width: 100px">
                <el-option :label="t('circuits.statusNormal')" :value="t('circuits.statusNormal')" />
                <el-option :label="t('circuits.statusFault')" :value="t('circuits.statusFault')" />
                <el-option :label="t('circuits.statusDisabled')" :value="t('circuits.statusDisabled')" />
              </el-select>
              <el-select v-model="filterSiteId" :placeholder="t('circuits.siteName')" clearable style="width: 120px">
                <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
              </el-select>
              <el-select v-model="filterExpiry" :placeholder="t('circuits.expiryStatus')" clearable style="width: 130px">
                <el-option :label="t('circuits.expiredUnrenewed')" value="expired" />
                <el-option :label="t('circuits.days7')" value="urgent" />
                <el-option :label="t('circuits.days30')" value="soon" />
                <el-option :label="t('circuits.contractValid')" value="valid" />
              </el-select>
              <el-input
                v-model="searchQuery"
                :placeholder="t('circuits.searchPlaceholder')"
                prefix-icon="Search"
                clearable
                style="width: 280px"
              />
            </div>
          </div>
          <div class="table-actions">
            <el-popover v-model:visible="showColumnSettings" placement="bottom-end" :width="180" trigger="click">
              <template #reference>
                <el-button plain>
                  <el-icon><Setting /></el-icon> {{ t('circuits.columnSettings') }}
                </el-button>
              </template>
              <div class="column-settings">
                <el-checkbox
                  :model-value="columnDefs.every(c => columnVisible[c.key])"
                  :indeterminate="columnDefs.some(c => columnVisible[c.key]) && !columnDefs.every(c => columnVisible[c.key])"
                  @change="(val: boolean) => columnDefs.forEach(c => columnVisible[c.key] = val)"
                >
                  {{ t('circuits.selectAll') }}
                </el-checkbox>
                <el-checkbox
                  v-for="col in columnDefs"
                  :key="col.key"
                  v-model="columnVisible[col.key]"
                >
                  {{ t(col.labelKey) }}
                </el-checkbox>
              </div>
            </el-popover>
            <el-button v-if="selectedRows.length > 0" type="danger" size="small">{{ t('common.batch') }} ({{ selectedRows.length }})</el-button>
            <el-button plain @click="handleExport">
              <el-icon><Download /></el-icon> {{ t('common.export') }}
            </el-button>
            <el-button plain @click="showImportDialog = true">
              <el-icon><Upload /></el-icon> {{ t('common.import') }}
            </el-button>
            <el-button type="primary" @click="openCreateDialog">
              <el-icon><Plus /></el-icon> {{ t('circuits.create') }}
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="filteredCircuits"
        style="width: 100%"
        border
        height="calc(100vh - 400px)"
        show-summary
        :summary-method="summaryMethod"
        @selection-change="(val: Circuit[]) => selectedRows = val.map((r: Circuit) => r.id)"
        :row-class-name="getRowClass"
        @sort-change="handleSortChange"
        class="circuits-table"
      >
        <el-table-column type="selection" width="50" fixed="left" />
        <el-table-column prop="name" :label="t('circuits.name')" min-width="180" fixed="left" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="circuit-name-cell">
              <div class="circuit-name-main" @click="viewDetail(row)">{{ row.name }}</div>
              <div class="circuit-name-sub">{{ row.circuitNo || '—' }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column
          v-if="columnVisible.site"
          prop="siteId"
          :label="t('circuits.siteName')"
          min-width="130"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <span v-if="row.siteId">{{ siteName(row.siteId) }}</span>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.provider" prop="provider" :label="t('circuits.provider')" width="110" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.provider">{{ row.provider }}</span>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.type" prop="type" :label="t('circuits.type')" width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.type">{{ row.type }}</span>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.bandwidth" prop="bandwidth" :label="t('circuits.bandwidth')" width="130" align="right" sortable :sort-method="(a: Circuit, b: Circuit) => (a.bandwidth || 0) - (b.bandwidth || 0)">
          <template #default="{ row }">
            <el-tooltip :content="formatBandwidth(row.bandwidth)" :disabled="formatBandwidth(row.bandwidth) === '—'" placement="top">
              <span class="nowrap">{{ formatBandwidth(row.bandwidth) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column
          v-if="columnVisible.publicIp"
          prop="publicIp"
          :label="t('circuits.publicIp')"
          width="180"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <span v-if="isMpls(row.type)" class="empty-placeholder">{{ t('circuits.notApplicable') }}</span>
            <span v-else-if="row.publicIp" class="ip-text nowrap">{{ row.publicIp }}</span>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.contract" prop="contractEnd" :label="t('circuits.contractTerm')" width="210" sortable :sort-method="(a: Circuit, b: Circuit) => daysUntil(a.contractEnd) - daysUntil(b.contractEnd)">
          <template #default="{ row }">
            <div v-if="row.contractStart || row.contractEnd" class="contract-cell">
              <div class="contract-range nowrap">
                {{ row.contractStart ? formatDate(row.contractStart) : '—' }} ~ {{ row.contractEnd ? formatDate(row.contractEnd) : '—' }}
              </div>
              <el-tag
                v-if="row.contractEnd && getExpiryDisplay(row.contractEnd).show"
                :type="getExpiryDisplay(row.contractEnd).type"
                size="small"
                effect="dark"
              >
                <el-icon><component :is="getExpiryDisplay(row.contractEnd).icon" /></el-icon>
                {{ getExpiryDisplay(row.contractEnd).text }}
              </el-tag>
            </div>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.status" prop="status" :label="t('common.status')" width="110" align="center">
          <template #default="{ row }">
            <div class="status-cell">
              <el-tag :type="getStatusType(row.status)" effect="dark">{{ row.status }}</el-tag>
              <el-tooltip
                v-if="isExpiredStillNormal(row) !== null"
                :content="t('circuits.expiredStillNormal', { days: isExpiredStillNormal(row) })"
                placement="top"
              >
                <el-icon class="expired-warning-icon"><WarningFilled /></el-icon>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="columnVisible.monthlyCost" prop="monthlyCost" :label="t('circuits.monthlyCost')" width="170" align="right" class-name="cost-column" sortable :sort-method="(a: Circuit, b: Circuit) => (a.monthlyCost || 0) - (b.monthlyCost || 0)">
          <template #default="{ row }">
            <span v-if="row.monthlyCost != null" class="cost-value nowrap">¥{{ money(row.monthlyCost) }}</span>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="160" fixed="right">
          <template #default="{ row }">
            <div class="actions-cell">
              <el-button
                v-if="getContractState(row) === 'expired'"
                type="danger"
                size="small"
                class="renew-button"
                @click="openRenewDialog(row)"
              >
                {{ t('circuits.renew') }}
              </el-button>
              <el-dropdown trigger="click">
                <el-button link type="primary" size="small">
                  {{ t('common.more') }}
                  <el-icon><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="viewDetail(row)">
                      <el-icon><View /></el-icon> {{ t('common.view') }}
                    </el-dropdown-item>
                    <el-dropdown-item @click="openEditDialog(row)">
                      <el-icon><Edit /></el-icon> {{ t('common.edit') }}
                    </el-dropdown-item>
                    <el-dropdown-item @click="viewChangeRecords(row)">
                      <el-icon><Document /></el-icon> {{ t('circuits.changeRecords') }}
                    </el-dropdown-item>
                    <el-dropdown-item divided @click="handleDelete(row)">
                      <el-icon><Delete /></el-icon> {{ t('common.delete') }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="showDialog"
      :title="viewMode ? t('circuits.viewDetail') : (editingCircuit ? t('circuits.edit') : t('circuits.create'))"
      width="720px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('circuits.name')">
              <el-input v-model="form.name" :placeholder="t('circuits.namePlaceholder')" :disabled="viewMode" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('circuits.circuitNo')">
              <el-input v-model="form.circuitNo" :placeholder="t('circuits.circuitNoPlaceholder')" :disabled="viewMode" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item :label="t('circuits.provider')">
              <el-select v-model="form.provider" style="width: 100%" :disabled="viewMode">
                <el-option :label="t('circuits.providerTelecom')" :value="t('circuits.providerTelecom')" />
                <el-option :label="t('circuits.providerUnicom')" :value="t('circuits.providerUnicom')" />
                <el-option :label="t('circuits.providerMobile')" :value="t('circuits.providerMobile')" />
                <el-option :label="t('circuits.providerOther')" :value="t('circuits.providerOther')" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="t('circuits.type')">
              <el-select v-model="form.type" style="width: 100%" :disabled="viewMode">
                <el-option :label="t('circuits.typeInternet')" :value="t('circuits.typeInternet')" />
                <el-option label="MPLS" value="MPLS" />
                <el-option label="SD-WAN" value="SD-WAN" />
                <el-option :label="t('circuits.typeFiber')" :value="t('circuits.typeFiber')" />
                <el-option label="云专线" value="云专线" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="t('circuits.site')">
              <el-select v-model="form.siteId" style="width: 100%" :placeholder="t('sites.select')" :disabled="viewMode">
                <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item :label="t('circuits.bandwidth')">
              <el-input-number v-model="form.bandwidth" :min="1" style="width: 100%" :disabled="viewMode" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="t('circuits.monthlyCost')">
              <el-input-number v-model="form.monthlyCost" :min="0" style="width: 100%" :disabled="viewMode" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="t('common.status')">
              <el-select v-model="form.status" style="width: 100%" :disabled="viewMode">
                <el-option :label="t('circuits.statusNormal')" :value="t('circuits.statusNormal')" />
                <el-option :label="t('circuits.statusFault')" :value="t('circuits.statusFault')" />
                <el-option :label="t('circuits.statusDisabled')" :value="t('circuits.statusDisabled')" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('circuits.contractStart')">
              <el-date-picker v-model="form.contractStart" type="date" style="width: 100%" :disabled="viewMode" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('circuits.contractEnd')">
              <el-date-picker v-model="form.contractEnd" type="date" style="width: 100%" :disabled="viewMode" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('circuits.publicIp')">
              <el-input v-model="form.publicIp" :placeholder="t('circuits.publicIpPlaceholder')" :disabled="viewMode" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('circuits.supportPhone')">
              <el-input v-model="form.supportPhone" :placeholder="t('circuits.supportPhonePlaceholder')" :disabled="viewMode" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="t('common.note')">
          <el-input v-model="form.note" type="textarea" :rows="3" :placeholder="t('common.notePlaceholder')" :disabled="viewMode" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="closeDialog">{{ viewMode ? t('common.close') : t('common.cancel') }}</el-button>
        <el-button v-if="!viewMode" type="primary" @click="handleSave">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- 续约对话框 -->
    <el-dialog
      v-model="renewDialog"
      :title="`${t('circuits.renew')} - ${renewTarget?.name || ''}`"
      width="520px"
      :close-on-click-modal="false"
      @close="renewTarget = null"
    >
      <el-form label-position="top">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('circuits.contractStart')" required>
              <el-date-picker
                v-model="renewForm.contractStart"
                type="date"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('circuits.contractEnd')" required>
              <el-date-picker
                v-model="renewForm.contractEnd"
                type="date"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('circuits.monthlyCost')">
              <el-input-number v-model="renewForm.monthlyCost" :min="0" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('circuits.circuitNo')">
              <el-input v-model="renewForm.circuitNo" :placeholder="t('circuits.circuitNoPlaceholder')" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-alert
          v-if="renewWarning"
          :title="renewWarning"
          type="warning"
          :closable="false"
          show-icon
        />
      </el-form>
      <template #footer>
        <el-button @click="renewDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleRenew">{{ t('common.submit') }}</el-button>
      </template>
    </el-dialog>

    <!-- 导入电路对话框 -->
    <el-dialog
      v-model="showImportDialog"
      :title="t('circuits.import')"
      width="600px"
      @close="importFile = null; importResult = null"
    >
      <el-alert
        :title="t('circuits.importGuide')"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      >
        <p>{{ t('circuits.importStep1') }}</p>
        <p>{{ t('circuits.importStep2') }}</p>
        <p>{{ t('circuits.importStep3') }}</p>
      </el-alert>

      <el-button
        type="primary"
        plain
        :icon="Download"
        style="margin-bottom: 16px;"
        @click="handleDownloadTemplate"
      >
        {{ t('circuits.downloadTemplate') }}
      </el-button>

      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.xls,.csv"
        :on-change="handleImportFileChange"
      >
        <el-icon class="el-icon--upload"><Upload /></el-icon>
        <div class="el-upload__text">
          {{ t('circuits.dropFile') }}
        </div>
      </el-upload>

      <div v-if="importResult" style="margin-top: 16px;">
        <el-divider />
        <h4>{{ t('circuits.importResult') }}</h4>
        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('circuits.successCount')">
            <el-tag type="success">{{ importResult.success_count }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('circuits.failedCount')">
            <el-tag type="danger">{{ importResult.failed_count }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="importResult.errors && importResult.errors.length > 0" style="margin-top: 16px;">
          <h5>{{ t('circuits.errorDetails') }}</h5>
          <el-alert
            v-for="(error, index) in importResult.errors"
            :key="index"
            :title="error"
            type="error"
            :closable="false"
            style="margin-bottom: 8px;"
          />
        </div>
      </div>

      <template #footer>
        <el-button @click="showImportDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="importLoading"
          :disabled="!importFile"
          @click="handleImport"
        >
          {{ t('circuits.startImport') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.circuits-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.overview-cards {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
}

.overview-card {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid var(--el-text-color-secondary);
  transition: all 0.2s ease;
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--el-box-shadow-light);
}

.overview-card-success { border-left-color: var(--el-color-success); }
.overview-card-danger { border-left-color: var(--el-color-danger); }
.overview-card-warning { border-left-color: var(--el-color-warning); }
.overview-card-blue { border-left-color: var(--el-color-primary); }

.overview-card-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}

.overview-card-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
  margin-bottom: 4px;
}

.overview-card-trend {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.table-card {
  border-radius: 8px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.table-filters-wrapper {
  flex: 1;
  overflow-x: auto;
  overflow-y: hidden;
}

.table-filters-wrapper::-webkit-scrollbar {
  height: 6px;
}

.table-filters-wrapper::-webkit-scrollbar-track {
  background: var(--el-fill-color-light);
  border-radius: 3px;
}

.table-filters-wrapper::-webkit-scrollbar-thumb {
  background: var(--el-border-color);
  border-radius: 3px;
}

.table-filters-wrapper::-webkit-scrollbar-thumb:hover {
  background: var(--el-text-color-placeholder);
}

.table-filters {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 4px 0;
  flex-wrap: wrap;
}

.table-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  align-items: center;
  margin-left: auto;
}

.circuit-name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-right: 8px;
}

.circuit-name-main {
  font-weight: 500;
  color: var(--el-color-primary);
  cursor: pointer;
}

.circuit-name-main:hover {
  text-decoration: underline;
}

.circuit-name-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* 合同期限列：日期区间 + 到期 tag */
.contract-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}

.contract-range {
  font-size: 12px;
  color: var(--el-text-color-regular);
}

/* 公网 IP 等宽，便于对齐阅读 */
.ip-text {
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
}

/* 空值占位：灰色 em dash */
.empty-placeholder {
  color: var(--el-text-color-placeholder);
}

.nowrap {
  white-space: nowrap;
}

/* 列设置面板 */
.column-settings {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 320px;
  overflow-y: auto;
}

.expiry-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}

.expiry-date {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cost-value {
  font-weight: 600;
  color: var(--el-text-color-primary);
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  white-space: nowrap;
}

.circuits-table :deep(.cell) {
  line-height: 1.5;
}

.circuits-table :deep(.cell .cost-value) {
  white-space: nowrap;
  overflow: visible;
  text-overflow: clip;
}

.circuits-table :deep(.cost-column .cell) {
  overflow: visible;
  white-space: nowrap;
}

/* 合计行月租列不吃上面的 nowrap，两行各自不折行 */
.circuits-table :deep(.el-table__footer .cost-column .cell) {
  white-space: normal;
  overflow: visible;
}

.circuits-table :deep(.cost-column .cell .cost-value) {
  display: inline-block;
  white-space: nowrap;
}

.circuits-table :deep(.cell .expiry-date) {
  white-space: nowrap;
}

.circuits-table :deep(.cell .circuit-name-main) {
  white-space: nowrap;
}

.circuits-table :deep(.el-table__cell) {
  padding: 8px 12px;
}

:deep(.fault-row) {
  background-color: var(--el-color-danger-light-9) !important;
}

:deep(.fault-row:hover) {
  background-color: var(--el-color-danger-light-9) !important;
}

:deep(.expiry-row) {
  background-color: var(--el-color-warning-light-9) !important;
}

:deep(.expiry-row:hover) {
  background-color: var(--el-color-warning-light-9) !important;
}

/* 已到期未续约行：左侧 3px 红色警示条 */
:deep(.expired-row) {
  background-color: var(--el-color-danger-light-9) !important;
  box-shadow: inset 3px 0 0 var(--el-color-danger);
}

:deep(.expired-row:hover) {
  background-color: var(--el-color-danger-light-9) !important;
}

/* 状态列：tag + 警示图标 */
.status-cell {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.expired-warning-icon {
  color: var(--el-color-danger);
  font-size: 16px;
  cursor: help;
}

/* 统计卡片可点击态 */
.overview-card-clickable {
  cursor: pointer;
}

.overview-card-clickable:hover {
  border-color: var(--el-color-primary-light-5);
}

.overview-card.is-active {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}

/* 卡片联动筛选提示条 */
.quick-filter-bar {
  display: flex;
  align-items: center;
}

.quick-filter-bar .el-tag {
  font-size: 13px;
}

/* 合计行月租列：VNode 两行显示（合同内 / 已到期未续约），行高自适应，不截断 */
.circuits-table :deep(.el-table__footer .summary-cost) {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}

.circuits-table :deep(.el-table__footer .summary-line) {
  white-space: nowrap;
  line-height: 1.5;
}

/* 已到期未续约行：红色，与逾期标签一致 */
.circuits-table :deep(.el-table__footer .summary-line-expired) {
  color: var(--el-color-danger);
}

/* 续约按钮 */
.renew-button {
  margin-right: 8px;
}

/* 操作列：续约靠左、「更多」靠右固定，保证「更多」位置一致 */
.actions-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  white-space: nowrap;
}

@media (max-width: 1024px) {
  .overview-cards {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
  .table-header {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  
  .table-filters-wrapper {
    overflow-x: auto;
  }
  
  .table-actions {
    justify-content: flex-end;
  }
}
</style>