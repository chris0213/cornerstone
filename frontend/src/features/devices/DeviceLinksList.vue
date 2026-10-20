<template>
  <div class="device-links-list">
    <div class="table-header">
      <h3>设备连接关系</h3>
      <div class="header-actions">
        <el-button type="primary" :icon="Plus" @click="showCreateDialog">
          新增连接
        </el-button>
        <el-button type="success" :icon="Search" @click="runLldpDiscovery" :loading="discovering">
          LLDP 发现
        </el-button>
        <el-button type="success" :icon="Search" @click="runMacDiscovery" :loading="macDiscovering">
          MAC/ARP 发现
        </el-button>
        <el-button :icon="Refresh" @click="loadDeviceLinks" :loading="loading">
          刷新
        </el-button>
      </div>
    </div>

    <!-- 发现任务进度 -->
    <el-alert
      v-if="discoveryTask && discoveryTask.status === 'running'"
      type="info"
      :closable="false"
      class="discovery-progress"
    >
      <template #title>
        <div class="discovery-progress-row">
          <span>
            {{ discoveryTask.phase }}
            <template v-if="discoveryTask.total">（{{ discoveryTask.done }}/{{ discoveryTask.total }}）</template>
          </span>
          <el-progress
            class="discovery-progress-bar"
            :percentage="Math.min(discoveryTask.percent, 99)"
            :stroke-width="10"
          />
          <span class="discovery-progress-msg">{{ discoveryTask.message }}</span>
        </div>
      </template>
    </el-alert>

    <el-table class="device-links-table" :data="deviceLinks" style="width: 100%" v-loading="loading">
      <el-table-column prop="id" label="ID" min-width="60" />
      <el-table-column label="源">
        <template #default="{ row }">
          <span>{{ getSourceName(row) }}</span>
          <span v-if="row.source_interface" class="interface-label">{{ row.source_interface }}</span>
        </template>
      </el-table-column>
      <el-table-column label="目标">
        <template #default="{ row }">
          <span>{{ getTargetName(row) }}</span>
          <span v-if="row.target_interface" class="interface-label">{{ row.target_interface }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="link_type" label="连接类型" min-width="100">
        <template #default="{ row }">
          <el-tag :type="getLinkTypeTagType(row.link_type)" size="small">
            {{ getLinkTypeText(row.link_type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="confidence" label="置信度" min-width="80">
        <template #default="{ row }">
          <span :class="getConfidenceClass(row.confidence)">{{ row.confidence }}%</span>
        </template>
      </el-table-column>
      <el-table-column prop="discovered_at" label="发现时间" min-width="180" />
      <el-table-column prop="note" label="备注" />
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="showEditDialog(row)">
            编辑
          </el-button>
          <el-button type="danger" link size="small" @click="confirmDelete(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 未知接入终端 -->
    <div class="table-header unknown-header">
      <h3>
        未知接入终端
        <el-badge v-if="unknownEndpoints.length" :value="unknownEndpoints.length" class="unknown-badge" />
        <span class="unknown-hint">交换机接入端口下发现、但未录入资产的终端</span>
      </h3>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadUnknownEndpoints" :loading="unknownLoading">
          刷新
        </el-button>
      </div>
    </div>

    <el-table class="unknown-table" :data="unknownEndpoints" style="width: 100%" v-loading="unknownLoading">
      <el-table-column prop="id" label="ID" min-width="60" />
      <el-table-column label="接入设备" min-width="140">
        <template #default="{ row }">
          {{ row.device_name || `设备${row.device_id}` }}
        </template>
      </el-table-column>
      <el-table-column prop="local_interface" label="接入端口" min-width="140" />
      <el-table-column label="终端 MAC" min-width="160">
        <template #default="{ row }">
          {{ formatMac(row.mac_address) }}
        </template>
      </el-table-column>
      <el-table-column label="IP（ARP）" min-width="140">
        <template #default="{ row }">
          <span v-if="row.ip_address">{{ row.ip_address }}</span>
          <span v-else class="text-muted">未知</span>
        </template>
      </el-table-column>
      <el-table-column label="首次发现" min-width="160">
        <template #default="{ row }">
          {{ formatTime(row.first_seen_at) }}
        </template>
      </el-table-column>
      <el-table-column label="最后发现" min-width="160">
        <template #default="{ row }">
          {{ formatTime(row.last_seen_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="showAcceptDialog(row)">
            入库
          </el-button>
          <el-button type="danger" link size="small" @click="confirmIgnoreEndpoint(row)">
            忽略
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建/编辑连接对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '创建连接' : '编辑连接'"
      width="600px"
      @close="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="源类型">
          <el-select v-model="form.source_type" placeholder="请选择源类型" style="width: 100%">
            <el-option label="设备" value="device" />
            <el-option label="专线" value="circuit" />
          </el-select>
        </el-form-item>
        <el-form-item label="源设备" v-if="form.source_type === 'device'" prop="source_device_id">
          <el-select v-model="form.source_device_id" placeholder="请选择源设备" filterable style="width: 100%">
            <el-option
              v-for="device in devices"
              :key="device.id"
              :label="device.name"
              :value="device.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="源专线" v-if="form.source_type === 'circuit'" prop="source_circuit_id">
          <el-select v-model="form.source_circuit_id" placeholder="请选择源专线" filterable style="width: 100%">
            <el-option
              v-for="circuit in circuits"
              :key="circuit.id"
              :label="circuit.name"
              :value="circuit.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="源接口" prop="source_interface">
          <el-input v-model="form.source_interface" placeholder="如：GigabitEthernet0/1" />
        </el-form-item>
        <el-form-item label="目标类型">
          <el-select v-model="form.target_type" placeholder="请选择目标类型" style="width: 100%">
            <el-option label="设备" value="device" />
            <el-option label="专线" value="circuit" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标设备" v-if="form.target_type === 'device'" prop="target_device_id">
          <el-select v-model="form.target_device_id" placeholder="请选择目标设备" filterable style="width: 100%">
            <el-option
              v-for="device in devices"
              :key="device.id"
              :label="device.name"
              :value="device.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="目标专线" v-if="form.target_type === 'circuit'" prop="target_circuit_id">
          <el-select v-model="form.target_circuit_id" placeholder="请选择目标专线" filterable style="width: 100%">
            <el-option
              v-for="circuit in circuits"
              :key="circuit.id"
              :label="circuit.name"
              :value="circuit.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="目标接口" prop="target_interface">
          <el-input v-model="form.target_interface" placeholder="如：GigabitEthernet0/2" />
        </el-form-item>
        <el-form-item label="连接类型" prop="link_type">
          <el-select v-model="form.link_type" placeholder="请选择连接类型" style="width: 100%">
            <el-option label="手动配置" value="manual" />
            <el-option label="LLDP 发现" value="lldp" />
            <el-option label="CDP 发现" value="cdp" />
            <el-option label="推断连接" value="inferred" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度" prop="confidence">
          <el-slider v-model="form.confidence" :min="0" :max="100" :step="5" show-input />
        </el-form-item>
        <el-form-item label="备注" prop="note">
          <el-input v-model="form.note" type="textarea" :rows="3" placeholder="请输入备注信息" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- 未知接入入库对话框 -->
    <el-dialog
      v-model="acceptDialogVisible"
      title="未知接入入库"
      width="560px"
      @close="resetAcceptForm"
    >
      <el-alert v-if="acceptTarget" type="info" :closable="false" class="accept-info">
        <template #title>
          {{ acceptTarget.device_name || `设备${acceptTarget.device_id}` }} /
          {{ acceptTarget.local_interface }} /
          MAC {{ formatMac(acceptTarget.mac_address) }}
          <template v-if="acceptTarget.ip_address"> / IP {{ acceptTarget.ip_address }}</template>
        </template>
      </el-alert>
      <el-form ref="acceptFormRef" :model="acceptForm" :rules="acceptRules" label-width="110px">
        <el-form-item label="设备名称" prop="name">
          <el-input v-model="acceptForm.name" placeholder="如：应用服务器-01" maxlength="100" />
        </el-form-item>
        <el-form-item label="设备类型" prop="device_type">
          <el-select v-model="acceptForm.device_type" style="width: 100%">
            <el-option label="服务器" value="server" />
            <el-option label="其他" value="other" />
            <el-option label="交换机" value="switch" />
            <el-option label="路由器" value="router" />
            <el-option label="防火墙" value="firewall" />
            <el-option label="AP" value="ap" />
            <el-option label="存储" value="storage" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属站点">
          <el-select v-model="acceptForm.site_id" placeholder="默认跟随接入交换机" clearable style="width: 100%">
            <el-option
              v-for="site in sites"
              :key="site.id"
              :label="site.name"
              :value="site.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-input v-model="acceptForm.owner" placeholder="选填" maxlength="50" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="acceptForm.note" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
        <el-form-item label="录入 IP" v-if="acceptTarget?.ip_address">
          <el-switch v-model="acceptForm.create_ip" />
          <span class="accept-switch-hint">同步将 {{ acceptTarget.ip_address }} 录入 IPAM 并绑定本设备</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="acceptDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAccept" :loading="accepting">
          确定入库
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import {
  getDeviceLinks,
  createDeviceLink,
  updateDeviceLink,
  deleteDeviceLink,
  startLldpDiscovery,
  startMacDiscovery,
  getDiscoveryTask,
  getUnknownEndpoints,
  acceptUnknownEndpoint,
  deleteUnknownEndpoint,
  type DeviceLink,
  type DeviceLinkCreate,
  type DeviceLinkUpdate,
  type DiscoveryStats,
  type DiscoveryTask,
  type UnknownEndpoint
} from '@/api/topology'
import { getDevices, type DeviceResponse } from '@/api/devices'
import { getCircuits, type CircuitResponse } from '@/api/circuits'
import { getSites, type SiteResponse } from '@/api/sites'
import { confirmAndRun } from '@/lib/confirm'

const loading = ref(false)
const submitting = ref(false)
const discovering = ref(false)
const macDiscovering = ref(false)
const deviceLinks = ref<DeviceLink[]>([])
const devices = ref<DeviceResponse[]>([])
const circuits = ref<CircuitResponse[]>([])
const unknownEndpoints = ref<UnknownEndpoint[]>([])
const unknownLoading = ref(false)
const acceptDialogVisible = ref(false)
const accepting = ref(false)
const acceptTarget = ref<UnknownEndpoint | null>(null)
const acceptFormRef = ref<FormInstance>()
const sites = ref<SiteResponse[]>([])
const acceptForm = ref<{
  name: string
  device_type: string
  site_id: number | null
  owner: string
  note: string
  create_ip: boolean
}>({
  name: '',
  device_type: 'server',
  site_id: null,
  owner: '',
  note: '',
  create_ip: true
})

const acceptRules: FormRules = {
  name: [{ required: true, message: '请输入设备名称', trigger: 'blur' }]
}
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingLinkId = ref<number | null>(null)
const formRef = ref<FormInstance>()

const form = ref<DeviceLinkCreate & { source_type?: string; target_type?: string; note?: string }>({
  source_type: 'device',
  source_device_id: undefined,
  source_interface: undefined,
  target_type: 'device',
  target_device_id: undefined,
  target_interface: undefined,
  link_type: 'manual',
  confidence: 100,
  note: undefined,
  source_circuit_id: undefined,
  target_circuit_id: undefined
})

const rules: FormRules = {
  source_device_id: [
    { 
      validator: (_rule, value, callback) => {
        if (form.value.source_type === 'device' && !value) {
          callback(new Error('请选择源设备'))
        } else {
          callback()
        }
      }, 
      trigger: 'change' 
    }
  ],
  source_circuit_id: [
    { 
      validator: (_rule, value, callback) => {
        if (form.value.source_type === 'circuit' && !value) {
          callback(new Error('请选择源专线'))
        } else {
          callback()
        }
      }, 
      trigger: 'change' 
    }
  ],
  target_device_id: [
    { 
      validator: (_rule, value, callback) => {
        if (form.value.target_type === 'device' && !value) {
          callback(new Error('请选择目标设备'))
        } else {
          callback()
        }
      }, 
      trigger: 'change' 
    }
  ],
  target_circuit_id: [
    { 
      validator: (_rule, value, callback) => {
        if (form.value.target_type === 'circuit' && !value) {
          callback(new Error('请选择目标专线'))
        } else {
          callback()
        }
      }, 
      trigger: 'change' 
    }
  ]
}

const getLinkTypeText = (type: string) => {
  const typeMap: Record<string, string> = {
    manual: '手动配置',
    lldp: 'LLDP 发现',
    cdp: 'CDP 发现',
    inferred: '推断连接'
  }
  return typeMap[type] || type
}

const getLinkTypeTagType = (type: string) => {
  const tagTypeMap: Record<string, 'success' | 'primary' | 'warning' | 'info'> = {
    manual: 'info',
    lldp: 'success',
    cdp: 'success',
    inferred: 'warning'
  }
  return tagTypeMap[type] || 'info'
}

const getConfidenceClass = (confidence: number | null) => {
  if (!confidence) return 'confidence-low'
  if (confidence >= 80) return 'confidence-high'
  if (confidence >= 50) return 'confidence-medium'
  return 'confidence-low'
}

const getDeviceName = (deviceId: number | undefined) => {
  if (!deviceId) return '-'
  const device = devices.value.find(d => d.id === deviceId)
  return device ? device.name : `设备${deviceId}`
}

const getCircuitName = (circuitId: number | undefined) => {
  if (!circuitId) return '-'
  const circuit = circuits.value.find(c => c.id === circuitId)
  return circuit ? circuit.name : `专线${circuitId}`
}

const getSourceName = (row: DeviceLink) => {
  if (row.source_device_id) return getDeviceName(row.source_device_id)
  if (row.source_circuit_id) return getCircuitName(row.source_circuit_id)
  return '-'
}

const getTargetName = (row: DeviceLink) => {
  if (row.target_device_id) return getDeviceName(row.target_device_id)
  if (row.target_circuit_id) return getCircuitName(row.target_circuit_id)
  return '-'
}

const loadDeviceLinks = async () => {
  loading.value = true
  try {
    deviceLinks.value = await getDeviceLinks()
  } catch (error) {
    console.error('Failed to load device links:', error)
    ElMessage.error('加载设备连接失败')
  } finally {
    loading.value = false
  }
}

const loadDevices = async () => {
  try {
    const data = await getDevices()
    devices.value = data
  } catch (error) {
    console.error('Failed to load devices:', error)
  }
}

const loadCircuits = async () => {
  try {
    const data = await getCircuits()
    circuits.value = data
  } catch (error) {
    console.error('Failed to load circuits:', error)
  }
}

const showCreateDialog = () => {
  dialogMode.value = 'create'
  dialogVisible.value = true
}

const showEditDialog = (link: DeviceLink) => {
  dialogMode.value = 'edit'
  editingLinkId.value = link.id
  form.value = {
    source_type: link.source_device_id ? 'device' : 'circuit',
    source_device_id: link.source_device_id,
    source_interface: link.source_interface,
    source_circuit_id: link.source_circuit_id,
    target_type: link.target_device_id ? 'device' : 'circuit',
    target_device_id: link.target_device_id,
    target_interface: link.target_interface,
    target_circuit_id: link.target_circuit_id,
    link_type: link.link_type,
    confidence: link.confidence || 100,
    note: link.note || undefined
  }
  dialogVisible.value = true
}

const resetForm = () => {
  formRef.value?.resetFields()
  editingLinkId.value = null
  form.value = {
    source_type: 'device',
    source_device_id: undefined,
    source_interface: undefined,
    source_circuit_id: undefined,
    target_type: 'device',
    target_device_id: undefined,
    target_interface: undefined,
    target_circuit_id: undefined,
    link_type: 'manual',
    confidence: 100,
    note: undefined
  }
}

const handleSubmit = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    
    submitting.value = true
    try {
      const submitData: DeviceLinkCreate = {
        source_device_id: form.value.source_type === 'device' ? form.value.source_device_id : undefined,
        source_interface: form.value.source_interface,
        source_circuit_id: form.value.source_type === 'circuit' ? form.value.source_circuit_id : undefined,
        target_device_id: form.value.target_type === 'device' ? form.value.target_device_id : undefined,
        target_interface: form.value.target_interface,
        target_circuit_id: form.value.target_type === 'circuit' ? form.value.target_circuit_id : undefined,
        link_type: form.value.link_type,
        confidence: form.value.confidence,
        note: form.value.note
      }
      
      if (dialogMode.value === 'create') {
        await createDeviceLink(submitData)
        ElMessage.success('创建成功')
      } else {
        if (!editingLinkId.value) return
        const updateData: DeviceLinkUpdate = { ...submitData }
        await updateDeviceLink(editingLinkId.value, updateData)
        ElMessage.success('更新成功')
      }
      dialogVisible.value = false
      await loadDeviceLinks()
    } catch (error) {
      console.error('Failed to submit device link:', error)
      ElMessage.error(dialogMode.value === 'create' ? '创建失败' : '更新失败')
    } finally {
      submitting.value = false
    }
  })
}

const confirmDelete = async (link: DeviceLink) => {
  await confirmAndRun({
    message: `确定要删除设备连接吗？`,
    title: '确认删除',
    confirmText: '确定',
    cancelText: '取消',
    action: async () => {
      await deleteDeviceLink(link.id)
      await loadDeviceLinks()
    },
    successMessage: '删除成功',
    errorMessage: '删除失败',
  })
}

const formatDiscoveryStats = (stats: DiscoveryStats): string => {
  const parts = [`设备成功 ${stats.devices_ok}/${stats.devices_total}，链路新增 ${stats.links_created} / 更新 ${stats.links_updated}`]
  if (stats.unknown_endpoints_total) {
    parts.push(`未知接入 ${stats.unknown_endpoints_total} 个`)
  }
  if (stats.unmatched_neighbors_total) {
    parts.push(`未匹配邻居 ${stats.unmatched_neighbors_total} 个`)
  }
  if (stats.devices_failed) {
    parts.push(`失败 ${stats.devices_failed} 台`)
  }
  return parts.join('，')
}

// ---------- 后台发现任务：启动 + 轮询进度 ----------
const POLL_INTERVAL_MS = 1500
const discoveryTask = ref<DiscoveryTask | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | null = null

const stopPolling = () => {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

const pollDiscoveryTask = async (taskId: string, onDone: (task: DiscoveryTask) => void) => {
  try {
    const task = await getDiscoveryTask(taskId)
    discoveryTask.value = task
    if (task.status === 'running') {
      pollTimer = setTimeout(() => pollDiscoveryTask(taskId, onDone), POLL_INTERVAL_MS)
      return
    }
    onDone(task)
  } catch (error: any) {
    // 任务丢失（后端重启）等：终止轮询并提示
    ElMessage.error(error?.response?.data?.detail || '查询发现进度失败')
    discoveryTask.value = null
  } finally {
    discovering.value = false
    macDiscovering.value = false
  }
}

const startDiscovery = async (type: 'lldp' | 'mac') => {
  const label = type === 'lldp' ? 'LLDP发现' : 'MAC/ARP发现'
  try {
    const { task_id: taskId } = type === 'lldp'
      ? await startLldpDiscovery()
      : await startMacDiscovery()
    discovering.value = type === 'lldp'
    macDiscovering.value = type === 'mac'
    discoveryTask.value = {
      task_id: taskId, type, status: 'running', phase: '启动中',
      done: 0, total: 0, percent: 0, message: '',
      result: null, error: null, created_at: '', finished_at: null
    }
    pollDiscoveryTask(taskId, async (task) => {
      stopPolling()
      discoveryTask.value = null
      if (task.status === 'completed' && task.result) {
        ElMessage.success(`${label}完成：${formatDiscoveryStats(task.result)}`)
      } else {
        ElMessage.error(`${label}失败：${task.error || '未知错误'}`)
      }
      await Promise.all([loadDeviceLinks(), loadUnknownEndpoints()])
    })
  } catch (error: any) {
    discovering.value = false
    macDiscovering.value = false
    console.error(`${label} failed:`, error)
    ElMessage.error(error?.response?.data?.detail || '发现失败')
  }
}

const runLldpDiscovery = () => startDiscovery('lldp')
const runMacDiscovery = () => startDiscovery('mac')

onUnmounted(stopPolling)

const formatMac = (mac: string) => {
  const hexed = (mac || '').replace(/[^0-9a-fA-F]/g, '')
  if (hexed.length !== 12) return mac
  return hexed.replace(/(.{4})(.{4})(.{4})/, '$1-$2-$3').toUpperCase()
}

const formatTime = (time: string | null) => {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN', { hour12: false })
}

const loadUnknownEndpoints = async () => {
  unknownLoading.value = true
  try {
    unknownEndpoints.value = await getUnknownEndpoints()
  } catch (error) {
    console.error('Failed to load unknown endpoints:', error)
    ElMessage.error('加载未知接入失败')
  } finally {
    unknownLoading.value = false
  }
}

const loadSites = async () => {
  try {
    sites.value = await getSites()
  } catch (error) {
    console.error('Failed to load sites:', error)
  }
}

const showAcceptDialog = (row: UnknownEndpoint) => {
  acceptTarget.value = row
  // 默认名称：MAC 尾 4 位（如终端-a1b2）
  acceptForm.value = {
    name: `终端-${row.mac_address.slice(-4)}`,
    device_type: 'server',
    site_id: row.site_id ?? null,
    owner: '',
    note: '',
    create_ip: true
  }
  acceptDialogVisible.value = true
}

const resetAcceptForm = () => {
  acceptFormRef.value?.resetFields()
  acceptTarget.value = null
}

const handleAccept = async () => {
  if (!acceptFormRef.value || !acceptTarget.value) return
  await acceptFormRef.value.validate(async (valid) => {
    if (!valid) return
    accepting.value = true
    try {
      const result = await acceptUnknownEndpoint(acceptTarget.value!.id, {
        name: acceptForm.value.name,
        device_type: acceptForm.value.device_type,
        site_id: acceptForm.value.site_id,
        owner: acceptForm.value.owner || null,
        note: acceptForm.value.note || null,
        create_ip: acceptForm.value.create_ip
      })
      ElMessage.success(`已入库为「${result.device_name}」，并创建到接入交换机的连接`)
      acceptDialogVisible.value = false
      await Promise.all([loadUnknownEndpoints(), loadDeviceLinks(), loadDevices()])
    } catch (error: any) {
      console.error('Failed to accept unknown endpoint:', error)
      ElMessage.error(error?.response?.data?.detail || '入库失败')
    } finally {
      accepting.value = false
    }
  })
}

const confirmIgnoreEndpoint = async (row: UnknownEndpoint) => {
  await confirmAndRun({
    message: `确定要忽略该未知接入吗？（MAC ${formatMac(row.mac_address)}，下次发现会重新记录）`,
    title: '确认忽略',
    confirmText: '确定',
    cancelText: '取消',
    action: async () => {
      await deleteUnknownEndpoint(row.id)
    },
    successMessage: '已忽略',
    errorMessage: '忽略失败',
  })
  await loadUnknownEndpoints()
}

onMounted(() => {
  loadDeviceLinks()
  loadDevices()
  loadCircuits()
  loadUnknownEndpoints()
  loadSites()
})
</script>

<style scoped>
.device-links-list {
  padding: 20px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.table-header h3 {
  margin: 0;
  font-size: 16px;
  color: #303133;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.interface-label {
  margin-left: 8px;
  padding: 2px 6px;
  background-color: #f5f7fa;
  border-radius: 4px;
  font-size: 12px;
  color: #606266;
}

.confidence-high {
  color: #67c23a;
  font-weight: bold;
}

.confidence-medium {
  color: #e6a23c;
  font-weight: bold;
}

.confidence-low {
  color: #f56c6c;
  font-weight: bold;
}

.device-links-table :deep(.cell) {
  line-height: 1.5;
}

.device-links-table :deep(.el-table__cell) {
  padding: 8px 12px;
}

.unknown-header {
  margin-top: 32px;
}

.discovery-progress {
  margin-bottom: 16px;
}

.discovery-progress-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.discovery-progress-bar {
  flex: 1;
  max-width: 320px;
}

.discovery-progress-msg {
  font-size: 12px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.unknown-badge {
  margin-left: 8px;
  vertical-align: middle;
}

.unknown-hint {
  margin-left: 10px;
  font-size: 12px;
  font-weight: normal;
  color: #909399;
}

.unknown-table :deep(.el-table__cell) {
  padding: 8px 12px;
}

.text-muted {
  color: #909399;
}

.accept-info {
  margin-bottom: 16px;
}

.accept-switch-hint {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
}
</style>
