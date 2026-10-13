<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '../../store'
import { useAuthStore } from '../../store/auth'
import { storeToRefs } from 'pinia'
import { applyKeywordFilter } from '@/lib/filters'
import { confirmAndRun } from '@/lib/confirm'
import type { Site } from '../../types/domain'
import { getSites, createSite, updateSite, deleteSite, type SiteResponse } from '../../api/sites'
import { ElMessage } from 'element-plus'
import { Location, Plus, Edit, Delete, Check, Warning, HelpFilled, DocumentCopy } from '@element-plus/icons-vue'

const { t } = useI18n()

const store = useAppStore()
const authStore = useAuthStore()
const { circuits } = storeToRefs(store)
const sites = ref<Site[]>([])
const searchQuery = ref('')
const statusFilter = ref<'all' | 'alert'>('all')
const showDialog = ref(false)
const editingSite = ref<Site | null>(null)
const loading = ref(false)

const isViewer = computed(() => authStore.isReadOnly())

const form = ref<Partial<Site>>({
  id: 0,
  name: '',
  location: '',
  city: '',
  room: '',
  contact: '',
  contactPhone: '',
  status: 'online',
  alertCount: 0,
})

const filteredSites = computed(() => {
  let items = [...sites.value]

  // 状态过滤
  if (statusFilter.value === 'alert') {
    items = items.filter(site => site.status === 'alert')
  }

  // 搜索过滤
  return applyKeywordFilter(items, searchQuery.value, ['name', 'location', 'contact'])
})

const alertSiteCount = computed(() => {
  return sites.value.filter(s => s.status === 'alert').length
})

const resetForm = () => {
  form.value = { 
    name: '', 
    location: '',
    city: '',
    room: '',
    contact: '',
    contactPhone: '',
    status: 'online',
    alertCount: 0,
  }
  editingSite.value = null
  showDialog.value = false
}

const openCreateDialog = () => {
  resetForm()
  showDialog.value = true
}

const openEditDialog = (site: Site) => {
  editingSite.value = site
  form.value = { ...site }
  showDialog.value = true
}

const handleSave = async () => {
  if (!form.value.name?.trim()) {
    ElMessage.error(t('sites.nameRequired'))
    return
  }
  if (!form.value.city?.trim()) {
    ElMessage.error(t('sites.cityRequired'))
    return
  }
  
  try {
    if (editingSite.value) {
      const response = await updateSite(editingSite.value.id as number, {
        name: form.value.name || '',
        location: form.value.location || null,
        city: form.value.city || '',
        room: form.value.room || null,
        contact: form.value.contact || null,
        contact_phone: form.value.contactPhone || null,
        status: form.value.status || 'online',
        alert_count: form.value.alertCount || 0,
      })
      const index = sites.value.findIndex(s => s.id === response.id)
      if (index !== -1) {
        sites.value[index] = convertToSite(response)
      }
      
      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: t('sites.updateSite'),
        resource: t('sites.siteManagement'),
        detail: `${t('sites.updateSite')}: ${form.value.name}`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'true'
      })
      
      ElMessage.success(t('sites.updateSuccess'))
    } else {
      const response = await createSite({
        name: form.value.name || '',
        location: form.value.location || null,
        city: form.value.city || '',
        room: form.value.room || null,
        contact: form.value.contact || null,
        contact_phone: form.value.contactPhone || null,
        status: form.value.status || 'online',
        alert_count: form.value.alertCount || 0,
      })
      sites.value.push(convertToSite(response))
      
      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: t('sites.createSite'),
        resource: t('sites.siteManagement'),
        detail: `${t('sites.createSite')}: ${form.value.name}`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'true'
      })
      
      ElMessage.success(t('sites.createSuccess'))
    }
    showDialog.value = false
    resetForm()
  } catch (error) {
    console.error('Failed to save site:', error)
    ElMessage.error(t('sites.saveFailed'))
  }
}

const handleDelete = async (site: Site) => {
  const circuitCount = getCircuitCount(String(site.id))
  if (circuitCount > 0) {
    ElMessage.warning(t('sites.deleteCircuitFirst'))
    return
  }

  await confirmAndRun({
    message: t('sites.confirmDelete', { name: site.name }),
    title: t('sites.deleteConfirmTitle'),
    confirmText: t('sites.deleteButton'),
    cancelText: t('sites.cancelButton'),
    action: async () => {
      await deleteSite(site.id as number)
      sites.value = sites.value.filter(s => s.id !== site.id)

      // 添加操作日志
      store.addAuditLog({
        user: authStore.user?.username || 'system',
        action: t('sites.deleteSite'),
        resource: t('sites.siteManagement'),
        detail: `${t('sites.deleteSite')}: ${site.name}`,
        ipAddress: null,
        createdAt: new Date().toISOString(),
        success: 'true'
      })
    },
    successMessage: t('sites.deleteSuccess'),
    errorMessage: t('sites.deleteFailed'),
  })
}

const getCircuitCount = (siteId: string | number) => {
  return circuits.value.filter(c => {
    const circuitSiteId = c.siteId
    return circuitSiteId !== undefined && String(circuitSiteId) === String(siteId)
  }).length
}

const getStatusInfo = (status: string, alertCount: number) => {
  switch (status) {
    case 'online':
      return { text: t('sites.runningNormal'), type: 'success', icon: Check }
    case 'alert':
      return { text: t('sites.hasAlert', { count: alertCount }), type: 'danger', icon: Warning }
    case 'offline':
      return { text: t('sites.offline'), type: 'info', icon: HelpFilled }
    default:
      return { text: t('sites.unknown'), type: 'info', icon: HelpFilled }
  }
}

const getRowClass = ({ row }: { row: Site }) => {
  return row.status === 'alert' ? 'alert-row' : ''
}

const openZabbixLink = (siteId: string) => {
  window.open(`#zabbix/site/${siteId}`, '_blank')
}

// 点击告警卡片，跳转到告警中心并过滤告警站点
const handleAlertCardClick = () => {
  console.log(t('sites.navigateToAlerts'))
  statusFilter.value = 'alert'
}

// 复制电话号码到剪贴板
const copyPhone = async (phone: string) => {
  try {
    await navigator.clipboard.writeText(phone)
    ElMessage.success(t('sites.phoneCopied'))
  } catch (err) {
    ElMessage.error(t('sites.copyFailed'))
  }
}

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
  loading.value = true
  try {
    const response = await getSites()
    sites.value = response.map(convertToSite)
  } catch (error) {
    console.error(t('sites.loadFailed'), error)
    ElMessage.error(t('sites.loadFailed'))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadSites()
})

</script>

<template>
  <div class="sites-page">
    <div class="overview-cards">
      <div class="overview-card">
        <div class="overview-card-label">{{ t('sites.totalSites') }}</div>
        <div class="overview-card-value">{{ sites.length }}</div>
        <div class="overview-card-trend">{{ t('sites.allSites') }}</div>
      </div>
      <div class="overview-card overview-card-blue">
        <div class="overview-card-label">{{ t('sites.assignedCircuits') }}</div>
        <div class="overview-card-value">{{ circuits.length }}</div>
        <div class="overview-card-trend">{{ t('sites.totalCircuits') }}</div>
      </div>
      <div 
        class="overview-card overview-card-warning clickable"
        @click="handleAlertCardClick"
      >
        <div class="overview-card-label">{{ t('sites.alertSites') }}</div>
        <div class="overview-card-value">{{ alertSiteCount }}</div>
        <div class="overview-card-trend">{{ t('sites.clickToView') }}</div>
      </div>
    </div>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="table-filters">
            <el-input
              v-model="searchQuery"
              :placeholder="t('sites.searchPlaceholder')"
              prefix-icon="Search"
              clearable
              style="width: 320px"
            />
            <el-tag 
              v-if="statusFilter === 'alert'" 
              type="danger" 
              closable 
              @close="statusFilter = 'all'"
            >
              {{ t('sites.showAlertOnly') }}
            </el-tag>
          </div>
          <div class="table-actions">
            <el-button v-if="!isViewer" type="primary" @click="openCreateDialog">
              <el-icon><Plus /></el-icon>
              {{ t('sites.addSite') }}
            </el-button>
          </div>
        </div>
      </template>

      <el-skeleton :loading="loading" animated :rows="5" v-if="loading">
        <template #template>
          <div class="skeleton-item" v-for="i in 5" :key="i">
            <el-skeleton-item variant="text" style="width: 200px" />
            <el-skeleton-item variant="text" style="width: 150px" />
            <el-skeleton-item variant="text" style="width: 100px" />
            <el-skeleton-item variant="text" style="width: 80px" />
          </div>
        </template>
      </el-skeleton>

      <el-table
        v-else
        class="sites-table"
        :data="filteredSites"
        style="width: 100%"
        stripe
        border
        height="calc(100vh - 380px)"
        :row-class-name="getRowClass"
      >
        <el-table-column prop="name" :label="t('sites.siteName')" min-width="240">
          <template #default="{ row }">
            <div class="site-name-cell">
              <div class="site-name-main">
                <el-icon><Location /></el-icon>
                {{ row.name }}
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('sites.location')" min-width="200">
          <template #default="{ row }">
            <div class="location-cell">
              <div class="location-city">{{ row.city }}</div>
              <div class="location-room">{{ row.room }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('sites.contact')" min-width="150">
          <template #default="{ row }">
            {{ row.contact }}
          </template>
        </el-table-column>
        <el-table-column :label="t('sites.contactPhone')" min-width="150">
          <template #default="{ row }">
            <div class="phone-cell">
              <span class="phone-text">{{ row.contactPhone }}</span>
              <el-icon 
                class="copy-icon" 
                @click.stop="copyPhone(row.contactPhone)"
              >
                <DocumentCopy />
              </el-icon>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer" :label="t('sites.circuitCount')" min-width="120" align="center">
          <template #default="{ row }">
            <el-tag type="info" effect="light">
              {{ getCircuitCount(row.id) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('sites.status')" min-width="180" align="center">
          <template #default="{ row }">
            <a 
              href="#" 
              class="status-link"
              @click.prevent="openZabbixLink(row.id)"
            >
              <el-icon :class="`status-icon status-${getStatusInfo(row.status, row.alertCount).type}`">
                <component :is="getStatusInfo(row.status, row.alertCount).icon" />
              </el-icon>
              <span :class="`status-text status-${getStatusInfo(row.status, row.alertCount).type}`">
                {{ getStatusInfo(row.status, row.alertCount).text }}
              </span>
            </a>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer" :label="t('common.actions')" width="180" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEditDialog(row)">
              <el-icon><Edit /></el-icon>
              {{ t('common.edit') }}
            </el-button>
            <el-button 
              link 
              type="danger" 
              size="small" 
              :disabled="getCircuitCount(row.id) > 0"
              @click="handleDelete(row)"
            >
              <el-icon><Delete /></el-icon>
              {{ t('common.delete') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      
      <el-empty 
        v-if="!loading && filteredSites.length === 0" 
        :description="t('sites.noData')"
      >
        <el-button v-if="!isViewer" type="primary" @click="openCreateDialog">{{ t('sites.createFirst') }}</el-button>
      </el-empty>
    </el-card>

    <el-dialog
      v-model="showDialog"
      :title="editingSite ? t('sites.editSite') : t('sites.addSite')"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item :label="t('sites.siteName')">
          <el-input v-model="form.name" :placeholder="t('sites.enterName')" />
        </el-form-item>
        <el-form-item :label="t('sites.city')">
          <el-input v-model="form.city" :placeholder="t('sites.exampleCity')" />
        </el-form-item>
        <el-form-item :label="t('sites.room')">
          <el-input v-model="form.room" :placeholder="t('sites.exampleRoom')" />
        </el-form-item>
        <el-form-item :label="t('sites.contact')">
          <el-input v-model="form.contact" :placeholder="t('sites.enterContact')" />
        </el-form-item>
        <el-form-item :label="t('sites.contactPhone')">
          <el-input v-model="form.contactPhone" :placeholder="t('sites.enterPhone')" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="resetForm">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleSave">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.sites-page {
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
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.overview-card.clickable {
  cursor: pointer;
}

.overview-card.clickable:hover {
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.12);
}

.overview-card-blue { border-left-color: #1890ff; }
.overview-card-warning { 
  border-left-color: #faad14; 
  background: linear-gradient(135deg, #fff7ed 0%, #fff 100%);
}
.overview-card-warning .overview-card-value {
  color: #d46b08;
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

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.table-filters {
  display: flex;
  gap: 12px;
  align-items: center;
}

.table-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.skeleton-item {
  display: flex;
  gap: 20px;
  padding: 16px 0;
  border-bottom: 1px solid #f0f0f0;
}

.site-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.site-name-main {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  color: #262626;
}

.site-name-main .el-icon {
  color: #1890ff;
}

.location-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.location-city {
  font-weight: 500;
  color: #262626;
  font-size: 14px;
}

.location-room {
  font-size: 12px;
  color: #8c8c8c;
}

.contact-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #262626;
  cursor: default;
}

.phone-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.phone-text {
  color: #262626;
  font-size: 13px;
}

.copy-icon {
  color: #8c8c8c;
  cursor: pointer;
  transition: color 0.2s;
  font-size: 14px;
}

.copy-icon:hover {
  color: #1890ff;
}

.status-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: inherit;
  text-decoration: none;
}

.status-link:hover .status-text {
  text-decoration: underline;
}

.status-icon {
  font-size: 14px;
}

.status-icon.status-success {
  color: #52c41a;
}

.status-icon.status-danger {
  color: #ff4d4f;
}

.status-icon.status-info {
  color: #bfbfbf;
}

.status-text {
  font-size: 13px;
}

.status-text.status-success {
  color: #52c41a;
}

.status-text.status-danger {
  color: #ff4d4f;
}

.status-text.status-info {
  color: #8c8c8c;
}

.el-table .alert-row {
  background-color: #fff5f5 !important;
}

.el-table .alert-row:hover {
  background-color: #fff1f0 !important;
}

.sites-table :deep(.cell) {
  line-height: 1.5;
}

.sites-table :deep(.el-table__cell) {
  padding: 8px 12px;
}

.sites-table .location-cell,
.sites-table .phone-cell,
.sites-table .site-name-cell {
  white-space: nowrap;
}

@media (max-width: 1200px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
