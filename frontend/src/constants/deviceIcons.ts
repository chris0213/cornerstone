/* ============================================================
   基石 Cornerstone · 网络设备图标库规范
   严格按照规范文件实现，不得自行修改颜色和图标
   ============================================================ */

export const DEVICE_TYPE_CONFIG: Record<string, {
  color: string
  bgColor: string
  borderColor: string
  label: string
  group: string
  iconClass: string
  svgInline?: string
}> = {
  // ── 核心网络设备 ──────────────────────────────────────────
  'router': {
    color: '#E6A23C',
    bgColor: 'rgba(230,162,60,0.15)',
    borderColor: 'rgba(230,162,60,0.4)',
    label: '路由器',
    group: '核心网络设备',
    iconClass: 'ti ti-router',
  },
  'core-switch': {
    color: '#409EFF',
    bgColor: 'rgba(64,158,255,0.15)',
    borderColor: 'rgba(64,158,255,0.4)',
    label: '核心交换机',
    group: '核心网络设备',
    iconClass: 'ti ti-switch',
  },
  'access-switch': {
    color: '#79BBFF',
    bgColor: 'rgba(121,187,255,0.12)',
    borderColor: 'rgba(121,187,255,0.35)',
    label: '接入交换机',
    group: '核心网络设备',
    iconClass: 'ti ti-switch-2',
  },
  'firewall': {
    color: '#64748B',
    bgColor: 'rgba(100,116,139,0.12)',
    borderColor: 'rgba(100,116,139,0.35)',
    label: '防火墙',
    group: '核心网络设备',
    iconClass: 'ti ti-shield',
  },
  'load-balancer': {
    color: '#9B59B6',
    bgColor: 'rgba(155,89,182,0.15)',
    borderColor: 'rgba(155,89,182,0.4)',
    label: '负载均衡',
    group: '核心网络设备',
    iconClass: 'ti ti-arrow-fork',
  },
  'ap': {
    color: '#67C23A',
    bgColor: 'rgba(103,194,58,0.15)',
    borderColor: 'rgba(103,194,58,0.4)',
    label: '无线AP',
    group: '核心网络设备',
    iconClass: 'ti ti-wifi',
  },
  'ac': {
    color: '#4CAF50',
    bgColor: 'rgba(76,175,80,0.15)',
    borderColor: 'rgba(76,175,80,0.4)',
    label: '无线控制器',
    group: '核心网络设备',
    iconClass: 'ti ti-broadcast',
  },
  'sdwan': {
    color: '#00BCD4',
    bgColor: 'rgba(0,188,212,0.15)',
    borderColor: 'rgba(0,188,212,0.4)',
    label: 'SD-WAN',
    group: '核心网络设备',
    iconClass: '',
    // SD-WAN 使用内联 SVG，不用 Tabler Icons
    svgInline: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="5" cy="5" r="2" fill="#00BCD4"/>
  <circle cx="19" cy="5" r="2" fill="#00BCD4"/>
  <circle cx="5" cy="19" r="2" fill="#00BCD4"/>
  <circle cx="19" cy="19" r="2" fill="#00BCD4"/>
  <circle cx="12" cy="12" r="2.5" fill="#00BCD4"/>
  <line x1="7" y1="5" x2="10.5" y2="10.5" stroke="#00BCD4" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="17" y1="5" x2="13.5" y2="10.5" stroke="#00BCD4" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="7" y1="19" x2="10.5" y2="13.5" stroke="#00BCD4" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="17" y1="19" x2="13.5" y2="13.5" stroke="#00BCD4" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="7" y1="6" x2="17" y2="6" stroke="#00BCD4" stroke-width="1" stroke-dasharray="2 2" stroke-linecap="round"/>
  <line x1="5" y1="7" x2="5" y2="17" stroke="#00BCD4" stroke-width="1" stroke-dasharray="2 2" stroke-linecap="round"/>
</svg>`,
  },

  // ── 服务器与终端 ───────────────────────────────────────────
  'server': {
    color: '#36CFC9',
    bgColor: 'rgba(54,207,201,0.15)',
    borderColor: 'rgba(54,207,201,0.4)',
    label: '服务器',
    group: '服务器与终端',
    iconClass: 'ti ti-server',
  },
  'pc': {
    color: '#8899AA',
    bgColor: 'rgba(136,153,170,0.15)',
    borderColor: 'rgba(136,153,170,0.35)',
    label: 'PC / 工作站',
    group: '服务器与终端',
    iconClass: 'ti ti-device-desktop',
  },
  'laptop': {
    color: '#8899AA',
    bgColor: 'rgba(136,153,170,0.15)',
    borderColor: 'rgba(136,153,170,0.35)',
    label: '笔记本',
    group: '服务器与终端',
    iconClass: 'ti ti-device-laptop',
  },
  'printer': {
    color: '#909399',
    bgColor: 'rgba(144,147,153,0.12)',
    borderColor: 'rgba(144,147,153,0.3)',
    label: '打印机',
    group: '服务器与终端',
    iconClass: 'ti ti-printer',
  },
  'nas': {
    color: '#2D5BE3',
    bgColor: 'rgba(45,91,227,0.15)',
    borderColor: 'rgba(45,91,227,0.4)',
    label: 'NAS / 存储',
    group: '服务器与终端',
    iconClass: 'ti ti-database',
  },
  'camera': {
    color: '#7B61FF',
    bgColor: 'rgba(123,97,255,0.15)',
    borderColor: 'rgba(123,97,255,0.4)',
    label: '网络摄像头',
    group: '服务器与终端',
    iconClass: 'ti ti-camera',
  },

  // ── 安全设备 ───────────────────────────────────────────────
  'ids-ips': {
    color: '#E85F5C',
    bgColor: 'rgba(232,95,92,0.15)',
    borderColor: 'rgba(232,95,92,0.4)',
    label: 'IDS / IPS',
    group: '安全设备',
    iconClass: 'ti ti-eye',
  },
  'vpn': {
    color: '#7B61FF',
    bgColor: 'rgba(123,97,255,0.15)',
    borderColor: 'rgba(123,97,255,0.4)',
    label: 'VPN 网关',
    group: '安全设备',
    iconClass: 'ti ti-lock',
  },
  'waf': {
    color: '#FF7A45',
    bgColor: 'rgba(255,122,69,0.15)',
    borderColor: 'rgba(255,122,69,0.4)',
    label: 'WAF',
    group: '安全设备',
    iconClass: 'ti ti-shield-check',
  },
  'sandbox': {
    color: '#C41D7F',
    bgColor: 'rgba(196,29,127,0.12)',
    borderColor: 'rgba(196,29,127,0.35)',
    label: '沙箱',
    group: '安全设备',
    iconClass: 'ti ti-box',
  },

  // ── 逻辑节点 ───────────────────────────────────────────────
  'internet': {
    color: '#40A9FF',
    bgColor: 'rgba(64,169,255,0.12)',
    borderColor: 'rgba(64,169,255,0.35)',
    label: '互联网 / 云',
    group: '逻辑节点',
    iconClass: 'ti ti-cloud',
  },
  'isp': {
    color: '#909399',
    bgColor: 'rgba(96,98,102,0.12)',
    borderColor: 'rgba(96,98,102,0.3)',
    label: '运营商',
    group: '逻辑节点',
    iconClass: 'ti ti-antenna',
  },
  'datacenter': {
    color: '#4A90D9',
    bgColor: 'rgba(31,78,121,0.18)',
    borderColor: 'rgba(31,78,121,0.4)',
    label: '数据中心',
    group: '逻辑节点',
    iconClass: 'ti ti-building',
  },
  'site': {
    color: '#1D9E75',
    bgColor: 'rgba(29,158,117,0.15)',
    borderColor: 'rgba(29,158,117,0.4)',
    label: '站点 / 办公室',
    group: '逻辑节点',
    iconClass: 'ti ti-home',
  },
  'unknown': {
    color: '#909399',
    bgColor: 'rgba(144,147,153,0.10)',
    borderColor: 'rgba(144,147,153,0.25)',
    label: '未知设备',
    group: '逻辑节点',
    iconClass: 'ti ti-question-mark',
  },
}

// 按分组获取图标列表（用于 IconPicker 组件）
export const DEVICE_ICON_GROUPS = [
  '核心网络设备',
  '服务器与终端',
  '安全设备',
  '逻辑节点',
]

export function getIconConfig(type: string) {
  return DEVICE_TYPE_CONFIG[type] ?? DEVICE_TYPE_CONFIG['unknown']
}