<script setup lang="ts">
/**
 * 路由级错误边界
 *
 * 背景：某个页面在渲染期抛错（例如 i18n 文案含未转义的 @ 触发 vue-i18n 编译异常）时，
 * 异常会一路冒泡到根组件，导致整棵渲染树停止更新——表现为该页白屏，并且此后
 * 点击任何菜单都不再有反应（URL 都不变），只能整页刷新。
 *
 * 这里用 onErrorCaptured 在路由内容外层兜住错误：
 *   1. 打印完整错误（不吞异常，仍可从 console 与上报里看到）
 *   2. 用错误态替换出错页面，App 外壳与路由本身继续工作
 *   3. 路由一跳转就清除错误态，避免错误状态黏住
 */
import { ref, watch, onErrorCaptured } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

const route = useRoute()
const { t } = useI18n()

const error = ref<Error | null>(null)
const errorInfo = ref('')

watch(
  () => route.fullPath,
  () => {
    error.value = null
    errorInfo.value = ''
  }
)

// 返回 false：阻止错误继续向上冒泡，避免整棵组件树停止渲染
onErrorCaptured((err, _instance, info) => {
  error.value = err as Error
  errorInfo.value = info
  console.error('[RouteErrorBoundary] 页面渲染出错:', err, info)
  return false
})
</script>

<template>
  <div v-if="error" class="route-error">
    <div class="route-error-card">
      <div class="route-error-icon">!</div>
      <h3>{{ t('common.pageErrorTitle') }}</h3>
      <p class="route-error-path">{{ route.fullPath }}</p>
      <pre class="route-error-msg">{{ error.message }}</pre>
      <div class="route-error-actions">
        <button class="route-error-btn primary" @click="error = null">{{ t('common.retry') }}</button>
        <button class="route-error-btn" @click="location.reload()">{{ t('common.refresh') }}</button>
      </div>
      <p class="route-error-hint">{{ t('common.pageErrorHint') }}</p>
    </div>
  </div>
  <slot v-else />
</template>

<style scoped>
.route-error {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 24px;
  min-height: 320px;
  width: 100%;
  box-sizing: border-box;
}

.route-error-card {
  max-width: 560px;
  width: 100%;
  background: var(--color-surface-0);
  border: 1px solid var(--color-line-1);
  border-radius: 12px;
  padding: 28px 32px;
  box-shadow: 0 12px 32px -18px rgba(0, 0, 0, 0.35);
  text-align: center;
}

.route-error-icon {
  width: 40px;
  height: 40px;
  margin: 0 auto 12px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 20px;
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.route-error-card h3 {
  margin: 0 0 8px;
  font-size: 16px;
  color: var(--color-text-1);
}

.route-error-path {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--color-text-3);
}

.route-error-msg {
  margin: 0 0 18px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--color-surface-1);
  color: var(--color-text-2);
  font-size: 12px;
  line-height: 1.6;
  text-align: left;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 140px;
  overflow: auto;
}

.route-error-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
}

.route-error-btn {
  padding: 8px 18px;
  border-radius: 8px;
  border: 1px solid var(--color-line-1);
  background: var(--color-surface-0);
  color: var(--color-text-1);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.route-error-btn:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.route-error-btn.primary {
  border-color: transparent;
  background: var(--color-accent);
  color: #fff;
}

.route-error-btn.primary:hover {
  background: var(--color-accent-hover);
  color: #fff;
}

.route-error-hint {
  margin: 16px 0 0;
  font-size: 12px;
  color: var(--color-text-3);
}
</style>
