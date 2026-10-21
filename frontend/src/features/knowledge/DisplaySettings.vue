<template>
  <div class="kb-display-settings">
    <div class="ds-group">
      <div class="ds-label">{{ t('knowledge.dsFontSize') }}</div>
      <el-radio-group v-model="kbDisplaySettings.fontSize" size="small">
        <el-radio-button value="small">{{ t('knowledge.dsFontSmall') }}</el-radio-button>
        <el-radio-button value="medium">{{ t('knowledge.dsFontMedium') }}</el-radio-button>
        <el-radio-button value="large">{{ t('knowledge.dsFontLarge') }}</el-radio-button>
      </el-radio-group>
    </div>
    <div class="ds-group">
      <div class="ds-label">{{ t('knowledge.dsFontFamily') }}</div>
      <el-radio-group v-model="kbDisplaySettings.fontFamily" size="small">
        <el-radio-button value="default">{{ t('knowledge.dsFontDefault') }}</el-radio-button>
        <el-radio-button value="serif">{{ t('knowledge.dsFontSerif') }}</el-radio-button>
        <el-radio-button value="mono">{{ t('knowledge.dsFontMono') }}</el-radio-button>
      </el-radio-group>
    </div>
    <div class="ds-group">
      <div class="ds-label">{{ t('knowledge.dsTheme') }}</div>
      <el-radio-group v-model="kbDisplaySettings.theme" size="small">
        <el-radio-button value="light">{{ t('knowledge.dsThemeLight') }}</el-radio-button>
        <el-radio-button value="sepia">{{ t('knowledge.dsThemeSepia') }}</el-radio-button>
        <el-radio-button value="dark">{{ t('knowledge.dsThemeDark') }}</el-radio-button>
      </el-radio-group>
    </div>
    <div class="ds-group">
      <div class="ds-label">{{ t('knowledge.dsTextColor') }}</div>
      <div class="ds-colors">
        <button
          v-for="c in TEXT_COLORS"
          :key="c.value"
          type="button"
          class="ds-color"
          :class="{ active: kbDisplaySettings.color === c.value }"
          :style="{ background: c.value || 'linear-gradient(45deg, #fff 45%, #c0c4cc 55%)' }"
          :title="t(c.labelKey)"
          @click="kbDisplaySettings.color = c.value"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { kbDisplaySettings, TEXT_COLORS } from './displaySettings'

const { t } = useI18n()
</script>

<style scoped>
.kb-display-settings {
  padding: 2px;
}

.ds-group {
  margin-bottom: 12px;
}

.ds-group:last-child {
  margin-bottom: 0;
}

.ds-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}

.ds-colors {
  display: flex;
  gap: 8px;
}

.ds-color {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
  outline: none;
}

.ds-color.active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 2px var(--el-color-primary-light-8);
}
</style>
