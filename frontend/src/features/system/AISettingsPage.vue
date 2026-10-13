<template>
  <div class="ai-settings-page">
    <div class="capability-card">
      <div class="capability-header">
        <span class="capability-title">巡检 AI 二次研判</span>
        <el-switch
          v-model="aiInspectionEnabled"
          @change="saveAIInspection"
        />
        <el-tag :type="aiInspectionEnabled ? 'success' : 'info'" size="small">
          {{ aiInspectionEnabled ? '已开启' : '已关闭' }}
        </el-tag>
      </div>
      <p class="capability-desc">
        开启后，巡检任务在快速扫描与全量扫描完成后，会对发现的异常调用 LLM 做二次研判，结论写入巡检结果的 ai_summary 字段。需要在上方 LLM 配置列表中至少启用一个配置。默认关闭，不影响现有巡检流程。
      </p>
    </div>

    <div class="capability-card">
      <div class="capability-header">
        <span class="capability-title">自适应告警基线</span>
      </div>
      <p class="capability-desc">
        将告警规则从固定阈值切换为动态基线检测（z-score 离群判定）与突变检测。仅对「延迟」与「丢包」两类条件生效；历史采样点不足 10 个时不会触发告警。默认全部为静态阈值。
      </p>
      <el-table :data="rules" border style="width: 100%">
        <el-table-column prop="name" label="规则名称" min-width="160" />
        <el-table-column prop="condition_type" label="条件类型" width="110" />
        <el-table-column label="检测模式" width="160">
          <template #default="{ row }">
            <el-select
              :model-value="ruleMode(row)"
              @change="(val: string) => onModeChange(row, val)"
              :disabled="!supportsAnomaly(row)"
            >
              <el-option label="静态阈值" value="static" />
              <el-option label="自适应基线" value="anomaly" />
            </el-select>
            <div v-if="!supportsAnomaly(row)" class="capability-tip">仅支持延迟与丢包规则</div>
          </template>
        </el-table-column>
        <el-table-column label="基线窗口（分钟）" width="140">
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
        <el-table-column label="灵敏度 z-score" width="150">
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
        <el-table-column label="突变阈值" width="140">
          <template #header>
            <el-tooltip content="相对基线的变化率，0.5 表示变化 50%" placement="top">
              <span>突变阈值</span>
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
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              type="primary"
              size="small"
              :loading="ruleSaving[row.id]"
              @click="saveRule(row)"
            >
              保存
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="config-list-container">
      <div class="list-header">
        <span class="list-title">LLM 配置列表</span>
        <el-button type="primary" @click="openAddModal">+ 添加配置</el-button>
      </div>

      <div v-if="configs.length === 0" class="empty-state">
        <el-icon class="empty-icon"><InfoFilled /></el-icon>
        <p>暂无 AI 配置</p>
        <el-button type="primary" @click="openAddModal">添加配置</el-button>
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
              <el-tag v-if="config.is_default" type="primary" size="small">默认</el-tag>
            </div>
            <div class="config-actions">
              <el-switch
                v-model="config.enabled"
                @change="toggleEnabled(config)"
              />
              <el-button type="text" @click="testStoredConfig(config)" :loading="testingId === config.id">测试</el-button>
              <el-button type="text" @click="openEditModal(config)">编辑</el-button>
              <el-button type="text" @click="deleteConfig(config)" style="color: #ff4d4f">删除</el-button>
            </div>
          </div>
          <div class="config-body">
            <div class="config-row">
              <span class="label">提供商</span>
              <span class="value">{{ getProviderLabel(config.provider) }}</span>
            </div>
            <div class="config-row">
              <span class="label">模型</span>
              <span class="value">{{ config.model }}</span>
            </div>
            <div class="config-row">
              <span class="label">API URL</span>
              <span class="value">{{ config.api_url }}</span>
            </div>
            <div v-if="config.description" class="config-row">
              <span class="label">描述</span>
              <span class="value">{{ config.description }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog
      :title="editingId ? '编辑 LLM 配置' : '添加 LLM 配置'"
      v-model="modalVisible"
      width="650px"
    >
      <div class="modal-form">
        <div class="form-row">
          <div class="form-group name-group">
            <label class="form-label required">名称</label>
            <el-input
              v-model="form.name"
              placeholder="请输入配置名称"
            />
          </div>
          <div class="form-group switch-group">
            <label class="form-label">启用</label>
            <el-switch v-model="form.enabled" />
          </div>
          <div class="form-group switch-group">
            <label class="form-label">默认</label>
            <el-switch v-model="form.is_default" />
          </div>
        </div>

        <div class="form-row">
          <div class="form-group full-width">
            <label class="form-label">描述</label>
            <el-input
              v-model="form.description"
              type="textarea"
              :rows="2"
              placeholder="请输入 LLM 配置的描述信息"
            />
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label required">提供商类型</label>
            <el-select
              v-model="form.provider"
              placeholder="请选择提供商类型"
              @change="handleProviderChange"
            >
              <el-option label="OpenAI" value="openai" />
              <el-option label="OpenAI 兼容" value="deepseek" />
              <el-option label="阿里通义千问" value="qwen" />
              <el-option label="智谱AI" value="zhipu" />
              <el-option label="Anthropic Claude" value="claude" />
              <el-option label="自定义 API" value="custom" />
            </el-select>
          </div>
          <div class="form-group">
            <label class="form-label required">模型</label>
            <el-input
              v-model="form.model"
              placeholder="请输入模型名称"
            />
          </div>
        </div>

        <div class="form-row">
          <div class="form-group full-width">
            <label class="form-label required">API URL</label>
            <el-input
              v-model="form.api_url"
              placeholder="请输入 API URL"
            />
          </div>
        </div>

        <div class="form-row">
          <div class="form-group full-width api-key-group">
            <label class="form-label required">API Key</label>
            <div class="input-with-icon">
              <el-input
                v-model="form.api_key"
                :type="showApiKey ? 'text' : 'password'"
                :placeholder="editingId ? '已保存，留空则不修改' : '请输入 API Key'"
              />
              <el-button type="text" @click="showApiKey = !showApiKey" class="eye-btn">
                <el-icon><View /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="closeModal">取消</el-button>
        <el-button @click="testConfig" :loading="testing">测试连接</el-button>
        <el-button type="primary" @click="saveConfig" :loading="loading">保存配置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { InfoFilled, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../../api/axios'
import { confirmAndRun } from '../../lib/confirm'

interface AIConfig {
  id: number
  name: string
  description: string
  provider: string
  model: string
  api_url: string
  api_key: string
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

const providerOptions: Record<string, string> = {
  openai: 'OpenAI',
  deepseek: 'OpenAI 兼容',
  qwen: '阿里通义千问',
  zhipu: '智谱AI',
  claude: 'Anthropic Claude',
  custom: '自定义 API',
}

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

const getProviderLabel = (provider: string) => providerOptions[provider] || provider

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
    ElMessage.warning('请填写完整的配置信息')
    return
  }
  // 编辑时 API Key 留空 = 不修改（安全：不回显已有 key）
  // 仅新建时才强制要求填写
  if (!editingId.value && !form.api_key) {
    ElMessage.warning('请填写 API Key')
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
    ElMessage.success('配置已保存')
    closeModal()
    await fetchConfigs()
  } catch (error: any) {
    console.error('保存配置失败:', error)
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    loading.value = false
  }
}

// 测试连接：用弹窗当前表单值；编辑时若 key 留空则回退用 config_id 测已存配置
const testConfig = async () => {
  if (!form.provider || !form.model || !form.api_url) {
    ElMessage.warning('请先填写提供商、模型和 API URL')
    return
  }
  // 编辑模式 + key 未重新输入 → 用库里已存 key 测（config_id 路径）
  if (editingId.value && !form.api_key) {
    const cfg = configs.value.find(c => c.id === editingId.value)
    if (cfg) {
      await testStoredConfig(cfg)
      return
    }
    ElMessage.warning('无法找到对应配置，请重新输入 API Key')
    return
  }
  if (!form.api_key) {
    ElMessage.warning('请填写 API Key')
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
      ElMessage.error(res.data?.message || '连接测试失败')
    }
  } catch (error: any) {
    console.error('测试失败:', error)
    ElMessage.error(error.response?.data?.detail || '连接测试失败')
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
      ElMessage.error(`${config.name}：${res.data?.message || '连接测试失败'}`)
    }
  } catch (error: any) {
    console.error('测试失败:', error)
    ElMessage.error(error.response?.data?.detail || '连接测试失败')
  } finally {
    testingId.value = null
  }
}

const toggleEnabled = async (config: AIConfig) => {
  try {
    await api.put(`/ai/config/${config.id}`, {
      name: config.name,
      description: config.description,
      provider: config.provider,
      model: config.model,
      api_url: config.api_url,
      api_key: '',
      enabled: config.enabled,
      is_default: config.is_default,
    })
    ElMessage.success(config.enabled ? '已启用' : '已禁用')
  } catch (error: any) {
    console.error('更新状态失败:', error)
    config.enabled = !config.enabled
    ElMessage.error('更新失败')
  }
}

const deleteConfig = async (config: AIConfig) => {
  await confirmAndRun({
    message: `确定要删除配置 "${config.name}" 吗？`,
    title: '确认删除',
    action: async () => {
      await api.delete(`/ai/config/${config.id}`)
      await fetchConfigs()
    },
    successMessage: '已删除',
    errorMessage: '删除失败',
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
    ElMessage.success(val ? '已开启巡检 AI 二次研判' : '已关闭巡检 AI 二次研判')
  } catch (error: any) {
    console.error('保存巡检AI研判设置失败:', error)
    aiInspectionEnabled.value = !val
    ElMessage.error('保存失败')
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
    ElMessage.warning('基线窗口需在 10~1440 分钟之间')
    return
  }
  if (row.baseline_sensitivity !== null && (row.baseline_sensitivity < 1 || row.baseline_sensitivity > 10)) {
    ElMessage.warning('灵敏度 z-score 需在 1~10 之间')
    return
  }
  if (row.mutation_threshold !== null && (row.mutation_threshold < 0.05 || row.mutation_threshold > 5)) {
    ElMessage.warning('突变阈值需在 0.05~5 之间')
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
    ElMessage.success('已保存')
  } catch (error: any) {
    console.error('保存告警规则失败:', error)
    ElMessage.error(error.response?.data?.detail || '保存失败')
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
  background: #f5f5f5;
  min-height: 100vh;
}

.config-list-container {
  background: #fff;
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
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
  color: #333;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 0;
  color: #8c8c8c;
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
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px;
  transition: all 0.2s;
}

.config-card:hover {
  border-color: #1890ff;
}

.config-card.active {
  border-color: #1890ff;
  background: #f0f5ff;
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f0f0;
}

.config-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.name-text {
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

.config-actions {
  display: flex;
  align-items: center;
  gap: 12px;
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
  color: #8c8c8c;
  min-width: 60px;
}

.config-row .value {
  font-size: 12px;
  color: #333;
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

.form-group.name-group {
  flex: 2;
}

.form-group.switch-group {
  flex: 0.4;
  min-width: 80px;
}

.form-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #333;
  margin-bottom: 8px;
}

.form-label.required::before {
  content: '*';
  color: #ff4d4f;
  margin-right: 4px;
}

.switch-group .form-label {
  margin-bottom: 4px;
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
  background: #fff;
  border: 1px solid #e8e8e8;
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
  color: #333;
}

.capability-desc {
  margin: 0;
  font-size: 13px;
  color: #8c8c8c;
  line-height: 1.6;
}

.capability-tip {
  margin-top: 4px;
  font-size: 12px;
  color: #bfbfbf;
  line-height: 1.4;
}
</style>
