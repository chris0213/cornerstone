<script setup lang="ts">
import { onMounted } from 'vue'
import { useBrandStore } from '../../store/brand'
import NetworkIllustration from './components/NetworkIllustration.vue'
import LoginForm from './components/LoginForm.vue'

const brandStore = useBrandStore()

onMounted(async () => {
  await brandStore.loadBrand()
})
</script>

<template>
  <div class="login-page">
    <NetworkIllustration />
    <LoginForm />
  </div>
</template>

<style scoped>
.login-page {
  height: 100dvh;
  min-height: 0;
  display: flex;
  position: relative;
  overflow: hidden;
  background-color: var(--color-ink-blue-950);
  /* 深蓝渐变 + 左中上主柔光（重心）+ 右下弱柔光（与卡片对角呼应） */
  background-image:
    radial-gradient(
      88% 72% at 30% 26%,
      color-mix(in srgb, var(--color-accent-on-dark) 20%, transparent) 0%,
      transparent 62%
    ),
    radial-gradient(
      62% 54% at 66% 74%,
      color-mix(in srgb, var(--color-accent-on-dark) 9%, transparent) 0%,
      transparent 70%
    ),
    linear-gradient(
      150deg,
      var(--color-ink-blue-950) 0%,
      var(--color-ink-blue-900) 45%,
      color-mix(in srgb, var(--color-ink-blue-800) 65%, var(--color-accent) 35%) 100%
    );
}

/* 极矮窗口才允许滚动，常规笔记本高度保持一屏 */
@media (max-height: 600px) {
  .login-page {
    height: auto;
    min-height: 100dvh;
    overflow-y: auto;
  }
}
</style>
