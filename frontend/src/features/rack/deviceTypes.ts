// 设备类型枚举 → i18n 文案
// 与设备页 DevicesPage.deviceTypeOptions 保持同一套枚举与 i18n key（devices.typeXxx）
const DEVICE_TYPE_LABEL_KEYS: Record<string, string> = {
  switch: 'devices.typeSwitch',
  router: 'devices.typeRouter',
  firewall: 'devices.typeFirewall',
  server: 'devices.typeServer',
  ap: 'devices.typeAP',
  'wireless-controller': 'devices.typeWirelessController',
  'load-balancer': 'devices.typeLoadBalancer',
  'ids-ips': 'devices.typeIdsIps',
  waf: 'devices.typeWaf',
  vpn: 'devices.typeVpn',
  storage: 'devices.typeStorage',
  other: 'devices.typeOther',
}

// 类型枚举 → 本地化文案；未知值原样回退（与设备页 typeText 行为一致）
export function deviceTypeText(t: (key: string) => string, type: string | null | undefined): string {
  if (!type) return '—'
  const key = DEVICE_TYPE_LABEL_KEYS[type]
  return key ? t(key) : type
}
