<template>
  <div class="changes-page">
    <div class="page-desc">{{ t('changes.description') }}</div>

    <!-- 统计卡片（可点击联动筛选来源） -->
    <div class="stat-grid">
      <div class="stat-card is-clickable" :class="{ 'is-active': !query.source }" @click="setSource('')">
        <div class="stat-label">{{ t('changes.statTotal') }}<span class="stat-sub">{{ t('changes.statThisMonth') }}</span></div>
        <div class="stat-value">{{ summary?.total ?? '-' }}</div>
      </div>
      <div class="stat-card is-clickable" :class="{ 'is-active': query.source === 'circuit', 'zero-muted': summary && summary.circuit_count === 0 }" @click="setSource('circuit')">
        <div class="stat-label">{{ t('changes.statCircuit') }}</div>
        <div class="stat-value">{{ summary?.circuit_count ?? '-' }}</div>
      </div>
      <div class="stat-card is-clickable" :class="{ 'is-active': query.source === 'config', 'zero-muted': summary && summary.config_count === 0 }" @click="setSource('config')">
        <div class="stat-label">{{ t('changes.statConfig') }}</div>
        <div class="stat-value">{{ summary?.config_count ?? '-' }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">{{ t('changes.statObjects') }}</div>
        <div class="stat-value">{{ summary?.object_count ?? '-' }}</div>
      </div>
    </div>
    <div v-if="summary" class="summary-scope">{{ t('changes.summaryScope', { start: summary.start.slice(0, 10), end: summary.end.slice(0, 10) }) }}</div>

    <!-- 筛选栏（即时筛选） -->
    <div class="filter-bar">
      <el-select v-model="query.source" :placeholder="t('changes.filterBySource')" clearable style="width: 130px" @change="onFilterChange">
        <el-option :label="t('changes.sourceCircuit')" value="circuit" />
        <el-option :label="t('changes.sourceConfig')" value="config" />
      </el-select>
      <el-select v-model="query.change_type" :placeholder="t('changes.typeAll')" clearable style="width: 110px" @change="onFilterChange">
        <el-option :label="t('changes.typeCreate')" value="create" />
        <el-option :label="t('changes.typeUpdate')" value="update" />
        <el-option :label="t('changes.typeDelete')" value="delete" />
      </el-select>
      <el-select v-model="query.operator" :placeholder="t('changes.filterByOperator')" clearable filterable style="width: 140px" @change="onFilterChange">
        <el-option v-for="op in operators" :key="op" :label="op" :value="op" />
      </el-select>
      <el-input
        v-model="query.keyword"
        :placeholder="t('changes.keywordPlaceholder')"
        clearable
        style="width: 200px"
        @keyup.enter="onFilterChange"
        @clear="onFilterChange"
      />
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        :start-placeholder="t('changes.startPlaceholder')"
        :end-placeholder="t('changes.endPlaceholder')"
        style="width: 240px"
        @change="onFilterChange"
      />
      <el-button @click="resetFilters">{{ t('changes.reset') }}</el-button>
      <div class="filter-right">
        <el-button :loading="exporting" @click="handleExport">{{ t('changes.export') }}</el-button>
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="timeline">{{ t('changes.viewTimeline') }}</el-radio-button>
          <el-radio-button value="table">{{ t('changes.viewTable') }}</el-radio-button>
        </el-radio-group>
      </div>
    </div>
    <div class="summary-scope">{{ t('changes.filterScopeHint') }}</div>

    <!-- 时间线视图（批次聚合卡片，按日期分组） -->
    <div v-if="viewMode === 'timeline'" class="timeline-wrap" v-loading="loading">
      <div v-if="!loading && changes.length === 0" class="empty-state">
        <el-icon :size="48" color="#ccc"><Files /></el-icon>
        <p>{{ t('changes.empty') }}</p>
      </div>
      <div v-for="group in timelineGroups" :key="group.date" class="timeline-group">
        <div class="timeline-date">{{ group.date }}</div>
        <div v-for="item in group.items" :key="item.id" class="change-card">
          <div class="change-head">
            <span class="change-time">{{ formatTime(item.created_at) }}</span>
            <el-tag size="small" :type="item.source === 'circuit' ? 'primary' : 'warning'" effect="plain">
              {{ item.source === 'circuit' ? t('changes.sourceCircuit') : t('changes.sourceConfig') }}
            </el-tag>
            <span class="change-object" @click="goObject(item)">{{ item.object_name || '-' }}</span>
            <el-tag size="small" :type="typeTag(item.change_type)" effect="light">{{ typeLabel(item.change_type) }}</el-tag>
            <span class="change-operator">{{ displayName(item.operator) }}</span>
          </div>
          <div class="change-body">
            <template v-if="item.changes.length === 1">
              <span class="change-field">{{ fieldLabel(item.changes[0].field) }}</span>
              <template v-if="item.changes[0].old_value || item.changes[0].new_value">
                <span class="value-old">{{ formatValue(item.changes[0].old_value) }}</span>
                <el-icon class="value-arrow"><Right /></el-icon>
                <span class="value-new">{{ formatValue(item.changes[0].new_value) }}</span>
              </template>
              <span v-else class="value-none">-</span>
            </template>
            <template v-else>
              <span class="batch-summary">
                <span class="batch-count">{{ item.field_count }} {{ t('changes.fieldCountSuffix') }}</span>
                <span v-for="(c, i) in item.changes.slice(0, 3)" :key="c.field" class="batch-field">
                  {{ fieldLabel(c.field) }}<template v-if="c.old_value || c.new_value">：{{ formatValue(c.old_value) }} → {{ formatValue(c.new_value) }}</template><template v-if="i < Math.min(item.changes.length, 3) - 1">；</template>
                </span>
                <span v-if="item.changes.length > 3" class="batch-more">…</span>
              </span>
            </template>
          </div>
          <template v-if="item.changes.length > 1">
            <el-button
              link
              size="small"
              class="expand-btn"
              @click="toggleExpand(item.id)"
            >
              {{ expanded.has(item.id) ? t('changes.collapseDetail') : t('changes.expandDetail') }}
              <el-icon><component :is="expanded.has(item.id) ? ArrowUp : ArrowDown" /></el-icon>
            </el-button>
            <div v-if="expanded.has(item.id)" class="change-detail">
              <div v-for="c in item.changes" :key="c.field" class="detail-row">
                <span class="detail-field">{{ fieldLabel(c.field) }}</span>
                <span class="value-old">{{ formatValue(c.old_value) }}</span>
                <el-icon class="value-arrow"><Right /></el-icon>
                <span class="value-new">{{ formatValue(c.new_value) }}</span>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 表格视图（每行一个字段明细） -->
    <template v-else>
      <el-table class="changes-table" :data="tableRows" v-loading="loading" border stripe show-overflow-tooltip>
        <el-table-column prop="created_at" :label="t('changes.colTime')" min-width="150" fixed>
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="object_name" :label="t('changes.colObject')" min-width="150">
          <template #default="{ row }">
            <span class="change-object" @click="goObject(row)">{{ row.object_name || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="field" :label="t('changes.colField')" min-width="110">
          <template #default="{ row }">{{ fieldLabel(row.field) }}</template>
        </el-table-column>
        <el-table-column prop="old_value" :label="t('changes.colOld')" min-width="140">
          <template #default="{ row }">{{ formatValue(row.old_value) }}</template>
        </el-table-column>
        <el-table-column prop="new_value" :label="t('changes.colNew')" min-width="140">
          <template #default="{ row }">{{ formatValue(row.new_value) }}</template>
        </el-table-column>
        <el-table-column prop="operator" :label="t('changes.colOperator')" min-width="100">
          <template #default="{ row }">{{ displayName(row.operator) }}</template>
        </el-table-column>
        <el-table-column prop="change_type" :label="t('changes.colType')" min-width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTag(row.change_type)" effect="light">{{ typeLabel(row.change_type) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- 分页 -->
    <div class="pagination-bar">
      <span class="total-text">{{ t('changes.totalItems', { total }) }}</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100, 200]"
        layout="sizes, prev, pager, next, jumper"
        @size-change="onPageSizeChange"
        @current-change="loadChanges"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Files, Right, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import {
  listChanges, getChangesSummary, getChangesOperators, exportChanges,
  type ChangeItem, type ChangeSummary,
} from '@/api/changes'
import { getUsers } from '@/api/users'
import { formatDateTime, formatDate } from '@/lib/utils'
import { exportToCSV } from '@/lib/csv'

const { t } = useI18n()
const router = useRouter()

const loading = ref(false)
const exporting = ref(false)
const changes = ref<ChangeItem[]>([])
const summary = ref<ChangeSummary | null>(null)
const operators = ref<string[]>([])
const userNameMap = ref<Record<string, string>>({})
const viewMode = ref<'timeline' | 'table'>('timeline')
const dateRange = ref<string[] | null>(null)
const expanded = reactive(new Set<string>())

const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const query = ref({
  source: '',
  change_type: '',
  operator: '',
  keyword: '',
})

let currentAbort: AbortController | null = null

async function loadChanges() {
  currentAbort?.abort()
  currentAbort = new AbortController()
  loading.value = true
  try {
    const params: Record<string, unknown> = { skip: (page.value - 1) * pageSize.value, limit: pageSize.value }
    if (query.value.source) params.source = query.value.source
    if (query.value.change_type) params.change_type = query.value.change_type
    if (query.value.operator) params.operator = query.value.operator
    if (query.value.keyword) params.keyword = query.value.keyword
    if (dateRange.value?.[0]) params.start = `${dateRange.value[0]}T00:00:00`
    if (dateRange.value?.[1]) params.end = `${dateRange.value[1]}T23:59:59`
    const data = await listChanges(params)
    changes.value = data.items
    total.value = data.total
    expanded.clear()
  } catch (error: any) {
    if (error?.name !== 'CanceledError' && error?.code !== 'ERR_CANCELED') {
      console.error('Failed to load changes:', error)
    }
  } finally {
    loading.value = false
  }
}

async function loadSummary() {
  try {
    summary.value = await getChangesSummary()
  } catch (error) {
    console.error('Failed to load change summary:', error)
  }
}

async function loadOperators() {
  try {
    operators.value = await getChangesOperators()
  } catch (error) {
    console.error('Failed to load operators:', error)
  }
}

async function loadUserNames() {
  try {
    const users = await getUsers()
    const map: Record<string, string> = {}
    for (const u of users) map[u.username] = u.full_name || u.username
    userNameMap.value = map
  } catch {
    /* 显示名映射失败时回退显示用户名 */
  }
}

// 操作人 username → 显示名（优先 full_name）
function displayName(username: string): string {
  return userNameMap.value[username] || username
}

// 即时筛选：任一条件变化立即重置到第一页并刷新
function onFilterChange() {
  page.value = 1
  loadChanges()
}

function setSource(source: string) {
  query.value.source = source
  onFilterChange()
}

function resetFilters() {
  query.value = { source: '', change_type: '', operator: '', keyword: '' }
  dateRange.value = null
  page.value = 1
  loadChanges()
}

function onPageSizeChange() {
  page.value = 1
  loadChanges()
}

// 字段名 → i18n 中文标签（未知字段回退原名）
const fieldKeyMap: Record<string, string> = {
  name: 'fieldName',
  contract_start: 'fieldContractStart',
  contract_end: 'fieldContractEnd',
  monthly_cost: 'fieldMonthlyCost',
  bandwidth: 'fieldBandwidth',
  carrier: 'fieldCarrier',
  provider: 'fieldProvider',
  type: 'fieldType',
  site_id: 'fieldSite',
  site_a_id: 'fieldSiteAId',
  site_b_id: 'fieldSiteBId',
  contact: 'fieldContact',
  phone: 'fieldPhone',
  status: 'fieldStatus',
  note: 'fieldNote',
  circuit_no: 'fieldCircuitNo',
  support_phone: 'fieldSupportPhone',
  public_ip: 'fieldPublicIp',
  updated_by: 'fieldUpdatedBy',
  配置内容: 'fieldConfig',
}

function fieldLabel(field: string): string {
  const key = fieldKeyMap[field]
  return key ? t(`changes.${key}`) : field
}

// 值格式化：日期值去尾随 00:00:00；空值显示 -
function formatValue(value: string): string {
  if (!value) return '-'
  return value.replace(/ 00:00:00$/, '')
}

// 时间线按日期分组（与全站一致的 YYYY-MM-DD）
const timelineGroups = computed(() => {
  const map = new Map<string, ChangeItem[]>()
  for (const item of changes.value) {
    const day = formatDate(item.created_at)
    const list = map.get(day) || []
    list.push(item)
    map.set(day, list)
  }
  return [...map.entries()].map(([date, items]) => ({ date, items }))
})

// 表格视图：批次展开为字段级行
const tableRows = computed(() =>
  changes.value.flatMap(item =>
    item.changes.map((c, i) => ({
      id: `${item.id}-${i}`,
      created_at: item.created_at,
      object_id: item.object_id,
      object_name: item.object_name,
      source: item.source,
      field: c.field,
      old_value: c.old_value,
      new_value: c.new_value,
      operator: item.operator,
      change_type: item.change_type,
    })),
  ),
)

function toggleExpand(id: string) {
  if (expanded.has(id)) expanded.delete(id)
  else expanded.add(id)
}

function formatTime(iso: string): string {
  return formatDateTime(iso).slice(11)
}

function typeLabel(type: string): string {
  if (type === 'create') return t('changes.typeCreate')
  if (type === 'delete') return t('changes.typeDelete')
  return t('changes.typeUpdate')
}

function typeTag(type: string): 'success' | 'danger' | 'primary' {
  if (type === 'create') return 'success'
  if (type === 'delete') return 'danger'
  return 'primary'
}

// 对象跳转：专线 → 详情页；配置 → 备份页（带设备筛选定位）
function goObject(item: { source: string; object_id: number | null }) {
  if (item.source === 'circuit' && item.object_id) {
    router.push(`/circuits/${item.object_id}`)
  } else if (item.source === 'config' && item.object_id) {
    router.push({ path: '/backups', query: { device_id: item.object_id } })
  } else {
    router.push('/backups')
  }
}

async function handleExport() {
  exporting.value = true
  try {
    const params: Record<string, unknown> = {}
    if (query.value.source) params.source = query.value.source
    if (query.value.change_type) params.change_type = query.value.change_type
    if (query.value.operator) params.operator = query.value.operator
    if (query.value.keyword) params.keyword = query.value.keyword
    if (dateRange.value?.[0]) params.start = `${dateRange.value[0]}T00:00:00`
    if (dateRange.value?.[1]) params.end = `${dateRange.value[1]}T23:59:59`
    const { items, count } = await exportChanges(params)
    const data = items.flatMap(row =>
      row.changes.map(c => ({
        created_at: formatDateTime(row.created_at),
        source: row.source === 'circuit' ? t('changes.sourceCircuit') : t('changes.sourceConfig'),
        object_name: row.object_name,
        change_type: typeLabel(row.change_type),
        field: fieldLabel(c.field),
        old_value: c.old_value,
        new_value: c.new_value,
        operator: displayName(row.operator),
        remark: row.remark,
      })),
    )
    exportToCSV(data, {
      created_at: t('changes.colTime'),
      source: t('changes.filterBySource'),
      object_name: t('changes.colObject'),
      change_type: t('changes.colType'),
      field: t('changes.colField'),
      old_value: t('changes.colOld'),
      new_value: t('changes.colNew'),
      operator: t('changes.colOperator'),
      remark: t('changes.remark'),
    } as Record<keyof typeof data[number], string>, 'changes.csv')
    ElMessage.success(t('changes.exportSuccess', { count }))
  } catch (error) {
    console.error('Failed to export changes:', error)
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  loadChanges()
  loadSummary()
  loadOperators()
  loadUserNames()
})
</script>

<style scoped>
.changes-page {
  padding: 0;
}

.page-desc {
  margin-bottom: 16px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.stat-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px 16px;
}

.stat-card.is-clickable {
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.stat-card.is-clickable:hover {
  border-color: var(--el-color-primary-light-5);
}

.stat-card.is-active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
}

.stat-card.zero-muted .stat-value {
  color: var(--el-text-color-placeholder);
}

.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.stat-sub {
  margin-left: 6px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.stat-value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.summary-scope {
  margin: 8px 0 4px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.filter-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.empty-state {
  text-align: center;
  padding: 60px 0;
  color: var(--el-text-color-secondary);
}

.timeline-wrap {
  margin-top: 8px;
}

.timeline-group {
  margin-bottom: 20px;
}

.timeline-date {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
  padding-left: 2px;
}

.change-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 8px;
}

.change-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.change-time {
  font-family: monospace;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.change-object {
  color: var(--el-color-primary);
  cursor: pointer;
  font-weight: 500;
  white-space: nowrap;
}

.change-object:hover {
  text-decoration: underline;
}

.change-operator {
  margin-left: auto;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.change-body {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 13px;
  flex-wrap: wrap;
}

.change-field {
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.batch-summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.batch-count {
  color: var(--el-color-primary);
  font-weight: 600;
}

.batch-field {
  color: var(--el-text-color-secondary);
}

.batch-more {
  color: var(--el-text-color-placeholder);
}

.expand-btn {
  margin-top: 2px;
  padding: 0;
}

.change-detail {
  margin-top: 6px;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
}

.detail-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 3px 0;
  font-size: 13px;
  flex-wrap: wrap;
}

.detail-field {
  min-width: 90px;
  color: var(--el-text-color-regular);
}

.value-old {
  color: var(--el-text-color-secondary);
  text-decoration: line-through;
  word-break: break-all;
}

.value-arrow {
  color: var(--el-text-color-placeholder);
  flex-shrink: 0;
  align-self: center;
}

.value-new {
  color: var(--el-color-success);
  font-weight: 500;
  word-break: break-all;
}

.value-none {
  color: var(--el-text-color-placeholder);
}

.changes-table {
  width: 100%;
  margin-top: 8px;
}

.changes-table :deep(th) {
  white-space: nowrap;
}

.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.total-text {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

/* 移动端：统计 2 列、筛选纵向、卡片内容自动换行 */
@media (max-width: 768px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }

  .filter-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .filter-right {
    margin-left: 0;
    justify-content: space-between;
  }

  .filter-bar .el-select,
  .filter-bar .el-input,
  .filter-bar .el-date-editor {
    width: 100% !important;
  }

  .change-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }

  .change-operator {
    margin-left: 0;
  }
}
</style>
