<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../../store/auth'
import { getChatLogs, exportChatLogsCsv, type ChatLogItem } from '../../api/ai'
import { formatDateTime } from '@/lib/utils'
import { getUsers } from '../../api/users'
import { Clock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const { t } = useI18n()
const authStore = useAuthStore()

const isSuperuser = computed(() => authStore.user?.is_superuser ?? false)

const logs = ref<ChatLogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const dataType = ref('')
const loading = ref(false)
const exporting = ref(false)
const users = ref<Array<{ id: number; username: string; full_name?: string | null }>>([])
const selectedUserId = ref<number | undefined>(undefined)
// 时间范围筛选：undefined = 全部（受 30 天留存约束），7 / 30 = 近 N 天
const days = ref<number | undefined>(undefined)

// 数据类型：value 为后端枚举，label 走 i18n 中文化
const DATA_TYPES = [
  'sites', 'circuits', 'devices', 'ip_addresses', 'prefixes',
  'backups', 'inspection_results', 'topology', 'vlans', 'audit_logs', 'unknown',
] as const

const dataTypeLabel = (value: string | null | undefined): string =>
  value ? t(`system.aiChatLogsType_${value}`) : t('system.aiChatLogsType_unknown')

const typeColor: Record<string, any> = {
  circuits: 'warning',
  devices: 'primary',
  prefixes: 'success',
  ip_addresses: 'info',
  backups: 'info',
  audit_logs: 'danger',
  unknown: 'info',
}

async function fetchLogs() {
  loading.value = true
  try {
    const resp = await getChatLogs({
      skip: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
      keyword: keyword.value.trim() || undefined,
      dataType: dataType.value || undefined,
      userId: selectedUserId.value || undefined,
      days: days.value,
    })
    logs.value = resp.items
    total.value = resp.total
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

async function loadUsers() {
  if (!isSuperuser.value) return
  try {
    users.value = await getUsers()
  } catch {
    users.value = []
  }
}

async function exportCsv() {
  exporting.value = true
  try {
    // 后端流式导出：沿用当前全部筛选条件，超大结果集也不会撑爆浏览器
    const filename = await exportChatLogsCsv({
      keyword: keyword.value.trim() || undefined,
      dataType: dataType.value || undefined,
      userId: selectedUserId.value || undefined,
      days: days.value,
    })
    ElMessage.success(`${t('common.export')}：${filename}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    exporting.value = false
  }
}

function onSearch() {
  page.value = 1
  fetchLogs()
}

// 即时搜索：关键字输入 300ms 防抖后自动查询（回车/清空行为保留）
let keywordTimer: ReturnType<typeof setTimeout> | undefined
watch(keyword, () => {
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(onSearch, 300)
})

function onPageChange() {
  fetchLogs()
}

onMounted(() => {
  loadUsers()
  fetchLogs()
})
</script>

<template>
  <div class="ai-chat-logs-page">
    <el-card class="info-card" shadow="never">
      <div class="info-header">
        <div class="info-title">
          <el-icon><Clock /></el-icon>
          {{ t('system.aiChatLogs') }}
        </div>
        <el-tag type="info" effect="plain" size="small">{{ t('system.aiChatLogsRetention') }}</el-tag>
      </div>
    </el-card>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="filter-bar">
          <el-input
            v-model="keyword"
            :placeholder="t('system.aiChatLogsSearchPlaceholder')"
            prefix-icon="Search"
            clearable
            style="width: 320px"
            @keyup.enter="onSearch"
            @clear="onSearch"
          />
          <el-select
            v-model="dataType"
            :placeholder="t('system.aiChatLogsAllTypes')"
            clearable
            style="width: 180px"
            @change="onSearch"
          >
            <el-option :label="t('system.aiChatLogsAllTypes')" value="" />
            <el-option v-for="dt in DATA_TYPES" :key="dt" :label="dataTypeLabel(dt)" :value="dt" />
          </el-select>
          <el-select
            v-if="isSuperuser"
            v-model="selectedUserId"
            :placeholder="t('system.aiChatLogsAllUsers')"
            clearable
            filterable
            style="width: 180px"
            @change="onSearch"
          >
            <el-option v-for="u in users" :key="u.id" :label="u.full_name || u.username" :value="u.id" />
          </el-select>
          <el-select
            v-model="days"
            :placeholder="t('system.aiChatLogsAllRanges')"
            clearable
            style="width: 150px"
            @change="onSearch"
          >
            <el-option :label="t('system.aiChatLogsLast7Days')" :value="7" />
            <el-option :label="t('system.aiChatLogsLast30Days')" :value="30" />
          </el-select>
          <el-button @click="fetchLogs">{{ t('common.refresh') }}</el-button>
          <el-button :loading="exporting" @click="exportCsv">{{ t('common.export') }}</el-button>
        </div>
      </template>

      <el-table
        v-loading="loading"
        :data="logs"
        style="width: 100%"
        stripe
        border
        max-height="calc(100vh - 320px)"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="answer-detail">
              <div class="answer-detail-label">{{ t('system.aiChatLogsQuestion') }}：</div>
              <div class="answer-detail-text">{{ row.question }}</div>
              <div class="answer-detail-label">{{ t('system.aiChatLogsAnswer') }}：</div>
              <div class="answer-detail-text">{{ row.answerText || '-' }}</div>
              <template v-if="row.errorMessage">
                <div class="answer-detail-label">{{ t('system.aiChatLogsErrorMessage') }}：</div>
                <div class="answer-detail-text error-text">{{ row.errorMessage }}</div>
              </template>
            </div>
          </template>
        </el-table-column>

        <el-table-column :label="t('system.logTime')" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="time-cell">
              <el-icon class="time-icon"><Clock /></el-icon>
              <span>{{ formatDateTime(row.createdAt) }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column v-if="isSuperuser" :label="t('system.aiChatLogsOperator')" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="user-cell">
              <el-icon class="user-icon"><User /></el-icon>
              <span>{{ row.username || row.userId }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column :label="t('system.aiChatLogsQuestion')" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="q-text">{{ row.question }}</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('system.aiChatLogsAnswer')" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="a-text">{{ row.answerText || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('system.aiChatLogsDataType')" min-width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="typeColor[row.dataType] || 'info'" size="small" effect="plain">
              {{ dataTypeLabel(row.dataType) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column :label="t('system.aiChatLogsModel')" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="model-text">{{ row.model || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('system.aiChatLogsDuration')" min-width="90" align="right">
          <template #default="{ row }">
            <span class="duration-text">{{ row.durationMs != null ? `${row.durationMs} ms` : '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('system.aiChatLogsStatus')" min-width="80" align="center">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'failed' ? 'danger' : row.status === 'success' ? 'success' : 'info'"
              size="small"
              effect="plain"
            >
              {{ t(`system.aiChatLogsStatus_${row.status || 'unknown'}`) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column :label="t('system.aiChatLogsClientIp')" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="ip-text">{{ row.clientIp || '-' }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="onPageChange"
          @size-change="onPageChange"
        />
      </div>

      <el-empty v-if="!loading && logs.length === 0" :description="t('common.noData')" />
    </el-card>
  </div>
</template>

<style scoped>
.ai-chat-logs-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.info-card {
  border-radius: 8px;
}

.info-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.info-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.info-title .el-icon {
  color: var(--accent-primary);
}

.table-card {
  border-radius: 8px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.time-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 13px;
}

.time-icon {
  color: var(--accent-primary);
  font-size: 14px;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-primary);
}

.user-icon {
  color: var(--accent-success);
  font-size: 14px;
}

.q-text {
  color: var(--text-primary);
  font-weight: 500;
}

.a-text {
  color: var(--text-secondary);
  font-size: 13px;
}

.model-text {
  color: var(--text-secondary);
  font-size: 13px;
  font-family: var(--font-mono);
}

.duration-text {
  color: var(--text-muted);
  font-size: 12px;
  font-family: var(--font-mono);
}

.ip-text {
  color: var(--text-muted);
  font-size: 13px;
  font-family: var(--font-mono);
}

.answer-detail {
  padding: 8px 16px;
  background: var(--bg-tertiary);
  border-radius: 6px;
}

.answer-detail-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 8px;
}

.answer-detail-label:first-child {
  margin-top: 0;
}

.answer-detail-text {
  font-size: 13px;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.answer-detail-text.error-text {
  color: var(--accent-danger);
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
