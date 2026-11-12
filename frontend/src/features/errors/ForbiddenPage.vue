<template>
  <div class="forbidden-page">
    <div class="forbidden-container">
      <div class="forbidden-icon">
        <el-icon :size="80" color="var(--color-danger)">
          <Lock />
        </el-icon>
      </div>
      <h1>403</h1>
      <p>{{ isViewer ? '您当前为IT负责人角色，需要运维工程师权限才能访问此页面' : '您没有访问此页面的权限' }}</p>
      <el-button type="primary" @click="goHome">
        返回首页
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Lock } from '@element-plus/icons-vue'
import { useAuthStore } from '../../store/auth'

const authStore = useAuthStore()
const isViewer = computed(() => authStore.isReadOnly())

function goHome() {
  window.location.href = '/'
}
</script>

<style scoped>
.forbidden-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface-1);
}

.forbidden-container {
  text-align: center;
  padding: 60px 40px;
  background: var(--color-surface-0);
  border: 1px solid var(--color-line-1);
  border-radius: 16px;
  box-shadow: 0 18px 40px -20px rgba(15, 20, 27, 0.18);
}

.forbidden-icon {
  margin-bottom: 20px;
}

h1 {
  font-size: 48px;
  font-weight: bold;
  color: var(--color-danger);
  margin: 0 0 10px 0;
}

p {
  font-size: 16px;
  color: var(--color-text-2);
  margin: 0 0 30px 0;
}
</style>