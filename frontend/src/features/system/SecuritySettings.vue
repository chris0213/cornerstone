<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Lock } from '@element-plus/icons-vue'
import api from '../../api'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const whitelist = ref('')

async function loadSettings() {
  loading.value = true
  try {
    const res = await api.get('/api/v1/settings/security/ip-whitelist')
    whitelist.value = res.data.whitelist
  } catch (err) {
    console.error('Failed to load IP whitelist settings', err)
    ElMessage.error(t('system.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  saving.value = true
  try {
    await api.put('/api/v1/settings/security/ip-whitelist', {
      whitelist: whitelist.value
    })
    ElMessage.success(t('system.saveSuccess'))
  } catch (err) {
    console.error('Failed to save IP whitelist settings', err)
    ElMessage.error(t('system.saveFailed'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadSettings()
})
</script>

<template>
  <div class="security-settings">
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

      <el-form-item>
        <el-button type="primary" :loading="saving" @click="saveSettings">
          {{ t('common.save') }}
        </el-button>
      </el-form-item>
    </el-form>

    <el-divider />

    <div class="current-status">
      <el-tag :type="whitelist.trim() ? 'danger' : 'success'" size="large">
        <Lock class="tag-icon" />
        {{ whitelist.trim() ? t('system.ipWhitelistEnabled') : t('system.ipWhitelistDisabled') }}
      </el-tag>
      <div class="status-desc" v-if="!whitelist.trim()">
        {{ t('system.ipWhitelistDisabledDesc') }}
      </div>
      <div class="status-desc" v-if="whitelist.trim()">
        {{ t('system.ipWhitelistEnabledDesc') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.security-settings {
  max-width: 800px;
  padding: 8px 0;
}

.helper-text {
  margin-top: 12px;
}

.current-status {
  padding: 16px 0;
}

.tag-icon {
  margin-right: 4px;
}

.status-desc {
  margin-top: 8px;
  color: #8c8c8c;
  font-size: 13px;
  line-height: 1.6;
}
</style>
