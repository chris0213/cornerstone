<script setup lang="ts">
import { ref, computed, reactive, onMounted, onBeforeUnmount, h } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ElMessage, ElNotification } from 'element-plus'
import { Plus, Edit, Delete, Aim, MoreFilled } from '@element-plus/icons-vue'
import { useAppStore } from '../../store'
import { useAuthStore } from '../../store/auth'
import RackSidebar from './RackSidebar.vue'
import RackStatsPanel from './RackStats.vue'
import RackTimeline from './RackTimeline.vue'
import { deviceTypeText } from './deviceTypes'
import type { Rack as RackType, RackDevice, RackStats as RackStatsType } from '../../types/domain'
import { getRack, listRacks, createRack, updateRack, deleteRack, updateDevicePosition } from '../../api/racks'
import { getSites } from '../../api/sites'
import { getDevices } from '../../api/devices'
import type { DeviceResponse } from '../../api/devices'

// ---- 日志级别控制 ----
// 0 = 仅 error; 1 = error + warn + 关键 info(默认); 2 = +汇总 debug; 3 = +详细 debug
// 临时开启 debug: localStorage.setItem('rack_log_level', '3') 后刷新页面
const _envLevel = (() => {
  try {
    const v = localStorage.getItem('rack_log_level')
    return v != null ? parseInt(v, 10) : NaN
  } catch { return NaN }
})()
const LOG_LEVEL: number = Number.isFinite(_envLevel) ? _envLevel! : 1
const PREFIX = '[Rack]'

const rackLog = {
  error: (msg: string, data?: unknown) => console.error(`${PREFIX} ${msg}`, ...(data !== undefined ? [data] : [])),
  warn: (msg: string, data?: unknown) => {
    if (LOG_LEVEL >= 1) console.warn(`${PREFIX} ${msg}`, ...(data !== undefined ? [data] : []))
  },
  info: (msg: string, data?: unknown) => {
    if (LOG_LEVEL >= 1) console.info(`${PREFIX} ${msg}`, ...(data !== undefined ? [data] : []))
  },
  // summary=true 时 level>=2 输出(汇总类); summary=false 时 level>=3 输出(详细明细类)
  debug: (msg: string, data?: unknown, summary = true) => {
    const min = summary ? 2 : 3
    if (LOG_LEVEL >= min) console.debug(`${PREFIX} ${msg}`, ...(data !== undefined ? [data] : []))
  },
}

const { t } = useI18n()
const router = useRouter()
const store = useAppStore()
const authStore = useAuthStore()

const loading = ref(false)
const selectedRackId = ref<number | null>(null)
const selectedRackDetail = ref<{ devices: RackDevice[]; stats: RackStatsType | null } | null>(null)
const rackSearch = ref('')

// ---- 站点选项 ----
const siteOptions = ref<{ id: number; name: string }[]>([])

const loadSites = async () => {
  rackLog.info('loadSites: 开始加载站点列表')
  try {
    const list = await getSites()
    siteOptions.value = list.map(s => ({ id: s.id, name: s.name }))
    rackLog.debug('loadSites: 成功', { count: siteOptions.value.length, sites: siteOptions.value })
  } catch (e) {
    rackLog.error('loadSites: 失败', e)
  }
}

// ---- 弹窗表单 ----
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const dialogLoading = ref(false)
const formRef = ref()
const form = reactive({
  id: null as number | null,
  name: '',
  site_id: null as number | null,
  room: '',
  row_position: 1,
  total_u: 42,
  status: 'active',
  description: '',
})

const formRules = computed(() => ({
  name: [{ required: true, message: t('rack.rackName') + t('common.required'), trigger: 'blur' }],
  total_u: [{ required: true, message: t('rack.rackTotalU') + t('common.required'), trigger: 'blur' }],
}))

const resetForm = () => {
  form.id = null
  form.name = ''
  form.site_id = null
  form.room = ''
  form.row_position = 1
  form.total_u = 42
  form.status = 'active'
  form.description = ''
}

const openCreate = () => {
  rackLog.info('openCreate: 打开新增弹窗')
  resetForm()
  dialogMode.value = 'create'
  dialogVisible.value = true
}

const openEdit = () => {
  if (!selectedRack.value) return
  rackLog.info('openEdit: 打开编辑弹窗', { id: selectedRack.value.id, name: selectedRack.value.name })
  rackLog.debug('openEdit: 原始机柜数据', selectedRack.value, false)
  form.id = selectedRack.value.id
  form.name = selectedRack.value.name
  form.site_id = selectedRack.value.siteId
  form.room = selectedRack.value.room || ''
  form.row_position = selectedRack.value.rowPosition || 1
  form.total_u = selectedRack.value.totalU || 42
  form.status = selectedRack.value.status || 'active'
  form.description = selectedRack.value.description || ''
  dialogMode.value = 'edit'
  dialogVisible.value = true
  rackLog.debug('openEdit: 表单已填充', { ...form }, false)
}

const submitForm = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) {
      rackLog.warn('submitForm: 表单校验未通过')
      rackLog.debug('submitForm: 校验失败时表单内容', { ...form }, false)
      return
    }
    dialogLoading.value = true
    const payload = {
      name: form.name,
      site_id: form.site_id || null,
      room: form.room || null,
      row_position: form.row_position,
      total_u: form.total_u,
      status: form.status,
      description: form.description || null,
    }
    rackLog.info('submitForm: 开始提交', { mode: dialogMode.value, id: form.id })
    rackLog.debug('submitForm: payload 明细', payload, false)
    try {
      if (dialogMode.value === 'create') {
        const created = await createRack(payload)
        rackLog.info('submitForm: 新增成功', { id: created.id, name: created.name })
        rackLog.debug('submitForm: 新增响应', created, false)
        ElMessage.success(t('rack.createSuccess'))
      } else if (form.id) {
        const updated = await updateRack(form.id, payload)
        rackLog.info('submitForm: 编辑成功', { id: form.id, name: updated.name })
        rackLog.debug('submitForm: 编辑响应', updated, false)
        ElMessage.success(t('rack.updateSuccess'))
      }
      dialogVisible.value = false
      await loadAllRacks()
      if (dialogMode.value === 'edit' && form.id) {
        rackLog.info('submitForm: 重新选中机柜', { id: form.id })
        await selectRack(form.id)
      }
    } catch (e) {
      rackLog.error('submitForm: 提交失败', { mode: dialogMode.value, id: form.id, error: e })
      ElMessage.error(t('rack.saveFailed'))
    } finally {
      dialogLoading.value = false
    }
  })
}

// ---- 删除机柜（自定义确认弹窗：显示机柜名与设备数，说明设备解除上架） ----
const deleteVisible = ref(false)
const deleteLoading = ref(false)
const deleteTarget = ref<RackType | null>(null)

const openDelete = () => {
  if (!selectedRack.value) return
  deleteTarget.value = selectedRack.value
  deleteVisible.value = true
}

const confirmDelete = async () => {
  const target = deleteTarget.value
  if (!target) return
  const rackId = target.id
  rackLog.info('confirmDelete: 用户确认删除机柜', { id: rackId, name: target.name })
  deleteLoading.value = true
  try {
    await deleteRack(rackId)
    rackLog.info('confirmDelete: 删除成功', { id: rackId })
    ElMessage.success(t('rack.deleteSuccess'))
    deleteVisible.value = false
    selectedRackId.value = null
    selectedRackDetail.value = null
    await loadAllRacks()
  } catch (e) {
    rackLog.error('confirmDelete: 删除失败', { id: rackId, error: e })
    ElMessage.error(t('rack.deleteFailed'))
  } finally {
    deleteLoading.value = false
  }
}

const goDevicePage = (deviceId: number) => {
  detailVisible.value = false
  router.push({ path: '/devices', query: { id: deviceId } })
}

// ---- 权限 ----
const canWrite = computed(() => authStore.hasPermission('sites:write'))
const canDelete = computed(() => authStore.hasPermission('sites:delete'))
const canManageDevices = computed(() => authStore.hasPermission('devices:write'))

// ---- 设备上架弹窗 ----
const placementVisible = ref(false)
const placementLoading = ref(false)
const placementTargetU = ref<number>(0)
const availableDevices = ref<DeviceResponse[]>([])
const deviceLoading = ref(false)
const placementForm = reactive({
  deviceId: null as number | null,
  uSize: 1,
})
const placementFormRef = ref()

// 虚拟滚动 select-v2 需要的 options 格式
const deviceOptions = computed(() =>
  availableDevices.value.map(d => ({
    value: d.id,
    label: `${d.name} (${d.type || '未知'})`,
  }))
)

// ---- 撤销上架状态 ----
type PlacementSnapshot = {
  deviceId: number
  deviceName: string
  rackId: number
  uPosition: number
  uSize: number
  undoTimer: ReturnType<typeof setTimeout>
  notifHandle: { close: () => void } | null
}
const lastPlacement = ref<PlacementSnapshot | null>(null)

const clearUndoTimer = () => {
  if (lastPlacement.value?.undoTimer) {
    clearTimeout(lastPlacement.value.undoTimer)
  }
  lastPlacement.value = null
}

const undoPlacement = async () => {
  const snap = lastPlacement.value
  if (!snap) return
  rackLog.info('undoPlacement: 用户触发撤销上架', {
    deviceId: snap.deviceId, deviceName: snap.deviceName, rackId: snap.rackId, uPosition: snap.uPosition,
  })
  try {
    await updateDevicePosition(snap.deviceId, { rack_id: null, u_position: null, u_size: 0 })
    rackLog.info('undoPlacement: 撤销成功，设备已移出机柜', { deviceId: snap.deviceId })
    ElMessage.success(t('rack.undoSuccess'))
    try { snap.notifHandle?.close() } catch {}
    clearUndoTimer()
    await selectRack(snap.rackId)
  } catch (e) {
    rackLog.error('undoPlacement: 撤销失败', { deviceId: snap.deviceId, error: e })
    ElMessage.error(t('rack.undoFailed'))
  }
}

const openPlacement = async (uPosition: number) => {
  if (!canManageDevices.value || !selectedRack.value) {
    rackLog.warn('openPlacement: 权限不足或未选中机柜')
    return
  }
  rackLog.info('openPlacement: 点击空U位', {
    uPosition, rackId: selectedRack.value.id, rackName: selectedRack.value.name, totalU: selectedRack.value.totalU,
  })
  placementTargetU.value = uPosition
  placementForm.deviceId = null
  placementForm.uSize = 1
  placementVisible.value = true

  deviceLoading.value = true
  const t0 = performance.now()
  try {
    const all = await getDevices()
    const t1 = performance.now()
    rackLog.info('openPlacement: 设备列表获取', { ms: Math.round(t1 - t0), total: all.length })
    availableDevices.value = all.filter(d => !d.rack_id)
    const t2 = performance.now()
    rackLog.info('openPlacement: 未上架设备过滤完成', {
      available: availableDevices.value.length, filterMs: Math.round(t2 - t1),
    })
    rackLog.debug('openPlacement: 可上架设备明细',
      availableDevices.value.slice(0, 30).map(d => ({ id: d.id, name: d.name, type: d.type })), false)
    if (availableDevices.value.length > 30) {
      rackLog.debug('openPlacement: 仅展示前30条，共' + availableDevices.value.length + '条')
    }
  } catch (e) {
    rackLog.error('openPlacement: 加载设备列表失败', e)
    ElMessage.error(t('rack.loadDevicesFailed'))
  } finally {
    deviceLoading.value = false
  }
}

const submitPlacement = async () => {
  if (!placementForm.deviceId || !selectedRack.value) {
    rackLog.warn('submitPlacement: 参数缺失')
    return
  }
  const rackId = selectedRack.value.id
  const deviceId = placementForm.deviceId
  const uPosition = placementTargetU.value
  const uSize = placementForm.uSize
  const deviceName = availableDevices.value.find(d => d.id === deviceId)?.name || `#${deviceId}`

  rackLog.info('submitPlacement: 开始提交', { deviceId, deviceName, rackId, uPosition, uSize })
  rackLog.debug('submitPlacement: payload 明细', { rack_id: rackId, u_position: uPosition, u_size: uSize }, false)

  placementLoading.value = true
  const t0 = performance.now()
  try {
    const result = await updateDevicePosition(deviceId, {
      rack_id: rackId, u_position: uPosition, u_size: uSize,
    })
    const t1 = performance.now()
    rackLog.info('submitPlacement: 上架成功', { ms: Math.round(t1 - t0), deviceId, deviceName, rackId, uPosition })
    rackLog.debug('submitPlacement: API 响应', result, false)
    placementVisible.value = false
    await selectRack(rackId)
    rackLog.info('submitPlacement: 机柜视图已刷新', { rackId, currentDeviceCount: currentDevices.value.length })

    // 显示"撤销上架"通知（10s）
    clearUndoTimer()
    const UNDO_TTL = 10000
    const snapshotToken = Date.now()
    const notifHandle = ElNotification({
      title: t('rack.placementSuccess'),
      type: 'success',
      duration: UNDO_TTL,
      message: h('div', { style: { display: 'flex', alignItems: 'center', gap: '12px' } }, [
        h('span', { style: { flex: 1, fontSize: '13px', color: '#303133' } },
          `${deviceName} → U${uPosition}${uSize > 1 ? '~' + (uPosition + uSize - 1) : ''}`),
        h('button', {
          style: {
            padding: '4px 12px', fontSize: '12px', lineHeight: '1', height: '24px',
            border: '1px solid #e6a23c', color: '#e6a23c', background: '#fdf6ec',
            borderRadius: '4px', cursor: 'pointer',
          },
          onClick: () => undoPlacement(),
        }, t('rack.undoPlacement')),
      ]),
    })
    const undoTimer = setTimeout(() => {
      if (lastPlacement.value && (lastPlacement.value as any)._token === snapshotToken) {
        rackLog.debug('undoPlacement: 撤销窗口已关闭', { deviceId, deviceName })
        lastPlacement.value = null
      }
    }, UNDO_TTL + 200)
    const snapshot: PlacementSnapshot & { _token?: number } = {
      deviceId, deviceName, rackId, uPosition, uSize, undoTimer, notifHandle,
    }
    snapshot._token = snapshotToken
    lastPlacement.value = snapshot
    rackLog.debug('undoPlacement: 撤销窗口已开启', { deviceId, deviceName, ttlMs: UNDO_TTL })
  } catch (e: any) {
    const t1 = performance.now()
    rackLog.error('submitPlacement: 上架失败', {
      ms: Math.round(t1 - t0), deviceId, rackId, uPosition, uSize,
      status: e?.response?.status, detail: e?.response?.data?.detail, error: e,
    })
    const msg = e?.response?.data?.detail || t('rack.placementFailed')
    ElMessage.error(msg)
  } finally {
    placementLoading.value = false
  }
}

// ---- 设备详情弹窗 ----
const detailVisible = ref(false)
const detailDevice = ref<RackDevice | null>(null)
const removeLoading = ref(false)

const deviceStatusMap: Record<string, { label: string; type: string }> = {
  active: { label: '在线', type: 'success' },
  alert: { label: '告警', type: 'warning' },
  offline: { label: '离线', type: 'info' },
}

// 设备块类型着色（与设备页 ICON_META 图标配色一致，避免用红色表示防火墙）
const DEVICE_BLOCK_COLORS: Record<string, { from: string; to: string; border: string }> = {
  firewall: { from: '#F8BBD0', to: '#F48FB1', border: '#EC7F9C' },
  router: { from: '#FBC588', to: '#F5A623', border: '#E09218' },
  switch: { from: '#A8D4FF', to: '#79BBFF', border: '#5FAAEF' },
  'load-balancer': { from: '#E1B7EA', to: '#CE93D8', border: '#BA7FC6' },
  server: { from: '#A8E4EE', to: '#80DEEA', border: '#63CEDB' },
  storage: { from: '#B4DFFB', to: '#8FCBF7', border: '#6FB8EF' },
  ap: { from: '#CBE8A4', to: '#AED581', border: '#97C368' },
  'wireless-controller': { from: '#A8DDB2', to: '#81C784', border: '#66B36F' },
  'ids-ips': { from: '#F7B8B8', to: '#EF9A9A', border: '#E48080' },
  waf: { from: '#FFC5B4', to: '#FFAB91', border: '#F0937A' },
  vpn: { from: '#E1B7EA', to: '#CE93D8', border: '#BA7FC6' },
  other: { from: '#CFC6BD', to: '#BCAAA4', border: '#A8968D' },
}
const deviceBlockStyle = (device: RackDevice) => {
  const c = DEVICE_BLOCK_COLORS[device.type || ''] || DEVICE_BLOCK_COLORS.other
  return {
    background: `linear-gradient(90deg, ${c.from} 0%, ${c.to} 100%)`,
    borderColor: c.border,
    color: '#26313f',
  }
}
const deviceStatusText = (status: string) => deviceStatusMap[status]?.label || status

const handleDeviceClick = (device: RackDevice) => {
  rackLog.info('handleDeviceClick: 点击设备打开详情', {
    deviceId: device.id, name: device.name, type: device.type,
    uPosition: device.uPosition, uSize: device.uSize, status: device.status,
  })
  detailDevice.value = device
  detailVisible.value = true
}

const confirmRemoveDevice = async () => {
  const device = detailDevice.value
  if (!device) return
  if (!canManageDevices.value) {
    rackLog.warn('confirmRemoveDevice: 无 devices:write 权限，操作被拦截')
    ElMessage.warning(t('rack.noPermission'))
    return
  }
  rackLog.info('confirmRemoveDevice: 用户确认下架', { deviceId: device.id, name: device.name })
  removeLoading.value = true
  const t0 = performance.now()
  try {
    await updateDevicePosition(device.id, { rack_id: null, u_position: null, u_size: 0 })
    const t1 = performance.now()
    rackLog.info('confirmRemoveDevice: 下架成功', { ms: Math.round(t1 - t0), deviceId: device.id })
    ElMessage.success(t('rack.removeSuccess'))
    detailVisible.value = false
    if (selectedRack.value) {
      rackLog.info('confirmRemoveDevice: 刷新机柜视图', { rackId: selectedRack.value.id })
      await selectRack(selectedRack.value.id)
      rackLog.info('confirmRemoveDevice: 机柜视图已刷新', { rackId: selectedRack.value.id, currentDeviceCount: currentDevices.value.length })
    }
  } catch (e: any) {
    rackLog.error('confirmRemoveDevice: 下架失败', {
      deviceId: device.id, name: device.name,
      status: e?.response?.status, detail: e?.response?.data?.detail, error: e,
    })
    const msg = e?.response?.data?.detail || t('rack.placementFailed')
    ElMessage.error(msg)
  } finally {
    removeLoading.value = false
  }
}

const allRacks = computed<RackType[]>(() => (store.racks as RackType[]) || [])

const racksFiltered = computed<RackType[]>(() => {
  const q = rackSearch.value.trim().toLowerCase()
  if (!q) return allRacks.value
  return allRacks.value.filter(r =>
    r.name.toLowerCase().includes(q) ||
    (r.room || '').toLowerCase().includes(q)
  )
})

const selectedRack = computed<RackType | null>(() => {
  if (!selectedRackId.value) return null
  return allRacks.value.find(r => r.id === selectedRackId.value) || null
})

// ---- U 位渲染辅助 ----
const currentDevices = ref<RackDevice[]>([])
const devicesMap = new Map<number, RackDevice>()

const rebuildDeviceMap = () => {
  devicesMap.clear()
  const list = currentDevices.value
  for (let i = 0; i < list.length; i++) {
    const dv = list[i]
    if (dv.uPosition == null) continue
    const size = dv.uSize || 1
    for (let u = dv.uPosition; u < dv.uPosition + size; u++) {
      devicesMap.set(u, dv)
    }
  }
}

function getUSlotInfo(u: number) {
  const d = devicesMap.get(u)
  if (!d) return { device: null as RackDevice | null, isTop: true, span: 1 }
  const size = d.uSize || 1
  return {
    device: d,
    // 机柜图高位在上（显示编号自上而下 42→1）。设备占 uPosition..uPosition+size-1，
    // 块必须锚定在视觉顶部行（编号 uPosition+size-1）向下延伸 size 行，
    // 才能与左侧 U 位标签对齐（否则 2U 设备会视觉下移一行，顶部行变成无虚线的 spacer）。
    isTop: u === d.uPosition + size - 1,
    span: size,
  }
}

const selectRack = async (id: number) => {
  rackLog.info('selectRack: 选中机柜', { id })
  selectedRackId.value = id
  loading.value = true
  try {
    const detail = await getRack(id)
    rackLog.info('selectRack: 获取详情成功', { id, deviceCount: detail.devices?.length,
      utilization: detail.stats?.utilization != null ? `${Math.round(detail.stats.utilization * 10) / 10}%` : undefined })
    currentDevices.value = detail.devices.map(d => ({
      id: d.id,
      name: d.name,
      type: d.type,
      vendor: d.vendor,
      model: d.model,
      sn: d.sn,
      uPosition: d.u_position,
      uSize: d.u_size,
      status: d.status,
      mgmtIp: d.mgmt_ip,
    }))
    rebuildDeviceMap()
    rackLog.debug('selectRack: 设备映射已重建', { id, count: currentDevices.value.length })
    rackLog.debug('selectRack: 设备U位明细',
      currentDevices.value.map(d => ({ name: d.name, u: d.uPosition, size: d.uSize, status: d.status })), false)
    selectedRackDetail.value = {
      devices: currentDevices.value,
      stats: detail.stats ? {
        totalU: detail.stats.total_u,
        usedU: detail.stats.used_u,
        freeU: detail.stats.free_u,
        utilization: detail.stats.utilization,
        deviceCount: detail.stats.device_count,
      } : null,
    }
  } catch (e) {
    rackLog.error('selectRack: 获取详情失败', { id, error: e })
    ElMessage.error(t('rack.loadFailed'))
  } finally {
    loading.value = false
  }
}

const loadAllRacks = async () => {
  rackLog.info('loadAllRacks: 开始加载机柜列表')
  loading.value = true
  try {
    const list = await listRacks()
    rackLog.debug('loadAllRacks: API原始响应', { count: list.length, items: list }, false)
    store.racks = list.map(r => ({
      id: r.id,
      name: r.name,
      siteId: r.site_id,
      room: r.room,
      rowPosition: r.row_position,
      totalU: r.total_u,
      status: r.status,
      description: r.description,
      usedU: r.used_u,
      utilization: r.utilization,
      deviceCount: r.device_count,
    }))
    rackLog.info('loadAllRacks: 完成', { count: store.racks.length })
    rackLog.debug('loadAllRacks: store摘要',
      store.racks.map(r => ({ id: r.id, name: r.name, status: r.status, totalU: r.totalU })))
    if (store.racks.length && !selectedRackId.value) {
      rackLog.info('loadAllRacks: 自动选中第一个机柜', { id: store.racks[0].id })
      await selectRack(store.racks[0].id)
    }
  } catch (e) {
    rackLog.error('loadAllRacks: 加载失败', e)
    ElMessage.error(t('rack.loadFailed'))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  rackLog.info('onMounted: 组件挂载', { hasUser: !!authStore.user, existingRacks: store.racks.length, logLevel: LOG_LEVEL })
  await loadSites()
  if (authStore.user && store.racks.length === 0) {
    await loadAllRacks()
  }
})

onBeforeUnmount(() => {
  devicesMap.clear()
  clearUndoTimer()
})
</script>

<template>
  <div class="rack-view">
    <div class="rack-page-header">
      <div class="rack-page-title">
        <h2 class="rack-title-text">{{ t('rack.title') }}</h2>
        <span class="rack-subtitle">{{ t('rack.subtitle') }}</span>
      </div>
      <div class="rack-page-actions">
        <el-button v-if="canWrite" type="primary" :icon="Plus" size="small" @click="openCreate">
          {{ t('rack.addRack') }}
        </el-button>
        <el-button v-if="canWrite && selectedRack" :icon="Edit" size="small" @click="openEdit">
          {{ t('rack.editRack') }}
        </el-button>
        <el-dropdown v-if="canDelete && selectedRack" trigger="click" @command="(cmd: string) => cmd === 'delete' && openDelete()">
          <el-button :icon="MoreFilled" size="small">{{ t('rack.more') }}</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="delete" class="more-delete-item">
                <el-icon><Delete /></el-icon>{{ t('rack.deleteRack') }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <div class="rack-layout">
      <aside class="rack-sidebar-col">
        <RackSidebar
          :racks="racksFiltered"
          :selected-id="selectedRackId"
          v-model:search="rackSearch"
          @select="selectRack"
          @refresh="loadAllRacks"
        />
      </aside>

      <section class="rack-center-col">
        <div v-if="loading && !selectedRack" class="rack-empty-state">
          <el-skeleton :rows="6" animated />
        </div>
        <div v-else-if="!selectedRack" class="rack-empty-state">
          <el-empty :description="t('rack.noRackSelected')" />
        </div>
        <template v-else>
          <div class="rack-center-header">
            <h3 class="rack-name">{{ selectedRack.name }}</h3>
            <el-tag
              :type="selectedRack.status === 'active' ? 'success' : selectedRack.status === 'alert' ? 'warning' : 'info'"
              size="small"
            >
              {{
                selectedRack.status === 'active'
                  ? t('rack.statusActive')
                  : selectedRack.status === 'alert'
                  ? t('rack.statusAlert')
                  : t('rack.statusOffline')
              }}
            </el-tag>
            <span v-if="selectedRack.room" class="rack-meta">{{ selectedRack.room }}</span>
            <span v-if="selectedRack.totalU" class="rack-meta">{{ selectedRack.totalU }}U</span>
          </div>

          <div class="rack-face-wrapper">
            <div class="rack-face" role="img" :aria-label="selectedRack.name + '机柜正视图'">
              <!-- 反向渲染：totalU 在顶，U1 在底 -->
              <template v-for="u in (selectedRack.totalU || 42)" :key="u">
                <div
                  class="u-slot"
                  :class="{ 'has-device': getUSlotInfo((selectedRack.totalU || 42) - u + 1).device != null }"
                >
                  <div class="u-label">{{ (selectedRack.totalU || 42) - u + 1 }}</div>
                  <el-tooltip
                    v-if="getUSlotInfo((selectedRack.totalU || 42) - u + 1).isTop && getUSlotInfo((selectedRack.totalU || 42) - u + 1).device"
                    placement="left"
                    :show-after="150"
                  >
                    <template #content>
                      <div class="dev-tip">
                        <div>{{ t('rack.devModel') }}: {{ getUSlotInfo((selectedRack.totalU || 42) - u + 1).device!.model || '—' }}</div>
                        <div>{{ t('rack.devMgmtIp') }}: {{ getUSlotInfo((selectedRack.totalU || 42) - u + 1).device!.mgmtIp || '—' }}</div>
                        <div>{{ t('rack.devStatus') }}: {{ deviceStatusText(getUSlotInfo((selectedRack.totalU || 42) - u + 1).device!.status) }}</div>
                      </div>
                    </template>
                    <div
                      class="u-device"
                      :style="{ ...deviceBlockStyle(getUSlotInfo((selectedRack.totalU || 42) - u + 1).device!), height: `calc(var(--u-height) * ${getUSlotInfo((selectedRack.totalU || 42) - u + 1).span} + var(--u-gap) * ${getUSlotInfo((selectedRack.totalU || 42) - u + 1).span - 1})` }"
                      @click="handleDeviceClick(getUSlotInfo((selectedRack.totalU || 42) - u + 1).device!)"
                    >
                      <span class="device-name">{{ getUSlotInfo((selectedRack.totalU || 42) - u + 1).device!.name }}</span>
                      <span class="device-size">{{ getUSlotInfo((selectedRack.totalU || 42) - u + 1).device!.uSize }}U</span>
                    </div>
                  </el-tooltip>
                  <div
                    v-else-if="getUSlotInfo((selectedRack.totalU || 42) - u + 1).device != null"
                    class="u-device-spacer"
                  ></div>
                  <div
                    v-else
                    class="u-slot-empty"
                    :class="{ 'u-slot-clickable': canManageDevices }"
                    :title="canManageDevices ? t('rack.clickToPlace') : ''"
                    @click="openPlacement((selectedRack.totalU || 42) - u + 1)"
                  >
                    <el-icon v-if="canManageDevices" class="slot-add-icon"><Plus /></el-icon>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </template>
      </section>

      <aside class="rack-right-col">
        <RackStatsPanel
          v-if="selectedRack && selectedRackDetail"
          :stats="selectedRackDetail.stats"
          :rack="selectedRack"
          :devices="selectedRackDetail.devices"
        />
        <RackTimeline
          :rack="selectedRack"
          :devices="selectedRackDetail?.devices || []"
        />
      </aside>
    </div>

    <!-- 新增/编辑机柜弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? t('rack.addRack') : t('rack.editRack')"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="90px" size="default">
        <el-form-item :label="t('rack.rackName')" prop="name">
          <el-input v-model="form.name" :placeholder="t('rack.rackName')" />
        </el-form-item>
        <el-form-item :label="t('rack.rackSite')" prop="site_id">
          <el-select v-model="form.site_id" :placeholder="t('rack.rackSite')" clearable filterable style="width: 100%">
            <el-option v-for="s in siteOptions" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('rack.rackRoom')" prop="room">
          <el-input v-model="form.room" :placeholder="t('rack.rackRoom')" />
        </el-form-item>
        <el-form-item :label="t('rack.rackRow')" prop="row_position">
          <el-input-number v-model="form.row_position" :min="1" :max="99" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('rack.rackTotalU')" prop="total_u">
          <el-input-number v-model="form.total_u" :min="1" :max="100" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('rack.status')" prop="status">
          <el-select v-model="form.status" style="width: 100%">
            <el-option :label="t('rack.statusActive')" value="active" />
            <el-option :label="t('rack.statusAlert')" value="alert" />
            <el-option :label="t('rack.statusOffline')" value="offline" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('rack.rackDescription')" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="2" :placeholder="t('rack.rackDescription')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="dialogLoading" @click="submitForm">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <!-- 设备上架弹窗 -->
    <el-dialog
      v-model="placementVisible"
      :title="t('rack.placeDevice') + ' - U' + placementTargetU"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form ref="placementFormRef" :model="placementForm" label-width="90px" size="default">
        <el-form-item :label="t('rack.selectDevice')" prop="deviceId" :rules="[{ required: true, message: t('rack.selectDeviceRequired'), trigger: 'change' }]">
          <el-select
            v-model="placementForm.deviceId"
            :placeholder="t('rack.selectDevice')"
            filterable
            clearable
            virtualized
            :loading="deviceLoading"
            :loading-text="t('common.loading')"
            :no-data-text="t('rack.noAvailableDevices')"
            style="width: 100%"
          >
            <el-option
              v-for="opt in deviceOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('rack.deviceUSize')" prop="uSize">
          <el-input-number v-model="placementForm.uSize" :min="1" :max="10" style="width: 100%" />
        </el-form-item>
      </el-form>
      <el-empty v-if="availableDevices.length === 0" :description="t('rack.noAvailableDevices')" :image-size="60" />
      <template #footer>
        <el-button @click="placementVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="placementLoading" :disabled="!placementForm.deviceId" @click="submitPlacement">
          {{ t('rack.confirmPlacement') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 删除机柜确认弹窗 -->
    <el-dialog
      v-model="deleteVisible"
      :title="t('rack.confirmDeleteTitle')"
      width="440px"
      :close-on-click-modal="false"
      class="rack-delete-dialog"
    >
      <template v-if="deleteTarget">
        <p class="delete-question">
          {{ t('rack.confirmDeleteText', { name: deleteTarget.name }) }}
        </p>
        <el-alert
          :title="t('rack.deleteUnassignNote', { count: deleteTarget.deviceCount ?? 0, name: deleteTarget.name })"
          type="warning"
          :closable="false"
          show-icon
          class="delete-note"
        />
      </template>
      <template #footer>
        <el-button @click="deleteVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="danger" :loading="deleteLoading" @click="confirmDelete">
          {{ t('rack.confirmDeleteBtn') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 设备详情弹窗 -->
    <el-dialog
      v-model="detailVisible"
      :title="t('rack.deviceDetail')"
      width="520px"
      :close-on-click-modal="true"
    >
      <template v-if="detailDevice">
        <el-descriptions :column="2" border size="default">
          <el-descriptions-item :label="t('rack.devName')" :span="2">
            <strong>{{ detailDevice.name }}</strong>
          </el-descriptions-item>
          <el-descriptions-item :label="t('rack.devType')">{{ deviceTypeText(t, detailDevice.type) }}</el-descriptions-item>
          <el-descriptions-item :label="t('rack.devStatus')">
            <el-tag :type="(deviceStatusMap[detailDevice.status]?.type as any) || 'info'" size="small" effect="light">
              {{ deviceStatusMap[detailDevice.status]?.label || detailDevice.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('rack.devVendor')">{{ detailDevice.vendor || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('rack.devModel')">{{ detailDevice.model || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('rack.devMgmtIp')" :span="2">{{ detailDevice.mgmtIp || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('rack.devSN')" :span="2">{{ detailDevice.sn || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('rack.devUPos')">
            <span v-if="detailDevice">{{ 'U' + (detailDevice as any).uPosition + ((detailDevice as any).uSize > 1 ? ' ~ U' + ((detailDevice as any).uPosition + (detailDevice as any).uSize - 1) : '') }}</span>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item :label="t('rack.devUSize')">{{ detailDevice?.uSize ?? '-' }}U</el-descriptions-item>
          <el-descriptions-item :label="t('rack.devRack')" :span="2">
            {{ selectedRack?.name || '-' }}
          </el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 12px; color: #909399;">{{ selectedRack?.name }} · U{{ detailDevice?.uPosition }}</span>
          <div>
            <el-button v-if="detailDevice" type="primary" plain @click="goDevicePage(detailDevice.id)">
              {{ t('rack.viewDevice') }}
            </el-button>
            <el-button @click="detailVisible = false">{{ t('common.close') }}</el-button>
            <el-button
              v-if="canManageDevices"
              type="danger"
              plain
              :loading="removeLoading"
              @click="confirmRemoveDevice"
            >
              {{ t('rack.removeDevice') }}
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.rack-view {
  width: 100%;
  padding: 20px 24px;
  background: var(--bg-page, #f5f7fa);
  min-height: 100%;
  box-sizing: border-box;
}

.rack-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.rack-page-title { display: flex; align-items: baseline; gap: 12px; min-width: 0; flex-shrink: 0; }
.rack-title-text { margin: 0; font-size: 22px; font-weight: 600; color: var(--text-primary, #1f2937); white-space: nowrap; }
.rack-subtitle { color: var(--text-secondary, #6b7280); font-size: 13px; }
.rack-page-actions { display: flex; gap: 8px; }

.rack-layout {
  display: grid;
  grid-template-columns: 280px minmax(360px, 1fr) 340px;
  gap: 16px;
  align-items: start;
}

.rack-sidebar-col,
.rack-center-col,
.rack-right-col {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  border: 1px solid var(--border-color, #eef0f3);
}

.rack-center-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px dashed var(--border-color, #eef0f3);
  flex-wrap: wrap;
}
.rack-name { margin: 0; font-size: 16px; font-weight: 600; }
.rack-meta { color: var(--text-secondary, #6b7280); font-size: 13px; }

.rack-face-wrapper {
  display: flex;
  justify-content: center;
  padding: 12px 0;
  --u-height: 22px;
  --u-gap: 3px;
}
.rack-face {
  width: 280px;
  background: linear-gradient(180deg, #2c3446 0%, #1f2634 100%);
  border-radius: 6px;
  padding: 12px 10px;
  display: flex;
  flex-direction: column; /* 从上往下：总U在顶，1U在底 */
  gap: var(--u-gap);
  border: 1px solid #111;
  box-shadow: inset 0 0 20px rgba(0,0,0,0.35), 0 4px 18px rgba(15,23,42,0.12);
}
.u-slot {
  display: flex;
  align-items: stretch;
  height: var(--u-height);
  gap: 6px;
  position: relative;
}
.u-label {
  color: #8d98aa;
  font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  width: 22px;
  text-align: right;
  flex: 0 0 22px;
  opacity: 0.8;
  display: flex;
  align-items: center;
  justify-content: flex-end;
}
.u-slot-empty {
  flex: 1;
  border-radius: 3px;
  border: 1px dashed rgba(255,255,255,0.045);
  background: rgba(255,255,255,0.008);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.u-slot-clickable {
  cursor: pointer;
}
.slot-add-icon {
  font-size: 12px;
  color: transparent;
  transition: color 0.15s;
}
.u-slot-clickable:hover {
  background: rgba(63, 131, 248, 0.1);
  border-color: rgba(63, 131, 248, 0.45);
}
.u-slot-clickable:hover .slot-add-icon {
  color: rgba(160, 200, 255, 0.95);
}
.u-device-spacer { flex: 1; }
.u-device {
  flex: 1;
  border-radius: 3px;
  color: #26313f;
  font-size: 11px;
  padding: 0 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid;
  position: relative;
  z-index: 2;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.25);
  cursor: pointer;
  transition: filter .15s;
  overflow: hidden;
  min-height: var(--u-height);
}
.u-device:hover { filter: brightness(1.08); z-index: 3; }
.device-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
.device-size {
  flex-shrink: 0;
  font-size: 10px;
  opacity: 0.65;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.rack-right-col { display: flex; flex-direction: column; gap: 16px; }
.rack-empty-state { padding: 40px 0; }

.more-delete-item { color: var(--el-color-danger, #f56c6c); }

.delete-question {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--text-primary, #1f2937);
  line-height: 1.6;
}
.delete-note { width: 100%; }
.rack-delete-dialog .el-alert { --el-alert-padding: 10px 12px; }

.dev-tip { line-height: 1.7; font-size: 12px; }

@media (max-width: 1100px) {
  .rack-layout { grid-template-columns: 240px 1fr; }
  .rack-right-col { grid-column: 1 / -1; }
}
@media (max-width: 768px) {
  .rack-layout { grid-template-columns: 1fr; }
  .rack-view { padding: 12px; }
}
</style>
