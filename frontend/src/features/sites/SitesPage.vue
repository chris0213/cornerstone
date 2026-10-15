<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '../../store'
import { useAuthStore } from '../../store/auth'
import { storeToRefs } from 'pinia'
import { applyKeywordFilter } from '@/lib/filters'
import { useCrudForm } from '@/lib/useCrudForm'
import type { Site } from '../../types/domain'
import { getSites, createSite, updateSite, deleteSite, type SiteResponse } from '../../api/sites'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { Location, Plus, Edit, Delete, Check, Warning, HelpFilled, DocumentCopy, ArrowDown } from '@element-plus/icons-vue'

const { t } = useI18n()

const store = useAppStore()
const authStore = useAuthStore()
const { circuits } = storeToRefs(store)
const sites = ref<Site[]>([])
const searchQuery = ref('')
const statusFilter = ref<'all' | 'online' | 'alert' | 'offline'>('all')
const loading = ref(false)

const isViewer = computed(() => authStore.isReadOnly())

// 表单弹窗状态（新建/编辑/关闭）
const {
  showDialog,
  editing: editingSite,
  form,
  openCreate: openCreateDialog,
  openEdit: openEditDialog,
  closeDialog,
} = useCrudForm<Site, Partial<Site>>({
  createDefaults: () => ({
    id: 0,
    name: '',
    location: '',
    city: '',
    room: '',
    contact: '',
    contactPhone: '',
    status: 'online',
    alertCount: 0,
  }),
})

const filteredSites = computed(() => {
  let items = [...sites.value]

  // 状态过滤
  if (statusFilter.value === 'online') {
    items = items.filter(site => site.status === 'online')
  } else if (statusFilter.value === 'alert') {
    items = items.filter(site => site.status === 'alert')
  } else if (statusFilter.value === 'offline') {
    items = items.filter(site => site.status === 'offline')
  }

  // 搜索过滤
  return applyKeywordFilter(items, searchQuery.value, ['name', 'location', 'contact'])
})

// 顶部统计卡片：基于表格数据计算
const statusCounts = computed(() => ({
  total: sites.value.length,
  online: sites.value.filter(s => s.status === 'online').length,
  alert: sites.value.filter(s => s.status === 'alert').length,
  offline: sites.value.filter(s => s.status === 'offline').length,
}))

const clickCard = (type: 'online' | 'alert' | 'offline') => {
  if (statusCounts.value[type] === 0) return
  statusFilter.value = statusFilter.value === type ? 'all' : type
}

const clearStatusFilter = () => {
  statusFilter.value = 'all'
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
    closeDialog()
  } catch (error) {
    console.error('Failed to save site:', error)
    ElMessage.error(t('sites.saveFailed'))
  }
}

// 操作列「更多」下拉命令分发
const handleCommand = (cmd: string, site: Site) => {
  if (cmd === 'delete') handleDelete(site)
}

const handleDelete = async (site: Site) => {
  const circuitCount = getCircuitCount(String(site.id))
  if (circuitCount > 0) {
    ElMessage.warning(t('sites.deleteBlockedTip', { count: circuitCount }))
    return
  }

  // 二次确认：明确要求点击「确认删除」
  try {
    await ElMessageBox.confirm(
      t('sites.confirmDelete', { name: site.name }),
      t('sites.deleteConfirmTitle'),
      {
        confirmButtonText: t('sites.confirmDeleteButton'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return // 用户取消
  }

  try {
    await deleteSite(site.id as number)
    sites.value = sites.value.filter(s => s.id !== site.id)
    ElMessage.success(t('sites.deleteSuccess'))

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
  } catch (error) {
    console.error('Failed to delete site:', error)
    ElMessage.error(t('sites.deleteFailed'))
  }
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
      return { text: t('sites.hasAlert', { count: alertCount }), type: 'warning', icon: Warning }
    case 'offline':
      return { text: t('sites.offline'), type: 'danger', icon: HelpFilled }
    default:
      return { text: t('sites.unknown'), type: 'info', icon: HelpFilled }
  }
}

const getRowClass = ({ row }: { row: Site }) => {
  if (row.status === 'alert') return 'row-status-alert'
  if (row.status === 'offline') return 'row-status-offline'
  return ''
}

const openZabbixLink = (siteId: string) => {
  window.open(`#zabbix/site/${siteId}`, '_blank')
}

// 状态排序权重：告警 > 离线 > 正常（异常优先）
const statusOrder = (site: Site) => {
  if (site.status === 'alert') return 0
  if (site.status === 'offline') return 1
  return 2
}

// 跳转专线页并按站点过滤
const router = useRouter()
const goToCircuits = (siteId: string | number) => {
  router.push({ path: '/circuits', query: { siteId: String(siteId) } })
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
      <div class="overview-card overview-card-total">
        <div class="overview-card-label">{{ t('sites.totalSites') }}</div>
        <div class="overview-card-value">{{ statusCounts.total }}</div>
        <div class="overview-card-trend">{{ t('sites.allSites') }}</div>
      </div>
      <div
        class="overview-card overview-card-success"
        :class="{ clickable: statusCounts.online > 0, disabled: statusCounts.online === 0 }"
        @click="clickCard('online')"
      >
        <div class="overview-card-label">{{ t('sites.runningNormal') }}</div>
        <div class="overview-card-value">{{ statusCounts.online }}</div>
        <div class="overview-card-trend">
          {{ statusCounts.online > 0 ? t('sites.clickToView') : t('sites.allNormal') }}
        </div>
      </div>
      <div
        class="overview-card overview-card-warning"
        :class="{ clickable: statusCounts.alert > 0, disabled: statusCounts.alert === 0 }"
        @click="clickCard('alert')"
      >
        <div class="overview-card-label">{{ t('sites.alertSites') }}</div>
        <div class="overview-card-value">{{ statusCounts.alert }}</div>
        <div class="overview-card-trend">
          {{ statusCounts.alert > 0 ? t('sites.clickToView') : t('sites.allNormal') }}
        </div>
      </div>
      <div
        class="overview-card overview-card-danger"
        :class="{ clickable: statusCounts.offline > 0, disabled: statusCounts.offline === 0 }"
        @click="clickCard('offline')"
      >
        <div class="overview-card-label">{{ t('sites.offline') }}</div>
        <div class="overview-card-value">{{ statusCounts.offline }}</div>
        <div class="overview-card-trend">
          {{ statusCounts.offline > 0 ? t('sites.clickToView') : t('sites.allNormal') }}
        </div>
      </div>
      <div class="overview-card overview-card-blue">
        <div class="overview-card-label">{{ t('sites.assignedCircuits') }}</div>
        <div class="overview-card-value">{{ circuits.length }}</div>
        <div class="overview-card-trend">{{ t('sites.totalCircuits') }}</div>
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
              v-if="statusFilter !== 'all'"
              :type="statusFilter === 'alert' ? 'warning' : statusFilter === 'offline' ? 'danger' : 'success'"
              closable
              @close="clearStatusFilter"
            >
              {{ t('sites.filteredLabel') }}：{{
                statusFilter === 'alert' ? t('sites.alertSites')
                : statusFilter === 'offline' ? t('sites.offline')
                : t('sites.runningNormal')
              }} ✕
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
        border
        height="calc(100vh - 380px)"
        :row-class-name="getRowClass"
        :default-sort="{ prop: 'name', order: null }"
      >
        <el-table-column prop="name" :label="t('sites.siteName')" min-width="240" sortable>
          <template #default="{ row }">
            <div class="site-name-cell">
              <div class="site-name-main">
                <el-icon><Location /></el-icon>
                {{ row.name }}
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('sites.cityRoom')" min-width="200">
          <template #default="{ row }">
            <div class="location-cell">
              <div class="location-city">{{ row.city || '—' }}</div>
              <div class="location-room">{{ row.room || '—' }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('sites.contact')" min-width="130">
          <template #default="{ row }">
            <span v-if="row.contact">{{ row.contact }}</span>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('sites.contactPhone')" min-width="150">
          <template #default="{ row }">
            <div v-if="row.contactPhone" class="phone-cell">
              <span class="phone-text">{{ row.contactPhone }}</span>
              <el-tooltip :content="t('sites.copyAction')" placement="top">
                <el-icon
                  class="copy-icon"
                  @click.stop="copyPhone(row.contactPhone)"
                >
                  <DocumentCopy />
                </el-icon>
              </el-tooltip>
            </div>
            <span v-else class="empty-placeholder">—</span>
          </template>
        </el-table-column>
        <el-table-column
          v-if="!isViewer"
          prop="circuitCountSort"
          :label="t('sites.circuitCount')"
          min-width="120"
          align="center"
          :sort-method="(a: Site, b: Site) => getCircuitCount(a.id) - getCircuitCount(b.id)"
        >
          <template #default="{ row }">
            <a
              v-if="getCircuitCount(row.id) > 0"
              class="circuit-count-link"
              :title="t('sites.viewCircuits')"
              @click.stop="goToCircuits(row.id)"
            >
              {{ getCircuitCount(row.id) }}
            </a>
            <span v-else class="empty-placeholder">{{ t('sites.notConnected') }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="status"
          :label="t('sites.status')"
          min-width="180"
          align="center"
          sortable
          :sort-method="(a: Site, b: Site) => statusOrder(a) - statusOrder(b)"
        >
          <template #default="{ row }">
            <a
              href="#"
              class="status-link"
              @click.prevent="openZabbixLink(row.id)"
            >
              <span :class="`status-dot status-${getStatusInfo(row.status, row.alertCount).type}`" />
              <span :class="`status-text status-${getStatusInfo(row.status, row.alertCount).type}`">
                {{ getStatusInfo(row.status, row.alertCount).text }}
              </span>
            </a>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer" :label="t('common.actions')" width="200" fixed="right" align="center">
          <template #default="{ row }">
            <div class="actions-cell">
              <el-button link type="primary" size="small" @click="openEditDialog(row)">
                <el-icon><Edit /></el-icon>
                {{ t('common.edit') }}
              </el-button>
              <el-dropdown trigger="click" @command="(cmd: string) => handleCommand(cmd, row)">
                <el-button link type="primary" size="small">
                  {{ t('common.more') }}
                  <el-icon><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-tooltip
                      :content="t('sites.deleteBlockedTip', { count: getCircuitCount(row.id) })"
                      :disabled="getCircuitCount(row.id) === 0"
                      placement="left"
                    >
                      <el-dropdown-item
                        command="delete"
                        :disabled="getCircuitCount(row.id) > 0"
                      >
                        <el-icon><Delete /></el-icon>
                        {{ t('common.delete') }}
                      </el-dropdown-item>
                    </el-tooltip>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
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
        <el-button @click="closeDialog">{{ t('common.cancel') }}</el-button>
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
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

.overview-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid var(--el-border-color);
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

.overview-card.disabled {
  opacity: 0.6;
  cursor: default;
}

.overview-card-total { border-left-color: var(--el-color-info-light-5); }
.overview-card-success {
  border-left-color: var(--el-color-success);
}
.overview-card-success .overview-card-value { color: var(--el-color-success); }
.overview-card-blue { border-left-color: var(--el-color-primary); }
.overview-card-warning {
  border-left-color: var(--el-color-warning);
  background: linear-gradient(135deg, var(--el-color-warning-light-9) 0%, #fff 100%);
}
.overview-card-warning .overview-card-value {
  color: var(--el-color-warning-dark-2);
}
.overview-card-danger {
  border-left-color: var(--el-color-danger);
  background: linear-gradient(135deg, var(--el-color-danger-light-9) 0%, #fff 100%);
}
.overview-card-danger .overview-card-value {
  color: var(--el-color-danger);
}

.overview-card-label {
  font-size: 13px;
  /* WCAG AA：--el-text-color-regular (#606266) 对白底约 5.9:1 */
  color: var(--el-text-color-regular);
  margin-bottom: 6px;
}

.overview-card-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
  margin-bottom: 4px;
}

.overview-card-trend {
  font-size: 12px;
  /* AA(大文字外)：--el-text-color-secondary (#909399) 对白底约 3.4:1，正文尺寸下加深到 regular */
  color: var(--el-text-color-secondary);
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

.actions-cell {
  display: inline-flex;
  align-items: center;
  gap: 12px;
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
  color: var(--el-text-color-secondary);
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

/* 空值占位：灰色居中破折号，保持行高一致 */
.empty-placeholder {
  color: var(--el-text-color-placeholder);
  font-weight: 400;
}

/* 电话号码等宽字体，数字对齐 */
.phone-text {
  font-family: var(--el-font-family-mono, 'SF Mono', Menlo, Consolas, monospace);
  color: var(--el-text-color-primary);
  font-size: 13px;
  letter-spacing: 0.3px;
}

/* 专线数量可点击链接 */
.circuit-count-link {
  color: var(--el-color-primary);
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  min-width: 24px;
  display: inline-block;
}

.circuit-count-link:hover {
  text-decoration: underline;
}

.copy-icon {
  color: var(--el-text-color-secondary);
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
  gap: 8px;
  cursor: pointer;
  color: inherit;
  text-decoration: none;
}

/* 状态圆点 */
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.status-success { background: var(--el-color-success); }
.status-dot.status-warning { background: var(--el-color-warning); }
.status-dot.status-danger { background: var(--el-color-danger); }
.status-dot.status-info { background: var(--el-color-info-light-3); }

.status-link:hover .status-text {
  text-decoration: underline;
}

.status-icon {
  font-size: 14px;
}

.status-icon.status-success {
  color: var(--el-color-success);
}

.status-icon.status-danger {
  color: var(--el-color-danger);
}

.status-icon.status-warning {
  color: var(--el-color-warning);
}

.status-icon.status-info {
  color: var(--el-color-info-light-3);
}

.status-text {
  font-size: 13px;
}

.status-text.status-success {
  color: var(--el-color-success);
}

.status-text.status-danger {
  color: var(--el-color-danger);
}

.status-text.status-warning {
  color: var(--el-color-warning-dark-2);
}

.status-text.status-info {
  color: var(--el-text-color-secondary);
}

/* 告警/离线行左侧 3px 色条 */
.sites-table :deep(.row-status-alert td.el-table__cell:first-child) {
  border-left: 3px solid var(--el-color-warning);
}

.sites-table :deep(.row-status-offline td.el-table__cell:first-child) {
  border-left: 3px solid var(--el-color-danger);
}

.sites-table :deep(.cell) {
  line-height: 1.5;
}

/* 表头加粗，与数据行区分 */
.sites-table :deep(.el-table__header .cell) {
  font-weight: 700;
  color: rgba(0, 0, 0, 0.88);
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
