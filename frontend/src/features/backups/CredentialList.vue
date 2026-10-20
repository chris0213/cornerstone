<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { getCredentials, createCredential, updateCredential, deleteCredential, testCredential } from '@/api/backups'
import { confirmAndRun } from '@/lib/confirm'
import { resolveErrorMessage, extractErrorDetail } from '@/lib/apiError'
import type { Credential } from '@/types/domain'
import { formatDateTime } from '@/lib/utils'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const credentials = ref<Credential[]>([])
const loading = ref(false)
const showDialog = ref(false)
const showTestDialog = ref(false)
const editingCredential = ref<Credential | null>(null)
const testingCredential = ref<Credential | null>(null)
const testing = ref(false)
const testIp = ref('')
const testResult = ref<{
  success: boolean
  message: string
  durationMs: number
  vendor?: string
  defaultsApplied?: string[]
} | null>(null)
const selectedCredentialIds = ref<number[]>([])

// 搜索 / 协议筛选 / 客户端分页
const searchText = ref('')
const protocolFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

const form = ref({
  name: '',
  deviceId: '',
  protocol: 'ssh',
  port: 22,
  username: '',
  password: '',
  enablePassword: '',
  authType: 'password',
  privateKey: '',
  jumpHost: '',
  jumpPort: 22,
  jumpUsername: '',
  jumpPassword: '',
  description: '',
})

const protocolOptions = [
  { value: 'ssh', label: 'SSH' },
  { value: 'telnet', label: 'Telnet' },
]

const authTypeOptions = computed(() => [
  { value: 'password', label: t('backups.authPassword') },
  { value: 'key', label: t('backups.authKey') },
])

const filteredCredentials = computed(() => {
  const kw = searchText.value.trim().toLowerCase()
  return credentials.value.filter((c) => {
    if (protocolFilter.value && c.protocol !== protocolFilter.value) return false
    if (kw && !c.name.toLowerCase().includes(kw) && !c.username.toLowerCase().includes(kw)) return false
    return true
  })
})

const pagedCredentials = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredCredentials.value.slice(start, start + pageSize.value)
})

// 「使用情况」列 tooltip：任务名以「、」拼接
function usageTooltip(row: Credential): string {
  return (row.usedByTasks || []).map((task) => task.name).join('、')
}

function resetForm() {
  form.value = {
    name: '',
    deviceId: '',
    protocol: 'ssh',
    port: 22,
    username: '',
    password: '',
    enablePassword: '',
    authType: 'password',
    privateKey: '',
    jumpHost: '',
    jumpPort: 22,
    jumpUsername: '',
    jumpPassword: '',
    description: '',
  }
  editingCredential.value = null
}

function openCreateDialog() {
  resetForm()
  showDialog.value = true
}

function openEditDialog(credential: Credential) {
  editingCredential.value = credential
  form.value = {
    name: credential.name,
    deviceId: credential.deviceId?.toString() || '',
    protocol: credential.protocol,
    port: credential.port,
    username: credential.username,
    // R10：敏感字段一律留空表示不修改，不回填掩码或明文
    password: '',
    enablePassword: '',
    authType: credential.authType,
    privateKey: '',
    jumpHost: credential.jumpHost || '',
    jumpPort: credential.jumpPort,
    jumpUsername: credential.jumpUsername || '',
    jumpPassword: '',
    description: credential.description || '',
  }
  showDialog.value = true
}

function closeDialog() {
  showDialog.value = false
  resetForm()
}

async function handleSave() {
  if (!form.value.name) {
    ElMessage.error(t('validation.required'))
    return
  }
  if (!form.value.username) {
    ElMessage.error(t('validation.usernameRequired'))
    return
  }
  if (!editingCredential.value && !form.value.password) {
    ElMessage.error(t('validation.passwordRequired'))
    return
  }

  try {
    const data: any = {
      name: form.value.name,
      protocol: form.value.protocol,
      port: form.value.port,
      username: form.value.username,
      authType: form.value.authType,
      jumpPort: form.value.jumpPort,
      description: form.value.description,
    }

    if (form.value.deviceId) {
      data.deviceId = parseInt(form.value.deviceId)
    }
    // 留空 = 不修改（API 层会剔除空值字段）
    if (form.value.password) data.password = form.value.password
    if (form.value.enablePassword) data.enablePassword = form.value.enablePassword
    if (form.value.privateKey) data.privateKey = form.value.privateKey
    if (form.value.jumpHost) {
      data.jumpHost = form.value.jumpHost
    }
    if (form.value.jumpUsername) {
      data.jumpUsername = form.value.jumpUsername
    }
    if (form.value.jumpPassword) data.jumpPassword = form.value.jumpPassword

    if (editingCredential.value) {
      await updateCredential(parseInt(editingCredential.value.id), data)
      ElMessage.success(t('backups.updateSuccess'))
    } else {
      await createCredential(data)
      ElMessage.success(t('backups.createSuccess'))
    }
    await loadCredentials()
    closeDialog()
  } catch (error: any) {
    console.error('保存凭证失败:', error?.message)
    ElMessage.error(resolveErrorMessage(error, 'backups.saveFailed'))
  }
}

/** 删除被引用凭证的 409 拦截弹窗 */
function showInUseBlocked(error: unknown) {
  const detail = extractErrorDetail(error)
  let taskNames: string[] = []
  if (detail && typeof detail === 'object') {
    const tasks = (detail.params as { tasks?: { name: string }[] } | undefined)?.tasks
    taskNames = tasks?.map((task) => task.name) ?? []
  }
  const message = taskNames.length
    ? t('backups.credentialErrors.inUse', { count: taskNames.length, tasks: taskNames.join('、') })
    : t('backups.deleteBlocked')
  ElMessageBox.alert(message, t('backups.cannotDeleteTitle'), {
    type: 'warning',
    confirmButtonText: t('backups.okBtn'),
  })
}

async function handleDelete(credential: Credential) {
  await confirmAndRun({
    message: t('backups.confirmDelete', { name: credential.name }),
    title: t('backups.deleteTitle'),
    confirmText: t('common.confirmDelete'),
    cancelText: t('common.cancel'),
    danger: true,
    action: async () => {
      await deleteCredential(parseInt(credential.id))
      await loadCredentials()
    },
    successMessage: t('backups.deleteSuccess'),
    errorMessage: (error) => {
      // 409：被备份任务引用，弹拦截框说明
      if ((error as { response?: { status?: number } })?.response?.status === 409) {
        showInUseBlocked(error)
        return ''
      }
      return resolveErrorMessage(error, 'backups.deleteFailed')
    },
  })
}

// 处理选择变化
const handleSelectionChange = (val: any[]) => {
  selectedCredentialIds.value = val.map(item => parseInt(item.id))
}

// 批量删除
async function handleBatchDelete() {
  await confirmAndRun({
    message: t('backups.confirmBatchDelete', { count: selectedCredentialIds.value.length }),
    title: t('backups.batchDeleteTitle'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    danger: true,
    action: async () => {
      // 逐个删除（可以优化为批量API）
      for (const id of selectedCredentialIds.value) {
        await deleteCredential(id)
      }
      selectedCredentialIds.value = []
      await loadCredentials()
    },
    successMessage: t('backups.batchDeleteSuccess', { count: selectedCredentialIds.value.length }),
    errorMessage: (error) => {
      if ((error as { response?: { status?: number } })?.response?.status === 409) {
        showInUseBlocked(error)
        return ''
      }
      return resolveErrorMessage(error, 'backups.batchDeleteFailed')
    },
  })
}

function openTestDialog(credential: Credential) {
  testingCredential.value = credential
  testIp.value = ''
  testResult.value = null
  showTestDialog.value = true
}

async function handleTest() {
  if (!testIp.value) {
    ElMessage.error(t('validation.testIpRequired'))
    return
  }
  const credential = testingCredential.value
  if (!credential || testing.value) return

  // 测试前确认：告知将真实登录目标设备
  try {
    await ElMessageBox.confirm(
      t('backups.testConfirm', { ip: testIp.value }),
      t('backups.testConfirmTitle'),
      {
        confirmButtonText: t('backups.testConfirmBtn'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      }
    )
  } catch {
    return
  }

  testing.value = true
  try {
    testResult.value = await testCredential(parseInt(credential.id), testIp.value)
    if (testResult.value.success) {
      ElMessage.success(t('backups.testSuccess', { ms: testResult.value.durationMs }))
    } else {
      // telnet 凭证测试失败：附加厂商可能不支持 Telnet 的提示
      const baseMsg = testResult.value.message || t('backups.testFailed')
      const failMsg = credential.protocol === 'telnet'
        ? `${baseMsg}；${t('backups.telnetFailHint')}`
        : baseMsg
      ElMessage.error(failMsg)
    }
  } catch (error: any) {
    console.error('测试连接失败:', error?.message)
    ElMessage.error(resolveErrorMessage(error, 'backups.testFailed'))
  } finally {
    testing.value = false
  }
}

async function loadCredentials() {
  loading.value = true
  try {
    credentials.value = await getCredentials()
  } catch (error: any) {
    console.error('加载凭证列表失败:', error?.message)
    ElMessage.error(resolveErrorMessage(error, 'backups.loadCredentialsFailed'))
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
}

function handleFilterChange() {
  currentPage.value = 1
}

function onRowCommand(command: string, credential: Credential) {
  if (command === 'delete') handleDelete(credential)
}

onMounted(() => {
  loadCredentials()
})
</script>

<template>
  <div class="credential-list-page">
    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <div class="card-title">
            <el-icon><Key /></el-icon>
            {{ t('backups.credentials') }}
          </div>
          <div class="table-actions">
            <el-input
              v-model="searchText"
              class="search-input"
              :placeholder="t('backups.searchPlaceholder')"
              clearable
              :prefix-icon="Search"
              @input="handleSearch"
            />
            <el-select
              v-model="protocolFilter"
              class="protocol-filter"
              :placeholder="t('backups.protocolFilterAll')"
              clearable
              @change="handleFilterChange"
            >
              <el-option
                v-for="opt in protocolOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
            <el-button
              v-if="selectedCredentialIds.length > 0"
              type="danger"
              @click="handleBatchDelete"
            >
              <el-icon><Delete /></el-icon>
              {{ t('backups.batchDelete') }} ({{ selectedCredentialIds.length }})
            </el-button>
            <el-button type="primary" @click="openCreateDialog">
              <el-icon><Plus /></el-icon>
              {{ t('backups.addCredential') }}
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        class="credential-table"
        :data="pagedCredentials"
        style="width: 100%"
        stripe
        border
        v-loading="loading"
        height="calc(100vh - 280px)"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column prop="name" :label="t('backups.nameColumn')" min-width="150">
          <template #default="{ row }">
            <div class="credential-name">
              <el-icon class="cred-icon"><Key /></el-icon>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="protocol" :label="t('backups.protocolPortColumn')" min-width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.protocol === 'ssh' ? 'success' : 'warning'" size="small">
              {{ row.protocol?.toUpperCase() }}:{{ row.port }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="username" :label="t('backups.usernameColumn')" min-width="120">
          <template #default="{ row }">{{ row.username }}</template>
        </el-table-column>
        <el-table-column prop="password" :label="t('backups.passwordColumn')" min-width="100" align="center">
          <template #default>
            <span class="password-masked">********</span>
          </template>
        </el-table-column>
        <el-table-column prop="jumpHost" :label="t('backups.jumpHost')" min-width="150">
          <template #default="{ row }">
            <span v-if="row.jumpHost">{{ row.jumpHost }}:{{ row.jumpPort }}</span>
            <span v-else class="text-muted">{{ t('backups.portEmpty') }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="authType" :label="t('backups.authTypeColumn')" min-width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.authType === 'key' ? 'info' : 'primary'" size="small">
              {{ row.authType === 'key' ? t('backups.authTypeKey') : t('backups.authTypePassword') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="usedByCount" :label="t('backups.usageColumn')" min-width="110" align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.usedByCount > 0"
              :content="usageTooltip(row)"
              placement="top"
            >
              <el-tag type="info" size="small">
                {{ t('backups.usedByTasks', { count: row.usedByCount }) }}
              </el-tag>
            </el-tooltip>
            <span v-else class="text-muted">{{ t('backups.notReferenced') }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="lastTestedAt" :label="t('backups.lastTestColumn')" min-width="150">
          <template #default="{ row }">
            <template v-if="row.lastTestedAt">
              <span class="test-status-dot" :class="row.lastTestStatus === 'success' ? 'is-success' : 'is-failed'" />
              <span class="last-test-text">{{ formatDateTime(row.lastTestedAt) }}</span>
            </template>
            <span v-else class="text-muted">{{ t('backups.neverTested') }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="200" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openTestDialog(row)">
              <el-icon><Connection /></el-icon>
              {{ t('backups.testConnection') }}
            </el-button>
            <el-button link type="primary" size="small" @click="openEditDialog(row)">
              <el-icon><Edit /></el-icon>
              {{ t('common.edit') }}
            </el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => onRowCommand(cmd, row)">
              <el-button link type="primary" size="small" class="more-trigger">
                {{ t('backups.moreActions') }}
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="delete" class="danger-item">
                    <el-icon><Delete /></el-icon>
                    {{ t('common.delete') }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <span class="total-text">{{ t('backups.totalCount', { count: filteredCredentials.length }) }}</span>
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="filteredCredentials.length"
          :page-sizes="[10, 20, 50]"
          layout="sizes, prev, pager, next, jumper"
          background
        />
      </div>

      <el-empty v-if="filteredCredentials.length === 0 && !loading" :description="t('backups.noCredentials')" />
    </el-card>

    <!-- 新建/编辑凭证对话框 -->
    <el-dialog
      v-model="showDialog"
      :title="editingCredential ? t('backups.editDialogTitle') : t('backups.addDialogTitle')"
      width="700px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item :label="t('backups.nameColumn')" required>
          <el-input v-model="form.name" :placeholder="t('backups.namePlaceholder')" />
        </el-form-item>

        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item :label="t('monitor.protocol')">
              <el-select v-model="form.protocol" style="width: 100%">
                <el-option v-for="opt in protocolOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="t('backups.portLabel')">
              <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="t('backups.authType')">
              <el-select v-model="form.authType" style="width: 100%">
                <el-option v-for="opt in authTypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="t('backups.usernameColumn')" required>
              <el-input v-model="form.username" :placeholder="t('backups.usernamePlaceholder')" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="editingCredential ? t('backups.passwordLabelEdit') : t('backups.password')" :required="!editingCredential">
              <el-input
                v-model="form.password"
                type="password"
                show-password
                :placeholder="editingCredential ? t('backups.passwordPlaceholderEdit') : t('backups.passwordPlaceholderNew')"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="t('backups.enablePassword')">
              <el-input
                v-model="form.enablePassword"
                type="password"
                show-password
                :placeholder="editingCredential ? t('backups.passwordPlaceholderEdit') : t('backups.enablePasswordPlaceholder')"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('backups.privateKey')" v-if="form.authType === 'key'">
              <el-input
                v-model="form.privateKey"
                type="textarea"
                :rows="3"
                :placeholder="editingCredential ? t('backups.passwordPlaceholderEdit') : t('backups.privateKeyPlaceholder')"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">
          <span class="divider-text">{{ t('backups.jumpSection') }}</span>
        </el-divider>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="t('backups.jumpHostIpLabel')">
              <el-input v-model="form.jumpHost" :placeholder="t('backups.jumpHostIpPlaceholder')" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('backups.jumpHostPortLabel')">
              <el-input-number v-model="form.jumpPort" :min="1" :max="65535" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="t('backups.jumpHostUserLabel')">
              <el-input v-model="form.jumpUsername" :placeholder="t('backups.jumpHostUserPlaceholder')" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('backups.jumpHostPassword')">
              <el-input
                v-model="form.jumpPassword"
                type="password"
                show-password
                :placeholder="editingCredential ? t('backups.passwordPlaceholderEdit') : t('backups.jumpPasswordPlaceholder')"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item :label="t('common.description')">
          <el-input v-model="form.description" type="textarea" :rows="2" :placeholder="t('backups.credentialDescPlaceholder')" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="closeDialog">{{ t('backups.cancelBtn') }}</el-button>
        <el-button type="primary" @click="handleSave">{{ t('backups.saveBtn') }}</el-button>
      </template>
    </el-dialog>

    <!-- 测试连接对话框 -->
    <el-dialog
      v-model="showTestDialog"
      :title="t('backups.testDialogTitle')"
      width="500px"
    >
      <el-form label-position="top">
        <el-form-item :label="t('backups.testDeviceIp')">
          <el-input
            v-model="testIp"
            :placeholder="t('backups.testIpPlaceholder')"
            :disabled="testing"
            @keyup.enter="handleTest"
          />
          <div class="test-ip-hint">{{ t('backups.testIpHint') }}</div>
        </el-form-item>

        <div v-if="testResult" class="test-result" :class="{ success: testResult.success, error: !testResult.success }">
          <el-icon v-if="testResult.success" class="result-icon"><CircleCheck /></el-icon>
          <el-icon v-else class="result-icon"><CircleClose /></el-icon>
          <div class="result-text">
            <div class="result-title">{{ testResult.success ? t('backups.resultSuccessTitle') : t('backups.resultFailTitle') }}</div>
            <div class="result-message">{{ testResult.message }}</div>
            <div v-if="testResult.success" class="result-duration">
              {{ t('backups.resultDuration', { seconds: (testResult.durationMs / 1000).toFixed(1) }) }}
            </div>
            <el-alert
              v-if="testResult.success && testResult.defaultsApplied?.includes('vendor')"
              class="result-hint"
              type="warning"
              :closable="false"
              show-icon
              :title="t('backups.vendorDefaultHint', { vendor: testResult.vendor || 'huawei_vrp' })"
            />
            <el-alert
              v-if="!testResult.success && testingCredential?.protocol === 'telnet'"
              class="result-hint"
              type="warning"
              :closable="false"
              show-icon
              :title="t('backups.telnetFailHint')"
            />
          </div>
        </div>
      </el-form>

      <template #footer>
        <el-button @click="showTestDialog = false">{{ t('common.close') }}</el-button>
        <el-button type="primary" :loading="testing" @click="handleTest">
          {{ testing ? t('backups.testing') : t('backups.testConfirmBtn') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.credential-list-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.table-card {
  border-radius: 8px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.card-title .el-icon {
  color: var(--el-color-primary);
}

.table-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-input {
  width: 220px;
}

.protocol-filter {
  width: 140px;
}

.credential-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cred-icon {
  color: var(--el-color-primary);
}

.password-masked {
  font-family: monospace;
  color: var(--el-text-color-secondary);
}

.text-muted {
  color: var(--el-text-color-placeholder);
}

.test-status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;

  &.is-success {
    background-color: var(--el-color-success);
  }

  &.is-failed {
    background-color: var(--el-color-danger);
  }
}

.last-test-text {
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.divider-text {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.more-trigger {
  margin-left: 12px;
}

:deep(.danger-item) {
  color: var(--el-color-danger);
}

.table-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
}

.total-text {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.test-ip-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
  line-height: 1.4;
}

.test-result {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  border-radius: 8px;
  margin-top: 16px;
}

.test-result.success {
  background: var(--el-color-success-light-9);
  border: 1px solid var(--el-color-success-light-5);
}

.test-result.error {
  background: var(--el-color-danger-light-9);
  border: 1px solid var(--el-color-danger-light-5);
}

.result-icon {
  font-size: 24px;
}

.success .result-icon {
  color: var(--el-color-success);
}

.error .result-icon {
  color: var(--el-color-danger);
}

.result-title {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.result-message {
  color: var(--el-text-color-regular);
  font-size: 13px;
  margin-top: 4px;
}

.result-duration {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 4px;
}

.result-hint {
  margin-top: 8px;
}

.credential-table :deep(.cell) {
  line-height: 1.5;
}

.credential-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>
