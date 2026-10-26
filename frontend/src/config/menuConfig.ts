/**
 * 菜单权限配置 —— 单一数据源
 * 
 * 此文件同时被 App.vue（渲染菜单）和测试（权限一致性断言）引用。
 * 新增菜单项时，必须同步更新 router.ts 中对应路由的 meta.permission。
 */

export interface MenuChild {
  path: string
  nameKey: string
  permission: string | null
}

export interface MenuItemConfig {
  path?: string
  nameKey: string
  key?: string
  permission: string | null
  /** 仅超级管理员可见/可访问（叠加在 permission 之上，如 AI 设置，后端接口已收紧为 super_admin） */
  superAdminOnly?: boolean
  children?: MenuChild[]
}

export interface MenuGroup {
  groupKey: string
  items: MenuItemConfig[]
}

export const menuConfig: MenuGroup[] = [
  {
    groupKey: '',
    items: [
      { path: '/', nameKey: 'dashboard.title', permission: null }
    ]
  },
  {
    groupKey: 'menuGroups.resourceManagement',
    items: [
      { path: '/sites', nameKey: 'sites.title', permission: 'sites:read' },
      { path: '/circuits', nameKey: 'circuits.title', permission: 'circuits:read' },
      {
        key: 'ipam',
        nameKey: 'ipam.title',
        permission: 'ipam:read',
        children: [
          { path: '/ipam', nameKey: 'ipam.ipAddress', permission: 'ipam:read' },
          { path: '/ipam/vlans', nameKey: 'ipam.vlans', permission: 'ipam:read' }
        ]
      }
    ]
  },
  {
    groupKey: 'menuGroups.operationsCenter',
    items: [
      { path: '/devices', nameKey: 'devices.title', permission: 'devices:read' },
      {
        key: 'topology',
        nameKey: 'topology.title',
        permission: 'topology:read',
        children: [
          { path: '/topology/sites', nameKey: 'topology.siteTopology', permission: 'topology:read' },
          { path: '/topology/devices', nameKey: 'topology.deviceTopology', permission: 'topology:read' },
          { path: '/topology/rack', nameKey: 'topology.rackTopology', permission: 'devices:read' }
        ]
      },
      {
        key: 'backups',
        nameKey: 'backups.title',
        permission: 'backups:read',
        children: [
          { path: '/backups', nameKey: 'backups.backupHistory', permission: 'backups:read' },
          { path: '/backups/credentials', nameKey: 'backups.credentials', permission: 'backups:read' },
          { path: '/backups/tasks', nameKey: 'backups.tasks', permission: 'backups:read' }
        ]
      },
      { path: '/alerts', nameKey: 'alerts.title', permission: 'alerts:read' },
      { path: '/changes', nameKey: 'changes.title', permission: 'logs:read' },
      { path: '/knowledge', nameKey: 'knowledge.title', permission: null },
      { path: '/reports', nameKey: 'reports.title', permission: 'reports:read' }
    ]
  },
  {
    groupKey: 'menuGroups.systemManagement',
    items: [
      { path: '/system/users', nameKey: 'system.userManagement', permission: 'system:admin' },
      { path: '/system/roles', nameKey: 'system.roleManagement', permission: 'system:admin' },
      { path: '/system/sso', nameKey: 'system.ssoSettings', permission: 'system:admin' }
    ]
  },
  {
    groupKey: 'menuGroups.systemSettings',
    items: [
      { path: '/system/settings', nameKey: 'system.settings', permission: 'system:read' },
      { path: '/system/security', nameKey: 'system.security', permission: 'system:admin' },
      { path: '/system/notifications', nameKey: 'system.notifications', permission: 'system:admin' },
      { path: '/system/ai-settings', nameKey: 'system.aiSettings', permission: 'system:read', superAdminOnly: true },
      { path: '/system/ai-chat-logs', nameKey: 'system.aiChatLogs', permission: null },
      { path: '/system/logs-settings', nameKey: 'system.logsSettings', permission: 'system:admin' }
    ]
  },
  {
    groupKey: '',
    items: [
      { path: '/system/logs', nameKey: 'system.logs', permission: 'logs:read' }
    ]
  }
]

/**
 * 提取所有菜单项（含子项）的 path → permission 映射
 * 用于与 router meta 做一致性断言
 */
export function extractMenuRoutePermissions(): Map<string, string | null> {
  const map = new Map<string, string | null>()
  for (const group of menuConfig) {
    for (const item of group.items) {
      if (item.path) {
        map.set(item.path, item.permission)
      }
      if (item.children) {
        for (const child of item.children) {
          map.set(child.path, child.permission)
        }
      }
    }
  }
  return map
}
