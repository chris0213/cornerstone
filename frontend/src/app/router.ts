import { createRouter, createWebHistory } from 'vue-router'
import LoginPage from '../features/auth/LoginPage.vue'
import ForbiddenPage from '../features/errors/ForbiddenPage.vue'

// 路由懒加载：首屏只加载 login/403，其余按需加载，预计减少 60%+ 首屏 JS 体积
const DashboardPage = () => import('../features/dashboard/DashboardPage.vue')
const CircuitsPage = () => import('../features/circuits/CircuitsPage.vue')
const CircuitDetail = () => import('../features/circuits/CircuitDetail.vue')
const CircuitChanges = () => import('../features/circuits/CircuitChanges.vue')
const IpamPage = () => import('../features/ipam/IpamPage.vue')
const VlanList = () => import('../features/ipam/VlanList.vue')
const DevicesPage = () => import('../features/devices/DevicesPage.vue')
const DeviceLinksList = () => import('../features/devices/DeviceLinksList.vue')
const BackupsPage = () => import('../features/backups/BackupsPage.vue')
const CredentialList = () => import('../features/backups/CredentialList.vue')
const BackupTaskList = () => import('../features/backups/BackupTaskList.vue')
const AlertsPage = () => import('../features/alerts/AlertsPage.vue')
const LogsPage = () => import('../features/system/LogsPage.vue')
const SettingsPage = () => import('../features/system/SettingsPage.vue')
const AISettingsPage = () => import('../features/system/AISettingsPage.vue')
const AIChatLogsPage = () => import('../features/system/AIChatLogsPage.vue')
const SitesPage = () => import('../features/sites/SitesPage.vue')
const SiteTopology = () => import('../features/topology/SiteTopology.vue')
const DeviceTopology = () => import('../features/topology/DeviceTopology.vue')
const ProfilePage = () => import('../features/system/ProfilePage.vue')
const RackViewPage = () => import('../features/rack/RackView.vue')
const ReportCenterPage = () => import('../features/reports/ReportCenterPage.vue')
const ChangesPage = () => import('../features/changes/ChangesPage.vue')
const KnowledgePage = () => import('../features/knowledge/KnowledgePage.vue')
const UserManagement = () => import('../features/system/UserManagement.vue')
const RoleManagement = () => import('../features/system/RoleManagement.vue')
const SSOSettingsPage = () => import('../features/system/SSOSettingsPage.vue')
const NotificationSettingsPage = () => import('../features/system/NotificationSettingsPage.vue')
const LogsSettingsPage = () => import('../features/system/LogsSettingsPage.vue')
const SecuritySettingsPage = () => import('../features/system/SecuritySettingsPage.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginPage, meta: { title: '' } },
    { path: '/403', name: 'forbidden', component: ForbiddenPage, meta: { title: '' } },
    { path: '/', name: 'dashboard', component: DashboardPage, meta: { requiresAuth: true, permission: null, titleKey: 'dashboard.title' } },
    { path: '/circuits', name: 'circuits', component: CircuitsPage, meta: { requiresAuth: true, permission: 'circuits:read', titleKey: 'circuits.title' } },
    { path: '/circuits/:id', name: 'circuit-detail', component: CircuitDetail, meta: { requiresAuth: true, permission: 'circuits:read', titleKey: 'circuits.title' } },
    
    { path: '/circuits/:id/changes', name: 'circuit-changes', component: CircuitChanges, meta: { requiresAuth: true, permission: 'circuits:read', titleKey: 'circuits.title' } },
    { path: '/ipam', name: 'ipam', component: IpamPage, meta: { requiresAuth: true, permission: 'ipam:read', titleKey: 'ipam.title' } },
    { path: '/ipam/vlans', name: 'ipam-vlans', component: VlanList, meta: { requiresAuth: true, permission: 'ipam:read', titleKey: 'ipam.vlans' } },
    { path: '/devices', name: 'devices', component: DevicesPage, meta: { requiresAuth: true, permission: 'devices:read', titleKey: 'devices.title' } },
    { path: '/devices/:id(\\d+)', redirect: to => ({ path: '/devices', query: { id: to.params.id } }) },
    { path: '/devices/links', name: 'device-links', component: DeviceLinksList, meta: { requiresAuth: true, permission: 'devices:read', titleKey: 'devices.title' } },
    { path: '/backups', name: 'backups', component: BackupsPage, meta: { requiresAuth: true, permission: 'backups:read', titleKey: 'backups.title' } },
    { path: '/backups/credentials', name: 'backup-credentials', component: CredentialList, meta: { requiresAuth: true, permission: 'backups:read', titleKey: 'backups.credentials' } },
    { path: '/backups/tasks', name: 'backup-tasks', component: BackupTaskList, meta: { requiresAuth: true, permission: 'backups:read', titleKey: 'backups.tasks' } },
    { path: '/alerts', name: 'alerts', component: AlertsPage, meta: { requiresAuth: true, permission: 'alerts:read', titleKey: 'alerts.title' } },
    { path: '/system', redirect: '/system/users' },
    { path: '/system/logs', name: 'system-logs', component: LogsPage, meta: { requiresAuth: true, permission: 'logs:read', titleKey: 'system.logs' } },
    { path: '/system/settings', name: 'system-settings', component: SettingsPage, meta: { requiresAuth: true, permission: 'system:read', titleKey: 'system.settings' } },
    { path: '/system/ai-settings', name: 'ai-settings', component: AISettingsPage, meta: { requiresAuth: true, permission: 'system:read', superAdminOnly: true, titleKey: 'system.aiSettings' } },
    { path: '/system/ai-chat-logs', name: 'ai-chat-logs', component: AIChatLogsPage, meta: { requiresAuth: true, permission: null, titleKey: 'system.aiChatLogs' } },
    { path: '/system/logs-settings', name: 'logs-settings', component: LogsSettingsPage, meta: { requiresAuth: true, permission: 'system:admin', titleKey: 'system.logsSettings' } },
    { path: '/system/security', name: 'system-security', component: SecuritySettingsPage, meta: { requiresAuth: true, permission: 'system:admin', titleKey: 'system.security' } },
    { path: '/system/users', name: 'system-users', component: UserManagement, meta: { requiresAuth: true, permission: 'system:admin', titleKey: 'system.userManagement' } },
    { path: '/system/roles', name: 'system-roles', component: RoleManagement, meta: { requiresAuth: true, permission: 'system:admin', titleKey: 'system.roleManagement' } },
    { path: '/system/sso', name: 'system-sso', component: SSOSettingsPage, meta: { requiresAuth: true, permission: 'system:admin', titleKey: 'system.ssoSettings' } },
    { path: '/system/notifications', name: 'system-notifications', component: NotificationSettingsPage, meta: { requiresAuth: true, permission: 'system:admin', titleKey: 'system.notifications' } },
    { path: '/profile', name: 'profile', component: ProfilePage, meta: { requiresAuth: true, permission: null, titleKey: 'system.profile' } },
    { path: '/sites', name: 'sites', component: SitesPage, meta: { requiresAuth: true, permission: 'sites:read', titleKey: 'sites.title' } },
    { path: '/topology/sites', name: 'topology-sites', component: SiteTopology, meta: { requiresAuth: true, permission: 'topology:read', titleKey: 'topology.siteTopology' } },
    { path: '/topology/devices', name: 'topology-devices', component: DeviceTopology, meta: { requiresAuth: true, permission: 'topology:read', titleKey: 'topology.deviceTopology' } },
    { path: '/topology/rack', name: 'topology-rack', component: RackViewPage, meta: { requiresAuth: true, permission: 'devices:read', titleKey: 'topology.rackTopology' } },
    { path: '/topology', redirect: '/topology/sites' },
    { path: '/inspection', redirect: '/reports' },
    { path: '/reports', name: 'reports', component: ReportCenterPage, meta: { requiresAuth: true, permission: 'reports:read', titleKey: 'reports.title' } },
    { path: '/changes', name: 'changes', component: ChangesPage, meta: { requiresAuth: true, permission: 'logs:read', titleKey: 'changes.title' } },
    { path: '/knowledge', name: 'knowledge', component: KnowledgePage, meta: { requiresAuth: true, permission: null, titleKey: 'knowledge.title' } },
    { path: '/rack-view', redirect: '/topology/rack' }
  ]
})

router.beforeEach(async (to, _from) => {
  const token = localStorage.getItem('access_token')
  const isLoggedIn = !!token
  
  // 如果路由需要认证，用户未登录，且不是登录页面
  if (to.meta.requiresAuth && !isLoggedIn && to.path !== '/login') {
    localStorage.setItem('redirect_after_login', to.fullPath)
    return '/login'
  }
  
  if (to.path === '/login' && isLoggedIn) {
    const redirectPath = localStorage.getItem('redirect_after_login') || '/'
    localStorage.removeItem('redirect_after_login')
    return redirectPath
  }
  
  // 检查权限和token有效性
  if (to.meta.requiresAuth && isLoggedIn) {
    // 动态导入auth store以避免循环依赖
    const { useAuthStore } = await import('../store/auth')
    const authStore = useAuthStore()
    
    // 如果用户信息还未加载，尝试加载
    if (!authStore.user) {
      try {
        await authStore.fetchUser()
      } catch (error) {
        // token无效，清除并重定向到登录页
        // axios 拦截器可能已触发跳转，这里加守卫避免重复
        if (router.currentRoute.value.path !== '/login') {
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          localStorage.setItem('redirect_after_login', to.fullPath)
          return '/login'
        }
        return false
      }
    }
    
    // 检查权限
    if (to.meta.permission && !authStore.hasPermission(to.meta.permission as string)) {
      return { name: 'forbidden' }
    }

    // 超管专属页面（如 AI 设置）：非超级管理员一律 403
    if (to.meta.superAdminOnly && !authStore.isAdmin()) {
      return { name: 'forbidden' }
    }
  }
  
  return true
})

// 路由切换后更新浏览器标签页标题
router.afterEach(async (to) => {
  const { useBrandStore } = await import('../store/brand')
  const brandStore = useBrandStore()
  const titleKey = to.meta.titleKey as string
  const { i18n } = await import('../i18n')
  const translatedTitle = titleKey ? i18n.global.t(titleKey) : undefined
  brandStore.updateDocumentTitle(translatedTitle)
})

/**
 * 提取路由权限映射 —— 用于与菜单配置做一致性断言
 * 返回 path → permission 的 Map（仅包含 requiresAuth 且有 permission 的路由）
 */
export function extractRoutePermissions(): Map<string, string | null> {
  const map = new Map<string, string | null>()
  for (const r of router.options.routes) {
    if (r.meta?.requiresAuth && r.meta.permission !== undefined) {
      map.set(r.path, r.meta.permission as string | null)
    }
  }
  return map
}

export default router
