<template>
  <div class="ai-settings-page">
    <div class="capability-card">
      <div class="capability-header">
        <span class="capability-title">{{ t('aiSettings.inspectionTitle') }}</span>
        <el-switch
          v-model="aiInspectionEnabled"
          @change="saveAIInspection"
        />
        <el-tag :type="aiInspectionEnabled ? 'success' : 'info'" size="small">
          {{ aiInspectionEnabled ? t('common.enabled') : t('common.disabled') }}
        </el-tag>
      </div>
      <p class="capability-desc">
        {{ t('aiSettings.inspectionDesc') }}
      </p>
    </div>

    <div class="capability-card">
      <div class="capability-header">
        <span class="capability-title">{{ t('aiSettings.adaptiveBaselineTitle') }}</span>
      </div>
      <p class="capability-desc">
        {{ t('aiSettings.adaptiveBaselineDesc') }}
      </p>
      <el-table :data="rules" border style="width: 100%">
        <el-table-column prop="name" :label="t('aiSettings.ruleName')" min-width="160" />
        <el-table-column prop="condition_type" :label="t('aiSettings.conditionType')" width="110" />
        <el-table-column :label="t('aiSettings.detectionMode')" width="160">
          <template #default="{ row }">
            <el-select
              :model-value="ruleMode(row)"
              @change="(val: string) => onModeChange(row, val)"
              :disabled="!supportsAnomaly(row)"
            >
              <el-option :label="t('aiSettings.staticThreshold')" value="static" />
              <el-option :label="t('aiSettings.adaptiveBaseline')" value="anomaly" />
            </el-select>
            <div v-if="!supportsAnomaly(row)" class="capability-tip">{{ t('aiSettings.latencyPacketLossOnly') }}</div>
          </template>
        </el-table-column>
        <el-table-column :label="t('aiSettings.baselineWindow')" width="140">
          <template #default="{ row }">
            <el-input-number
              v-model="row.baseline_window"
              :min="10"
              :max="1440"
              :controls="false"
              :disabled="ruleMode(row) === 'static'"
              style="width: 100%"
            />
          </template>
        </el-table-column>
        <el-table-column :label="t('aiSettings.sensitivityZScore')" width="150">
          <template #default="{ row }">
            <el-input-number
              v-model="row.baseline_sensitivity"
              :min="1"
              :max="10"
              :step="0.5"
              :controls="false"
              :disabled="ruleMode(row) === 'static'"
              style="width: 100%"
            />
          </template>
        </el-table-column>
        <el-table-column width="140">
          <template #header>
            <el-tooltip :content="t('aiSettings.mutationThresholdTip')" placement="top">
              <span>{{ t('aiSettings.mutationThreshold') }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <el-input-number
              v-model="row.mutation_threshold"
              :min="0.05"
              :max="5"
              :step="0.05"
              :controls="false"
              :disabled="ruleMode(row) === 'static'"
              style="width: 100%"
            />
          </template>
        </el-table-column>
        <el-table-column :label="t('aiSettings.actions')" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              type="primary"
              size="small"
              :loading="ruleSaving[row.id]"
              @click="saveRule(row)"
            >
              {{ t('common.save') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="config-list-container">
      <div class="list-header">
        <span class="list-title">{{ t('aiSettings.llmConfigList') }}</span>
        <el-button type="primary" @click="openAddModal">{{ t('aiSettings.addConfig') }}</el-button>
      </div>

      <div v-if="configs.length === 0" class="empty-state">
        <el-icon class="empty-icon"><InfoFilled /></el-icon>
        <p>{{ t('aiSettings.noConfigs') }}</p>
        <el-button type="primary" @click="openAddModal">{{ t('aiSettings.addConfig') }}</el-button>
      </div>

      <div v-else class="config-list">
        <div
          v-for="config in configs"
          :key="config.id"
          class="config-card"
          :class="{ active: editingId === config.id }"
        >
          <div class="config-header">
            <div class="config-name">
              <span class="name-text">{{ config.name }}</span>
              <el-tag v-if="config.is_default" type="primary" size="small">{{ t('aiSettings.default') }}</el-tag>
              <el-tag
                :type="config.has_key ? 'success' : 'info'"
                size="small"
                effect="plain"
              >
                {{ config.has_key ? t('aiSettings.keyConfigured') : t('aiSettings.keyMissing') }}
              </el-tag>
            </div>
            <div class="config-actions">
              <el-switch
                v-model="config.enabled"
                @change="toggleEnabled(config)"
              />
              <el-button type="text" @click="testStoredConfig(config)" :loading="testingId === config.id">{{ t('aiSettings.test') }}</el-button>
              <el-button type="text" @click="openEditModal(config)">{{ t('common.edit') }}</el-button>
              <el-button type="text" @click="deleteConfig(config)" class="danger-btn">{{ t('common.delete') }}</el-button>
            </div>
          </div>
          <div class="config-body">
            <div class="config-row">
              <span class="label">{{ t('aiSettings.provider') }}</span>
              <span class="value">{{ getProviderLabel(config.provider) }}</span>
            </div>
            <div class="config-row">
              <span class="label">{{ t('aiSettings.model') }}</span>
              <span class="value">{{ config.model }}</span>
            </div>
            <div class="config-row">
              <span class="label">API URL</span>
              <span class="value">{{ config.api_url }}</span>
            </div>
            <div v-if="config.description" class="config-row">
              <span class="label">{{ t('aiSettings.description') }}</span>
              <span class="value">{{ config.description }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog
      :title="editingId ? t('aiSettings.editConfigTitle') : t('aiSettings.addConfigTitle')"
      v-model="modalVisible"
      width="650px"
    >
      <div class="modal-form">
        <div class="form-row">
          <div class="form-group">
            <label class="form-label required">{{ t('aiSettings.configName') }}</label>
            <el-input
              v-model="form.name"
              :placeholder="t('aiSettings.configNamePlaceholder')"
            />
          </div>
          <div class="form-group">
            <label class="form-label required">{{ t('aiSettings.provider') }}</label>
            <el-select
              v-model="form.provider"
              :placeholder="t('aiSettings.selectProvider')"
              @change="handleProviderChange"
            >
              <el-option
                v-for="(label, value) in providerOptions"
                :key="value"
                :label="label"
                :value="value"
              />
            </el-select>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label required">{{ t('aiSettings.model') }}</label>
            <el-input
              v-model="form.model"
              :placeholder="t('aiSettings.modelNamePlaceholder')"
            />
          </div>
        </div>

        <div class="form-row">
          <div class="form-group full-width">
            <label class="form-label required">API URL</label>
            <el-input
              v-model="form.api_url"
              placeholder="https://..."
            />
            <div class="form-tip">{{ t('aiSettings.apiUrlTip') }}</div>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group full-width api-key-group">
            <label class="form-label" :class="{ required: !editingId }">API Key</label>
            <div class="input-with-icon">
              <el-input
                v-model="form.api_key"
                :type="showApiKey ? 'text' : 'password'"
                :placeholder="editingId ? t('aiSettings.apiKeyKeepHint') : t('aiSettings.apiKeyPlaceholder')"
              />
              <el-button type="text" @click="showApiKey = !showApiKey" class="eye-btn">
                <el-icon><View /></el-icon>
              </el-button>
            </div>
            <div class="form-tip">{{ t('aiSettings.apiKeyHint') }}</div>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group switch-group">
            <label class="form-label">{{ t('aiSettings.enable') }}</label>
            <el-switch v-model="form.enabled" />
          </div>
          <div class="form-group switch-group">
            <label class="form-label">{{ t('aiSettings.setDefault') }}</label>
            <el-switch v-model="form.is_default" />
          </div>
        </div>

        <div class="form-row">
          <div class="form-group full-width">
            <label class="form-label">{{ t('aiSettings.description') }}</label>
            <el-input
              v-model="form.description"
              type="textarea"
              :rows="2"
              :placeholder="t('aiSettings.descriptionPlaceholder')"
            />
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="closeModal">{{ t('common.cancel') }}</el-button>
        <el-button @click="testConfig" :loading="testing">{{ t('aiSettings.testConnection') }}</el-button>
        <el-button type="primary" @click="saveConfig" :loading="loading">{{ t('aiSettings.saveConfig') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { InfoFilled, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../../api/axios'
import { confirmAndRun } from '../../lib/confirm'

const { t } = useI18n()

interface AIConfig {
  id: number
  name: string
  description: string
  provider: string
  model: string
  api_url: string
  /** 后端不回传 api_key，仅回传是否已配置密钥 */
  has_key: boolean
  enabled: boolean
  is_default: boolean
}

const loading = ref(false)
const testing = ref(false)
const testingId = ref<number | null>(null)
const modalVisible = ref(false)
const editingId = ref<number | null>(null)
const showApiKey = ref(false)
const configs = ref<AIConfig[]>([])

const form = reactive({
  name: '',
  description: '',
  provider: '',
  model: '',
  api_url: '',
  api_key: '',
  enabled: true,
  is_default: false,
})

const providerOptions = computed(() => ({
  openai: 'OpenAI',
  deepseek: t('aiSettings.providers.deepseekCompatible'),
  qwen: t('aiSettings.providers.qwen'),
  zhipu: t('aiSettings.providers.zhipu'),
  claude: t('aiSettings.providers.claude'),
  custom: t('aiSettings.providers.custom'),
}))

const apiUrlDefaults: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  deepseek: 'https://api.deepseek.com',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  zhipu: 'https://open.bigmodel.cn/api/paas/v4',
  claude: 'https://api.anthropic.com',
  custom: '',
}

const modelDefaults: Record<string, string> = {
  openai: 'gpt-4o-mini',
  deepseek: 'deepseek-v4-flash',
  qwen: 'qwen-plus',
  zhipu: 'glm-4-flash',
  claude: 'claude-3-5-sonnet-20241022',
  custom: '',
}

const getProviderLabel = (provider: string): string =>
  (providerOptions.value as Record<string, string>)[provider] || provider

const handleProviderChange = () => {
  form.api_url = apiUrlDefaults[form.provider] || ''
  form.model = modelDefaults[form.provider] || ''
}

const fetchConfigs = async () => {
  try {
    const res = await api.get('/ai/config')
    configs.value = res.data || []
  } catch (error: any) {
    console.error('加载AI配置失败:', error)
    configs.value = []
  }
}

const openAddModal = () => {
  editingId.value = null
  showApiKey.value = false
  form.name = ''
  form.description = ''
  form.provider = ''
  form.model = ''
  form.api_url = ''
  form.api_key = ''
  form.enabled = true
  form.is_default = configs.value.length === 0
  modalVisible.value = true
}

const openEditModal = (config: AIConfig) => {
  editingId.value = config.id
  showApiKey.value = false
  form.name = config.name
  form.description = config.description
  form.provider = config.provider
  form.model = config.model
  form.api_url = config.api_url
  // 编辑时不清空也不回显已有 key（安全），留空表示"不修改"
  form.api_key = ''
  form.enabled = config.enabled
  form.is_default = config.is_default
  modalVisible.value = true
}

const closeModal = () => {
  modalVisible.value = false
  editingId.value = null
}

const saveConfig = async () => {
  if (!form.name || !form.provider || !form.api_url || !form.model) {
    ElMessage.warning(t('aiSettings.fillAllFields'))
    return
  }
  // 编辑时 API Key 留空 = 不修改（安全：不回显已有 key）
  // 仅新建时才强制要求填写
  if (!editingId.value && !form.api_key) {
    ElMessage.warning(t('aiSettings.enterApiKey'))
    return
  }

  loading.value = true
  try {
    const payload: Record<string, any> = {
      name: form.name,
      description: form.description,
      provider: form.provider,
      model: form.model,
      api_url: form.api_url,
      enabled: form.enabled,
      is_default: form.is_default,
    }
    // 编辑且未重新输入 key 时，不发送 api_key 字段，避免空串覆盖已有值
    if (form.api_key) {
      payload.api_key = form.api_key
    }

    if (editingId.value) {
      await api.put(`/ai/config/${editingId.value}`, payload)
    } else {
      await api.post('/ai/config', payload)
    }
    ElMessage.success(t('aiSettings.configSaved'))
    closeModal()
    await fetchConfigs()
  } catch (error: any) {
    console.error('保存配置失败:', error)
    ElMessage.error(error.response?.data?.detail || t('aiSettings.saveFailed'))
  } finally {
    loading.value = false
  }
}

// 测试连接：用弹窗当前表单值；编辑时若 key 留空则回退用 config_id 测已存配置
const testConfig = async () => {
  if (!form.provider || !form.model || !form.api_url) {
    ElMessage.warning(t('aiSettings.fillProviderModelUrl'))
    return
  }
  // 编辑模式 + key 未重新输入 → 用库里已存 key 测（config_id 路径）
  if (editingId.value && !form.api_key) {
    const cfg = configs.value.find(c => c.id === editingId.value)
    if (cfg) {
      await testStoredConfig(cfg)
      return
    }
    ElMessage.warning(t('aiSettings.reenterApiKey'))
    return
  }
  if (!form.api_key) {
    ElMessage.warning(t('aiSettings.enterApiKey'))
    return
  }
  testing.value = true
  try {
    const res = await api.post('/ai/config/test', {
      provider: form.provider,
      model: form.model,
      api_url: form.api_url,
      api_key: form.api_key,
    })
    if (res.data?.ok) {
      ElMessage.success(res.data.message)
    } else {
      ElMessage.error(res.data?.message || t('aiSettings.testFailed'))
    }
  } catch (error: any) {
    console.error('测试失败:', error)
    ElMessage.error(error.response?.data?.detail || t('aiSettings.testFailed'))
  } finally {
    testing.value = false
  }
}

// 测试连接：用列表里已存配置（按 config_id，使用库里已存的 key）
const testStoredConfig = async (config: AIConfig) => {
  testingId.value = config.id
  try {
    const res = await api.post('/ai/config/test', { config_id: config.id })
    if (res.data?.ok) {
      ElMessage.success(`${config.name}：${res.data.message}`)
    } else {
      ElMessage.error(`${config.name}：${res.data?.message || t('aiSettings.testFailed')}`)
    }
  } catch (error: any) {
    console.error('测试失败:', error)
    ElMessage.error(error.response?.data?.detail || t('aiSettings.testFailed'))
  } finally {
    testingId.value = null
  }
}

const toggleEnabled = async (config: AIConfig) => {
  try {
    // 不发送 api_key 字段：留空/缺省 = 后端保留已存密钥
    await api.put(`/ai/config/${config.id}`, {
      name: config.name,
      description: config.description,
      provider: config.provider,
      model: config.model,
      api_url: config.api_url,
      enabled: config.enabled,
      is_default: config.is_default,
    })
    ElMessage.success(config.enabled ? t('aiSettings.enabledMsg') : t('aiSettings.disabledMsg'))
  } catch (error: any) {
    console.error('更新状态失败:', error)
    config.enabled = !config.enabled
    ElMessage.error(t('aiSettings.updateFailed'))
  }
}

const deleteConfig = async (config: AIConfig) => {
  await confirmAndRun({
    message: t('aiSettings.deleteConfirm', { name: config.name }),
    title: t('aiSettings.deleteTitle'),
    action: async () => {
      await api.delete(`/ai/config/${config.id}`)
      await fetchConfigs()
    },
    successMessage: t('aiSettings.deleteSuccess'),
    errorMessage: t('aiSettings.deleteFailed'),
  })
}

interface AlertRuleRow {
  id: number
  name: string
  condition_type: string
  detection_mode: string | null
  baseline_window: number | null
  baseline_sensitivity: number | null
  mutation_threshold: number | null
  enabled: boolean
}

const aiInspectionEnabled = ref(false)
const rules = ref<AlertRuleRow[]>([])
const ruleSaving = ref<Record<number, boolean>>({})

const DEFAULT_WINDOW = 60
const DEFAULT_SENSITIVITY = 3.0
const DEFAULT_MUTATION = 0.5

const ANOMALY_CONDITIONS = ['latency', 'packet_loss']

const supportsAnomaly = (row: AlertRuleRow) => ANOMALY_CONDITIONS.includes(row.condition_type)

const ruleMode = (row: AlertRuleRow) => row.detection_mode || 'static'

const fetchAIInspection = async () => {
  try {
    const res = await api.get('/settings/ai-inspection')
    aiInspectionEnabled.value = !!res.data?.enabled
  } catch (error: any) {
    console.error('加载巡检AI研判设置失败:', error)
    aiInspectionEnabled.value = false
  }
}

const saveAIInspection = async (val: boolean) => {
  try {
    await api.put('/settings/ai-inspection', { enabled: val })
    ElMessage.success(val ? t('aiSettings.inspectionEnabledMsg') : t('aiSettings.inspectionDisabledMsg'))
  } catch (error: any) {
    console.error('保存巡检AI研判设置失败:', error)
    aiInspectionEnabled.value = !val
    ElMessage.error(t('aiSettings.saveFailed'))
  }
}

const fetchRules = async () => {
  try {
    const res = await api.get('/alerts/rules')
    rules.value = (res.data?.data ?? []).map((row: AlertRuleRow) => ({
      ...row,
      detection_mode: row.detection_mode ?? 'static',
      baseline_window: row.baseline_window ?? DEFAULT_WINDOW,
      baseline_sensitivity: row.baseline_sensitivity ?? DEFAULT_SENSITIVITY,
      mutation_threshold: row.mutation_threshold ?? DEFAULT_MUTATION,
    }))
  } catch (error: any) {
    console.error('加载告警规则失败:', error)
    rules.value = []
  }
}

const onModeChange = (row: AlertRuleRow, val: string) => {
  row.detection_mode = val
  if (val === 'anomaly') {
    if (row.baseline_window === null) row.baseline_window = DEFAULT_WINDOW
    if (row.baseline_sensitivity === null) row.baseline_sensitivity = DEFAULT_SENSITIVITY
    if (row.mutation_threshold === null) row.mutation_threshold = DEFAULT_MUTATION
  }
}

const saveRule = async (row: AlertRuleRow) => {
  if (row.baseline_window !== null && (row.baseline_window < 10 || row.baseline_window > 1440)) {
    ElMessage.warning(t('aiSettings.baselineWindowRange'))
    return
  }
  if (row.baseline_sensitivity !== null && (row.baseline_sensitivity < 1 || row.baseline_sensitivity > 10)) {
    ElMessage.warning(t('aiSettings.sensitivityRange'))
    return
  }
  if (row.mutation_threshold !== null && (row.mutation_threshold < 0.05 || row.mutation_threshold > 5)) {
    ElMessage.warning(t('aiSettings.mutationRange'))
    return
  }

  ruleSaving.value[row.id] = true
  try {
    await api.put(`/alerts/rules/${row.id}`, {
      detection_mode: ruleMode(row),
      baseline_window: row.baseline_window,
      baseline_sensitivity: row.baseline_sensitivity,
      mutation_threshold: row.mutation_threshold,
    })
    ElMessage.success(t('aiSettings.savedMsg'))
  } catch (error: any) {
    console.error('保存告警规则失败:', error)
    ElMessage.error(error.response?.data?.detail || t('aiSettings.saveFailed'))
  } finally {
    ruleSaving.value[row.id] = false
  }
}

onMounted(() => {
  fetchConfigs()
  fetchAIInspection()
  fetchRules()
})
</script>

<style scoped>
.ai-settings-page {
  background: var(--bg-secondary);
  min-height: 100vh;
}

.config-list-container {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 24px;
  box-shadow: var(--shadow-sm);
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

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 0;
  color: var(--text-muted);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.empty-state p {
  margin: 0 0 16px 0;
}

.config-list {
  display: grid;
  gap: 16px;
}

.config-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
  transition: all 0.2s;
}

.config-card:hover {
  border-color: var(--accent-primary);
}

.config-card.active {
  border-color: var(--accent-primary);
  background: var(--bg-hover);
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}

.config-name {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
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

.config-actions .danger-btn {
  color: var(--accent-danger);
}

.config-body {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.config-row {
  display: flex;
  gap: 8px;
}

.config-row .label {
  font-size: 12px;
  color: var(--text-muted);
  min-width: 60px;
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

.form-group.switch-group {
  flex: 0.4;
  min-width: 80px;
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
  color: var(--accent-danger);
  margin-right: 4px;
}

.switch-group .form-label {
  margin-bottom: 4px;
}

.form-tip {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
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

.capability-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 16px;
}

.capability-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.capability-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.capability-desc {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
}

.capability-tip {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
}
</style>
