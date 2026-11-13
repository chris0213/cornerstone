<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, OfficeBuilding } from '@element-plus/icons-vue'
import api from '../../api/axios'
import { formatDateTime } from '../../lib/utils'

const { t } = useI18n()

interface TenantItem {
  id: number
  code: string
  name: string
  status: string
  plan: string
  description?: string | null
  created_at?: string | null
  user_count: number
  is_default: boolean
}

const tenants = ref<TenantItem[]>([])
const loading = ref(false)
const showCreate = ref(false)
const saving = ref(false)
const form = ref({ code: '', name: '', plan: 'standard', description: '' })

async function loadTenants() {
  loading.value = true
  try {
    const resp = await api.get('/api/v1/tenants/')
    tenants.value = resp.data || []
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || t('tenants.loadFailed'))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { code: '', name: '', plan: 'standard', description: '' }
  showCreate.value = true
}

async function handleCreate() {
  if (!form.value.code.trim()) {
    ElMessage.warning(t('tenants.codeRequired'))
    return
  }
  if (!form.value.name.trim()) {
    ElMessage.warning(t('tenants.nameRequired'))
    return
  }
  saving.value = true
  try {
    await api.post('/api/v1/tenants/', {
      code: form.value.code.trim(),
      name: form.value.name.trim(),
      plan: form.value.plan || 'standard',
      description: form.value.description || null,
    })
    showCreate.value = false
    ElMessage.success(t('tenants.createSuccess'))
    await loadTenants()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || t('tenants.createFailed'))
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: TenantItem) {
  const target = row.status === 'active' ? 'suspended' : 'active'
  try {
    await ElMessageBox.confirm(
      target === 'suspended'
        ? t('tenants.disableConfirm', { name: row.name })
        : t('tenants.enableConfirm', { name: row.name }),
      t('tenants.statusLabel'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
    )
  } catch {
    return
  }
  try {
    await api.put(`/api/v1/tenants/${row.id}/status`, { status: target })
    ElMessage.success(t('tenants.statusUpdated'))
    await loadTenants()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || t('tenants.updateFailed'))
  }
}

onMounted(loadTenants)
</script>

<template>
  <div class="tenant-management">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <OfficeBuilding class="el-icon" />
            {{ t('tenants.title') }}
          </div>
          <div class="header-actions">
            <el-button @click="loadTenants" :loading="loading">
              <Refresh class="el-icon" />
              {{ t('common.refresh') }}
            </el-button>
            <el-button type="primary" @click="openCreate">
              <Plus class="el-icon" />
              {{ t('tenants.create') }}
            </el-button>
          </div>
        </div>
        <p class="card-desc">{{ t('tenants.description') }}</p>
      </template>

      <el-table :data="tenants" :loading="loading" border stripe style="width: 100%">
        <el-table-column prop="code" :label="t('tenants.code')" min-width="180">
          <template #default="scope">
            <span>{{ scope.row.code }}</span>
            <el-tag v-if="scope.row.is_default" size="small" type="info" class="default-tag">
              {{ t('tenants.defaultTenant') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" :label="t('tenants.name')" min-width="180" />
        <el-table-column prop="status" :label="t('tenants.statusLabel')" min-width="110">
          <template #default="scope">
            <el-tag :type="scope.row.status === 'active' ? 'success' : 'danger'" size="small">
              {{ scope.row.status === 'active' ? t('tenants.active') : t('tenants.suspended') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="user_count" :label="t('tenants.userCount')" min-width="100" />
        <el-table-column prop="created_at" :label="t('tenants.createdAt')" min-width="170">
          <template #default="scope">
            {{ scope.row.created_at ? formatDateTime(scope.row.created_at) : '-' }}
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" min-width="140">
          <template #default="scope">
            <el-button
              size="small"
              :type="scope.row.status === 'active' ? 'danger' : 'success'"
              :disabled="scope.row.is_default"
              @click="toggleStatus(scope.row)"
            >
              {{ scope.row.status === 'active' ? t('tenants.disable') : t('tenants.enable') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" :title="t('tenants.create')" width="520px">
      <el-form :model="form" label-width="110px" class="tenant-form">
        <el-form-item :label="t('tenants.code')" required>
          <el-input v-model="form.code" :placeholder="t('tenants.codePlaceholder')" autocomplete="off" />
        </el-form-item>
        <el-form-item :label="t('tenants.name')" required>
          <el-input v-model="form.name" :placeholder="t('tenants.namePlaceholder')" autocomplete="off" />
        </el-form-item>
        <el-form-item :label="t('tenants.plan')">
          <el-input v-model="form.plan" />
        </el-form-item>
        <el-form-item :label="t('tenants.descriptionLabel')">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleCreate">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tenant-management {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.card-desc {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.default-tag {
  margin-left: 8px;
}
</style>
