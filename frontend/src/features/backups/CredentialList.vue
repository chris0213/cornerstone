<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { getCredentials, createCredential, updateCredential, deleteCredential, testCredential } from '@/api/backups'
import { confirmAndRun } from '@/lib/confirm'
import type { Credential } from '@/types/domain'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const credentials = ref<Credential[]>([])
const loading = ref(false)
const showDialog = ref(false)
const showTestDialog = ref(false)
const editingCredential = ref<Credential | null>(null)
const testingCredentialId = ref<number | null>(null)
const testIp = ref('')
const testResult = ref<{ success: boolean; message: string; durationMs: number } | null>(null)
const selectedCredentialIds = ref<number[]>([])

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
    password: '********',
    enablePassword: credential.enablePassword || '',
    authType: credential.authType,
    privateKey: credential.privateKey || '',
    jumpHost: credential.jumpHost || '',
    jumpPort: credential.jumpPort,
    jumpUsername: credential.jumpUsername || '',
    jumpPassword: credential.jumpPassword || '',
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
    if (form.value.password && form.value.password !== '********') {
      data.password = form.value.password
    }
    if (form.value.enablePassword && form.value.enablePassword !== '********') {
      data.enablePassword = form.value.enablePassword
    }
    if (form.value.privateKey && form.value.privateKey !== '********') {
      data.privateKey = form.value.privateKey
    }
    if (form.value.jumpHost) {
      data.jumpHost = form.value.jumpHost
    }
    if (form.value.jumpUsername) {
      data.jumpUsername = form.value.jumpUsername
    }
    if (form.value.jumpPassword && form.value.jumpPassword !== '********') {
      data.jumpPassword = form.value.jumpPassword
    }

    if (editingCredential.value) {
      await updateCredential(parseInt(editingCredential.value.id), data)
      ElMessage.success(t('backups.updateSuccess'))
    } else {
      await createCredential(data)
      ElMessage.success(t('backups.createSuccess'))
    }
    await loadCredentials()
    closeDialog()
  } catch (error) {
    console.error('Failed to save credential:', error)
    ElMessage.error(t('backups.saveFailed'))
  }
}

async function handleDelete(credential: Credential) {
  await confirmAndRun({
    message: t('backups.confirmDelete', { name: credential.name }),
    title: t('backups.deleteTitle'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    action: async () => {
      await deleteCredential(parseInt(credential.id))
      await loadCredentials()
    },
    successMessage: t('backups.deleteSuccess'),
    errorMessage: t('backups.deleteFailed'),
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
    action: async () => {
      // 逐个删除（可以优化为批量API）
      for (const id of selectedCredentialIds.value) {
        await deleteCredential(id)
      }
      selectedCredentialIds.value = []
      await loadCredentials()
    },
    successMessage: t('backups.batchDeleteSuccess', { count: selectedCredentialIds.value.length }),
    errorMessage: t('backups.batchDeleteFailed'),
  })
}

function openTestDialog(credential: Credential) {
  testingCredentialId.value = parseInt(credential.id)
  testIp.value = ''
  testResult.value = null
  showTestDialog.value = true
}

async function handleTest() {
  if (!testIp.value) {
    ElMessage.error(t('validation.testIpRequired'))
    return
  }

  if (!testingCredentialId.value) return

  try {
    testResult.value = await testCredential(testingCredentialId.value, testIp.value)
    if (testResult.value.success) {
      ElMessage.success(t('backups.testSuccess', { ms: testResult.value.durationMs }))
    } else {
      ElMessage.error(testResult.value.message)
    }
  } catch (error) {
    console.error('Failed to test credential:', error)
    ElMessage.error(t('backups.testFailed'))
  }
}

async function loadCredentials() {
  loading.value = true
  try {
    credentials.value = await getCredentials()
  } catch (error) {
    console.error('Failed to load credentials:', error)
    ElMessage.error(t('backups.loadCredentialsFailed'))
  } finally {
    loading.value = false
  }
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
              {{ t('backups.newCredential') }}
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        class="credential-table"
        :data="credentials"
        style="width: 100%"
        stripe
        border
        v-loading="loading"
        height="calc(100vh - 220px)"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column prop="name" :label="t('backups.credentialName')" min-width="150">
          <template #default="{ row }">
            <div class="credential-name">
              <el-icon class="cred-icon"><Key /></el-icon>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="protocol" label="协议" min-width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.protocol === 'ssh' ? 'success' : 'warning'" size="small">
              {{ row.protocol?.toUpperCase() }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="port" label="端口" min-width="80" align="center">
          <template #default="{ row }">{{ row.port }}</template>
        </el-table-column>
        <el-table-column prop="username" label="用户名" min-width="120">
          <template #default="{ row }">{{ row.username }}</template>
        </el-table-column>
        <el-table-column prop="password" label="密码" min-width="120" align="center">
          <template #default>
            <span class="password-masked">********</span>
          </template>
        </el-table-column>
        <el-table-column prop="jumpHost" :label="t('backups.jumpHost')" min-width="150">
          <template #default="{ row }">
            <span v-if="row.jumpHost">{{ row.jumpHost }}:{{ row.jumpPort }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="authType" label="认证方式" min-width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.authType === 'key' ? 'info' : 'primary'" size="small">
              {{ row.authType === 'key' ? '密钥' : '密码' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="220" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openTestDialog(row)">
              <el-icon><Connection /></el-icon>
              {{ t('backups.testConnection') }}
            </el-button>
            <el-button link type="primary" size="small" @click="openEditDialog(row)">
              <el-icon><Edit /></el-icon>
              {{ t('common.edit') }}
            </el-button>
            <el-button link type="danger" size="small" @click="handleDelete(row)">
              <el-icon><Delete /></el-icon>
              {{ t('common.delete') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="credentials.length === 0 && !loading" :description="t('backups.noCredentials')" />
    </el-card>

    <!-- 新建/编辑凭证对话框 -->
    <el-dialog
      v-model="showDialog"
      :title="editingCredential ? '编辑凭证' : '新建凭证'"
      width="700px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="凭证名称" required>
          <el-input v-model="form.name" placeholder="如：华为核心设备组" />
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
            <el-form-item label="端口">
              <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="认证方式">
              <el-select v-model="form.authType" style="width: 100%">
                <el-option v-for="opt in authTypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="t('backups.username')" required>
              <el-input v-model="form.username" placeholder="请输入用户名" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="editingCredential ? t('backups.passwordKeepEmpty') : t('backups.password')" :required="!editingCredential">
              <el-input v-model="form.password" type="password" show-password :placeholder="editingCredential ? t('backups.passwordNoChange') : t('validation.passwordRequired')" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="t('backups.enablePassword')">
              <el-input v-model="form.enablePassword" type="password" show-password placeholder="可选，Cisco设备用" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('backups.privateKey')" v-if="form.authType === 'key'">
              <el-input v-model="form.privateKey" type="textarea" :rows="3" placeholder="SSH私钥内容" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">
          <span class="divider-text">{{ t('backups.jumpSection') }}</span>
        </el-divider>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="跳板机IP">
              <el-input v-model="form.jumpHost" placeholder="如：192.0.2.1" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="跳板机端口">
              <el-input-number v-model="form.jumpPort" :min="1" :max="65535" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="跳板机用户名">
              <el-input v-model="form.jumpUsername" placeholder="跳板机用户名" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('backups.jumpHostPassword')">
              <el-input v-model="form.jumpPassword" type="password" show-password placeholder="跳板机密码" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item :label="t('common.description')">
          <el-input v-model="form.description" type="textarea" :rows="2" :placeholder="t('backups.credentialDescPlaceholder')" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="closeDialog">取消</el-button>
        <el-button type="primary" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 测试连接对话框 -->
    <el-dialog
      v-model="showTestDialog"
      title="测试连接"
      width="500px"
    >
      <el-form label-position="top">
        <el-form-item :label="t('backups.testDeviceIp')">
          <el-input v-model="testIp" placeholder="请输入测试设备IP地址" />
        </el-form-item>

        <div v-if="testResult" class="test-result" :class="{ success: testResult.success, error: !testResult.success }">
          <el-icon v-if="testResult.success" class="result-icon"><CircleCheck /></el-icon>
          <el-icon v-else class="result-icon"><CircleClose /></el-icon>
          <div class="result-text">
            <div class="result-title">{{ testResult.success ? '连接成功' : '连接失败' }}</div>
            <div class="result-message">{{ testResult.message }}</div>
            <div v-if="testResult.success" class="result-duration">耗时: {{ (testResult.durationMs / 1000).toFixed(1) }}s</div>
          </div>
        </div>
      </el-form>

      <template #footer>
        <el-button @click="showTestDialog = false">{{ t('common.close') }}</el-button>
        <el-button type="primary" @click="handleTest">{{ t('backups.testConnection') }}</el-button>
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

.credential-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cred-icon {
  color: #1890ff;
}

.password-masked {
  font-family: monospace;
  color: #8c8c8c;
}

.text-muted {
  color: #bfbfbf;
}

.divider-text {
  font-size: 13px;
  color: #8c8c8c;
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
  background: #f6ffed;
  border: 1px solid #b7eb8f;
}

.test-result.error {
  background: #fff2f0;
  border: 1px solid #ffccc7;
}

.result-icon {
  font-size: 24px;
}

.success .result-icon {
  color: #52c41a;
}

.error .result-icon {
  color: #ff4d4f;
}

.result-title {
  font-weight: 600;
  color: #262626;
}

.result-message {
  color: #595959;
  font-size: 13px;
  margin-top: 4px;
}

.result-duration {
  color: #8c8c8c;
  font-size: 12px;
  margin-top: 4px;
}

.credential-table :deep(.cell) {
  line-height: 1.5;
}

.credential-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>
