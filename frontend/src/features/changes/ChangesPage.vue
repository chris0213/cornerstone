<template>
  <div class="changes-page">
    <div class="page-desc">{{ t('changes.description') }}</div>

    <!-- 统计卡片 -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">{{ t('changes.statTotal') }}<span class="stat-sub">{{ t('changes.statThisMonth') }}</span></div>
        <div class="stat-value">{{ summary?.total ?? '-' }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">{{ t('changes.statCircuit') }}</div>
        <div class="stat-value">{{ summary?.circuit_count ?? '-' }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">{{ t('changes.statConfig') }}</div>
        <div class="stat-value">{{ summary?.config_count ?? '-' }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">{{ t('changes.statObjects') }}</div>
        <div class="stat-value">{{ summary?.object_count ?? '-' }}</div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="query.source" :placeholder="t('changes.sourceAll')" clearable style="width: 130px">
        <el-option :label="t('changes.sourceCircuit')" value="circuit" />
        <el-option :label="t('changes.sourceConfig')" value="config" />
      </el-select>
      <el-input v-model="query.operator" :placeholder="t('changes.operatorPlaceholder')" clearable style="width: 130px" />
      <el-input v-model="query.keyword" :placeholder="t('changes.keywordPlaceholder')" clearable style="width: 200px" />
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        :start-placeholder="t('changes.startPlaceholder')"
        :end-placeholder="t('changes.endPlaceholder')"
        style="width: 240px"
      />
      <el-button type="primary" @click="search">{{ t('changes.query') }}</el-button>
      <el-button @click="resetFilters">{{ t('changes.reset') }}</el-button>
      <div class="filter-right">
        <el-button @click="handleExport">{{ t('changes.export') }}</el-button>
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="timeline">{{ t('changes.viewTimeline') }}</el-radio-button>
          <el-radio-button value="table">{{ t('changes.viewTable') }}</el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <!-- 时间线视图 -->
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
            <span
              class="change-object"
              @click="goObject(item)"
            >{{ item.object_name || '-' }}</span>
            <span class="change-field">{{ item.field }}</span>
            <el-tag size="small" :type="typeTag(item.change_type)">{{ typeLabel(item.change_type) }}</el-tag>
          </div>
          <div class="change-body">
            <template v-if="item.old_value || item.new_value">
              <span class="value-old">{{ item.old_value || '空' }}</span>
              <el-icon class="value-arrow"><Right /></el-icon>
              <span class="value-new">{{ item.new_value || '空' }}</span>
            </template>
            <span v-else class="value-none">-</span>
            <span class="change-operator">{{ item.operator }}</span>
          </div>
          <div v-if="item.remark" class="change-remark">{{ item.remark }}</div>
        </div>
      </div>
    </div>

    <!-- 表格视图 -->
    <el-table
      v-else
      class="changes-table"
      :data="changes"
      v-loading="loading"
      border
      stripe
      show-overflow-tooltip
    >
      <el-table-column prop="created_at" :label="t('changes.colTime')" min-width="150" fixed>
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="object_name" :label="t('changes.colObject')" min-width="160">
        <template #default="{ row }">
          <span class="change-object" @click="goObject(row)">{{ row.object_name || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="field" :label="t('changes.colField')" min-width="110" />
      <el-table-column prop="old_value" :label="t('changes.colOld')" min-width="140" />
      <el-table-column prop="new_value" :label="t('changes.colNew')" min-width="140" />
      <el-table-column prop="operator" :label="t('changes.colOperator')" min-width="100" />
      <el-table-column prop="change_type" :label="t('changes.colType')" min-width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="typeTag(row.change_type)">{{ typeLabel(row.change_type) }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Files, Right } from '@element-plus/icons-vue'
import { listChanges, getChangesSummary, type ChangeItem, type ChangeSummary } from '@/api/changes'
import { formatDateTime } from '@/lib/utils'
import { exportToCSV } from '@/lib/csv'

const { t } = useI18n()
const router = useRouter()

const loading = ref(false)
const changes = ref<ChangeItem[]>([])
const summary = ref<ChangeSummary | null>(null)
const viewMode = ref<'timeline' | 'table'>('timeline')
const dateRange = ref<string[] | null>(null)

const query = ref({
  source: '',
  operator: '',
  keyword: '',
})

// AbortController：新查询取消旧请求
let currentAbort: AbortController | null = null

async function loadChanges() {
  currentAbort?.abort()
  currentAbort = new AbortController()
  loading.value = true
  try {
    const params: Record<string, unknown> = { limit: 200 }
    if (query.value.source) params.source = query.value.source
    if (query.value.operator) params.operator = query.value.operator
    if (query.value.keyword) params.keyword = query.value.keyword
    if (dateRange.value?.[0]) params.start = `${dateRange.value[0]}T00:00:00`
    if (dateRange.value?.[1]) params.end = `${dateRange.value[1]}T23:59:59`
    changes.value = await listChanges(params)
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

function search() {
  loadChanges()
}

function resetFilters() {
  query.value = { source: '', operator: '', keyword: '' }
  dateRange.value = null
  loadChanges()
}

// 时间线按日期分组
const timelineGroups = computed(() => {
  const map = new Map<string, ChangeItem[]>()
  for (const item of changes.value) {
    const day = formatDateTime(item.created_at).slice(0, 10)
    const list = map.get(day) || []
    list.push(item)
    map.set(day, list)
  }
  return [...map.entries()].map(([date, items]) => ({ date, items }))
})

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

function goObject(item: ChangeItem) {
  if (item.source === 'circuit' && item.object_id) {
    router.push(`/circuits/${item.object_id}/changes`)
  } else {
    router.push('/backups')
  }
}

function handleExport() {
  const data = changes.value.map(c => ({
    created_at: formatDateTime(c.created_at),
    source: c.source === 'circuit' ? t('changes.sourceCircuit') : t('changes.sourceConfig'),
    object_name: c.object_name,
    field: c.field,
    old_value: c.old_value,
    new_value: c.new_value,
    operator: c.operator,
    change_type: typeLabel(c.change_type),
    remark: c.remark,
  }))
  exportToCSV(data, {
    created_at: t('changes.colTime'),
    source: t('changes.colType'),
    object_name: t('changes.colObject'),
    field: t('changes.colField'),
    old_value: t('changes.colOld'),
    new_value: t('changes.colNew'),
    operator: t('changes.colOperator'),
    change_type: t('changes.colType'),
    remark: t('changes.remark'),
  } as Record<keyof typeof data[number], string>, 'changes.csv')
}

onMounted(() => {
  loadChanges()
  loadSummary()
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
  margin-bottom: 16px;
}

.stat-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px 16px;
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

.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
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

.change-field {
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.change-body {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 13px;
}

.value-old {
  color: var(--el-text-color-secondary);
  text-decoration: line-through;
  word-break: break-all;
}

.value-arrow {
  color: var(--el-text-color-placeholder);
  flex-shrink: 0;
}

.value-new {
  color: var(--el-color-success);
  font-weight: 500;
  word-break: break-all;
}

.change-operator {
  margin-left: auto;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.change-remark {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.changes-table {
  width: 100%;
}

.changes-table :deep(th) {
  white-space: nowrap;
}

/* 移动端：统计 2 列、筛选纵向、时间线自动换行 */
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

  .change-body {
    flex-wrap: wrap;
  }

  .change-operator {
    margin-left: 0;
  }
}
</style>
