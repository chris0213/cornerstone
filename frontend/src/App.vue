<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './store/auth'
import { useBrandStore } from './store/brand'
import LanguageSwitcher from './components/LanguageSwitcher.vue'
import GlobalSearch from './components/GlobalSearch.vue'
import AIAssistant from './components/AIAssistant.vue'
import { useGlobalShortcut } from './lib/shortcuts'
import api from './api/axios'
import { ElMessage } from 'element-plus'
import { startAlertSocket, onNewAlert } from './lib/alertSocket'
import { useI18n } from 'vue-i18n'
import { menuConfig } from './config/menuConfig'
import { 
  DataBoard, 
  Connection, 
  Bell, 
  Setting, 
  Files, 
  SwitchButton, 
  ArrowDown, 
  ArrowUp,
  User,
  Search,
  ChatDotRound,
  OfficeBuilding,
  Grid,
  Monitor,
  Share,
  Box,
  Tickets,
  Reading,
  Avatar,
  Key,
  Lock,
  Message,
  MagicStick,
  Memo,
  Operation
} from '@element-plus/icons-vue'
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const brandStore = useBrandStore()
const companyLogo = ref<string>(localStorage.getItem('companyLogo') || '')
const isLogoLoading = ref(!companyLogo.value)
const ipamMenuOpen = ref(false)
const backupMenuOpen = ref(false)
const topologyMenuOpen = ref(false)
const sidebarCollapsed = ref(false)
const mobileSidebarOpen = ref(false)
const activeTooltip = ref('')
const globalSearchRef = ref<InstanceType<typeof GlobalSearch> | null>(null)
const aiAssistantRef = ref<InstanceType<typeof AIAssistant> | null>(null)
let hideTimer: ReturnType<typeof setTimeout> | null = null
const isRouteReady = ref(false)

useGlobalShortcut(() => globalSearchRef.value?.open())

router.isReady().then(() => {
  setTimeout(() => {
    isRouteReady.value = true
  }, 300)
})

const toggleIpamMenu = () => {
  ipamMenuOpen.value = !ipamMenuOpen.value
}

const toggleBackupMenu = () => {
  backupMenuOpen.value = !backupMenuOpen.value
}

const toggleTopologyMenu = () => {
  topologyMenuOpen.value = !topologyMenuOpen.value
}

const showTooltip = (name: string) => {
  if (hideTimer) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
  activeTooltip.value = name
}

const hideTooltip = () => {
  hideTimer = setTimeout(() => {
    activeTooltip.value = ''
    hideTimer = null
  }, 200)
}

onMounted(() => {
  brandStore.loadBrand()
  if (authStore.isLoggedIn) {
    authStore.fetchUser().catch(() => {
      // fetchUser 失败（token 过期等），axios 拦截器已处理跳转，这里静默即可
    })
    // 告警实时推送：新告警产生时全局弹出通知
    startAlertSocket()
    onNewAlert((alert) => {
      const type = alert.severity === 'critical'
        ? 'error'
        : alert.severity === 'warning'
          ? 'warning'
          : 'info'
      ElMessage({ message: alert.message, type, duration: 6000, showClose: true })
    })
  }
  loadLogo()
})

const loadLogo = async () => {
  if (!authStore.isLoggedIn) return
  
  isLogoLoading.value = true
  try {
    const response = await api.get('/settings/logo')
    if (!response.data || !response.data.value) {
      companyLogo.value = ''
      localStorage.removeItem('companyLogo')
      return
    }
    const base64 = response.data.value
    companyLogo.value = `data:image/png;base64,${base64}`
    localStorage.setItem('companyLogo', companyLogo.value)
  } catch (error) {
    console.warn('加载Logo失败:', error)
  } finally {
    isLogoLoading.value = false
  }
}

const pageTitle = computed(() => {
  if (!isRouteReady.value) return ''
  
  const matched = route.matched[route.matched.length - 1]
  if (!matched) return ''
  
  const titleKey = matched.meta.titleKey as string
  if (titleKey) {
    return t(titleKey)
  }
  
  return ''
})

const isLoginPage = computed(() => {
  return route.path === '/login'
})

// 菜单渲染配置 —— 从 menuConfig 派生，加 icon 和翻译
interface MenuItem {
  path?: string
  name: string
  key?: string
  icon: typeof DataBoard
  permission: string | null
  superAdminOnly?: boolean
  children?: Array<{ path: string; name: string; permission: string | null }>
}

const iconMap: Record<string, any> = {
  DataBoard,
  OfficeBuilding,
  Connection,
  Grid,
  Monitor,
  Share,
  Box,
  Bell,
  Tickets,
  Reading,
  Memo,
  User,
  Avatar,
  Key,
  Setting,
  Lock,
  Message,
  MagicStick,
  ChatDotRound,
  Operation,
  Files,
}

const menuItems = computed((): Array<{ group: string; items: MenuItem[] }> => {
  return menuConfig.map((group) => ({
    group: group.groupKey ? t(group.groupKey) : '',
    items: group.items.map((item) => {
      const iconName = getIconForItem(item.nameKey)
      const result: MenuItem = {
        path: item.path,
        name: t(item.nameKey),
        key: item.key,
        icon: iconMap[iconName] || DataBoard,
        permission: item.permission,
        superAdminOnly: item.superAdminOnly,
      }
      if (item.children) {
        result.children = item.children.map((child) => ({
          path: child.path,
          name: t(child.nameKey),
          permission: child.permission,
        }))
      }
      return result
    }),
  }))
})

// 菜单图标：按功能一对一分配，避免重复
// 资源管理：场所/专线/网络；运营中心：设备/拓扑/备份/告警/变更/知识库/报表；系统：管理/安全/AI/日志
function getIconForItem(nameKey: string): string {
  const iconMap: Record<string, string> = {
    // 概览
    'dashboard.title': 'DataBoard',
    // 资源管理
    'sites.title': 'OfficeBuilding',   // 场所：办公楼
    'circuits.title': 'Connection',    // 专线：连接
    'ipam.title': 'Grid',              // IP 地址管理：网格
    // 运营中心
    'devices.title': 'Monitor',        // 设备：显示器
    'topology.title': 'Share',         // 拓扑：节点连线
    'backups.title': 'Box',            // 备份：箱子
    'alerts.title': 'Bell',            // 告警：铃铛
    'changes.title': 'Tickets',        // 变更记录：工单
    'knowledge.title': 'Reading',      // 知识库：阅读
    'reports.title': 'Memo',           // 报表：文档记录
    // 系统管理
    'system.userManagement': 'User',       // 用户：人像
    'system.roleManagement': 'Avatar',     // 角色：身份
    'system.ssoSettings': 'Key',           // 单点登录：密钥
    // 系统设置
    'system.settings': 'Setting',          // 系统设置：齿轮
    'system.security': 'Lock',             // 安全：锁
    'system.notifications': 'Message',     // 通知配置：消息
    'system.aiSettings': 'MagicStick',     // AI 设置：魔法棒
    'system.aiChatLogs': 'ChatDotRound',   // AI 对话记录：对话气泡
    'system.logsSettings': 'Operation',    // 日志采集配置：操作
    'system.logs': 'Files',                // 系统日志：文件
  }
  return iconMap[nameKey] || 'DataBoard'
}

// 检查菜单项是否有权限
function hasMenuPermission(permission: string | null): boolean {
  if (!permission) return true
  return authStore.hasPermission(permission)
}

// 超管专属菜单项（如 AI 设置）仅超级管理员可见
function isSuperAdminMenuItem(item: MenuItem): boolean {
  return !item.superAdminOnly || authStore.isAdmin()
}

// 过滤菜单
const filteredMenuItems = computed(() => {
  return menuItems.value.map(group => {
    const filteredItems = group.items.filter(item => {
      // 超管专属菜单项：非超管直接隐藏
      if (!isSuperAdminMenuItem(item)) return false
      // 如果是有子菜单的项目
      if (item.children) {
        // 检查是否有子项有权限
        return item.children.some(child => hasMenuPermission(child.permission))
      }
      return hasMenuPermission(item.permission)
    })
    return {
      ...group,
      items: filteredItems
    }
  }).filter(group => group.items.length > 0)
})

async function handleLogout() {
  await authStore.logout()
  await router.push('/login')
}

// 移动端底部Tab导航配置
const mobileTabs = [
  { path: '/', nameKey: 'nav.dashboard', icon: DataBoard },
  { path: '/circuits', nameKey: 'nav.circuits', icon: Connection },
  { path: '/alerts', nameKey: 'nav.alerts', icon: Bell },
  { path: '/profile', nameKey: 'nav.profile', icon: User }
]
</script>

<template>
  <div v-if="isLoginPage" class="login-wrapper">
    <div class="global-language-switcher"><LanguageSwitcher /></div>
    <RouterView />
  </div>
  
  <div v-else class="enterprise-shell">
    <!-- 移动端侧边栏遮罩 -->
    <div v-if="mobileSidebarOpen" class="mobile-sidebar-overlay" @click="mobileSidebarOpen = false"></div>
    <aside class="enterprise-sidebar" :class="{ collapsed: sidebarCollapsed, 'mobile-expanded': mobileSidebarOpen }">
      <div class="enterprise-brand">
        <div v-if="companyLogo" class="enterprise-brand-logo">
          <img :src="companyLogo" alt="Logo" class="brand-logo-image" />
        </div>
        <div v-else-if="!isLogoLoading" class="enterprise-brand-mark">C</div>
        <div v-else class="enterprise-brand-mark loading"></div>
        <div class="enterprise-brand-text" v-show="!sidebarCollapsed">
          <strong>{{ brandStore.brandNameZh }}</strong>
          <span>{{ brandStore.brandNameEn }}</span>
        </div>
      </div>

      <nav class="enterprise-nav">
        <div v-for="group in filteredMenuItems" :key="group.group" class="enterprise-nav-group">
          <div class="enterprise-nav-group-title" v-show="!sidebarCollapsed">{{ group.group }}</div>
          <div class="enterprise-nav-group-items">
            <template v-for="item in group.items" :key="item.name">
              <!-- 普通菜单项 -->
              <RouterLink 
                v-if="item.path && !item.children"
                :to="item.path" 
                class="enterprise-nav-item" 
                active-class="active"
                @click="mobileSidebarOpen = false"
                @mouseenter="showTooltip(item.name)"
                @mouseleave="hideTooltip"
              >
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.name }}</span>
                <div 
                  v-if="sidebarCollapsed && activeTooltip === item.name" 
                  class="nav-tooltip"
                  @mouseenter="showTooltip(item.name)"
                  @mouseleave="hideTooltip"
                >{{ item.name }}</div>
              </RouterLink>
              
              <!-- 带子菜单的项目 -->
              <div
                v-else-if="item.children"
                class="enterprise-nav-item has-children"
                :class="{ 'active': item.children.some(child => route.path.startsWith(child.path)) }"
                @click="item.key === 'ipam' ? toggleIpamMenu() : item.key === 'topology' ? toggleTopologyMenu() : item.key === 'backups' ? toggleBackupMenu() : null"
                @mouseenter="showTooltip(item.name)"
                @mouseleave="hideTooltip"
              >
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.name }}</span>
                <el-icon class="arrow-icon">
                  <ArrowUp v-if="(item.key === 'ipam' && ipamMenuOpen) || (item.key === 'backups' && backupMenuOpen) || (item.key === 'topology' && topologyMenuOpen)" />
                  <ArrowDown v-else />
                </el-icon>
                <div 
                  v-if="sidebarCollapsed && activeTooltip === item.name" 
                  class="nav-tooltip nav-tooltip-submenu"
                  @mouseenter="showTooltip(item.name)"
                  @mouseleave="hideTooltip"
                >
                  <div class="tooltip-title">{{ item.name }}</div>
                  <div class="tooltip-submenu">
                    <RouterLink 
                      v-for="child in item.children" 
                      :key="child.path"
                      :to="child.path" 
                      class="tooltip-subitem"
                    >
                      {{ child.name }}
                    </RouterLink>
                  </div>
                </div>
              </div>
              
              <!-- 子菜单 -->
              <div
                v-if="item.children"
                v-show="!sidebarCollapsed && ((item.key === 'ipam' && ipamMenuOpen) || (item.key === 'backups' && backupMenuOpen) || (item.key === 'topology' && topologyMenuOpen))"
                class="enterprise-nav-submenu"
              >
                <RouterLink 
                  v-for="child in item.children" 
                  :key="child.path"
                  :to="child.path" 
                  class="enterprise-nav-item sub-item" 
                  active-class="active"
                  v-show="hasMenuPermission(child.permission)"
                  :title="child.name"
                >
                  <span>{{ child.name }}</span>
                </RouterLink>
              </div>
            </template>
          </div>
        </div>
      </nav>
      
      <div class="sidebar-footer">
        <button 
          class="sidebar-toggle" 
          @click="sidebarCollapsed = !sidebarCollapsed"
          :aria-label="sidebarCollapsed ? t('common.expandSidebar') : t('common.collapseSidebar')"
          :aria-expanded="!sidebarCollapsed"
        >
          <svg v-if="sidebarCollapsed" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18l6-6-6-6"/>
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M15 18l-6-6 6-6"/>
          </svg>
        </button>
      </div>
    </aside>

    <main class="enterprise-workspace" :class="{ 'route-loading': !isRouteReady }">
      <header class="enterprise-topbar">
        <div class="enterprise-topbar-left">
          <button
            class="mobile-menu-btn"
            @click="mobileSidebarOpen = !mobileSidebarOpen"
            :aria-label="mobileSidebarOpen ? t('common.collapseSidebar') : t('common.expandSidebar')"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 6h18M3 12h18M3 18h18"/>
            </svg>
          </button>
          <h1 class="enterprise-page-title">
            <span v-if="pageTitle">{{ pageTitle }}</span>
            <span v-else class="page-title-loading"></span>
          </h1>
        </div>
        <div class="enterprise-topbar-right">
          <button
            class="ai-assistant-btn"
            @click="aiAssistantRef?.open()"
            :title="t('aiAssistant.title')"
            :aria-label="t('aiAssistant.title')"
          >
            <el-icon><ChatDotRound /></el-icon>
            <span class="ai-assistant-text">{{ t('aiAssistant.title') }}</span>
          </button>
          <button 
            class="global-search-btn" 
            @click="globalSearchRef?.open()"
            :aria-label="t('aiSearch.searchOrAsk')"
          >
            <el-icon><Search /></el-icon>
            <span class="search-btn-text">{{ t('aiSearch.searchOrAsk') }}</span>
            <kbd class="search-btn-kbd">⌘K</kbd>
          </button>
          <LanguageSwitcher />
          <div class="enterprise-user-info">
              <RouterLink to="/profile" class="user-profile-link">
                <el-icon><User /></el-icon>
                <span class="username">{{ authStore.user?.display_name || authStore.user?.username || 'admin' }}</span>
              </RouterLink>
              <el-button link @click="handleLogout">
                <el-icon><SwitchButton /></el-icon>
                <span class="logout-text">{{ $t('login.logout') }}</span>
              </el-button>
            </div>
        </div>
      </header>
      <section class="enterprise-content">
        <RouterView />
      </section>
    </main>

  </div>
  <!-- 移动端底部Tab导航（移到 enterprise-shell 外部，避免 flex 布局影响） -->
  <nav class="mobile-bottom-tabs" v-if="!isLoginPage">
    <RouterLink
      v-for="tab in mobileTabs"
      :key="tab.path"
      :to="tab.path"
      class="mobile-tab-item"
      :class="{ active: route.path === tab.path }"
    >
      <el-icon><component :is="tab.icon" /></el-icon>
      <span>{{ t(tab.nameKey) }}</span>
    </RouterLink>
  </nav>
  <GlobalSearch ref="globalSearchRef" />
  <AIAssistant ref="aiAssistantRef" />
</template>

<style scoped>
.login-wrapper {
  min-height: 100vh;
}

.enterprise-shell {
  display: flex;
  min-height: 100vh;
  background: var(--bg-secondary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

.enterprise-sidebar {
  width: 220px;
  background: linear-gradient(180deg, #001529 0%, #001a33 100%);
  color: rgba(255, 255, 255, 0.85);
  height: 100vh;
  position: fixed;
  left: 0;
  top: 0;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  z-index: 1000;
  box-shadow: 
    4px 0 20px rgba(0, 0, 0, 0.3),
    8px 0 40px rgba(0, 0, 0, 0.1);
}

.enterprise-sidebar::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(90deg, rgba(255,255,255,0.03) 0%, transparent 50%);
  pointer-events: none;
}

.enterprise-sidebar.collapsed {
  width: 64px;
}

.enterprise-workspace {
  margin-left: 220px;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  transition: margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.collapsed + .enterprise-workspace {
  margin-left: 64px;
}

.enterprise-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 64px;
  background: #fff;
  border-bottom: 1px solid var(--border-color, #e5e7eb);
  position: sticky;
  top: 0;
  z-index: 100;
  flex-shrink: 0;
}

.enterprise-topbar-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex: 1;
}

.enterprise-eyebrow {
  font-size: 12px;
  color: #8c8c8c;
  margin: 0;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.enterprise-page-title {
  font-size: 20px;
  font-weight: 600;
  color: #262626;
  margin: 0;
  min-height: 28px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.enterprise-page-title .page-title-loading {
  display: inline-block;
  width: 120px;
  height: 24px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e8e8e8 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: 4px;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.enterprise-workspace.route-loading {
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.2s ease, visibility 0.2s ease;
}

.enterprise-workspace:not(.route-loading) {
  opacity: 1;
  visibility: visible;
  transition: opacity 0.2s ease, visibility 0.2s ease;
}

.enterprise-topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.global-search-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  background: #f8f8f8;
  color: #8c8c8c;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  min-width: 220px;
}

.global-search-btn:hover {
  border-color: #d9d9d9;
  background: #f0f0f0;
  color: #595959;
}

.global-search-btn .el-icon {
  font-size: 16px;
}

.search-btn-text {
  flex: 1;
  text-align: left;
}

.search-btn-kbd {
  padding: 1px 6px;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
  font-size: 11px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  color: #bbb;
  background: #fff;
}

.ai-assistant-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid #1890ff;
  border-radius: 8px;
  background: linear-gradient(135deg, #1890ff 0%, #096dd9 100%);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.ai-assistant-btn:hover {
  box-shadow: 0 4px 14px rgba(24, 144, 255, 0.35);
  transform: translateY(-1px);
}

.ai-assistant-btn .el-icon {
  font-size: 16px;
}

.enterprise-search-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
}

.enterprise-user-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-profile-link {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #262626;
  text-decoration: none;
  font-size: 14px;
  transition: color 0.2s;
}

.user-profile-link:hover {
  color: #1890ff;
  text-decoration: none;
}

.enterprise-content {
  flex: 1;
  padding: 24px;
  min-width: 0;
  overflow-y: auto;
  overflow-x: auto;
}

.logout-text {
  margin-left: 4px;
}

.enterprise-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 64px;
  padding: 0 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  position: relative;
  gap: 12px;
}

.enterprise-brand-logo,
.enterprise-brand-mark {
  flex-shrink: 0;
}

.sidebar-toggle {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.65);
  cursor: pointer;
  padding: 6px;
  border-radius: 4px;
  transition: all 0.15s ease;
  width: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
}


.sidebar-toggle:hover {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}

.enterprise-brand-mark {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: linear-gradient(135deg, #1890ff 0%, #096dd9 100%);
  display: grid;
  place-items: center;
  color: white;
  font-weight: 700;
  font-size: 18px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 16px rgba(24, 144, 255, 0.3);
}

.enterprise-brand-mark.loading {
  background: rgba(24, 144, 255, 0.2);
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}

.enterprise-brand-mark:hover {
  transform: scale(1.05) rotate(2deg);
  box-shadow: 
    0 8px 32px rgba(24, 144, 255, 0.4),
    0 0 20px rgba(24, 144, 255, 0.2);
}

.enterprise-brand-logo {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.1);
}

.brand-logo-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.enterprise-brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.enterprise-brand-text strong {
  font-size: 15px;
  font-weight: 600;
  color: white;
}

.enterprise-brand-text span {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.45);
}

.enterprise-nav {
  padding: 16px 8px;
  overflow-y: auto;
  flex: 1;
}

.sidebar-footer {
  padding: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.enterprise-nav-group {
  margin-bottom: 8px;
}

.enterprise-nav-group-title {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
  padding: 8px 16px 4px;
  font-weight: 500;
  letter-spacing: 0.5px;
}

.enterprise-nav-group-items {
  display: grid;
  gap: 2px;
}

.enterprise-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.65);
  text-decoration: none;
  font-size: 14px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  transform-origin: left center;
}

.enterprise-nav-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: white;
  transform: translateX(4px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.enterprise-nav-item.active {
  background: linear-gradient(135deg, #1890ff 0%, #096dd9 100%);
  color: white;
  box-shadow: 0 4px 16px rgba(24, 144, 255, 0.3);
}

.enterprise-nav-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  background: white;
  border-radius: 0 2px 2px 0;
}

.enterprise-nav-item .el-icon {
  font-size: 20px;
  width: 20px;
  height: 20px;
  line-height: 20px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.enterprise-nav-item:hover .el-icon {
  transform: scale(1.1);
  filter: drop-shadow(0 0 8px rgba(24, 144, 255, 0.5));
}

.enterprise-nav-item.active .el-icon {
  filter: drop-shadow(0 0 10px rgba(255, 255, 255, 0.6));
}

.enterprise-nav-item.has-children {
  cursor: pointer;
}

.enterprise-nav-item.has-children .arrow-icon {
  margin-left: auto;
  font-size: 16px;
  width: 16px;
  height: 16px;
  line-height: 16px;
  transition: transform 0.2s ease;
}

.enterprise-nav-submenu {
  padding-left: 0;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 0 0 6px 6px;
  overflow: hidden;
}

.enterprise-nav-item.sub-item {
  padding-left: 48px;
  font-size: 13px;
}

/* 折叠状态下的样式 */
.enterprise-sidebar.collapsed .enterprise-nav-item span:not(.nav-tooltip) {
  display: none;
}

.enterprise-sidebar.collapsed .enterprise-nav-item {
  justify-content: center;
  padding: 12px;
}

.enterprise-sidebar.collapsed .enterprise-nav-item .el-icon {
  font-size: 20px;
  width: 20px;
  height: 20px;
  line-height: 20px;
}

.enterprise-sidebar.collapsed .enterprise-nav-item.has-children .arrow-icon {
  display: none;
}

.enterprise-sidebar.collapsed .enterprise-nav-item.sub-item {
  padding-left: 12px;
  justify-content: center;
}

.enterprise-sidebar.collapsed .enterprise-nav-group-title {
  display: none;
}

.enterprise-sidebar.collapsed .enterprise-nav {
  padding: 8px 0;
}

.enterprise-sidebar.collapsed .enterprise-nav-group {
  margin-bottom: 0;
}

.enterprise-sidebar.collapsed .enterprise-nav-group-items {
  gap: 6px;
}

/* P0-3a: 折叠态侧边栏 tooltip——之前模板引用但样式未定义，撑坏布局 */
.nav-tooltip {
  position: fixed;
  left: 64px;
  z-index: 2000;
  background: #fff;
  color: #262626;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.12);
  padding: 8px 12px;
  font-size: 13px;
  white-space: nowrap;
  pointer-events: auto;
}

.nav-tooltip-submenu {
  padding: 6px;
  white-space: normal;
  min-width: 160px;
}

.tooltip-title {
  font-size: 12px;
  font-weight: 600;
  color: #8c8c8c;
  padding: 4px 8px;
  border-bottom: 1px solid #f0f0f0;
  margin-bottom: 4px;
}

.tooltip-submenu {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tooltip-subitem {
  display: block;
  padding: 6px 8px;
  border-radius: 4px;
  color: #262626;
  text-decoration: none;
  font-size: 13px;
  transition: background 0.15s ease;
}

.tooltip-subitem:hover {
  background: #f0f7ff;
  color: #1890ff;
  text-decoration: none;
}

/* P0-3c: 登录页语言切换器定位——之前模板引用 .global-language-switcher 但无定义 */
.global-language-switcher {
  position: fixed;
  top: 16px;
  right: 24px;
  z-index: 1000;
}

/* #12b 移动端适配：<768px 侧边栏可叠加展开/收起，顶栏加汉堡按钮 */
.mobile-menu-btn {
  display: none;
  background: none;
  border: none;
  color: var(--text-primary, #262626);
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  align-items: center;
  justify-content: center;
  margin-right: 8px;
}

.mobile-menu-btn:hover {
  background: var(--bg-secondary, #f5f7fa);
}

@media (max-width: 768px) {
  .enterprise-sidebar {
    position: fixed;
    left: -240px;
    width: 240px;
    transition: left 0.3s ease;
  }

  /* 移动端：只有手动展开时才显示 */
  .enterprise-sidebar.mobile-expanded {
    left: 0;
    box-shadow: 4px 0 20px rgba(0, 0, 0, 0.3);
    z-index: 1500;
  }

  /* 移动端侧边栏遮罩 */
  .mobile-sidebar-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 1400;
  }

  .enterprise-workspace {
    margin-left: 0 !important;
    max-width: 100vw;
    overflow-x: hidden;
  }

  .enterprise-topbar {
    padding: 0 12px;
    height: 56px;
    min-width: 0;
  }

  .enterprise-topbar-left {
    min-width: 0;
    flex: 1;
  }

  .enterprise-topbar-right {
    flex-shrink: 0;
    gap: 8px;
  }

  .enterprise-page-title {
    font-size: 16px;
    max-width: 120px;
  }

  .enterprise-content {
    padding: 12px;
    overflow-x: hidden;
  }

  .mobile-menu-btn {
    display: flex;
  }

  .search-btn-text,
  .search-btn-kbd,
  .ai-assistant-text {
    display: none;
  }

  .global-search-btn {
    padding: 8px 10px;
    min-width: auto;
  }

  /* 移动端隐藏语言切换器和用户信息 */
  .language-switcher-wrapper,
  .enterprise-user-info {
    display: none !important;
  }

  /* 登录页语言切换器：适配移动端 */
  .global-language-switcher {
    top: 10px;
    right: 12px;
  }
}

/* 中等屏幕：<1024px 内容区缩减内边距 */
@media (max-width: 1024px) and (min-width: 769px) {
  .enterprise-content {
    padding: 16px;
  }
}

/* 移动端底部Tab导航 */
.mobile-bottom-tabs {
  display: none;
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: #fff;
  border-top: 1px solid #e4e7ed;
  padding: 8px 0;
  padding-bottom: calc(8px + env(safe-area-inset-bottom));
  z-index: 1000;
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.05);
}

.mobile-tab-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  color: #909399;
  text-decoration: none;
  transition: all 0.2s;
  font-size: 12px;
}

.mobile-tab-item .el-icon {
  font-size: 20px;
  margin-bottom: 4px;
}

.mobile-tab-item.active {
  color: #409eff;
}

.mobile-tab-item:hover {
  color: #66b1ff;
}

@media (max-width: 768px) {
  .mobile-bottom-tabs {
    display: flex;
    justify-content: space-around;
  }

  .enterprise-content {
    padding-bottom: 70px;
  }
}
</style>
