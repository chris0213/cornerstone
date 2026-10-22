<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElForm, ElFormItem, ElInput, ElSelect, ElSwitch, ElButton, ElRow, ElCol, ElDivider } from 'element-plus'
import { Check, Refresh } from '@element-plus/icons-vue'
import { useAuthStore } from '../../store/auth'

const { t } = useI18n()
const authStore = useAuthStore()

const authHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (authStore.token) {
    headers['Authorization'] = `Bearer ${authStore.token}`
  }
  return headers
}

interface LDAPConfig {
  enabled: boolean
  server: string
  port: number
  use_ssl: boolean
  use_starttls: boolean
  verify_cert: boolean
  bind_dn: string
  bind_password: string
  base_dn: string
  user_filter: string
  username_attr: string
  display_attr: string
  email_attr: string
  phone_attr: string
  department_attr: string
  group_attr: string
  default_role: string
}

const config = ref<LDAPConfig>({
  enabled: false,
  server: '',
  port: 389,
  use_ssl: false,
  use_starttls: false,
  verify_cert: true,
  bind_dn: '',
  bind_password: '',
  base_dn: '',
  user_filter: '(objectClass=person)',
  username_attr: 'sAMAccountName',
  display_attr: 'displayName',
  email_attr: 'mail',
  phone_attr: 'mobile',
  department_attr: 'department',
  group_attr: 'memberOf',
  default_role: 'viewer'
})

const isLoading = ref(false)
const isTesting = ref(false)
const originalConfig = ref<LDAPConfig>({ ...config.value })

const roles = [
  { value: 'super_admin', label: t('system.superAdmin') },
  { value: 'admin', label: t('system.admin') },
  { value: 'editor', label: t('system.editor') },
  { value: 'viewer', label: t('system.viewer') }
]

onMounted(async () => {
  await fetchConfig()
})

const fetchConfig = async () => {
  try {
    const response = await fetch('/api/v1/auth/ldap/config', {
      headers: authHeaders()
    })
    if (response.ok) {
      const data = await response.json()
      config.value = { ...config.value, ...data }
      originalConfig.value = { ...config.value }
    }
    // 接口不存在时保持默认值（enabled: false）
  } catch (error) {
    console.debug('LDAP not configured, using defaults')
    // 保持默认值 enabled: false
  }
}

const hasChanges = () => {
  return JSON.stringify(config.value) !== JSON.stringify(originalConfig.value)
}

const handleSave = async () => {
  isLoading.value = true
  try {
    const response = await fetch('/api/v1/auth/ldap/config', {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify(config.value)
    })

    if (response.ok) {
      ElMessage.success(t('system.ldapConfigSaved'))
      originalConfig.value = { ...config.value }
    } else {
      const error = await response.json()
      ElMessage.error(error.detail || t('system.saveFailed'))
    }
  } catch (error) {
    console.error('保存LDAP配置失败:', error)
    ElMessage.error(t('system.saveFailed'))
  } finally {
    isLoading.value = false
  }
}

const handleTest = async () => {
  if (!config.value.server || !config.value.bind_dn || !config.value.bind_password) {
    ElMessage.warning(t('system.ldapFillRequired'))
    return
  }

  isTesting.value = true
  try {
    const response = await fetch('/api/v1/auth/ldap/test', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(config.value)
    })

    const data = await response.json()
    if (data.success) {
      ElMessage.success(data.message)
    } else {
      ElMessage.error(data.message)
    }
  } catch (error) {
    console.error('测试LDAP连接失败:', error)
    ElMessage.error(t('system.testFailed'))
  } finally {
    isTesting.value = false
  }
}

const handleReset = () => {
  config.value = { ...originalConfig.value }
  ElMessage.info(t('system.configReset'))
}

watch(() => config.value.use_ssl, (newVal) => {
  if (newVal) {
    config.value.use_starttls = false
    if (config.value.port === 389) {
      config.value.port = 636
    }
  }
})

watch(() => config.value.use_starttls, (newVal) => {
  if (newVal) {
    config.value.use_ssl = false
    if (config.value.port === 636) {
      config.value.port = 389
    }
  }
})
</script>

<template>
  <div class="ldap-settings">
    <el-form :model="config" label-width="140px">
      <!-- 基本设置 -->
      <div class="section">
        <h3 class="section-title">{{ t('system.ldapBasicSettings') }}</h3>
        
        <ElRow :gutter="20">
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapEnabled')">
              <ElSwitch v-model="config.enabled" />
            </ElFormItem>
          </ElCol>
        </ElRow>

        <ElRow :gutter="20">
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapServer')" prop="server">
              <ElInput 
                v-model="config.server" 
                :placeholder="t('system.ldapServerPlaceholder')"
              />
            </ElFormItem>
          </ElCol>
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapPort')" prop="port">
              <ElInput 
                v-model.number="config.port" 
                type="number"
                :placeholder="t('system.ldapPortPlaceholder')"
              />
            </ElFormItem>
          </ElCol>
        </ElRow>

        <ElRow :gutter="20">
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapUseSSL')">
              <ElSwitch v-model="config.use_ssl" />
            </ElFormItem>
          </ElCol>
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapUseStartTLS')">
              <ElSwitch v-model="config.use_starttls" />
            </ElFormItem>
          </ElCol>
        </ElRow>

        <ElRow :gutter="20">
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapVerifyCert')">
              <ElSwitch v-model="config.verify_cert" />
            </ElFormItem>
          </ElCol>
        </ElRow>
      </div>

      <ElDivider />

      <!-- 绑定设置 -->
      <div class="section">
        <h3 class="section-title">{{ t('system.ldapBindSettings') }}</h3>
        
        <ElFormItem :label="t('system.ldapBindDN')" prop="bind_dn">
          <ElInput 
            v-model="config.bind_dn" 
            :placeholder="t('system.ldapBindDNPlaceholder')"
          />
        </ElFormItem>

        <ElFormItem :label="t('system.ldapBindPassword')" prop="bind_password">
          <ElInput 
            v-model="config.bind_password" 
            type="password"
            :placeholder="t('system.ldapBindPasswordPlaceholder')"
          />
        </ElFormItem>

        <ElFormItem :label="t('system.ldapBaseDN')" prop="base_dn">
          <ElInput 
            v-model="config.base_dn" 
            :placeholder="t('system.ldapBaseDNPlaceholder')"
          />
        </ElFormItem>
      </div>

      <ElDivider />

      <!-- 用户属性映射 -->
      <div class="section">
        <h3 class="section-title">{{ t('system.ldapAttributeMapping') }}</h3>
        
        <ElFormItem :label="t('system.ldapUserFilter')" prop="user_filter">
          <ElInput 
            v-model="config.user_filter" 
            :placeholder="t('system.ldapUserFilterPlaceholder')"
          />
        </ElFormItem>

        <ElRow :gutter="20">
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapUsernameAttr')" prop="username_attr">
              <ElInput 
                v-model="config.username_attr" 
                :placeholder="t('system.ldapUsernameAttrPlaceholder')"
              />
            </ElFormItem>
          </ElCol>
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapDisplayAttr')" prop="display_attr">
              <ElInput 
                v-model="config.display_attr" 
                :placeholder="t('system.ldapDisplayAttrPlaceholder')"
              />
            </ElFormItem>
          </ElCol>
        </ElRow>

        <ElRow :gutter="20">
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapEmailAttr')" prop="email_attr">
              <ElInput 
                v-model="config.email_attr" 
                :placeholder="t('system.ldapEmailAttrPlaceholder')"
              />
            </ElFormItem>
          </ElCol>
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapPhoneAttr')" prop="phone_attr">
              <ElInput 
                v-model="config.phone_attr" 
                :placeholder="t('system.ldapPhoneAttrPlaceholder')"
              />
            </ElFormItem>
          </ElCol>
        </ElRow>

        <ElRow :gutter="20">
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapDepartmentAttr')" prop="department_attr">
              <ElInput 
                v-model="config.department_attr" 
                :placeholder="t('system.ldapDepartmentAttrPlaceholder')"
              />
            </ElFormItem>
          </ElCol>
          <ElCol :span="12">
            <ElFormItem :label="t('system.ldapGroupAttr')" prop="group_attr">
              <ElInput 
                v-model="config.group_attr" 
                :placeholder="t('system.ldapGroupAttrPlaceholder')"
              />
            </ElFormItem>
          </ElCol>
        </ElRow>
      </div>

      <ElDivider />

      <!-- 默认角色 -->
      <div class="section">
        <h3 class="section-title">{{ t('system.ldapDefaultRole') }}</h3>
        
        <ElFormItem :label="t('system.defaultRole')">
          <ElSelect v-model="config.default_role" :placeholder="t('system.selectRole')">
            <el-option 
              v-for="role in roles" 
              :key="role.value" 
              :label="role.label" 
              :value="role.value" 
            />
          </ElSelect>
        </ElFormItem>
      </div>
    </el-form>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <ElButton 
        type="default" 
        :icon="Refresh" 
        @click="handleReset"
        :disabled="!hasChanges()"
      >
        {{ t('system.reset') }}
      </ElButton>
      <ElButton 
        type="primary" 
        :icon="Check" 
        @click="handleTest"
        :loading="isTesting"
      >
        {{ t('system.testConnection') }}
      </ElButton>
      <ElButton 
        type="primary" 
        @click="handleSave"
        :loading="isLoading"
        :disabled="!hasChanges()"
      >
        {{ t('system.save') }}
      </ElButton>
    </div>
  </div>
</template>

<style scoped>
.ldap-settings {
  padding: 24px;
}

.section {
  margin-bottom: 20px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #262626;
  margin-bottom: 16px;
  padding-left: 8px;
  border-left: 3px solid #1890ff;
}

.action-bar {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding-top: 24px;
  border-top: 1px solid #f0f0f0;
  margin-top: 20px;
}
</style>
