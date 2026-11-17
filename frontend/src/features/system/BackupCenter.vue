<script setup lang="ts">
import { ref, onMounted } from 'vue'
import DatabaseBackup from './DatabaseBackup.vue'
import OffsiteSyncSettings from './OffsiteSyncSettings.vue'

const tab = ref('local')
onMounted(() => { tab.value = 'local' })
</script>

<template>
  <div class="backup-center">
    <div class="page-head">
      <h2>备份与容灾</h2>
      <p class="sub">数据库备份的本地留存与异地同步统一在此管理。</p>
    </div>

    <el-tabs v-model="tab" class="tabs">
      <el-tab-pane label="本地备份" name="local">
        <DatabaseBackup />
      </el-tab-pane>
      <el-tab-pane label="异地同步" name="offsite">
        <OffsiteSyncSettings />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.backup-center { padding: 20px; }
.page-head { margin-bottom: 8px; }
.page-head h2 { margin: 0; font-size: 20px; color: var(--text-primary); }
.sub { margin: 6px 0 0; font-size: 13px; color: var(--text-tertiary); }
.tabs :deep(.el-tabs__content) { padding-top: 8px; }
</style>
