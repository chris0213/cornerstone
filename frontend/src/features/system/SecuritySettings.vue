<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Lock, Warning } from '@element-plus/icons-vue'
import api from '../../api'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const whitelist = ref('')

// 服务端返回状态（以服务端解析结果为准，不再用文本非空判断）
const validLines = ref(0)
const invalidLines = ref<number[]>([])
const operatorIp = ref('')
const operatorIpInList = ref(true)

// 预演
const previewIp = ref('')
const previewResult = ref<{ allowed: boolean; reason: string } | null>(null)
const previewing = ref(false)

// 状态指示：以服务端解析的有效网段数为准
const isEnabled = computed(() => validLines.value > 0)

async function loadSettings() {
  loading.value = true
  try {
    const res = await api.get('/api/v1/settings/security/ip-whitelist')
    whitelist.value = res.data.whitelist
    validLines.value = res.data.valid_lines ?? 0
    invalidLines.value = res.data.invalid_lines ?? []
    operatorIp.value = res.data.operator_ip ?? ''
    operatorIpInList.value = res.data.operator_ip_in_list ?? true
  } catch (err) {
    console.error('Failed to load IP whitelist settings', err)
    ElMessage.error(t('system.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function addToWhitelist() {
  if (!operatorIp.value) return
  const line = operatorIp.value
  const lines = whitelist.value.split('\n').map(l => l.trim()).filter(Boolean)
  if (lines.includes(line)) {
    ElMessage.info(t('system.ipWhitelistAlreadyAdded'))
    return
  }
  lines.push(line)
  whitelist.value = lines.join('\n')
}

async function saveSettings() {
  // 保存二次确认：展示有效/非法行与当前 IP 是否在名单内
  const lines = whitelist.value.split('\n').map(l => l.trim()).filter(Boolean)
  const summary = t('system.ipWhitelistSaveConfirm', {
    total: lines.length
  })
  try {
    await ElMessageBox.confirm(summary, t('system.ipWhitelistSaveConfirmTitle'), {
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
      type: 'warning'
    })
  } catch {
    return
  }

  await doSave(false)
}

async function doSave(force: boolean) {
  saving.value = true
  try {
    const res = await api.put('/api/v1/settings/security/ip-whitelist', {
      whitelist: whitelist.value,
      force
    })
    ElMessage.success(t('system.saveSuccess'))
    validLines.value = res.data.valid_lines ?? 0
    invalidLines.value = res.data.invalid_lines ?? []
    operatorIpInList.value = res.data.operator_ip_in_list ?? true
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    if (detail?.code === 'IP_WHITELIST_LOCKOUT') {
      // 防自锁拦截：二次确认后 force 重试
      try {
        await ElMessageBox.confirm(
          detail.message || t('system.ipWhitelistLockoutMsg', { ip: operatorIp.value }),
          t('system.ipWhitelistLockoutTitle'),
          {
            confirmButtonText: t('system.ipWhitelistForceSave'),
            cancelButtonText: t('common.cancel'),
            type: 'error',
            distinguishCancelAndClose: true
          }
        )
        await doSave(true)
      } catch {
        /* 用户取消 */
      }
    } else if (detail?.code === 'IP_WHITELIST_INVALID_LINES') {
      ElMessage.error(detail.message || t('system.saveFailed'))
    } else {
      console.error('Failed to save IP whitelist settings', err)
      ElMessage.error(t('system.saveFailed'))
    }
  } finally {
    saving.value = false
  }
}

async function runPreview() {
  const ip = previewIp.value.trim()
  if (!ip) return
  previewing.value = true
  previewResult.value = null
  try {
    const res = await api.post('/api/v1/settings/security/preview', { ip })
    previewResult.value = { allowed: res.data.allowed, reason: res.data.reason }
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : t('system.ipWhitelistPreviewFailed'))
  } finally {
    previewing.value = false
  }
}

onMounted(() => {
  loadSettings()
})
</script>

<template>
  <div class="security-settings">
    <!-- 状态指示：上移至表单上方，橙色警示，以服务端解析为准 -->
    <div class="status-bar">
      <el-tag
        :type="isEnabled ? 'warning' : 'success'"
        size="large"
        class="status-tag"
      >
        <el-icon class="tag-icon"><component :is="isEnabled ? Warning : Lock" /></el-icon>
        <span>{{ isEnabled ? t('system.ipWhitelistEnabled') : t('system.ipWhitelistDisabled') }}</span>
      </el-tag>
      <span class="status-desc">
        {{
          isEnabled
            ? t('system.ipWhitelistEnabledDesc', { count: validLines })
            : t('system.ipWhitelistDisabledDesc')
        }}
      </span>
      <span v-if="isEnabled && !operatorIpInList" class="status-warning">
        {{ t('system.ipWhitelistNotInList', { ip: operatorIp }) }}
      </span>
    </div>

    <!-- 当前访问 IP -->
    <div class="my-ip-bar">
      <span class="my-ip-label">{{ t('system.ipWhitelistMyIp') }}</span>
      <span class="my-ip-value">{{ operatorIp || '-' }}</span>
      <el-button size="small" type="primary" link :disabled="!operatorIp" @click="addToWhitelist">
        {{ t('system.ipWhitelistAddMyIp') }}
      </el-button>
    </div>

    <el-form label-width="140px">
      <el-form-item :label="t('system.ipWhitelist')">
        <el-input
          v-model="whitelist"
          type="textarea"
          :rows="12"
          :placeholder="t('system.ipWhitelistPlaceholder')"
          :disabled="loading"
        />
        <div class="helper-text">
          <el-alert
            :title="t('system.ipWhitelistHelp')"
            type="info"
            :closable="false"
            show-icon
          />
        </div>
      </el-form-item>

      <el-form-item :label="t('system.ipWhitelistPreview')">
        <div class="preview-row">
          <el-input
            v-model="previewIp"
            :placeholder="t('system.ipWhitelistPreviewPlaceholder')"
            class="preview-input"
            :disabled="loading"
            @keyup.enter="runPreview"
          />
          <el-button :loading="previewing" :disabled="loading" @click="runPreview">
            {{ t('system.ipWhitelistPreviewRun') }}
          </el-button>
        </div>
        <div v-if="previewResult" class="preview-result">
          <el-tag :type="previewResult.allowed ? 'success' : 'danger'" size="small">
            {{ previewResult.allowed ? t('system.ipWhitelistPreviewAllow') : t('system.ipWhitelistPreviewDeny') }}
          </el-tag>
          <span class="preview-reason">{{ previewResult.reason }}</span>
        </div>
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :loading="saving" @click="saveSettings">
          {{ t('common.save') }}
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<style scoped>
.security-settings {
  max-width: 800px;
  padding: 8px 0;
}

.status-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

.status-tag {
  display: inline-flex;
  align-items: center;
}

.tag-icon {
  margin-right: 4px;
}

.status-desc {
  color: var(--text-secondary, #909399);
  font-size: 13px;
}

.status-warning {
  color: var(--el-color-warning, #e6a23c);
  font-size: 13px;
  font-weight: 600;
}

.my-ip-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding: 10px 14px;
  border-radius: 6px;
  background: var(--bg-secondary, #f5f7fa);
}

.my-ip-label {
  color: var(--text-secondary, #909399);
  font-size: 13px;
}

.my-ip-value {
  font-family: monospace;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #303133);
}

.helper-text {
  margin-top: 12px;
}

.preview-row {
  display: flex;
  gap: 10px;
  width: 100%;
  max-width: 480px;
}

.preview-input {
  flex: 1;
}

.preview-result {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.preview-reason {
  color: var(--text-secondary, #909399);
  font-size: 13px;
}
</style>
