<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import SecuritySettings from './SecuritySettings.vue'
import { Lock } from '@element-plus/icons-vue'

const { t } = useI18n()
</script>

<template>
  <div class="security-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><Lock /></el-icon>
          {{ t('system.security') }}
        </div>
      </template>
      <SecuritySettings />
    </el-card>
  </div>
</template>

<script lang="ts">
</script>

<style scoped>
.security-page {
  padding: 20px;
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
</style>
