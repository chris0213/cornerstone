<script setup lang="ts">import { ref, computed, onMounted } from 'vue';
import { ElMessage, ElIcon } from 'element-plus';
import { confirmAndRun } from '@/lib/confirm';
import { Warning, Clock, Cpu, TrendCharts, Promotion } from '@element-plus/icons-vue';
import { getTasks, getRecords, getFingerprints, getAlertCount, createTask, updateTask, deleteTask, executeTask, toggleTask, getInspectionCategories, getDevicesByCategory, type InspectionTask, type InspectionTaskCreate, type InspectionRecord, type DeviceFingerprint, type AlertCount, type ExecuteResponse, type InspectionCategory, type InspectionDeviceResult } from '@/api/inspection';
import { getSites, type SiteResponse } from '@/api/sites';
import { useAuthStore } from '@/store/auth';
import { useI18n } from 'vue-i18n'
const { locale, t } = useI18n();
const authStore = useAuthStore();
// 写操作（新建/编辑/删除/启停/执行）需要 inspection:write 权限
const canWrite = computed(() => authStore.hasPermission('inspection', 'write'));
// 状态管理
const activeTab = ref('tasks');
const loading = ref(false);
const tasks = ref<InspectionTask[]>([]);
const records = ref<InspectionRecord[]>([]);
const fingerprints = ref<DeviceFingerprint[]>([]);
const sites = ref<SiteResponse[]>([]);
const alertCount = ref<AlertCount>({
 total: 0,
 unresolved: 0,
 new_device: 0,
 missing_device: 0,
 changed_device: 0
});

// 批量选择
const selectedTaskIds = ref<number[]>([])
// 任务表单
const showTaskForm = ref(false);
const editingTask = ref<InspectionTask | null>(null);
const taskForm = ref<InspectionTaskCreate>({
 name: '',
 scan_type: 'full',
 is_enabled: true,
 cron_expr: '0 */4 * * *',
 target_type: 'all_devices',
 site_id: undefined,
 ip_range: '',
 snmp_community: 'Ushareit.com',
 snmp_version: 'v2c',
 snmp_timeout: 3,
 snmp_retries: 1,
 tcp_ports: [22, 80, 443, 445, 3389],
 tcp_timeout_ms: 2000,
 max_concurrent: 50,
 alert_on_offline: true,
 alert_on_new_device: true,
 alert_on_fingerprint_change: true
});
// 执行状态
const executingTaskId = ref<number | null>(null);

// 智能分类相关
const selectedResultId = ref<number | null>(null);
const categories = ref<InspectionCategory[]>([]);
const selectedCategory = ref<string>('');
const categoryDevices = ref<InspectionDeviceResult[]>([]);
const categoryLoading = ref(false);

async function loadCategories(recordId: number) {
  try {
    selectedResultId.value = recordId;
    const result = await getInspectionCategories(recordId);
    categories.value = result.categories;
    selectedCategory.value = '';
    categoryDevices.value = [];
  } catch (error) {
    console.error('Failed to load categories:', error);
    categories.value = [];
  }
}

async function loadDevicesByCategory(categoryName: string) {
  if (!selectedResultId.value) return;
  
  categoryLoading.value = true;
  try {
    selectedCategory.value = categoryName;
    categoryDevices.value = await getDevicesByCategory(selectedResultId.value, categoryName);
  } catch (error) {
    console.error('Failed to load devices:', error);
    categoryDevices.value = [];
  } finally {
    categoryLoading.value = false;
  }
}

// 统计数据
const latestRecord = computed(() => records.value[0] || null);
const onlineRate = computed(() => {
 if (!latestRecord.value)
 return 0;
 const total = latestRecord.value.online_count + latestRecord.value.offline_count;
 if (total === 0)
 return 0;
 return ((latestRecord.value.online_count / total) * 100).toFixed(1);
});
// 格式化时间
function formatTime(dateString: string) {
 if (!dateString || dateString === 'None' || dateString === 'null') {
 return '-';
 }
 let date: Date;
 if (dateString.includes('T') && !dateString.includes('Z') && !dateString.includes('+')) {
 date = new Date(dateString.replace('T', ' '));
 } else {
 date = new Date(dateString);
 }
 if (date.getTime() < 86400000) {
 return '-';
 }
 return date.toLocaleString(locale.value || 'zh-CN', {
 year: 'numeric',
 month: '2-digit',
 day: '2-digit',
 hour: '2-digit',
 minute: '2-digit'
 });
}
// 格式化时长
function formatDuration(seconds: number) {
 if (!seconds || seconds < 0)
 return '-';
 if (seconds < 60)
 return `${seconds.toFixed(1)}${t('inspection.seconds')}`;
 if (seconds < 3600)
 return `${(seconds / 60).toFixed(1)}${t('inspection.minutes')}`;
 return `${(seconds / 3600).toFixed(1)}${t('inspection.hours')}`;
}
// 获取扫描类型名称
function getScanTypeName(type: string): string {
 return type === 'full' ? t('inspection.fullScan') : t('inspection.quickScan');
}
// 获取目标类型名称
function getTargetTypeName(type: string): string {
 const typeMap: Record<string, string> = {
 all_devices: t('inspection.allDevices'),
 site: t('inspection.bySite'),
 ip_range: t('inspection.ipRange')
 };
 return typeMap[type] || type;
}
// 根据站点ID获取站点名称
function getSiteName(siteId: number): string {
 if (!sites.value || sites.value.length === 0) {
 return `${t('inspection.site')} ${siteId}`;
 }
 const site = sites.value.find(s => s.id === siteId);
 return site ? site.name : `${t('inspection.site')} ${siteId}`;
}
// 获取状态样式
function getStatusClass(status: string): string {
 const classMap: Record<string, string> = {
 running: 'el-tag--warning',
 completed: 'el-tag--success',
 failed: 'el-tag--danger',
 pending: 'el-tag--info'
 };
 return classMap[status] || 'el-tag--info';
}
// 获取状态名称
function getStatusName(status: string): string {
 const nameMap: Record<string, string> = {
 running: t('inspection.running'),
 completed: t('inspection.completed'),
 success: t('common.success'),
 failed: t('common.failed'),
 pending: t('inspection.pending')
 };
 return nameMap[status] || status;
}
// 获取触发类型名称
function getTriggerName(trigger: string): string {
 const nameMap: Record<string, string> = {
 manual: t('inspection.manualTrigger'),
 scheduled: t('inspection.scheduledTask'),
 api: t('inspection.apiCall')
 };
 return nameMap[trigger] || trigger;
}
// 加载数据
async function loadData() {
 loading.value = true;
 try {
 await Promise.all([
 loadTasks(),
 loadRecords(),
 loadFingerprints(),
 loadAlertCount(),
 loadSites()
 ]);
 }
 catch (error) {
 console.error(t('inspection.loadFailed'), error);
 }
 finally {
 loading.value = false;
 }
}
async function loadTasks() {
 tasks.value = await getTasks();
}
async function loadRecords() {
 records.value = await getRecords(undefined, undefined, undefined, 10);
}
async function loadFingerprints() {
 fingerprints.value = await getFingerprints();
}
async function loadAlertCount() {
 alertCount.value = await getAlertCount();
}
async function loadSites() {
 sites.value = await getSites();
}
// 打开表单
function openTaskForm(task?: InspectionTask) {
 if (task) {
 editingTask.value = task;
 taskForm.value = {
 name: task.name,
 scan_type: task.scan_type,
 is_enabled: task.is_enabled,
 cron_expr: task.cron_expr,
 target_type: task.target_type,
 site_id: task.site_id ?? undefined,
 ip_range: task.ip_range || '',
 snmp_community: task.snmp_community,
 snmp_version: task.snmp_version,
 snmp_timeout: task.snmp_timeout,
 snmp_retries: task.snmp_retries,
 tcp_ports: task.tcp_ports,
 tcp_timeout_ms: task.tcp_timeout_ms,
 max_concurrent: task.max_concurrent,
 alert_on_offline: task.alert_on_offline,
 alert_on_new_device: task.alert_on_new_device,
 alert_on_fingerprint_change: task.alert_on_fingerprint_change
 };
 }
 else {
 editingTask.value = null;
 taskForm.value = {
 name: '',
 scan_type: 'full',
 is_enabled: true,
 cron_expr: '0 */4 * * *',
 target_type: 'all_devices',
 site_id: undefined,
 ip_range: '',
 snmp_community: 'public',
 snmp_version: 'v2c',
 snmp_timeout: 3,
 snmp_retries: 1,
 tcp_ports: [22, 80, 443, 445, 3389],
 tcp_timeout_ms: 2000,
 max_concurrent: 50,
 alert_on_offline: true,
 alert_on_new_device: true,
 alert_on_fingerprint_change: true
 };
 }
 showTaskForm.value = true;
}
// 关闭表单
function closeTaskForm() {
 showTaskForm.value = false;
 editingTask.value = null;
}
// 保存任务
async function saveTask() {
 if (!taskForm.value.name) {
 ElMessage.error(t('inspection.taskNameRequired'));
 return;
 }
 // 如果选择IP范围但未填写，显示警告
 if (taskForm.value.target_type === 'ip_range' && !taskForm.value.ip_range) {
 ElMessage.error(t('inspection.ipRangeRequired'));
 return;
 }
 
 // 兼容：将 tcp_ports 文本输入转为 number[]
 const payload: any = { ...taskForm.value };
 if (typeof payload.tcp_ports === 'string') {
   payload.tcp_ports = payload.tcp_ports
     .split(/[,，\s]+/)
     .map((s: string) => parseInt(s, 10))
     .filter((n: number) => Number.isFinite(n) && n > 0);
 }
 
 loading.value = true;
 try {
 const hasId = editingTask.value && typeof (editingTask.value as any).id === 'number';
 if (hasId) {
 await updateTask((editingTask.value as any).id, payload);
 ElMessage.success(t('inspection.taskUpdated'));
 }
 else {
 await createTask(payload);
 ElMessage.success(t('inspection.taskCreated'));
 }
 await loadTasks();
 closeTaskForm();
 }
 catch (error: any) {
   const detail = error?.response?.data?.detail;
   ElMessage.error(detail ? `${t('inspection.saveFailed')}: ${detail}` : t('inspection.saveFailed'));
 }
 finally {
 loading.value = false;
 }
}
// 删除任务
async function handleDelete(taskId: number) {
  // 失败静默与原行为一致：不传 errorMessage
  await confirmAndRun({
    message: t('inspection.confirmDelete'),
    title: t('common.confirm'),
    action: async () => {
      await deleteTask(taskId);
      await loadTasks();
    },
    successMessage: t('inspection.deleteSuccess'),
  });
}
// 切换任务启用状态
async function handleToggle(task: InspectionTask) {
 const taskId = task.id;
 // v-model 已经切换了值，所以 newValue 是切换后的值
 const newValue = task.is_enabled;
 const expectedValue = !newValue; // 期望的值（切换前的值）

 try {
 await toggleTask(taskId);
 // 切换成功，newValue 就是新的状态
 ElMessage.success(newValue ? t('inspection.taskEnabled') : t('inspection.taskDisabled'));
 }
 catch (error) {
 // 如果失败，恢复原来的状态（使用 find 确保 task 仍存在）
 const taskToRestore = tasks.value.find(t => t.id === taskId);
 if (taskToRestore) {
 taskToRestore.is_enabled = expectedValue;
 }
 ElMessage.error(t('inspection.toggleFailed'));
 }
}

// 选择变化（批量操作）
function handleSelectionChange(val: any[]) {
 selectedTaskIds.value = val.map(item => item.id)
}

// 批量删除
async function handleBatchDelete() {
 if (selectedTaskIds.value.length === 0) return;
 await confirmAndRun({
   message: t('inspection.confirmBatchDelete', { count: selectedTaskIds.value.length }),
   title: t('inspection.confirmBatchDeleteTitle'),
   confirmText: t('common.delete'),
   cancelText: t('common.cancel'),
   action: async () => {
     for (const id of selectedTaskIds.value) {
       await deleteTask(id)
     }
     selectedTaskIds.value = []
     await loadTasks()
   },
   successMessage: t('inspection.batchDeleteSuccess', { count: selectedTaskIds.value.length }),
   errorMessage: t('inspection.batchDeleteFailed'),
 })
}

// 复制任务
async function duplicateTask(task: InspectionTask) {
 try {
 const copy: any = { ...task }
 // 清理id和时间字段
 delete copy.id
 copy.name = `${task.name} - ${t('inspection.copy')}`
 // 将可能为null的数组字段保底
 copy.tcp_ports = copy.tcp_ports || [22,80,443,445,3389]
 await createTask(copy)
 ElMessage.success(t('inspection.duplicateSuccess'))
 await loadTasks()
 } catch (error) {
 console.error(t('inspection.duplicateFailed'), error)
 ElMessage.error(t('inspection.duplicateFailed'))
 }
}
// 执行巡检
async function handleExecute(taskId: number) {
 executingTaskId.value = taskId;
 try {
 const result: ExecuteResponse = await executeTask(taskId);
 if (result.result_id) {
 ElMessage.success(t('inspection.started'));
 await loadRecords();
 await loadFingerprints();
 await loadAlertCount();
 }
 else {
 ElMessage.error(t('inspection.executeFailed'));
 }
 }
 catch (error) {
 ElMessage.error(t('inspection.executeFailed'));
 }
 finally {
 executingTaskId.value = null;
 }
}
onMounted(() => {
 loadData();
});
</script>

<template>
  <div class="inspection-page">
    <!-- 统计卡片 -->
    <div class="overview-cards">
      <div class="overview-card">
        <div class="overview-card-icon">
          <ElIcon><Clock /></ElIcon>
        </div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('inspection.tasks') }}</div>
          <div class="overview-card-value">{{ tasks.length }}</div>
          <div class="overview-card-trend">{{ t('inspection.configuredTasks') }}</div>
        </div>
      </div>
      <div class="overview-card overview-card-purple">
        <div class="overview-card-icon">
          <ElIcon><Promotion /></ElIcon>
        </div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('inspection.records') }}</div>
          <div class="overview-card-value">{{ records.length }}</div>
          <div class="overview-card-trend">{{ t('inspection.historyRecords') }}</div>
        </div>
      </div>
      <div class="overview-card overview-card-success">
        <div class="overview-card-icon">
          <ElIcon><Cpu /></ElIcon>
        </div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('inspection.fingerprints') }}</div>
          <div class="overview-card-value">{{ fingerprints.length }}</div>
          <div class="overview-card-trend">{{ t('inspection.discoveredDevices') }}</div>
        </div>
      </div>
      <div class="overview-card overview-card-warning">
        <div class="overview-card-icon">
          <ElIcon><Warning /></ElIcon>
        </div>
        <div class="overview-card-content">
          <div class="overview-card-label">{{ t('inspection.pendingAlerts') }}</div>
          <div class="overview-card-value">{{ alertCount.unresolved }}</div>
          <div class="overview-card-trend">{{ t('inspection.needAttention') }}</div>
        </div>
      </div>
    </div>

    <!-- 最近巡检概览 -->
    <el-card class="table-card" shadow="never" v-if="latestRecord">
      <template #header>
        <div class="card-title">
          <ElIcon><TrendCharts /></ElIcon>
          {{ t('inspection.latestInspection') }}
          <span class="card-time">{{ formatTime(latestRecord.started_at) }}</span>
        </div>
      </template>
      <div class="overview-stats">
        <div class="overview-item">
          <span class="overview-label">{{ t('inspection.scanTargets') }}</span>
          <span class="overview-value">{{ latestRecord.total_targets }}</span>
        </div>
        <div class="overview-item">
          <span class="overview-label">{{ t('inspection.onlineDevices') }}</span>
          <span class="overview-value success">{{ latestRecord.online_count }}</span>
        </div>
        <div class="overview-item">
          <span class="overview-label">{{ t('inspection.offlineDevices') }}</span>
          <span class="overview-value danger">{{ latestRecord.offline_count }}</span>
        </div>
        <div class="overview-item">
          <span class="overview-label">{{ t('inspection.onlineRate') }}</span>
          <span class="overview-value info">{{ onlineRate }}%</span>
        </div>
        <div class="overview-item">
          <span class="overview-label">{{ t('inspection.newDiscovered') }}</span>
          <span class="overview-value warning">{{ latestRecord.new_device_count }}</span>
        </div>
        <div class="overview-item">
          <span class="overview-label">{{ t('inspection.changeCount') }}</span>
          <span class="overview-value">{{ latestRecord.change_count }}</span>
        </div>
        <div class="overview-item">
          <span class="overview-label">{{ t('inspection.duration') }}</span>
          <span class="overview-value">{{ formatDuration(latestRecord.duration_seconds || 0) }}</span>
        </div>
        <div class="overview-item">
          <span class="overview-label">{{ t('common.status') }}</span>
          <el-tag :class="getStatusClass(latestRecord.status)" size="small">
            {{ getStatusName(latestRecord.status) }}
          </el-tag>
        </div>
      </div>
    </el-card>

    <!-- 标签页内容 -->
    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="card-title">
          <ElIcon><TrendCharts /></ElIcon>
          {{ t('inspection.smartRobot') }}
        </div>
      </template>
      
      <el-tabs v-model="activeTab" class="inspection-tabs">
        <!-- 巡检任务 -->
        <el-tab-pane :label="t('inspection.tasks')" name="tasks">
          <div class="tab-content">
            <div class="content-header">
              <el-button v-if="canWrite" type="primary" icon="Plus" @click="openTaskForm">
                {{ t('inspection.createTask') }}
              </el-button>
              <el-button v-if="canWrite" type="danger" style="margin-left:8px" @click="handleBatchDelete" :disabled="selectedTaskIds.length===0">
                {{ t('inspection.batchDelete') }}
              </el-button>
            </div>

            <el-table class="inspection-task-table" :data="tasks" v-loading="loading" @selection-change="handleSelectionChange">
              <el-table-column v-if="canWrite" type="selection" width="55" />
              <el-table-column prop="name" :label="t('inspection.taskName')" min-width="200" />
              <el-table-column prop="scan_type" :label="t('inspection.scanType')" min-width="100">
                <template #default="{ row }">{{ getScanTypeName(row.scan_type) }}</template>
              </el-table-column>
              <el-table-column prop="target_type" :label="t('inspection.scanScope')" min-width="100">
                <template #default="{ row }">{{ getTargetTypeName(row.target_type) }}</template>
              </el-table-column>
              <el-table-column :label="t('inspection.targetRange')" min-width="120">
                <template #default="{ row }">
                  <template v-if="row.target_type === 'site' && row.site_id">
                    {{ getSiteName(row.site_id) }}
                  </template>
                  <template v-else-if="row.target_type === 'ip_range' && row.ip_range">
                    {{ row.ip_range }}
                  </template>
                  <template v-else-if="row.target_type === 'all_devices'">
                    {{ t('inspection.allDevices') }}
                  </template>
                  <template v-else>
                    -
                  </template>
                </template>
              </el-table-column>
              <el-table-column prop="cron_expr" :label="t('inspection.cronExpression')" min-width="120" />
              <el-table-column prop="is_enabled" :label="t('common.status')" min-width="80">
                <template #default="{ row }">
                  <el-switch
                    v-if="canWrite"
                    v-model="row.is_enabled"
                    @change="handleToggle(row)"
                    :disabled="loading"
                  />
                  <el-tag v-else size="small" :type="row.is_enabled ? 'success' : 'info'" effect="plain">
                    {{ row.is_enabled ? t('common.enabled') : t('common.disabled') }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="last_run_at" :label="t('inspection.lastExecution')" min-width="140">
                <template #default="{ row }">
                  {{ row.last_run_at ? formatTime(row.last_run_at) : '-' }}
                </template>
              </el-table-column>
              <el-table-column :label="t('common.actions')" min-width="320">
                <template #default="{ row }">
                  <div style="display: flex; gap: 8px; flex-wrap: nowrap;">
                    <el-button
                      v-if="canWrite"
                      type="primary"
                      size="small"
                      icon="VideoPlay"
                      :loading="executingTaskId === row.id"
                      @click="handleExecute(row.id)"
                    >
                      {{ t('inspection.execute') }}
                    </el-button>
                    <el-button
                      v-if="canWrite"
                      type="default"
                      size="small"
                      icon="Edit"
                      @click="openTaskForm(row)"
                    >
                      {{ t('common.edit') }}
                    </el-button>
                    <el-button
                      v-if="canWrite"
                      type="info"
                      size="small"
                      icon="DocumentCopy"
                      @click="duplicateTask(row)"
                    >
                      {{ t('inspection.duplicate') }}
                    </el-button>
                    <el-button
                      v-if="canWrite"
                      type="danger"
                      size="small"
                      icon="Delete"
                      @click="handleDelete(row.id)"
                    >
                      {{ t('common.delete') }}
                    </el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 巡检记录 -->
        <el-tab-pane :label="t('inspection.records')" name="records">
          <div class="tab-content">
            <div v-if="categories.length > 0" class="smart-categories-section">
              <div class="section-header">
                <span>智能分类</span>
                <el-button size="small" @click="selectedResultId = null; categories = []; selectedCategory = ''; categoryDevices = []">关闭</el-button>
              </div>
              
              <div class="category-tabs">
                <button 
                  v-for="cat in categories" 
                  :key="cat.name"
                  class="category-tab"
                  :class="{ active: selectedCategory === cat.name }"
                  :style="{ '--category-color': cat.color }"
                  @click="loadDevicesByCategory(cat.name)"
                >
                  <span class="category-dot" :style="{ backgroundColor: cat.color }"></span>
                  <span>{{ cat.label }}</span>
                  <span class="category-count">{{ cat.count }}</span>
                </button>
              </div>
              
              <div v-if="selectedCategory && categoryDevices.length > 0" class="category-devices">
                <el-table class="inspection-category-table" :data="categoryDevices" v-loading="categoryLoading">
                  <el-table-column prop="ip_address" label="IP地址" min-width="120" />
                  <el-table-column prop="sys_name" label="设备名称" min-width="150" />
                  <el-table-column prop="vendor" label="厂商" min-width="100" />
                  <el-table-column prop="cpu_usage" label="CPU使用率" min-width="100">
                    <template #default="{ row }">{{ row.cpu_usage ? row.cpu_usage.toFixed(1) + '%' : '-' }}</template>
                  </el-table-column>
                  <el-table-column prop="memory_usage" label="内存使用率" min-width="100">
                    <template #default="{ row }">{{ row.memory_usage ? row.memory_usage.toFixed(1) + '%' : '-' }}</template>
                  </el-table-column>
                  <el-table-column prop="is_online" label="状态" min-width="80">
                    <template #default="{ row }">
                      <el-tag :type="row.is_online ? 'success' : 'danger'" size="small">
                        {{ row.is_online ? '在线' : '离线' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="error_message" label="错误信息" min-width="200">
                    <template #default="{ row }">{{ row.error_message || '-' }}</template>
                  </el-table-column>
                </el-table>
              </div>
              <div v-if="selectedCategory && categoryDevices.length === 0" class="empty-category">
                <el-empty description="该分类下无设备" />
              </div>
            </div>
            
            <el-table class="inspection-records-table" :data="records" v-loading="loading">
              <el-table-column prop="id" :label="t('inspection.recordId')" min-width="80" />
              <el-table-column prop="scan_type" :label="t('inspection.scanType')" min-width="100">
                <template #default="{ row }">{{ getScanTypeName(row.scan_type) }}</template>
              </el-table-column>
              <el-table-column prop="trigger" :label="t('inspection.triggerMethod')" min-width="100">
                <template #default="{ row }">{{ getTriggerName(row.trigger) }}</template>
              </el-table-column>
              <el-table-column prop="total_targets" :label="t('inspection.scanTargets')" min-width="100" />
              <el-table-column prop="online_count" :label="t('inspection.onlineDevices')" min-width="100" />
              <el-table-column prop="offline_count" :label="t('inspection.offlineDevices')" min-width="100" />
              <el-table-column prop="new_device_count" :label="t('inspection.newDevices')" min-width="80" />
              <el-table-column prop="change_count" :label="t('inspection.changeCount')" min-width="80" />
              <el-table-column prop="duration_seconds" :label="t('inspection.duration')" min-width="100">
                <template #default="{ row }">{{ formatDuration(row.duration_seconds || 0) }}</template>
              </el-table-column>
              <el-table-column prop="status" :label="t('common.status')" min-width="80">
                <template #default="{ row }">
                  <el-tag :class="getStatusClass(row.status)" size="small">
                    {{ getStatusName(row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="started_at" :label="t('inspection.executeTime')" min-width="140">
                <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" min-width="100">
                <template #default="{ row }">
                  <el-button size="small" type="primary" @click="loadCategories(row.id)">查看分类</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 设备指纹 -->
        <el-tab-pane :label="t('inspection.fingerprints')" name="fingerprints">
          <div class="tab-content">
            <el-table class="inspection-fingerprints-table" :data="fingerprints" v-loading="loading">
              <el-table-column prop="ip_address" :label="t('inspection.ipAddress')" min-width="110" />
              <el-table-column prop="sys_name" :label="t('inspection.deviceName')" min-width="120" />
              <el-table-column prop="vendor" :label="t('inspection.vendor')" min-width="100" />
              <el-table-column prop="sys_descr" :label="t('inspection.deviceDescription')" min-width="200" />
              <el-table-column prop="last_seen_online" :label="t('inspection.lastOnline')" min-width="140">
                <template #default="{ row }">{{ formatTime(row.last_seen_online) }}</template>
              </el-table-column>
              <el-table-column prop="last_full_scan_at" :label="t('inspection.fullScan')" min-width="140">
                <template #default="{ row }">{{ formatTime(row.last_full_scan_at) }}</template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 任务表单弹窗 -->
    <el-dialog 
      :title="editingTask ? t('inspection.editTask') : t('inspection.createTask')" 
      v-model="showTaskForm" 
      width="700px"
      @close="closeTaskForm"
    >
      <el-form :model="taskForm" label-width="140px">
        <el-form-item :label="t('inspection.taskName')" required>
          <el-input v-model="taskForm.name" :placeholder="t('inspection.taskNamePlaceholder')" />
        </el-form-item>
        
        <el-form-item :label="t('inspection.scanType')">
          <el-select v-model="taskForm.scan_type">
            <el-option :label="t('inspection.fullScan')" value="full" />
            <el-option :label="t('inspection.quickScan')" value="quick" />
          </el-select>
        </el-form-item>
        
        <el-form-item :label="t('inspection.scanScope')">
          <el-select v-model="taskForm.target_type">
            <el-option :label="t('inspection.allDevices')" value="all_devices" />
            <el-option :label="t('inspection.bySite')" value="site" />
            <el-option :label="t('inspection.ipRange')" value="ip_range" />
          </el-select>
        </el-form-item>
        
        <el-form-item :label="t('inspection.selectSite')" v-if="taskForm.target_type === 'site'">
          <el-select v-model="taskForm.site_id" :placeholder="t('inspection.selectSite')">
            <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
          </el-select>
        </el-form-item>
        
        <el-form-item :label="t('inspection.ipRange')" v-if="taskForm.target_type === 'ip_range'">
          <el-input v-model="taskForm.ip_range" :placeholder="t('inspection.ipRangePlaceholder')" />
        </el-form-item>
        
        <el-form-item :label="t('inspection.cronExpression')">
          <el-input v-model="taskForm.cron_expr" :placeholder="t('inspection.cronPlaceholder')" />
          <el-button type="link" size="small" @click="taskForm.cron_expr = '0 */4 * * *'">{{ t('inspection.every4Hours') }}</el-button>
          <el-button type="link" size="small" @click="taskForm.cron_expr = '0 * * * *'">{{ t('inspection.every1Hour') }}</el-button>
          <el-button type="link" size="small" @click="taskForm.cron_expr = '0 0 * * *'">{{ t('inspection.everyDay') }}</el-button>
        </el-form-item>
        
        <el-divider :content="t('inspection.snmpConfig')" content-position="left"></el-divider>
        
        <el-form-item :label="t('inspection.snmpVersion')">
          <el-select v-model="taskForm.snmp_version">
            <el-option label="v2c" value="v2c" />
            <el-option label="v3" value="v3" />
          </el-select>
        </el-form-item>
        
        <el-form-item :label="t('inspection.snmpCommunity')">
          <el-input v-model="taskForm.snmp_community" :placeholder="t('inspection.snmpCommunityPlaceholder')" />
        </el-form-item>
        
        <el-form-item :label="t('inspection.snmpTimeout')">
          <el-input-number v-model="taskForm.snmp_timeout" :min="1" :max="30" />
        </el-form-item>
        
        <el-form-item :label="t('inspection.snmpRetries')">
          <el-input-number v-model="taskForm.snmp_retries" :min="0" :max="5" />
        </el-form-item>
        
        <el-divider :content="t('inspection.tcpConfig')" content-position="left"></el-divider>
        
        <el-form-item :label="t('inspection.tcpPorts')">
          <el-input v-model="taskForm.tcp_ports" type="textarea" rows="2" :placeholder="t('inspection.tcpPortsPlaceholder')" />
        </el-form-item>
        
        <el-form-item :label="t('inspection.tcpTimeout')">
          <el-input-number v-model="taskForm.tcp_timeout_ms" :min="500" :max="10000" />
        </el-form-item>
        
        <el-form-item :label="t('inspection.maxConcurrent')">
          <el-input-number v-model="taskForm.max_concurrent" :min="1" :max="200" />
        </el-form-item>
        
        <el-divider :content="t('inspection.alertConfig')" content-position="left"></el-divider>
        
        <el-form-item :label="t('inspection.alertOptions')">
          <el-checkbox v-model="taskForm.alert_on_offline">{{ t('inspection.alertOffline') }}</el-checkbox>
          <el-checkbox v-model="taskForm.alert_on_new_device">{{ t('inspection.alertNewDevice') }}</el-checkbox>
          <el-checkbox v-model="taskForm.alert_on_fingerprint_change">{{ t('inspection.alertFingerprintChange') }}</el-checkbox>
        </el-form-item>
        
        <el-form-item :label="t('inspection.enableStatus')">
          <el-switch v-model="taskForm.is_enabled" />
        </el-form-item>
      </el-form>
      
      <template #footer>
        <el-button @click="closeTaskForm">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveTask" :loading="loading">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.inspection-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.overview-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.overview-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid #8c8c8c;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  gap: 16px;
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.overview-card-success { border-left-color: #52c41a; }
.overview-card-warning { border-left-color: #faad14; }
.overview-card-purple { border-left-color: #722ed1; }

.overview-card-icon {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  background: #f5f5f5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #8c8c8c;
}

.overview-card-success .overview-card-icon { background: #f6ffed; color: #52c41a; }
.overview-card-warning .overview-card-icon { background: #fff7e6; color: #faad14; }
.overview-card-purple .overview-card-icon { background: #f9f0ff; color: #722ed1; }

.overview-card-content {
  flex: 1;
}

.overview-card-label {
  font-size: 13px;
  color: #8c8c8c;
  margin-bottom: 6px;
}

.overview-card-value {
  font-size: 28px;
  font-weight: 700;
  color: #262626;
  line-height: 1.2;
  margin-bottom: 4px;
}

.overview-card-trend {
  font-size: 12px;
  color: #bfbfbf;
}

.table-card {
  border-radius: 8px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #262626;
  font-size: 15px;
}

.card-time {
  margin-left: auto;
  font-size: 14px;
  color: #9ca3af;
  font-weight: normal;
}

.overview-stats {
  display: flex;
  gap: 32px;
  padding: 16px 0;
  flex-wrap: wrap;
}

.overview-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-width: 100px;
}

.overview-label {
  font-size: 14px;
  color: #6b7280;
}

.overview-value {
  font-size: 20px;
  font-weight: 600;
  color: #1f2937;
}

.overview-value.success { color: #10b981; }
.overview-value.warning { color: #f59e0b; }
.overview-value.danger { color: #ef4444; }
.overview-value.info { color: #3b82f6; }

.tab-content {
  padding-top: 16px;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.alert-summary {
  display: flex;
  gap: 12px;
}

.inspection-tabs {
  margin-top: 16px;
}

.smart-categories-section {
  background: #fafafa;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
  border: 1px solid #e8e8e8;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  font-weight: 600;
  font-size: 15px;
}

.category-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

.category-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 20px;
  background: #fff;
  border: 2px solid #e8e8e8;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 14px;
}

.category-tab:hover {
  border-color: var(--category-color);
  transform: translateY(-2px);
}

.category-tab.active {
  background: var(--category-color);
  border-color: var(--category-color);
  color: #fff;
}

.category-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.category-tab.active .category-dot {
  background: #fff;
}

.category-count {
  background: rgba(0, 0, 0, 0.1);
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}

.category-tab.active .category-count {
  background: rgba(255, 255, 255, 0.3);
}

.category-devices {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
}

.empty-category {
  text-align: center;
  padding: 40px;
}

.inspection-task-table :deep(.cell),
.inspection-category-table :deep(.cell),
.inspection-records-table :deep(.cell),
.inspection-fingerprints-table :deep(.cell) {
  line-height: 1.5;
}

.inspection-task-table :deep(.el-table__cell),
.inspection-category-table :deep(.el-table__cell),
.inspection-records-table :deep(.el-table__cell),
.inspection-fingerprints-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>
