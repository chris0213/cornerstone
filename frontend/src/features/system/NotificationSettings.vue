<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Edit, View, Hide } from '@element-plus/icons-vue'
import { getNotificationSettings, updateNotificationSettings, testNotification } from '../../api/settings'
import type { NotificationSettings, TestNotificationResult } from '../../api/settings'

const { t } = useI18n()

// 渠道元信息：品牌图标（inline SVG）、品牌色
const dingtalkSvg = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 9.36l-5.5 5.02c-.13.12-.32.01-.34-.16l-.42-3.4-2.9-.68c-.18-.04-.2-.28-.04-.37l5.9-3.44c.15-.09.34.03.33.2l-.3 3.28 3.24.05c.18 0 .26.36.03.5z"/></svg>`
const wecomSvg = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M8.69 4C4.98 4 2 6.72 2 10.07c0 1.89.94 3.58 2.42 4.68l-.61 1.97a.3.3 0 0 0 .42.36l2.3-1.22c.61.17 1.26.27 1.94.28a5.1 5.1 0 0 1-.13-1.13c0-3.13 2.83-5.67 6.32-5.67.21 0 .43.01.64.03C14.72 6.4 12.02 4 8.69 4zM6.62 7.27a.86.86 0 1 1 0 1.72.86.86 0 0 1 0-1.72zm4.34 0a.86.86 0 1 1 0 1.72.86.86 0 0 1 0-1.72zM15.3 10.4c-3.02 0-5.47 2.08-5.47 4.65 0 2.57 2.45 4.65 5.47 4.65.55 0 1.09-.07 1.59-.21l1.9 1a.25.25 0 0 0 .35-.3l-.5-1.62c1.21-.86 1.98-2.13 1.98-3.52 0-2.57-2.3-4.65-5.32-4.65zm-1.83 2.63a.72.72 0 1 1 0 1.44.72.72 0 0 1 0-1.44zm3.66 0a.72.72 0 1 1 0 1.44.72.72 0 0 1 0-1.44z"/></svg>`
const feishuSvg = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M6.67 3.5C4.09 3.5 2 5.6 2 8.17c0 1.24.5 2.36 1.32 3.18l4.94 4.94-2.05 4.51a.4.4 0 0 0 .56.51l8.32-5.03c2.35-1.42 3.91-4 3.91-6.96C19 6.05 16.95 4 14.4 4c-1.35 0-2.57.58-3.42 1.5A5.2 5.2 0 0 0 6.67 3.5zm7.53 4.13c.24 0 .47.02.7.05l-3.35 3.35-.86-3.24c.35-.1.72-.16 1.1-.16h2.41zm-4.32.83l.9 3.4-3.4.9a3.36 3.36 0 0 1 2.5-4.3zm-4.31 3.2a5.66 5.66 0 0 1-.19-1.46c0-.4.04-.78.12-1.15l3.1.83-3.03 1.78zm9.62-2.65c.5.68.8 1.52.8 2.43 0 1.16-.5 2.2-1.3 2.92l-3.3-.88 3.8-4.47z"/></svg>`
const emailSvg = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></svg>`

interface ChannelMeta {
  key: 'dingtalk' | 'wechat' | 'feishu' | 'email'
  icon: string
  color: string
}

const channels: ChannelMeta[] = [
  { key: 'dingtalk', icon: dingtalkSvg, color: '#0089FF' },
  { key: 'wechat', icon: wecomSvg, color: '#07C160' },
  { key: 'feishu', icon: feishuSvg, color: '#3370FF' },
  { key: 'email', icon: emailSvg, color: '#722ED1' },
]

const form = ref<NotificationSettings>({})
const isLoading = ref(false)
const editingChannel = ref<string | null>(null)
const modalVisible = ref(false)
const showPassword = ref(false)
const testing = ref<string | null>(null)
const lastResults = ref<Record<string, TestNotificationResult>>({})

const editingForm = reactive({
  key: '',
  name: '',
  webhook_url: '',
  smtp_host: '',
  smtp_port: 587,
  smtp_security: 'starttls' as 'none' | 'starttls' | 'ssl',
  smtp_username: '',
  smtp_password: '',
  smtp_from_email: '',
})

const isEnabled = (key: string) => (form.value.channel_enabled || {})[key] !== false
const isConfigured = (channelKey: string) => {
  switch (channelKey) {
    case 'dingtalk': return !!form.value.has_dingtalk_webhook_url
    case 'wechat': return !!form.value.has_wechat_webhook_url
    case 'feishu': return !!form.value.has_feishu_webhook_url
    case 'email': return !!form.value.smtp_host && !!form.value.has_smtp_password
    default: return false
  }
}

const channelName = (key: string) => t(`system.notification.channel_${key}`)

const maskSecret = (has: boolean | undefined, tail: string | undefined) => {
  if (!has) return ''
  return `••••••••${tail || ''}`
}

const getDisplayValue = (channelKey: string) => {
  switch (channelKey) {
    case 'dingtalk':
    case 'wechat':
    case 'feishu': {
      const has = channelKey === 'dingtalk' ? form.value.has_dingtalk_webhook_url
        : channelKey === 'wechat' ? form.value.has_wechat_webhook_url
        : form.value.has_feishu_webhook_url
      const tail = channelKey === 'dingtalk' ? form.value.dingtalk_webhook_url_tail
        : channelKey === 'wechat' ? form.value.wechat_webhook_url_tail
        : form.value.feishu_webhook_url_tail
      if (!has) return t('system.notification.notConfigured')
      return maskSecret(has, tail)
    }
    case 'email': {
      if (!form.value.smtp_host) return t('system.notification.notConfigured')
      return `${form.value.smtp_host}:${form.value.smtp_port}`
    }
    default: return t('system.notification.notConfigured')
  }
}

const rowLabel = (channelKey: string) =>
  channelKey === 'email' ? t('system.notification.smtpServerLabel') : t('system.notification.webhookLabel')

const openEditModal = (channel: ChannelMeta) => {
  editingChannel.value = channel.key
  editingForm.key = channel.key
  editingForm.name = channelName(channel.key)
  // 密钥字段留空 = 不修改；只预填非敏感字段
  editingForm.webhook_url = ''
  editingForm.smtp_host = form.value.smtp_host || ''
  editingForm.smtp_port = form.value.smtp_port || 587
  editingForm.smtp_security = form.value.smtp_security || 'starttls'
  editingForm.smtp_username = form.value.smtp_username || ''
  editingForm.smtp_password = ''
  editingForm.smtp_from_email = form.value.smtp_from_email || ''
  showPassword.value = false
  modalVisible.value = true
}

const closeModal = () => {
  modalVisible.value = false
  editingChannel.value = null
}

// 统一单一保存流程：弹窗保存 = 构造 payload 直接 PUT 落库
const saveEdit = async () => {
  const key = editingForm.key
  const payload: NotificationSettings = {
    smtp_host: form.value.smtp_host,
    smtp_port: form.value.smtp_port,
    smtp_username: form.value.smtp_username,
    smtp_from_email: form.value.smtp_from_email,
    smtp_security: (form.value.smtp_security || 'starttls') as NotificationSettings['smtp_security'],
    channel_enabled: { ...(form.value.channel_enabled || {}) },
    // 密钥字段默认留空 = 不修改
    dingtalk_webhook_url: '',
    wechat_webhook_url: '',
    feishu_webhook_url: '',
    smtp_password: '',
  }

  if (key === 'email') {
    payload.smtp_host = editingForm.smtp_host
    payload.smtp_port = editingForm.smtp_port
    payload.smtp_username = editingForm.smtp_username
    payload.smtp_from_email = editingForm.smtp_from_email
    payload.smtp_security = editingForm.smtp_security
    if (editingForm.smtp_password) payload.smtp_password = editingForm.smtp_password
  } else {
    if (editingForm.webhook_url.trim()) payload[`${key}_webhook_url` as keyof NotificationSettings] = editingForm.webhook_url.trim() as never
  }

  isLoading.value = true
  try {
    form.value = await updateNotificationSettings(payload)
    ElMessage.success(t('system.notification.updateSuccess'))
    closeModal()
  } catch (error: any) {
    console.error('Update notification settings failed:', error)
    ElMessage.error(error.response?.data?.detail || t('system.notification.updateFailed'))
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  loadSettings()
})

const loadSettings = async () => {
  try {
    form.value = await getNotificationSettings()
  } catch (error) {
    console.error('Load notification settings failed:', error)
    ElMessage.error(t('system.notification.loadFailed'))
  }
}

// 每渠道测试发送按钮；先保存当前弹窗草稿再发测试（测试读库中配置）
const handleTest = async (channel: 'dingtalk' | 'wechat' | 'feishu' | 'email') => {
  testing.value = channel
  try {
    const result = await testNotification(channel)
    lastResults.value = { ...lastResults.value, [channel]: result }
    if (result.success) {
      ElMessage.success(result.message)
    } else {
      ElMessage.error(result.message)
    }
  } catch (error: any) {
    console.error('Test notification failed:', error)
    ElMessage.error(error.response?.data?.detail || t('system.notification.testFailed'))
  } finally {
    testing.value = null
  }
}

const toggleEnabled = (key: string, val: boolean | string | number | undefined) => {
  const enabled = { ...(form.value.channel_enabled || {}), [key]: !!val }
  form.value.channel_enabled = enabled
  saveEnabledOnly(enabled)
}

const saveEnabledOnly = async (enabled: Record<string, boolean>) => {
  isLoading.value = true
  try {
    await updateNotificationSettings({
      smtp_host: form.value.smtp_host,
      smtp_port: form.value.smtp_port,
      smtp_username: form.value.smtp_username,
      smtp_from_email: form.value.smtp_from_email,
      smtp_security: form.value.smtp_security || 'starttls',
      channel_enabled: enabled,
      dingtalk_webhook_url: '',
      wechat_webhook_url: '',
      feishu_webhook_url: '',
      smtp_password: '',
    })
    ElMessage.success(t('system.notification.updateSuccess'))
  } catch (error: any) {
    console.error('Update channel enabled failed:', error)
    ElMessage.error(error.response?.data?.detail || t('system.notification.updateFailed'))
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="notification-settings-page">
    <div class="config-list-container">
      <div class="list-header">
        <span class="list-title">{{ t('system.notification.channelConfig') }}</span>
      </div>

      <div class="config-list">
        <div
          v-for="channel in channels"
          :key="channel.key"
          class="config-card"
          :class="{ active: editingChannel === channel.key }"
        >
          <div class="config-header">
            <div class="config-name">
              <div class="channel-icon" :style="{ background: channel.color }" v-html="channel.icon" />
              <span class="name-text">{{ channelName(channel.key) }}</span>
              <el-tag v-if="isConfigured(channel.key)" type="success" size="small">{{ t('system.notification.configured') }}</el-tag>
              <el-tag v-else type="danger" size="small">{{ t('system.notification.notConfigured') }}</el-tag>
            </div>
            <div class="config-actions">
              <el-switch
                :model-value="isEnabled(channel.key)"
                @change="(val: any) => toggleEnabled(channel.key, val)"
              />
              <el-button type="text" @click="handleTest(channel.key)" :loading="testing === channel.key">
                {{ t('system.notification.testSend') }}
              </el-button>
              <el-button type="text" @click="openEditModal(channel)">
                <el-icon><Edit /></el-icon>
                {{ t('system.notification.configure') }}
              </el-button>
            </div>
          </div>
          <div class="config-body">
            <div class="config-row">
              <span class="label">{{ rowLabel(channel.key) }}</span>
              <span class="value">{{ getDisplayValue(channel.key) }}</span>
            </div>
            <div v-if="channel.key === 'email' && form.smtp_username" class="config-row">
              <span class="label">{{ t('system.notification.smtpUsername') }}</span>
              <span class="value">{{ form.smtp_username }}</span>
            </div>
            <div v-if="lastResults[channel.key]" class="config-row">
              <span class="label">{{ t('system.notification.lastResult') }}</span>
              <el-tag :type="lastResults[channel.key].success ? 'success' : 'danger'" size="small">
                {{ lastResults[channel.key].success ? t('system.notification.testSuccess') : lastResults[channel.key].message }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog
      :title="`${t('system.notification.configure')} ${editingForm.name}`"
      v-model="modalVisible"
      width="600px"
    >
      <div class="modal-form" v-if="editingForm.key !== 'email'">
        <div class="form-row">
          <div class="form-group full-width">
            <label class="form-label required">Webhook URL</label>
            <el-input
              v-model="editingForm.webhook_url"
              type="textarea"
              :rows="4"
              :placeholder="t('system.notification.webhookKeepPlaceholder')"
            />
            <p class="form-hint">{{ t('system.notification.webhookHttpsHint') }}</p>
          </div>
        </div>
      </div>

      <div class="modal-form" v-if="editingForm.key === 'email'">
        <div class="form-row">
          <div class="form-group">
            <label class="form-label required">{{ t('system.notification.smtpServerLabel') }}</label>
            <el-input
              v-model="editingForm.smtp_host"
              placeholder="smtp.example.com"
            />
          </div>
          <div class="form-group">
            <label class="form-label">{{ t('system.notification.smtpPort') }}</label>
            <el-input
              v-model.number="editingForm.smtp_port"
              type="number"
              placeholder="587"
            />
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">{{ t('system.notification.smtpSecurity') }}</label>
            <el-select v-model="editingForm.smtp_security" style="width: 100%">
              <el-option label="STARTTLS (587)" value="starttls" />
              <el-option label="SSL/TLS (465)" value="ssl" />
              <el-option label="None (25)" value="none" />
            </el-select>
          </div>
          <div class="form-group">
            <label class="form-label">{{ t('system.notification.smtpUsername') }}</label>
            <el-input
              v-model="editingForm.smtp_username"
              :placeholder="t('system.notification.smtpUserPlaceholder')"
            />
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">{{ t('system.notification.smtpFromEmail') }}</label>
            <el-input
              v-model="editingForm.smtp_from_email"
              placeholder="sender@example.com"
            />
          </div>
          <div class="form-group full-width api-key-group">
            <label class="form-label required">{{ t('system.notification.smtpPassword') }}</label>
            <div class="input-with-icon">
              <el-input
                v-model="editingForm.smtp_password"
                :type="showPassword ? 'text' : 'password'"
                :placeholder="form.has_smtp_password ? t('system.notification.keepSecretPlaceholder') : t('system.notification.smtpPwdPlaceholder')"
              />
              <el-button type="text" @click="showPassword = !showPassword" class="eye-btn">
                <el-icon><View v-if="showPassword" /><Hide v-else /></el-icon>
              </el-button>
            </div>
            <p class="form-hint">{{ t('system.notification.smtpPwdHint') }}</p>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="closeModal">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveEdit" :loading="isLoading">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.notification-settings-page {
  background: var(--bg-secondary);
  min-height: 100%;
}

.config-list-container {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 24px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.list-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.config-list {
  display: grid;
  gap: 16px;
}

.config-card {
  border: 1px solid var(--border-primary);
  border-radius: 8px;
  padding: 16px;
  transition: border-color 0.2s;
}

.config-card:hover {
  border-color: var(--accent-primary);
}

.config-card.active {
  border-color: var(--accent-primary);
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-secondary);
}

.config-name {
  display: flex;
  align-items: center;
  gap: 12px;
}

.channel-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  color: #fff;
}

.name-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.config-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.config-body {
  display: grid;
  gap: 8px;
}

.config-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.config-row .label {
  font-size: 12px;
  color: var(--text-tertiary);
  min-width: 90px;
}

.config-row .value {
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.modal-form {
  padding: 8px 0;
}

.form-row {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.form-group {
  flex: 1;
  min-width: 150px;
}

.form-group.full-width {
  flex: 100;
}

.form-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.form-label.required::before {
  content: '*';
  color: var(--el-color-danger);
  margin-right: 4px;
}

.form-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 6px 0 0 0;
  padding-left: 4px;
}

.api-key-group {
  position: relative;
}

.input-with-icon {
  display: flex;
  align-items: center;
}

.input-with-icon .eye-btn {
  margin-left: -40px;
  z-index: 10;
  padding: 0 10px;
}
</style>
