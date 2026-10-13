<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../store'
import { storeToRefs } from 'pinia'
import { applyKeywordFilter } from '@/lib/filters'
import { useCrudForm } from '@/lib/useCrudForm'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { Plus, Download, Upload, Clock, Warning, WarningFilled, ArrowDown, View, Edit, Document, Delete } from '@element-plus/icons-vue'
import { daysUntil, money, formatDate } from '../../lib/utils'
import api from '../../api/axios'
import type { Circuit, Site } from '../../types/domain'
import { getCircuits, createCircuit, updateCircuit, deleteCircuit, type CircuitResponse } from '../../api/circuits'
import { getSites, type SiteResponse } from '../../api/sites'
import { getLocale } from '@/i18n'

const { t, locale } = useI18n()

const router = useRouter()
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
const expiryCount = computed(() => circuits.value.filter(c => {
  const days = daysUntil(c.contractEnd)
  return days >= 0 && days <= 30
}).length)
const totalCost = computed(() => circuits.value.reduce((sum, c) => sum + (c.monthlyCost || 0), 0))

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
      const days = daysUntil(c.contractEnd)
      if (filterExpiry.value === 'urgent') return days >= 0 && days <= 7
      if (filterExpiry.value === 'soon') return days >= 0 && days <= 30
      return true
    })
  }
  
  return items
})

function getStatusType(status: string) {
  if (status === t('circuits.statusNormal')) return 'success'
  if (status === t('circuits.statusFault')) return 'danger'
  if (status === t('circuits.statusDisabled')) return 'info'
  return 'warning'
}

function getRowClass(row: Circuit) {
  if (row.status === t('circuits.statusFault')) return 'fault-row'
  const days = daysUntil(row.contractEnd)
  if (days >= 0 && days <= 30) return 'expiry-row'
  return ''
}

function getExpiryDisplay(date: string) {
  const days = daysUntil(date)
  if (days === -999) return { text: '-', type: 'info', icon: Clock }
  if (days < 0) return { text: t('circuits.expired'), type: 'danger', icon: Warning }
  if (days === 0) return { text: t('circuits.expireToday'), type: 'danger', icon: WarningFilled }
  if (days <= 7) return { text: `${t('circuits.expireDays', { days })}`, type: 'warning', icon: Clock }
  return { text: `${t('circuits.expireRemaining', { days })}`, type: 'info', icon: Clock }
}

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
  if (confirm(`${t('common.confirm')} ${t('common.delete')} ${t('circuits.title')} "${row.name}"?`)) {
    deleteCircuit(Number(row.id)).then(() => {
      circuits.value = circuits.value.filter(c => c.id !== row.id)
      store.save()
      ElMessage.success(t('common.success'))
    }).catch(error => {
      console.error('Failed to delete circuit:', error)
      ElMessage.error(t('common.error'))
    })
  }
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
      <div class="overview-card overview-card-danger">
        <div class="overview-card-label">{{ t('circuits.fault') }}</div>
        <div class="overview-card-value">{{ faultCount }}</div>
        <div class="overview-card-trend">{{ t('circuits.needHandle') }}</div>
      </div>
      <div class="overview-card overview-card-warning">
        <div class="overview-card-label">{{ t('circuits.expiring') }}</div>
        <div class="overview-card-value">{{ expiryCount }}</div>
        <div class="overview-card-trend">{{ t('circuits.days30') }}</div>
      </div>
      <div class="overview-card overview-card-blue">
        <div class="overview-card-label">{{ t('circuits.monthlyCost') }}</div>
        <div class="overview-card-value">¥{{ money(totalCost) }}</div>
        <div class="overview-card-trend">{{ t('circuits.monthlyFee') }}</div>
      </div>
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
              <el-select v-model="filterSiteId" :placeholder="t('sites.title')" clearable style="width: 120px">
                <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
              </el-select>
              <el-select v-model="filterExpiry" :placeholder="t('circuits.expiryStatus')" clearable style="width: 120px">
                <el-option :label="t('circuits.days7')" value="urgent" />
                <el-option :label="t('circuits.days30')" value="soon" />
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
            <el-button v-if="selectedRows.length > 0" type="danger" size="small">{{ t('common.batch') }} ({{ selectedRows.length }})</el-button>
            <el-button type="success" plain @click="handleExport">
              <el-icon><Download /></el-icon> {{ t('common.export') }}
            </el-button>
            <el-button type="warning" plain @click="showImportDialog = true">
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
        stripe
        border
        height="calc(100vh - 360px)"
        @selection-change="(val: Circuit[]) => selectedRows = val.map((r: Circuit) => r.id)"
        :row-class-name="getRowClass"
        class="circuits-table"
      >
        <el-table-column type="selection" width="50" fixed="left" />
        <el-table-column prop="name" :label="t('circuits.name')" min-width="160" fixed="left">
          <template #default="{ row }">
            <div class="circuit-name-cell">
              <div class="circuit-name-main" @click="viewDetail(row)">{{ row.name }}</div>
              <div class="circuit-name-sub">{{ row.circuitNo }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="siteId" :label="t('sites.title')" min-width="100">
          <template #default="{ row }">{{ siteName(row.siteId) }}</template>
        </el-table-column>
        <el-table-column prop="provider" :label="t('circuits.provider')" min-width="100" />
        <el-table-column prop="type" :label="t('circuits.type')" min-width="110" />
        <el-table-column prop="bandwidth" :label="t('circuits.bandwidth')" min-width="90">
          <template #default="{ row }">{{ row.bandwidth }} Mbps</template>
        </el-table-column>
        <el-table-column prop="publicIp" :label="t('circuits.publicIp')" min-width="130" show-overflow-tooltip />
        <el-table-column prop="contractStart" :label="t('circuits.contractStart')" min-width="110">
          <template #default="{ row }">
            <div class="expiry-date">{{ formatDate(row.contractStart) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="contractEnd" :label="t('circuits.contractEnd')" min-width="120">
          <template #default="{ row }">
            <div class="expiry-cell">
              <el-tag :type="getExpiryDisplay(row.contractEnd).type" size="small" effect="dark">
                <el-icon><component :is="getExpiryDisplay(row.contractEnd).icon" /></el-icon>
                {{ getExpiryDisplay(row.contractEnd).text }}
              </el-tag>
              <div class="expiry-date">{{ formatDate(row.contractEnd) }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" :label="t('common.status')" min-width="80">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" effect="dark">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="monthlyCost" :label="t('circuits.monthlyCost')" min-width="140" class-name="cost-column">
          <template #default="{ row }">
            <span class="cost-value">¥{{ money(row.monthlyCost) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="110" fixed="right">
          <template #default="{ row }">
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
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

.overview-card {
  background: white;
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid #8c8c8c;
  transition: all 0.2s ease;
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.overview-card-success { border-left-color: #52c41a; }
.overview-card-danger { border-left-color: #ff4d4f; }
.overview-card-warning { border-left-color: #faad14; }
.overview-card-blue { border-left-color: #1890ff; }

.overview-card-label {
  font-size: 13px;
  color: #8c8c8c;
  margin-bottom: 6px;
}

.overview-card-value {
  font-size: 26px;
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
  background: #f5f5f5;
  border-radius: 3px;
}

.table-filters-wrapper::-webkit-scrollbar-thumb {
  background: #d9d9d9;
  border-radius: 3px;
}

.table-filters-wrapper::-webkit-scrollbar-thumb:hover {
  background: #bfbfbf;
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
}

.circuit-name-main {
  font-weight: 500;
  color: #1890ff;
  cursor: pointer;
}

.circuit-name-main:hover {
  text-decoration: underline;
}

.circuit-name-sub {
  font-size: 12px;
  color: #8c8c8c;
}

.expiry-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}

.expiry-date {
  font-size: 12px;
  color: #8c8c8c;
}

.cost-value {
  font-weight: 600;
  color: #262626;
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
  background-color: #fff1f0 !important;
}

:deep(.fault-row:hover) {
  background-color: #fff2f0 !important;
}

:deep(.expiry-row) {
  background-color: #fffbe6 !important;
}

:deep(.expiry-row:hover) {
  background-color: #fffbe6 !important;
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