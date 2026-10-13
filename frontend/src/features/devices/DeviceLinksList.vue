<template>
  <div class="device-links-list">
    <div class="table-header">
      <h3>设备连接关系</h3>
      <div class="header-actions">
        <el-button type="primary" :icon="Plus" @click="showCreateDialog">
          新增连接
        </el-button>
        <el-button type="success" :icon="Search" @click="runLldpDiscovery" :loading="discovering">
          发现邻居
        </el-button>
        <el-button :icon="Refresh" @click="loadDeviceLinks" :loading="loading">
          刷新
        </el-button>
      </div>
    </div>

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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import {
  getDeviceLinks,
  createDeviceLink,
  updateDeviceLink,
  deleteDeviceLink,
  discoverLldpNeighbors,
  type DeviceLink,
  type DeviceLinkCreate,
  type DeviceLinkUpdate
} from '@/api/topology'
import { getDevices, type DeviceResponse } from '@/api/devices'
import { getCircuits, type CircuitResponse } from '@/api/circuits'
import { confirmAndRun } from '@/lib/confirm'

const loading = ref(false)
const submitting = ref(false)
const discovering = ref(false)
const deviceLinks = ref<DeviceLink[]>([])
const devices = ref<DeviceResponse[]>([])
const circuits = ref<CircuitResponse[]>([])
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

const runLldpDiscovery = async () => {
  discovering.value = true
  try {
    await discoverLldpNeighbors()
    ElMessage.success('LLDP发现完成')
    await loadDeviceLinks()
  } catch (error) {
    console.error('LLDP discovery failed:', error)
    ElMessage.error('发现失败')
  } finally {
    discovering.value = false
  }
}

onMounted(() => {
  loadDeviceLinks()
  loadDevices()
  loadCircuits()
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
</style>
