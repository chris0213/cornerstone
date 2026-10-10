<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  getCircuitIncidents,
  createCircuitIncident,
  getIncidentLogs,
  addIncidentLog,
  resolveIncident,
  getCircuitIncidentStats,
  type CircuitIncident,
  type CircuitIncidentCreate,
  type CircuitIncidentLog,
  type CircuitIncidentStats,
} from '@/api/circuit_incidents'

const route = useRoute()
const circuitId = computed(() => parseInt(route.params.id as string))

const incidents = ref<CircuitIncident[]>([])
const stats = ref<CircuitIncidentStats | null>(null)
const logs = ref<CircuitIncidentLog[]>([])
const loading = ref(true)
const showCreateDialog = ref(false)
const showDetailDrawer = ref(false)
const showResolveDialog = ref(false)
const selectedIncident = ref<CircuitIncident | null>(null)
const newLogContent = ref('')

const newIncident = ref<CircuitIncidentCreate>({
  title: '',
  severity: 'minor',
  started_at: new Date().toISOString(),
  symptom: '',
  affected_sites: [],
  ticket_no: ''
})

const resolveForm = ref({
  root_cause: '',
  resolution: ''
})

const severityOptions = [
  { label: '严重', value: 'critical' },
  { label: '重要', value: 'major' },
  { label: '轻微', value: 'minor' }
]

const severityColors: Record<string, string> = {
  critical: '#F56C6C',
  major: '#E6A23C',
  minor: '#409EFF'
}

const severityLabels: Record<string, string> = {
  critical: '严重',
  major: '重要',
  minor: '轻微'
}

const statusLabels: Record<string, string> = {
  open: '处理中',
  resolved: '已解决'
}

function formatDuration(minutes: number | null): string {
  if (minutes === null) return '-'
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  if (hours > 0) {
    return `${hours}h ${mins}m`
  }
  return `${mins}m`
}

function formatTime(dateString: string): string {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

async function loadData() {
  loading.value = true
  try {
    const [incidentsData, statsData] = await Promise.all([
      getCircuitIncidents(circuitId.value),
      getCircuitIncidentStats(circuitId.value)
    ])
    incidents.value = incidentsData
    stats.value = statsData
  } catch (error) {
    console.error('Failed to load incidents:', error)
  } finally {
    loading.value = false
  }
}

async function loadLogs(incidentId: number) {
  try {
    logs.value = await getIncidentLogs(incidentId)
  } catch (error) {
    console.error('Failed to load logs:', error)
  }
}

async function handleCreateIncident() {
  try {
    await createCircuitIncident(circuitId.value, newIncident.value)
    showCreateDialog.value = false
    newIncident.value = {
      title: '',
      severity: 'minor',
      started_at: new Date().toISOString(),
      symptom: '',
      affected_sites: [],
      ticket_no: ''
    }
    await loadData()
  } catch (error) {
    console.error('Failed to create incident:', error)
  }
}

async function handleViewDetail(incident: CircuitIncident) {
  selectedIncident.value = incident
  await loadLogs(incident.id)
  showDetailDrawer.value = true
}

async function handleAddLog() {
  if (!newLogContent.value.trim() || !selectedIncident.value) return
  try {
    await addIncidentLog(selectedIncident.value.id, { content: newLogContent.value })
    newLogContent.value = ''
    await loadLogs(selectedIncident.value.id)
  } catch (error) {
    console.error('Failed to add log:', error)
  }
}

async function handleResolve() {
  if (!selectedIncident.value) return
  try {
    await resolveIncident(selectedIncident.value.id, resolveForm.value)
    showResolveDialog.value = false
    resolveForm.value = { root_cause: '', resolution: '' }
    await loadData()
    showDetailDrawer.value = false
  } catch (error) {
    console.error('Failed to resolve incident:', error)
  }
}

watch(circuitId, () => {
  loadData()
})

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="circuit-incidents-tab">
    <div class="stats-row" v-if="stats">
      <div class="stat-card">
        <div class="stat-value" :style="{ color: stats.current_count > 0 ? '#F56C6C' : '#67C23A' }">
          {{ stats.current_count }}
        </div>
        <div class="stat-label">当前故障</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.monthly_count }}</div>
        <div class="stat-label">本月故障</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.avg_duration_hours }}h</div>
        <div class="stat-label">平均恢复时长</div>
      </div>
    </div>

    <div class="actions-row">
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon> 报告新故障
      </el-button>
    </div>

    <el-table class="circuit-incidents-table" :data="incidents" v-loading="loading" border>
      <el-table-column prop="title" label="故障标题" min-width="200">
        <template #default="{ row }">
          <div class="incident-title">
            <span class="severity-dot" :style="{ backgroundColor: severityColors[row.severity] }"></span>
            {{ row.title }}
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="started_at" label="开始时间" min-width="150">
        <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
      </el-table-column>
      <el-table-column label="持续时长" min-width="120">
        <template #default="{ row }">{{ formatDuration(row.duration_minutes) }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" min-width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'open' ? 'danger' : 'success'" size="small">
            {{ statusLabels[row.status] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="150">
        <template #default="{ row }">
          <el-button size="small" @click="handleViewDetail(row)">查看详情</el-button>
          <el-button v-if="row.status === 'open'" size="small" type="success" @click="selectedIncident = row; showResolveDialog = true">
            标记解决
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && incidents.length === 0" description="暂无故障记录" />

    <el-dialog title="报告新故障" v-model="showCreateDialog" width="500px">
      <el-form :model="newIncident" label-width="100px">
        <el-form-item label="故障标题" required>
          <el-input v-model="newIncident.title" placeholder="例如：上海电信专线中断" />
        </el-form-item>
        <el-form-item label="严重程度" required>
          <el-select v-model="newIncident.severity">
            <el-option v-for="opt in severityOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="故障开始时间">
          <el-date-picker v-model="newIncident.started_at" type="datetime" value-format="yyyy-MM-dd'T'HH:mm:ss" />
        </el-form-item>
        <el-form-item label="故障现象">
          <el-input v-model="newIncident.symptom" type="textarea" :rows="3" placeholder="描述故障现象" />
        </el-form-item>
        <el-form-item label="影响站点">
          <el-input v-model="newIncident.affected_sites" type="textarea" :rows="2" placeholder="每行一个站点" />
        </el-form-item>
        <el-form-item label="运营商工单号">
          <el-input v-model="newIncident.ticket_no" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreateIncident">提交</el-button>
      </template>
    </el-dialog>

    <el-drawer title="故障详情" v-model="showDetailDrawer" direction="rtl" size="500px">
      <div v-if="selectedIncident" class="incident-detail">
        <div class="detail-header">
          <div class="detail-title">
            <span class="severity-dot-lg" :style="{ backgroundColor: severityColors[selectedIncident.severity] }"></span>
            <span>{{ selectedIncident.title }}</span>
          </div>
          <el-tag :type="selectedIncident.status === 'open' ? 'danger' : 'success'">
            {{ statusLabels[selectedIncident.status] }}
          </el-tag>
        </div>

        <el-descriptions :column="1" border class="detail-descriptions">
          <el-descriptions-item label="严重程度">
            <span :style="{ color: severityColors[selectedIncident.severity] }">{{ severityLabels[selectedIncident.severity] }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(selectedIncident.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="恢复时间">{{ selectedIncident.resolved_at ? formatTime(selectedIncident.resolved_at) : '-' }}</el-descriptions-item>
          <el-descriptions-item label="持续时长">{{ formatDuration(selectedIncident.duration_minutes) }}</el-descriptions-item>
          <el-descriptions-item label="故障现象">{{ selectedIncident.symptom }}</el-descriptions-item>
          <el-descriptions-item label="根因分析">{{ selectedIncident.root_cause || '-' }}</el-descriptions-item>
          <el-descriptions-item label="解决方案">{{ selectedIncident.resolution || '-' }}</el-descriptions-item>
          <el-descriptions-item label="运营商工单号">{{ selectedIncident.ticket_no || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="logs-section">
          <div class="logs-header">
            <el-icon><Clock /></el-icon> 处理进度
          </div>
          <div class="logs-list">
            <div v-for="log in logs" :key="log.id" class="log-item">
              <div class="log-time">{{ formatTime(log.created_at) }}</div>
              <div class="log-content">
                <span class="log-operator">{{ log.operator || '系统' }}：</span>
                {{ log.content }}
              </div>
            </div>
            <el-empty v-if="logs.length === 0" description="暂无处理记录" />
          </div>
          <div class="log-input" v-if="selectedIncident.status === 'open'">
            <el-input v-model="newLogContent" placeholder="添加处理记录..." @keyup.enter="handleAddLog" />
            <el-button type="primary" size="small" @click="handleAddLog">追加</el-button>
          </div>
        </div>

        <div v-if="selectedIncident.status === 'open'" class="resolve-section">
          <el-button type="success" @click="showResolveDialog = true">
            <el-icon><CircleCheck /></el-icon> 标记已解决
          </el-button>
        </div>
      </div>
    </el-drawer>

    <el-dialog title="标记故障已解决" v-model="showResolveDialog" width="500px">
      <el-form :model="resolveForm" label-width="100px">
        <el-form-item label="根因分析">
          <el-input v-model="resolveForm.root_cause" type="textarea" :rows="3" placeholder="描述故障根因" />
        </el-form-item>
        <el-form-item label="解决方案">
          <el-input v-model="resolveForm.resolution" type="textarea" :rows="3" placeholder="描述解决方案" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showResolveDialog = false">取消</el-button>
        <el-button type="success" @click="handleResolve">确认解决</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.circuit-incidents-tab {
  padding: 16px 0;
}

.stats-row {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  flex: 1;
  background: #fafafa;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #262626;
}

.stat-label {
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 4px;
}

.actions-row {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
}

.incident-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.severity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.severity-dot-lg {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.detail-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 600;
}

.detail-descriptions {
  margin-bottom: 20px;
}

.logs-section {
  background: #fafafa;
  border-radius: 8px;
  padding: 16px;
}

.logs-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  margin-bottom: 16px;
  color: #262626;
}

.logs-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.log-item {
  padding: 12px;
  background: #fff;
  border-radius: 6px;
}

.log-time {
  font-size: 12px;
  color: #bfbfbf;
  margin-bottom: 4px;
}

.log-content {
  font-size: 14px;
  color: #262626;
}

.log-operator {
  font-weight: 600;
  color: #1890ff;
}

.log-input {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.log-input .el-input {
  flex: 1;
}

.resolve-section {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.circuit-incidents-table :deep(.cell) {
  line-height: 1.5;
}

.circuit-incidents-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>