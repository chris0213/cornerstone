<script setup lang="ts">import { ref, onMounted, reactive, computed } from 'vue';
import { useAuthStore } from '../../store/auth';
import { useAppStore } from '../../store';
import { ElMessage } from 'element-plus';
import { confirmAndRun } from '../../lib/confirm';
import { User, Plus, Edit, Delete, Lock, Key, Refresh, CopyDocument } from '@element-plus/icons-vue';
import api from '../../api/axios';
import { useI18n } from 'vue-i18n';
import { formatDateTime } from '../../lib/utils';

const { t } = useI18n();
interface UserItem {
 id: number;
 username: string;
 display_name: string;
 email: string;
 role: string;
 role_display_name: string;
 permissions: string[];
 is_active: boolean;
 is_superuser: boolean;
 last_login_at?: string;
 last_login_ip?: string;
 created_at?: string;
}
interface RoleItem {
 id: number;
 name: string;
 display_name: string;
 description: string;
 is_builtin: boolean;
 permissions: string[];
}
const authStore = useAuthStore();
const appStore = useAppStore();
const users = ref<UserItem[]>([]);
const roles = ref<RoleItem[]>([]);
const loading = ref(false);
// 权限配置矩阵（computed 保证语言切换时实时更新）
const rolePermissions = computed((): Record<string, { name: string; description: string; permissions: string[]; color: string }> => ({
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
}));

// 当前用户角色信息
const currentUserRoleInfo = computed(() => {
 const currentRole = authStore.user?.role;
 if (!currentRole || !rolePermissions.value[currentRole]) return null;
 const config = rolePermissions.value[currentRole];
 return {
   name: config.name,
   description: config.description,
   permissions: config.permissions,
   color: config.color
 };
});

// 默认角色数据（computed 保证语言切换时实时更新）
const defaultRoles = computed<RoleItem[]>(() => [
 { id: 1, name: 'super_admin', display_name: t('system.roles.superAdmin'), description: t('system.roles.superAdminDesc'), is_builtin: true, permissions: ['system:read', 'system:write', 'users:read', 'users:write', 'alerts:read', 'alerts:write', 'ai:config'] },
 { id: 2, name: 'engineer', display_name: t('system.roles.engineer'), description: t('system.roles.engineerDesc'), is_builtin: true, permissions: ['system:read', 'users:read', 'alerts:read', 'alerts:write', 'ai:use'] },
 { id: 3, name: 'viewer', display_name: t('system.roles.viewer'), description: t('system.roles.viewerDesc'), is_builtin: true, permissions: ['system:read', 'users:read', 'alerts:read'] }
]);

// 显示的角色（优先使用API返回的数据，否则用默认）
const displayRoles = computed(() => {
  const availableRoles = roles.value.length > 0 ? roles.value : defaultRoles.value;
  return availableRoles.map(role => {
    const displayName = role.display_name || role.name;
    const translatedName = rolePermissions.value[role.name]?.name || displayName;
    return {
      ...role,
      display_name: translatedName
    };
  });
});

// 可配置的权限列表（权威源为后端 Permission 表，40 项，含 display_name/description）
const availablePermissions = ref<{ key: string; name: string; description: string }[]>([]);
async function loadPermissions() {
  if (!authStore.token) return;
  try {
    const response = await api.get('/api/v1/permissions/permissions');
    availablePermissions.value = (response.data || []).map((p: any) => ({
      key: `${p.module}:${p.action}`,
      name: p.display_name || `${p.module}:${p.action}`,
      description: p.description || ''
    }));
  } catch (error) {
    console.error('Load permissions failed:', error);
  }
}

// 筛选与分页
const searchKeyword = ref('');
const roleFilter = ref<number | null>(null);
const currentPage = ref(1);
const pageSize = ref(10);
const filteredUsers = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase();
  return users.value.filter(u => {
    const matchKw = !kw || u.username.toLowerCase().includes(kw)
      || (u.display_name || '').toLowerCase().includes(kw)
      || (u.email || '').toLowerCase().includes(kw);
    const matchRole = !roleFilter.value || u.role
      ? roles.value.find(r => r.name === u.role)?.id === roleFilter.value
      : false;
    return matchKw && (roleFilter.value ? matchRole : true);
  });
});
const pagedUsers = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredUsers.value.slice(start, start + pageSize.value);
});
function handlePageChange(page: number) {
  currentPage.value = page;
}

// 新增用户表单
const addForm = reactive({
 username: '',
 email: '',
 password: '',
 display_name: '',
 role_id: null as number | null,
 is_active: true
});
// 编辑用户表单
const editForm = reactive({
 id: 0,
 username: '',
 email: '',
 display_name: '',
 role_id: null as number | null,
 is_active: true
});
const addRoleForm = reactive({
 name: '',
 display_name: '',
 description: '',
 permissions: [] as string[]
});
const editRoleForm = reactive({
 id: 0,
 name: '',
 display_name: '',
 description: '',
 permissions: [] as string[]
});
// 弹窗状态
const showAddModal = ref(false);
const showEditModal = ref(false);
const showResetPwdModal = ref(false);
const showSessionsModal = ref(false);
const showAddRoleModal = ref(false);
const showEditRoleModal = ref(false);
const selectedUser = ref<UserItem | null>(null);
const selectedUserId = ref<number>(0);
const selectedUsers = ref<UserItem[]>([]);
const resetPassword = ref('');
function handleSelectionChange(val: UserItem[]) {
  selectedUsers.value = val;
}
async function handleBatchDelete() {
  if (selectedUsers.value.length === 0) return;
  const deletable = selectedUsers.value.filter(u => u.id !== authStore.user?.id && !u.is_superuser);
  const skippedCount = selectedUsers.value.length - deletable.length;
  if (deletable.length === 0) {
    ElMessage.warning(t('system.batchDeleteAllSkipped'));
    return;
  }
  const names = deletable.slice(0, 5).map(u => u.username).join('、')
    + (deletable.length > 5 ? t('system.batchDeleteMoreSuffix') : '');
  await confirmAndRun({
    message: t('system.batchDeleteConfirm', { count: deletable.length, names })
      + (skippedCount > 0 ? t('system.batchDeleteSkippedSuffix', { count: skippedCount }) : ''),
    title: t('common.confirm'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    action: async () => {
      for (const user of deletable) {
        await api.delete(`/users/${user.id}`);
      }
      loadUsers();
      selectedUsers.value = [];
    },
    successMessage: t('system.deleteSuccess'),
    errorMessage: t('system.operationFailed'),
  });
}
async function loadUsers() {
 if (!authStore.token)
 return;
 loading.value = true;
 for (let i = 0; i < 3; i++) {
 try {
 const response = await api.get('/api/v1/users/');
 users.value = response.data;
 return;
 } catch (error: any) {
 const isConnectionError = error.code === 'ECONNREFUSED' || 
   error.message?.includes('ECONNREFUSED') ||
   error.errno === 'ECONNREFUSED';
 if (i < 2 && isConnectionError) {
 await new Promise(resolve => setTimeout(resolve, 1000));
 continue;
 }
 console.error('Load users failed:', error);
 ElMessage.error(t('system.loadUsersFailed'));
 }
 }
 loading.value = false;
}
async function loadRoles() {
 if (!authStore.token)
 return;
 for (let i = 0; i < 3; i++) {
 try {
 const response = await api.get('/api/v1/users/roles/');
 roles.value = response.data;
 return;
 } catch (error: any) {
 const isConnectionError = error.code === 'ECONNREFUSED' || 
 error.message?.includes('ECONNREFUSED') ||
 error.errno === 'ECONNREFUSED';
 if (i < 2 && isConnectionError) {
 await new Promise(resolve => setTimeout(resolve, 1000));
 continue;
 }
 console.error('Load roles failed:', error);
 ElMessage.error(t('system.loadRolesFailed'));
 }
 }
}
function resetAddForm() {
 addForm.username = '';
 addForm.email = '';
 addForm.password = '';
 addForm.display_name = '';
 addForm.role_id = null;
 addForm.is_active = true;
}
async function handleAddUser() {
 if (!addForm.username.trim()) {
 ElMessage.warning(t('system.enterUsername'));
 return;
 }
 if (!addForm.email.trim()) {
 ElMessage.warning(t('system.enterEmail'));
 return;
 }
 if (!addForm.password) {
 ElMessage.warning(t('system.enterPassword'));
 return;
 }
 if (!addForm.role_id) {
 ElMessage.warning(t('system.selectRole'));
 return;
 }
 try {
 await api.post('/api/v1/users/', {
 username: addForm.username,
 email: addForm.email,
 password: addForm.password,
 display_name: addForm.display_name,
 role_id: addForm.role_id,
 is_active: addForm.is_active
 });
 // 添加审计日志
 appStore.addAuditLog({
 user: authStore.user?.username || 'system',
 action: t('system.action.createUser'),
 resource: t('system.userManagement'),
 detail: `${t('system.action.createUser')}: ${addForm.username} (${addForm.email})`,
 ipAddress: null,
 createdAt: new Date().toISOString(),
 success: 'true'
 });
 showAddModal.value = false;
 resetAddForm();
 await loadUsers();
 ElMessage.success(t('system.userCreated'));
 }
 catch (error: any) {
 console.error('Add user failed:', error);
 const errorMsg = error.response?.data?.detail || error.message || t('system.createFailed');
 ElMessage.error(errorMsg);
 }
}
function openEditModal(user: UserItem) {
 editForm.id = user.id;
 editForm.username = user.username;
 editForm.email = user.email;
 editForm.display_name = user.display_name;
 editForm.role_id = roles.value.find(r => r.name === user.role)?.id || null;
 editForm.is_active = user.is_active;
 showEditModal.value = true;
}
async function handleEditUser() {
 if (!editForm.role_id) {
 ElMessage.warning(t('system.selectRole'));
 return;
 }
 try {
 await api.put(`/api/v1/users/${editForm.id}`, {
 username: editForm.username,
 email: editForm.email,
 display_name: editForm.display_name,
 role_id: editForm.role_id,
 is_active: editForm.is_active
 });
 // 添加审计日志
 appStore.addAuditLog({
 user: authStore.user?.username || 'system',
 action: t('system.action.updateUser'),
 resource: t('system.userManagement'),
 detail: `${t('system.action.updateUser')}: ${editForm.username} (${editForm.email})`,
 ipAddress: null,
 createdAt: new Date().toISOString(),
 success: 'true'
 });
 showEditModal.value = false;
 await loadUsers();
 ElMessage.success(t('system.userUpdated'));
 }
 catch (error: any) {
 console.error('Edit user failed:', error);
 const errorMsg = error.response?.data?.detail || error.message || t('system.updateFailed');
 ElMessage.error(errorMsg);
 }
}
async function handleToggleActive(user: UserItem) {
 try {
 // 后端 PATCH toggle：含自身/最后超管保护，返回更新后的用户
 const response = await api.patch(`/api/v1/users/${user.id}/toggle`);
 user.is_active = response.data.is_active;
 // 添加审计日志
 appStore.addAuditLog({
 user: authStore.user?.username || 'system',
 action: user.is_active ? t('system.action.enableUser') : t('system.action.disableUser'),
 resource: t('system.userManagement'),
 detail: `${user.is_active ? t('system.action.enable') : t('system.action.disable')}${t('system.user')}: ${user.username}`,
 ipAddress: null,
 createdAt: new Date().toISOString(),
 success: 'true'
 });
 ElMessage.success(user.is_active ? t('system.userEnabled') : t('system.userDisabled'));
 }
 catch (error: any) {
 console.error('Toggle active failed:', error);
 const errorMsg = error.response?.data?.detail || error.message || t('system.operationFailed');
 ElMessage.error(errorMsg);
 }
}
function openResetPwdModal(userId: number) {
 selectedUserId.value = userId;
 showResetPwdModal.value = true;
}
// 标记是否已重置成功（用于禁用按钮）
const hasReset = ref(false);

async function handleResetPassword() {
 if (hasReset.value) {
 ElMessage.info(t('system.pwdResetCopy'));
 return;
 }
 const userToReset = users.value.find(u => u.id === selectedUserId.value);
 try {
 const response = await api.post(`/api/v1/users/${selectedUserId.value}/reset-password`);
 resetPassword.value = response.data.new_password;
 hasReset.value = true;
 // 添加审计日志
 appStore.addAuditLog({
 user: authStore.user?.username || 'system',
 action: t('system.action.resetPwd'),
 resource: t('system.userManagement'),
 detail: `${t('system.action.resetUserPwd')}: ${userToReset?.username || selectedUserId.value}`,
 ipAddress: null,
 createdAt: new Date().toISOString(),
 success: 'true'
 });
 ElMessage.success(t('system.pwdResetSuccess'));
 }
 catch (error: any) {
 console.error('Reset password failed:', error);
 const errorMsg = error.response?.data?.detail || error.message || t('system.resetFailed');
 ElMessage.error(errorMsg);
 }
}

// 复制密码到剪贴板
async function copyPassword() {
 if (!resetPassword.value) return;
 try {
 await navigator.clipboard.writeText(resetPassword.value);
 ElMessage.success(t('system.pwdCopied'));
 } catch (error) {
 // 降级方案
 const textarea = document.createElement('textarea');
 textarea.value = resetPassword.value;
 document.body.appendChild(textarea);
 textarea.select();
 document.execCommand('copy');
 document.body.removeChild(textarea);
 ElMessage.success(t('system.pwdCopied'));
 }
}

// 关闭重置密码弹窗时重置状态
function closeResetPwdModal() {
 showResetPwdModal.value = false;
 resetPassword.value = '';
 hasReset.value = false;
}
interface SessionItem {
  id: string | number;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
  expires_at: string;
  is_revoked: boolean;
  is_current: boolean;
}
const sessions = ref<SessionItem[]>([]);
async function openSessionsModal(user: UserItem) {
  selectedUser.value = user;
  try {
    const response = await api.get(`/users/${user.id}/sessions`);
    sessions.value = response.data;
  } catch (error) {
    console.error('Load sessions failed:', error);
    sessions.value = [];
  }
  showSessionsModal.value = true;
}
async function revokeSession(sessionId: string) {
  await confirmAndRun({
    message: t('system.confirmRevokeSession'),
    title: t('system.confirmRevoke'),
    confirmText: t('system.revoke'),
    cancelText: t('common.cancel'),
    action: async () => {
      // 调后端真实吊销接口（is_revoked=True，token 立即失效）
      await api.delete(`/api/v1/users/${selectedUser.value?.id}/sessions/${sessionId}`);
      await openSessionsModal(selectedUser.value!);
    },
    successMessage: t('system.sessionRevoked'),
    errorMessage: t('system.operationFailed'),
  });
}
async function revokeAllSessions() {
  await confirmAndRun({
    message: t('system.confirmRevokeAll'),
    title: t('system.confirmRevoke'),
    confirmText: t('system.revoke'),
    cancelText: t('common.cancel'),
    action: async () => {
      // 调后端批量强制下线接口（含审计）
      await api.post(`/api/v1/users/${selectedUser.value?.id}/revoke-sessions`);
      await openSessionsModal(selectedUser.value!);
    },
    successMessage: t('system.otherSessionsRevoked'),
    errorMessage: t('system.operationFailed'),
  });
}
function getRoleType(roleName: string): string {
 const types: Record<string, string> = {
 super_admin: 'danger',
 engineer: 'primary',
 viewer: 'info'
 };
 return types[roleName] || 'info';
}
async function handleAddRole() {
 if (!addRoleForm.name.trim()) {
 ElMessage.warning(t('system.enterRoleIdentifier'));
 return;
 }
 try {
 await api.post('/api/v1/roles/', addRoleForm);
 ElMessage.success(t('system.roleCreated'));
 showAddRoleModal.value = false;
 addRoleForm.name = '';
 addRoleForm.display_name = '';
 addRoleForm.description = '';
 addRoleForm.permissions = [];
 await loadRoles();
 } catch (error: any) {
 console.error('Add role failed:', error);
 ElMessage.error(error.response?.data?.detail || t('system.createFailed'));
 }
}
async function handleEditRole() {
 try {
 await api.put(`/api/v1/roles/${editRoleForm.id}`, {
 display_name: editRoleForm.display_name,
 description: editRoleForm.description,
 permissions: editRoleForm.permissions
 });
 ElMessage.success(t('system.roleUpdated'));
 showEditRoleModal.value = false;
 await loadRoles();
 } catch (error: any) {
 console.error('Edit role failed:', error);
 ElMessage.error(error.response?.data?.detail || t('system.updateFailed'));
 }
}

// 获取角色显示名称（支持国际化）
function getRoleDisplayName(roleName: string): string {
  const displayNames: Record<string, string> = {
    super_admin: t('system.roles.superAdmin'),
    engineer: t('system.roles.engineer'),
    viewer: t('system.roles.viewer'),
    admin: t('system.roles.admin')
  };
  return displayNames[roleName] || roleName || t('system.roles.unknownRole');
}
onMounted(() => {
 loadUsers();
 loadRoles();
 loadPermissions();
});
</script>

<template>
  <div class="user-management">
    <!-- 当前用户权限提示 -->
    <el-card class="permission-tip-card" shadow="never" v-if="currentUserRoleInfo">
      <div class="permission-tip">
        <div class="tip-icon">
          <Key :class="`text-${currentUserRoleInfo.color}`" />
        </div>
        <div class="tip-content">
          <div class="tip-title">{{ t('system.currentRole') }}: {{ currentUserRoleInfo.name }}</div>
          <div class="tip-desc">{{ currentUserRoleInfo.description }}</div>
        </div>
        <el-tag :type="currentUserRoleInfo.color" size="small">{{ currentUserRoleInfo.name }}</el-tag>
      </div>
    </el-card>

    <!-- 用户操作栏 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-title">
          <User class="el-icon" />
          {{ t('system.userManagement') }}
        </div>
      </template>
        <div class="toolbar">
          <el-input
            v-model="searchKeyword"
            :placeholder="t('system.searchUserPlaceholder')"
            clearable
            class="toolbar-search"
          />
          <el-select
            v-model="roleFilter"
            :placeholder="t('system.allRoles')"
            clearable
            class="toolbar-role-filter"
          >
            <el-option
              v-for="role in displayRoles"
              :key="role.id"
              :value="role.id"
              :label="role.display_name"
            />
          </el-select>
          <el-button
            type="primary"
            @click="showAddModal = true"
            v-permission="'system:write'"
          >
            <Plus class="el-icon" />
            {{ t('system.addUser') }}
          </el-button>
          <el-button
            type="danger"
            @click="handleBatchDelete"
            v-permission="'system:write'"
            :disabled="selectedUsers.length === 0"
          >
            <Delete class="el-icon" />
            {{ t('common.delete') }}
          </el-button>
        </div>

    <!-- 用户列表表格 -->
    <el-table
      class="user-management-table"
      :data="pagedUsers"
      :loading="loading"
      border
      stripe
      style="width: 100%;"
      highlight-current-row
      @selection-change="handleSelectionChange"
    >
      <el-table-column type="selection" width="55" />
      <el-table-column prop="username" :label="t('system.userName')" min-width="140">
        <template #default="scope">
          <div class="user-cell">
            <div class="avatar-wrapper">
              <User class="avatar-icon" />
            </div>
            <div class="user-info">
              <span class="user-name">{{ scope.row.username }}</span>
              <span class="user-email">{{ scope.row.email }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="display_name" :label="t('system.userDisplayName')" min-width="120" />
      <el-table-column :label="t('system.userRole')" min-width="120">
        <template #default="scope">
          <el-tag 
            :type="getRoleType(scope.row.role)"
            size="small"
          >
            {{ scope.row.role_display_name || getRoleDisplayName(scope.row.role) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('system.userStatus')" min-width="100">
        <template #default="scope">
          <el-switch 
            :model-value="scope.row.is_active" 
            v-permission="'system:write'"
            @change="handleToggleActive(scope.row)"
          />
        </template>
      </el-table-column>
      <el-table-column :label="t('system.superAdmin')" min-width="100">
        <template #default="scope">
          <el-tag v-if="scope.row.is_superuser" type="danger" size="small">{{ t('common.yes') }}</el-tag>
          <span v-else class="text-gray">{{ t('common.no') }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('system.lastLogin')" min-width="180">
        <template #default="scope">
          <div v-if="scope.row.last_login_at" class="last-login">
            <div>{{ formatDateTime(scope.row.last_login_at) }}</div>
            <div class="login-ip">{{ scope.row.last_login_ip }}</div>
          </div>
          <span v-else class="text-gray">{{ t('system.neverLoggedIn') }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="320" fixed="right">
        <template #default="scope">
          <div class="action-buttons">
            <el-button 
              size="small" 
              @click="openEditModal(scope.row)"
              v-permission="'system:write'"
              class="action-btn"
            >
              <Edit class="el-icon" />
              {{ t('common.edit') }}
            </el-button>
            <el-button 
              size="small" 
              @click="openResetPwdModal(scope.row.id)"
              v-permission="'system:write'"
              class="action-btn"
            >
              <Key class="el-icon" />
              {{ t('system.resetPassword') }}
            </el-button>
            <el-button 
              size="small" 
              @click="openSessionsModal(scope.row)"
              v-permission="'system:write'"
              class="action-btn"
            >
              <Refresh class="el-icon" />
              {{ t('system.sessions') }}
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && users.length === 0" :description="t('system.noUsers')" />

    <el-pagination
      v-if="filteredUsers.length > pageSize"
      class="table-pagination"
      layout="total, sizes, prev, pager, next"
      :total="filteredUsers.length"
      :current-page="currentPage"
      :page-size="pageSize"
      :page-sizes="[10, 20, 50]"
      @current-change="handlePageChange"
      @size-change="(size: number) => { pageSize = size; currentPage = 1 }"
    />
    </el-card>

    <!-- 新增用户弹窗 -->
    <el-dialog 
      :title="t('system.addUser')" 
      v-model="showAddModal"
      width="500px"
    >
      <el-form :model="addForm" label-width="100px" class="form-container">
        <el-form-item :label="t('system.userName')" required>
          <el-input 
            v-model="addForm.username" 
            :placeholder="t('system.enterUsername')"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item :label="t('system.userEmail')" required>
          <el-input 
            v-model="addForm.email" 
            type="email" 
            :placeholder="t('system.enterEmail')"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item :label="t('system.password')" required>
          <el-input 
            v-model="addForm.password" 
            type="password" 
            :placeholder="t('system.enterPassword')"
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item :label="t('system.userDisplayName')">
          <el-input 
            v-model="addForm.display_name" 
            :placeholder="t('system.enterDisplayName')"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item :label="t('system.userRole')" required>
          <el-select 
            v-model="addForm.role_id" 
            :placeholder="t('system.selectRole')"
            class="w-full"
          >
            <el-option 
              v-for="role in displayRoles" 
              :key="role.id" 
              :value="role.id" 
              :label="role.display_name"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.userStatus')">
          <el-switch v-model="addForm.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddModal = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleAddUser">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <!-- 编辑用户弹窗 -->
    <el-dialog 
      :title="t('system.editUser')" 
      v-model="showEditModal"
      width="500px"
    >
      <el-form :model="editForm" label-width="100px" class="form-container">
        <el-form-item :label="t('system.userName')">
          <el-input v-model="editForm.username" disabled />
        </el-form-item>
        <el-form-item :label="t('system.userEmail')">
          <el-input 
            v-model="editForm.email" 
            type="email" 
            :placeholder="t('system.enterEmail')"
          />
        </el-form-item>
        <el-form-item :label="t('system.userDisplayName')">
          <el-input 
            v-model="editForm.display_name" 
            :placeholder="t('system.enterDisplayName')"
          />
        </el-form-item>
        <el-form-item :label="t('system.userRole')" required>
          <el-select 
            v-model="editForm.role_id" 
            :placeholder="t('system.selectRole')"
            class="w-full"
          >
            <el-option 
              v-for="role in displayRoles" 
              :key="role.id" 
              :value="role.id" 
              :label="role.display_name"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.userStatus')">
          <el-switch v-model="editForm.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditModal = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleEditUser">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码弹窗 -->
    <el-dialog 
      :title="t('system.resetPassword')" 
      v-model="showResetPwdModal"
      width="450px"
      @close="closeResetPwdModal"
    >
      <div class="reset-pwd-content">
        <p v-if="!hasReset">{{ t('system.confirmResetPassword') }}</p>
        <div v-if="resetPassword" class="new-password">
          <div class="password-header">
            <span class="label">{{ t('system.newPassword') }}：</span>
            <el-button 
              size="small" 
              type="success" 
              @click="copyPassword"
              class="copy-btn"
            >
              <CopyDocument class="el-icon" />
              {{ t('common.copy') }}
            </el-button>
          </div>
          <div class="password-display">
            <span class="password-text">{{ resetPassword }}</span>
          </div>
          <p class="password-tip">{{ t('system.passwordTip') }}</p>
        </div>
      </div>
      <template #footer>
        <el-button @click="closeResetPwdModal">{{ t('common.close') }}</el-button>
        <el-button 
          type="primary" 
          @click="handleResetPassword"
          :disabled="hasReset"
        >
          {{ hasReset ? t('system.alreadyReset') : t('system.confirmReset') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 会话管理弹窗 -->
    <el-dialog 
      :title="t('system.sessions') + ' - ' + selectedUser?.username" 
      v-model="showSessionsModal"
      width="600px"
    >
      <div class="sessions-content">
        <el-button 
          size="small" 
          type="danger"
          @click="revokeAllSessions"
          class="revoke-all-btn"
        >
          <Lock class="el-icon" />
          {{ t('system.revokeAllSessions') }}
        </el-button>
        <el-table class="user-sessions-table" :data="sessions" border style="width: 100%; margin-top: 16px;">
          <el-table-column prop="ip_address" :label="t('system.ipAddress')" min-width="120" />
          <el-table-column prop="user_agent" :label="t('system.device')" min-width="200" />
          <el-table-column prop="created_at" :label="t('system.loginTime')" min-width="160">
            <template #default="scope">{{ formatDateTime(scope.row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="expires_at" :label="t('system.expireTime')" min-width="160">
            <template #default="scope">{{ formatDateTime(scope.row.expires_at) }}</template>
          </el-table-column>
          <el-table-column :label="t('system.userStatus')" min-width="80">
            <template #default="scope">
              <el-tag v-if="scope.row.is_revoked" type="danger" size="small">{{ t('system.revoked') }}</el-tag>
              <span v-else class="text-gray">{{ t('system.active') }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" min-width="100">
            <template #default="scope">
              <el-button 
                size="small" 
                type="danger"
                @click="revokeSession(String(scope.row.id))"
                :disabled="scope.row.is_revoked"
              >
                {{ t('system.revoke') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="showSessionsModal = false">{{ t('common.close') }}</el-button>
      </template>
    </el-dialog>

    <!-- 新增角色弹窗 -->
    <el-dialog 
      :title="t('system.addRole')" 
      v-model="showAddRoleModal"
      width="600px"
    >
      <el-form :model="addRoleForm" label-width="120px" class="form-container">
        <el-form-item :label="t('system.roleIdentifier')" required>
          <el-input 
            v-model="addRoleForm.name" 
            :placeholder="t('system.enterRoleIdentifier')"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item :label="t('system.roleName')" required>
          <el-input 
            v-model="addRoleForm.display_name" 
            :placeholder="t('system.enterRoleName')"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item :label="t('system.roleDescription')">
          <el-input 
            v-model="addRoleForm.description" 
            :placeholder="t('system.enterRoleDescription')"
            type="textarea"
            :rows="2"
          />
        </el-form-item>
        <el-form-item :label="t('system.permissionConfig')">
          <el-checkbox-group v-model="addRoleForm.permissions">
            <div class="permission-grid">
              <el-checkbox 
                v-for="perm in availablePermissions" 
                :key="perm.key" 
                :label="perm.key"
              >
                <span class="perm-name">{{ perm.name }}</span>
                <span class="perm-desc">{{ perm.description }}</span>
              </el-checkbox>
            </div>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddRoleModal = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleAddRole">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <!-- 编辑角色弹窗 -->
    <el-dialog 
      :title="t('system.editRole')" 
      v-model="showEditRoleModal"
      width="600px"
    >
      <el-form :model="editRoleForm" label-width="120px" class="form-container">
        <el-form-item :label="t('system.roleIdentifier')">
          <el-input v-model="editRoleForm.name" disabled />
        </el-form-item>
        <el-form-item :label="t('system.roleName')" required>
          <el-input 
            v-model="editRoleForm.display_name" 
            :placeholder="t('system.enterRoleName')"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item :label="t('system.roleDescription')">
          <el-input 
            v-model="editRoleForm.description" 
            :placeholder="t('system.enterRoleDescription')"
            type="textarea"
            :rows="2"
          />
        </el-form-item>
        <el-form-item :label="t('system.permissionConfig')">
          <el-checkbox-group v-model="editRoleForm.permissions">
            <div class="permission-grid">
              <el-checkbox 
                v-for="perm in availablePermissions" 
                :key="perm.key" 
                :label="perm.key"
              >
                <span class="perm-name">{{ perm.name }}</span>
                <span class="perm-desc">{{ perm.description }}</span>
              </el-checkbox>
            </div>
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
.user-management {
  padding: 16px 0;
}

/* 当前用户权限提示卡片 */
.permission-tip-card {
  margin-bottom: 16px;
  background: linear-gradient(135deg, #f0f5ff 0%, #fff 100%);
  border: 1px solid #e8f0fe;
}

.permission-tip {
  display: flex;
  align-items: center;
  gap: 12px;
}

.tip-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: rgba(64, 158, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.tip-content {
  flex: 1;
}

.tip-title {
  font-weight: 600;
  color: #262626;
  margin-bottom: 4px;
}

.tip-desc {
  font-size: 13px;
  color: #8c8c8c;
}

.toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 4px;
  margin-bottom: 16px;
}

.toolbar-search {
  width: 220px;
  margin-right: 4px;
}

.toolbar-role-filter {
  width: 160px;
  margin-right: 4px;
}

.table-pagination {
  margin-top: 16px;
  justify-content: flex-end;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.avatar-wrapper {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-icon {
  font-size: 18px;
  color: white;
}

.user-info {
  display: flex;
  flex-direction: column;
}

.user-name {
  font-weight: 500;
  color: #303133;
}

.user-email {
  font-size: 12px;
  color: #909399;
}

.text-gray {
  color: #909399;
}

.last-login {
  display: flex;
  flex-direction: column;
  font-size: 13px;
}

.login-ip {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.action-btn {
  margin-right: 4px;
  white-space: nowrap;
}

.form-container {
  padding-top: 10px;
}

.w-full {
  width: 100%;
}

.reset-pwd-content {
  padding: 20px 0;
}

.reset-pwd-content p {
  margin: 0 0 20px 0;
  color: #606266;
}

.new-password {
  margin-top: 16px;
}

.password-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.password-header .label {
  font-size: 14px;
  color: #606266;
  font-weight: 500;
}

.copy-btn {
  margin-left: auto;
}

.password-display {
  padding: 16px;
  background: #f5f7fa;
  border-radius: 8px;
  border: 1px dashed #d9d9d9;
}

.password-text {
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 16px;
  color: #409eff;
  font-weight: 600;
  letter-spacing: 2px;
}

.password-tip {
  margin-top: 12px;
  font-size: 13px;
  color: #909399;
  text-align: center;
}

.sessions-content {
  padding-top: 10px;
}

.revoke-all-btn {
  margin-bottom: 16px;
}

/* Tab切换样式 */
.main-tabs {
  margin-bottom: 16px;
}

/* 权限选择网格 */
.permission-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.perm-name {
  display: block;
  font-weight: 500;
  color: #303133;
}

.perm-desc {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.user-management-table :deep(.cell),
.user-sessions-table :deep(.cell) {
  line-height: 1.5;
  white-space: nowrap;
}

.user-management-table :deep(.el-table__cell),
.user-sessions-table :deep(.el-table__cell) {
  padding: 8px 12px;
  overflow: visible;
}
</style>
