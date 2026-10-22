<script setup lang="ts">
import { ref, onMounted, reactive, computed } from 'vue'
import { useAuthStore } from '../../store/auth'
import { useAppStore } from '../../store'
import { confirmAndRun } from '../../lib/confirm'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete, InfoFilled } from '@element-plus/icons-vue'
import api from '../../api/axios'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface RoleItem {
  id: number
  name: string
  display_name: string
  description: string
  is_builtin: boolean
  permissions: string[]
}

const authStore = useAuthStore()
const appStore = useAppStore()
const roles = ref<RoleItem[]>([])
const loading = ref(false)

const defaultRoles = ref([
  { id: 1, name: 'super_admin', display_name: t('system.roles.superAdmin'), description: t('system.roles.superAdminDesc'), is_builtin: true, permissions: ['all'] },
  { id: 2, name: 'engineer', display_name: t('system.roles.engineer'), description: t('system.roles.engineerDesc'), is_builtin: true, permissions: ['sites:read', 'sites:write', 'sites:delete', 'sites:export', 'circuits:read', 'circuits:write', 'circuits:delete', 'circuits:export', 'ipam:read', 'ipam:write', 'ipam:delete', 'ipam:export', 'ipam:scan_exec', 'devices:read', 'devices:write', 'devices:delete', 'devices:export', 'backups:read', 'backups:write', 'backups:delete', 'backups:export', 'backups:backup_exec', 'topology:read', 'topology:write', 'topology:delete', 'alerts:read', 'logs:read'] },
  { id: 3, name: 'viewer', display_name: t('system.roles.viewer'), description: t('system.roles.viewerDesc'), is_builtin: true, permissions: ['sites:read', 'circuits:read', 'ipam:read', 'devices:read', 'backups:read', 'topology:read', 'alerts:read', 'logs:read'] }
])

const rolePermissions = computed(() => ({
  super_admin: {
    name: t('system.roles.superAdmin'),
    description: t('system.roles.superAdminDesc'),
    permissions: [t('system.perm.userMgmt'), t('system.perm.roleMgmt'), t('system.perm.sysSettings'), t('system.perm.auditLog'), t('system.perm.dataMgmt'), t('system.perm.alertMgmt'), t('system.perm.aiConfig')],
    color: 'danger'
  },
  engineer: {
    name: t('system.roles.engineer'),
    description: t('system.roles.engineerDesc'),
    permissions: [t('system.perm.userView'), t('system.perm.auditLog'), t('system.perm.alertMgmt'), t('system.perm.deviceMgmt'), t('system.perm.networkMgmt'), t('system.perm.aiUse')],
    color: 'primary'
  },
  viewer: {
    name: t('system.roles.viewer'),
    description: t('system.roles.viewerDesc'),
    permissions: [t('system.perm.userView'), t('system.perm.auditLog'), t('system.perm.alertView'), t('system.perm.deviceView'), t('system.perm.networkView')],
    color: 'info'
  }
}))

// 可配置的权限列表（权威源为后端 Permission 表，40 项，含 display_name/description）
const availablePermissions = ref<{ key: string; name: string; description: string }[]>([])
async function loadPermissions() {
  if (!authStore.token) return
  try {
    const response = await api.get('/api/v1/permissions/permissions')
    availablePermissions.value = (response.data || []).map((p: any) => ({
      key: `${p.module}:${p.action}`,
      name: p.display_name || `${p.module}:${p.action}`,
      description: p.description || ''
    }))
  } catch (error) {
    console.error('Load permissions failed:', error)
  }
}

// 搜索与分页
const searchKeyword = ref('')
const currentPage = ref(1)
const pageSize = ref(10)
const filteredRoles = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return displayRoles.value
  return displayRoles.value.filter(r =>
    r.name.toLowerCase().includes(kw)
    || (r.display_name || '').toLowerCase().includes(kw)
    || (r.description || '').toLowerCase().includes(kw)
  )
})
const pagedRoles = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredRoles.value.slice(start, start + pageSize.value)
})

const addRoleForm = reactive({
  name: '',
  display_name: '',
  description: '',
  permissions: [] as string[]
})

const editRoleForm = reactive({
  id: 0,
  name: '',
  display_name: '',
  description: '',
  permissions: [] as string[]
})

const showAddRoleModal = ref(false)
const showEditRoleModal = ref(false)

function resetAddRoleForm() {
  addRoleForm.name = ''
  addRoleForm.display_name = ''
  addRoleForm.description = ''
  addRoleForm.permissions = []
}

async function loadRoles() {
  if (!authStore.token) return
  loading.value = true
  try {
    const response = await api.get('/api/v1/users/roles/')
    roles.value = response.data
  } catch (error: any) {
    console.error('Load roles failed:', error)
    ElMessage.error(t('system.loadRolesFailed'))
  } finally {
    loading.value = false
  }
}

async function handleAddRole() {
  if (!addRoleForm.name.trim()) { ElMessage.warning(t('system.enterRoleIdentifier')); return }
  if (!addRoleForm.display_name.trim()) { ElMessage.warning(t('system.enterRoleName')); return }
  try {
    await api.post('/api/v1/users/roles/', {
      name: addRoleForm.name,
      display_name: addRoleForm.display_name,
      description: addRoleForm.description,
      permissions: addRoleForm.permissions,
      is_builtin: false
    })
    appStore.addAuditLog({
      user: authStore.user?.username || 'system',
      action: t('system.action.createRole'),
      resource: t('system.roleManagement'),
      detail: `${t('system.action.createRole')}: ${addRoleForm.display_name} (${addRoleForm.name})`,
      ipAddress: null,
      createdAt: new Date().toISOString(),
      success: 'true'
    })
    showAddRoleModal.value = false
    resetAddRoleForm()
    await loadRoles()
    ElMessage.success(t('system.roleCreated'))
  } catch (error: any) {
    const errorMsg = error.response?.data?.detail || error.message || t('system.createFailed')
    ElMessage.error(errorMsg)
  }
}

function openEditRoleModal(role: RoleItem) {
  editRoleForm.id = role.id
  editRoleForm.name = role.name
  editRoleForm.display_name = role.display_name
  editRoleForm.description = role.description
  editRoleForm.permissions = [...(role.permissions || [])]
  showEditRoleModal.value = true
}

async function handleEditRole() {
  if (!editRoleForm.display_name.trim()) { ElMessage.warning(t('system.enterRoleName')); return }
  try {
    await api.put(`/api/v1/users/roles/${editRoleForm.id}`, {
      name: editRoleForm.name,
      display_name: editRoleForm.display_name,
      description: editRoleForm.description,
      permissions: editRoleForm.permissions
    })
    appStore.addAuditLog({
      user: authStore.user?.username || 'system',
      action: t('system.action.updateRole'),
      resource: t('system.roleManagement'),
      detail: `${t('system.action.updateRole')}: ${editRoleForm.display_name} (${editRoleForm.name})`,
      ipAddress: null,
      createdAt: new Date().toISOString(),
      success: 'true'
    })
    showEditRoleModal.value = false
    await loadRoles()
    ElMessage.success(t('system.roleUpdated'))
  } catch (error: any) {
    const errorMsg = error.response?.data?.detail || error.message || t('system.updateFailed')
    ElMessage.error(errorMsg)
  }
}

async function handleDeleteRole(roleId: number) {
  const roleToDelete = roles.value.find(r => r.id === roleId)
  // 请求分支在 action 内自理（失败文案含后端 detail），故不传 success/errorMessage
  await confirmAndRun({
    message: t('system.confirmDeleteRole'),
    title: t('system.confirmDelete'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    action: async () => {
      const response = await fetch(`/api/v1/users/roles/${roleId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${authStore.token}` }
      })
      if (response.ok) {
        appStore.addAuditLog({
          user: authStore.user?.username || 'system',
          action: t('system.action.deleteRole'),
          resource: t('system.roleManagement'),
          detail: `${t('system.action.deleteRole')}: ${roleToDelete?.display_name || roleId}`,
          ipAddress: null,
          createdAt: new Date().toISOString(),
          success: 'true'
        })
        await loadRoles()
        ElMessage.success(t('system.roleDeleted'))
      } else {
        const error = await response.json()
        ElMessage.error(`${t('system.deleteFailed')}: ${error.detail || t('system.unknownError')}`)
      }
    },
  })
}

const displayRoles = computed(() => {
  const availableRoles = roles.value.length > 0 ? roles.value : defaultRoles.value
  return availableRoles.map(role => ({
    ...role,
    display_name: role.display_name || role.name || `${t('system.role')} ${role.id}`
  }))
})

function getRoleDisplayName(roleName: string): string {
  const displayNames: Record<string, string> = {
    super_admin: t('system.roles.superAdmin'),
    engineer: t('system.roles.engineer'),
    viewer: t('system.roles.viewer'),
    admin: t('system.roles.admin')
  }
  return displayNames[roleName] || roleName
}

onMounted(() => {
  loadRoles()
  loadPermissions()
})
</script>

<template>
  <div class="role-management">
    <el-card shadow="never">
      <div class="toolbar">
        <el-input
          v-model="searchKeyword"
          :placeholder="t('system.searchRolePlaceholder')"
          clearable
          class="toolbar-search"
        />
        <el-button type="primary" @click="showAddRoleModal = true" v-permission="'system:write'">
          <Plus class="el-icon" />
          {{ t('system.addRole') }}
        </el-button>
      </div>

      <el-table class="role-management-table" :data="pagedRoles" :loading="loading" border stripe style="width: 100%;" highlight-current-row>
        <el-table-column prop="display_name" :label="t('system.roleName')" min-width="140">
          <template #default="scope">
            {{ getRoleDisplayName(scope.row.name) }}
          </template>
        </el-table-column>
        <el-table-column prop="name" :label="t('system.roleIdentifier')" min-width="120" />
        <el-table-column prop="description" :label="t('system.roleDescription')" min-width="200" />
        <el-table-column :label="t('system.builtinRole')" min-width="100">
          <template #default="scope">
            <el-tag v-if="scope.row.is_builtin" type="primary" size="small">{{ t('common.yes') }}</el-tag>
            <span v-else class="text-gray">{{ t('common.no') }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('system.permissionCount')" min-width="100">
          <template #default="scope">
            <el-tag type="info" size="small">{{ (scope.row.permissions || []).length }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="180" fixed="right">
          <template #default="scope">
            <el-button size="small" @click="openEditRoleModal(scope.row)" v-permission="'system:write'" :disabled="scope.row.is_builtin" class="action-btn">
              <Edit class="el-icon" />
              {{ t('common.edit') }}
            </el-button>
            <el-button size="small" type="danger" @click="handleDeleteRole(scope.row.id)" v-permission="'system:write'" :disabled="scope.row.is_builtin" class="action-btn">
              <Delete class="el-icon" />
              {{ t('common.delete') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && displayRoles.length === 0" :description="t('system.noRoles')" />

      <el-pagination
        v-if="filteredRoles.length > pageSize"
        class="table-pagination"
        layout="total, prev, pager, next"
        :total="filteredRoles.length"
        :current-page="currentPage"
        :page-size="pageSize"
        @current-change="(page: number) => currentPage = page"
      />
    </el-card>

    <!-- 权限边界说明 -->
    <el-card class="permission-matrix-card" shadow="never" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <InfoFilled class="el-icon" />
            {{ t('system.permissionBoundary') }}
          </div>
        </div>
      </template>
      <div class="permission-matrix">
        <div v-for="(config, roleKey) in rolePermissions" :key="roleKey" class="role-section">
          <div class="role-header">
            <el-tag :type="config.color" size="medium">{{ config.name }}</el-tag>
            <span class="role-desc">{{ config.description }}</span>
          </div>
          <div class="permission-tags">
            <el-tag v-for="(perm, idx) in config.permissions" :key="idx" size="small" effect="light" :type="config.color">
              {{ perm }}
            </el-tag>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 新增角色弹窗 -->
    <el-dialog :title="t('system.addRole')" v-model="showAddRoleModal" width="500px">
      <el-form :model="addRoleForm" label-width="100px" class="form-container">
        <el-form-item :label="t('system.roleIdentifier')" required>
          <el-input v-model="addRoleForm.name" :placeholder="t('system.enterRoleIdentifier')" />
        </el-form-item>
        <el-form-item :label="t('system.roleName')" required>
          <el-input v-model="addRoleForm.display_name" :placeholder="t('system.enterRoleName')" />
        </el-form-item>
        <el-form-item :label="t('system.roleDescription')">
          <el-input v-model="addRoleForm.description" type="textarea" :rows="3" :placeholder="t('system.enterRoleDescription')" />
        </el-form-item>
        <el-form-item :label="t('system.permissionConfig')">
          <el-checkbox-group v-model="addRoleForm.permissions">
            <el-checkbox v-for="perm in availablePermissions" :key="perm.key" :label="perm.key">
              {{ perm.name }} - {{ perm.description }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddRoleModal = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleAddRole">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <!-- 编辑角色弹窗 -->
    <el-dialog :title="t('system.editRole')" v-model="showEditRoleModal" width="500px">
      <el-form :model="editRoleForm" label-width="100px" class="form-container">
        <el-form-item :label="t('system.roleIdentifier')">
          <el-input v-model="editRoleForm.name" disabled />
        </el-form-item>
        <el-form-item :label="t('system.roleName')" required>
          <el-input v-model="editRoleForm.display_name" :placeholder="t('system.enterRoleName')" />
        </el-form-item>
        <el-form-item :label="t('system.roleDescription')">
          <el-input v-model="editRoleForm.description" type="textarea" :rows="3" :placeholder="t('system.enterRoleDescription')" />
        </el-form-item>
        <el-form-item :label="t('system.permissionConfig')">
          <el-checkbox-group v-model="editRoleForm.permissions">
            <el-checkbox v-for="perm in availablePermissions" :key="perm.key" :label="perm.key">
              {{ perm.name }} - {{ perm.description }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditRoleModal = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleEditRole">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.role-management {
  padding: 20px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #262626;
}

.card-title .el-icon {
  color: #1890ff;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.toolbar-search {
  width: 260px;
}

.table-pagination {
  margin-top: 16px;
  justify-content: flex-end;
}

.permission-matrix-card {
  border-radius: 8px;
}

.permission-matrix {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.role-section {
  padding: 16px;
  background: #f9f9f9;
  border-radius: 8px;
}

.role-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.role-desc {
  font-size: 13px;
  color: #8c8c8c;
}

.permission-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.form-container {
  padding: 20px;
}

.role-management-table :deep(.cell) {
  line-height: 1.5;
}

.role-management-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>
