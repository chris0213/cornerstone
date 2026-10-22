<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api/axios'

const { t } = useI18n()

interface SSOConfig {
  enabled: boolean
  client_id: string
  client_secret: string
  authorize_url: string
  token_url: string
  userinfo_url: string
  redirect_url: string
  login_methods: string
  allowed_redirect_hosts: string
}

const loading = ref(false)
const saving = ref(false)
const config = ref<SSOConfig>({
  enabled: false,
  client_id: '',
  client_secret: '',
  authorize_url: '',
  token_url: '',
  userinfo_url: '',
  redirect_url: '',
  login_methods: 'local,oauth2,saml',
  allowed_redirect_hosts: ''
})

// 登录方式多选（local 必选不可取消）
const loginMethodOptions = [
  { value: 'local', label: '本地登录 (local)', disabled: true },
  { value: 'oauth2', label: 'OAuth2 单点登录', disabled: false },
  { value: 'saml', label: 'SAML 单点登录', disabled: false },
]
const loginMethodsSelected = ref<string[]>(['local', 'oauth2', 'saml'])
const onLoginMethodsChange = (selected: string[]) => {
  if (!selected.includes('local')) {
    selected.unshift('local')
  }
  loginMethodsSelected.value = [...selected]
  config.value.login_methods = selected.join(',')
}

// secret 只回显是否已设置；留空提交表示不修改
const hasClientSecret = ref(false)

const testLoading = ref(false)
const testResult = ref('')

async function loadConfig() {
  loading.value = true
  try {
    const response = await api.get('/system/sso-config')
    if (response.data) {
      hasClientSecret.value = !!response.data.has_client_secret
      const methods = (response.data.login_methods || 'local,oauth2,saml')
        .split(',').map((s: string) => s.trim()).filter(Boolean)
      if (!methods.includes('local')) methods.unshift('local')
      loginMethodsSelected.value = methods
      config.value = {
        enabled: response.data.enabled || false,
        client_id: response.data.client_id || '',
        client_secret: '',
        authorize_url: response.data.authorize_url || '',
        token_url: response.data.token_url || '',
        userinfo_url: response.data.userinfo_url || '',
        redirect_url: response.data.redirect_url || '',
        login_methods: methods.join(','),
        allowed_redirect_hosts: response.data.allowed_redirect_hosts || ''
      }
    }
  } catch (error: any) {
    if (error.response?.status !== 404) {
      ElMessage.error(t('system.sso.loadFailed'))
    }
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  try {
    await api.post('/system/sso-config', config.value)
    ElMessage.success(t('system.sso.saveSuccess'))
    testResult.value = ''
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || t('system.sso.saveFailed'))
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  if (!config.value.client_id || !config.value.authorize_url) {
    ElMessage.warning(t('system.sso.fillClientIdUrl'))
    return
  }

  testLoading.value = true
  testResult.value = ''
  try {
    const response = await api.post('/system/sso-config/test', config.value)
    testResult.value = '✓ ' + t('system.sso.connectSuccess') + ': ' + response.data.message
    ElMessage.success(t('system.sso.testSuccess'))
  } catch (error: any) {
    testResult.value = '✗ ' + t('system.sso.connectFailed') + ': ' + (error.response?.data?.detail || error.message)
    ElMessage.error(t('system.sso.testFailed'))
  } finally {
    testLoading.value = false
  }
}

async function resetConfig() {
  try {
    await ElMessageBox.confirm(
      t('system.sso.resetConfirm'),
      t('system.sso.confirmReset'),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      }
    )
    
    config.value = {
      enabled: false,
      client_id: '',
      client_secret: '',
      authorize_url: '',
      token_url: '',
      userinfo_url: '',
      redirect_url: '',
      login_methods: 'local,oauth2,saml',
      allowed_redirect_hosts: ''
    }
    loginMethodsSelected.value = ['local', 'oauth2', 'saml']
    hasClientSecret.value = false
    
    await api.delete('/system/sso-config')
    ElMessage.success(t('system.sso.resetSuccess'))
    testResult.value = ''
  } catch (error) {
    // 用户取消
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <div class="sso-settings">
    <el-alert
      :title="t('system.sso.configTitle')"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 20px;"
    >
      <template #default>
        {{ t('system.sso.configDesc') }}
      </template>
    </el-alert>

    <el-form 
      :model="config" 
      label-width="140px" 
      v-loading="loading"
      label-position="left"
    >
      <el-form-item :label="t('system.sso.enableSSO')">
        <el-switch v-model="config.enabled" />
        <span class="form-hint">{{ t('system.sso.enableHint') }}</span>
      </el-form-item>

      <el-divider content-position="left">{{ t('system.sso.oauthConfig') }}</el-divider>

      <el-form-item label="Client ID" required>
        <el-input 
          v-model="config.client_id" 
          :placeholder="t('system.sso.clientIdPlaceholder')"
          :disabled="!config.enabled"
        />
      </el-form-item>

      <el-form-item label="Client Secret" :required="!hasClientSecret">
        <el-input 
          v-model="config.client_secret" 
          type="password"
          :placeholder="hasClientSecret ? '已设置，留空表示不修改' : t('system.sso.clientSecretPlaceholder')"
          show-password
          :disabled="!config.enabled"
        />
      </el-form-item>

      <el-form-item :label="t('system.sso.authorizeUrl')" required>
        <el-input 
          v-model="config.authorize_url" 
          :placeholder="t('system.sso.authorizeUrlPlaceholder')"
          :disabled="!config.enabled"
        />
        <span class="form-hint">{{ t('system.sso.authorizeUrlHint') }}</span>
      </el-form-item>

      <el-form-item label="Token URL" required>
        <el-input 
          v-model="config.token_url" 
          :placeholder="t('system.sso.tokenUrlPlaceholder')"
          :disabled="!config.enabled"
        />
        <span class="form-hint">{{ t('system.sso.tokenUrlHint') }}</span>
      </el-form-item>

      <el-form-item :label="t('system.sso.userinfoUrl')" required>
        <el-input 
          v-model="config.userinfo_url" 
          :placeholder="t('system.sso.userinfoUrlPlaceholder')"
          :disabled="!config.enabled"
        />
        <span class="form-hint">{{ t('system.sso.userinfoUrlHint') }}</span>
      </el-form-item>

      <el-form-item :label="t('system.sso.redirectUrl')" required>
        <el-input 
          v-model="config.redirect_url" 
          :placeholder="t('system.sso.redirectUrlPlaceholder')"
          :disabled="!config.enabled"
        />
        <span class="form-hint">{{ t('system.sso.redirectUrlHint') }}</span>
      </el-form-item>

      <el-form-item :label="t('system.sso.loginMethods')">
        <el-checkbox-group 
          v-model="loginMethodsSelected" 
          @change="onLoginMethodsChange"
          :disabled="!config.enabled"
        >
          <el-checkbox 
            v-for="opt in loginMethodOptions" 
            :key="opt.value" 
            :value="opt.value"
            :disabled="opt.disabled"
          >
            {{ opt.label }}
          </el-checkbox>
        </el-checkbox-group>
        <span class="form-hint">本地登录必须保留，避免无法进入系统</span>
      </el-form-item>

      <el-form-item label="回调域名白名单">
        <el-input 
          v-model="config.allowed_redirect_hosts" 
          placeholder="如: app.example.com, sso.corp.com（可选，多个用英文逗号分隔）"
          :disabled="!config.enabled"
        />
        <span class="form-hint">可选。配置后回调地址域名必须在白名单内；留空仅要求 https</span>
      </el-form-item>

      <el-form-item>
        <el-button type="primary" @click="saveConfig" :loading="saving">
          {{ t('system.sso.saveConfig') }}
        </el-button>
        <el-button @click="testConnection" :loading="testLoading" :disabled="!config.enabled">
          {{ t('system.sso.testConnection') }}
        </el-button>
        <el-button @click="resetConfig" type="danger" plain>
          {{ t('common.reset') }}
        </el-button>
      </el-form-item>

      <el-form-item v-if="testResult">
        <el-alert
          :title="testResult"
          :type="testResult.startsWith('✓') ? 'success' : 'error'"
          :closable="false"
          show-icon
        />
      </el-form-item>
    </el-form>

    <el-divider content-position="left">{{ t('system.sso.exampleTitle') }}</el-divider>

    <el-card shadow="never" class="example-card">
      <template #header>
        <span>{{ t('system.sso.keycloakExample') }}</span>
      </template>
      <div class="example-content">
        <p><strong>Client ID:</strong> cornerstone</p>
        <p><strong>{{ t('system.sso.authorizeUrl') }}:</strong> https://sso.example.com/auth/realms/master/protocol/openid-connect/auth</p>
        <p><strong>Token URL:</strong> https://sso.example.com/auth/realms/master/protocol/openid-connect/token</p>
        <p><strong>{{ t('system.sso.userinfoUrl') }}:</strong> https://sso.example.com/auth/realms/master/protocol/openid-connect/userinfo</p>
        <p><strong>{{ t('system.sso.redirectUrl') }}:</strong> https://your-app.example.com/login</p>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.sso-settings {
  padding: 20px;
}

.form-hint {
  display: block;
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.example-card {
  margin-top: 20px;
}

.example-content {
  font-size: 13px;
  line-height: 1.8;
}

.example-content p {
  margin: 8px 0;
}

.example-content strong {
  color: #1890ff;
}
</style>
