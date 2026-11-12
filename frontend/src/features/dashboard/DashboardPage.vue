<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAuthStore } from '@/store/auth'
import ManagerDashboard from './ManagerDashboard.vue'
import EngineerDashboard from './EngineerDashboard.vue'
import { Tools, TrendCharts } from '@element-plus/icons-vue'

const authStore = useAuthStore()
const PREF_KEY = 'dashboard_view_preference'

// 从 localStorage 读取上次偏好，默认运维视图
const currentView = ref<'engineer' | 'manager'>(
  (localStorage.getItem(PREF_KEY) as 'engineer' | 'manager') || 'engineer'
)

const role = computed(() => authStore.user?.role)

// viewer 强制管理视图，engineer 强制运维视图，super_admin 可切换
const activeView = computed(() => {
  if (role.value === 'viewer') return 'manager'
  if (role.value === 'engineer') return 'engineer'
  return currentView.value  // super_admin 使用用户偏好
})

// 只有 super_admin 显示切换 Tab
const showTabs = computed(() => role.value === 'super_admin')

function switchView(view: 'engineer' | 'manager') {
  currentView.value = view
  localStorage.setItem(PREF_KEY, view)
}
</script>

<template>
  <div class="dashboard-wrap">
    <!-- 页面标题行 -->
    <div class="dashboard-header">
      <h1 class="page-title">首页</h1>

      <!-- 切换 Tab（仅 super_admin 可见） -->
      <div v-if="showTabs" class="view-switcher">
        <button
          class="switcher-btn"
          :class="{ active: activeView === 'engineer' }"
          @click="switchView('engineer')"
        >
          <el-icon><Tools /></el-icon>
          运维视图
        </button>
        <button
          class="switcher-btn"
          :class="{ active: activeView === 'manager' }"
          @click="switchView('manager')"
        >
          <el-icon><TrendCharts /></el-icon>
          管理视图
        </button>
      </div>
    </div>

    <!-- 视图内容 -->
    <EngineerDashboard v-if="activeView === 'engineer'" />
    <ManagerDashboard  v-if="activeView === 'manager'" />
  </div>
</template>

<style scoped>
.dashboard-wrap {
  padding: 20px;
}

.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 500;
  color: var(--color-text-1);
  margin: 0;
}

.view-switcher {
  display: flex;
  background: var(--color-surface-1);
  border: 0.5px solid #e0e0e0;
  border-radius: 6px;
  padding: 3px;
  gap: 2px;
}

.switcher-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 14px;
  border-radius: 4px;
  border: none;
  background: transparent;
  color: #6e6e6e;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.switcher-btn:hover {
  color: var(--color-text-1);
}

.switcher-btn.active {
  background: #ffffff;
  color: var(--color-text-1);
  border: 0.5px solid #e0e0e0;
  font-weight: 500;
}

.switcher-btn .el-icon {
  font-size: 14px;
}
</style>
