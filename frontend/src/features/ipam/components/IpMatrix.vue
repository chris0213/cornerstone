<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import type { IPAddress } from '../../../types/domain'
import { ElTooltip } from 'element-plus'

const props = defineProps<{
  prefixId: number
  network: string
  ipList: IPAddress[]
  scanningCurrentIp?: string
  scanResults?: Record<string, boolean>
  scanPercent?: number
}>()

const emit = defineEmits<{
  (e: 'assign', address: string): void
  (e: 'view', ip: IPAddress): void
}>()

// 解析 CIDR：网络地址转长整型 + 主机容量
const ipToLong = (ip: string): number | null => {
  const o = ip.split('.').map(Number)
  if (o.length !== 4 || o.some(n => isNaN(n) || n < 0 || n > 255)) return null
  return ((o[0] << 24) | (o[1] << 16) | (o[2] << 8) | o[3]) >>> 0
}
const longToIp = (n: number) =>
  [`${(n >>> 24) & 255}`, `${(n >>> 16) & 255}`, `${(n >>> 8) & 255}`, `${n & 255}`].join('.')

const cidrInfo = computed(() => {
  const [ipStr, maskStr] = props.network.split('/')
  const base = ipToLong(ipStr || '')
  const mask = Number(maskStr)
  if (base === null || !Number.isInteger(mask) || mask < 8 || mask > 32) {
    // 无效 CIDR（脏数据如 "192.168.16/23"）退回 /24 行为
    const legacyBase = ipStr ? ipToLong(ipStr.split('.').slice(0, 3).concat('0').join('.')) ?? 0 : 0
    return { base: legacyBase, totalHosts: 254, valid: false }
  }
  return { base, totalHosts: Math.max(2 ** (32 - mask) - 2, 1), valid: true }
})

const isLargeNetwork = computed(() => cidrInfo.value.totalHosts > 512)

// 生成子网内所有主机地址（跳过网络地址，末尾广播地址自然落在范围外）
const allIPs = computed(() => {
  const { base, totalHosts, valid } = cidrInfo.value
  const ips: { address: string; data?: IPAddress }[] = []
  for (let i = 0; i < totalHosts; i++) {
    // 有效 CIDR：从网络地址+1 开始；无效退回旧逻辑（前3段.1-254）
    const address = valid
      ? longToIp(((base + 1 + i) >>> 0))
      : `${props.network.split('/')[0].split('.').slice(0, 3).join('.')}.${i + 1}`
    // 尝试匹配，同时处理可能的字段名不一致问题
    const found = props.ipList.find(ip => 
      ip.address === address || 
      (ip as any).Address === address ||
      (ip as any).ip === address
    )
    ips.push({ address, data: found })
  }
  return ips
})

// 按16列分组
const rows = computed(() => {
  const result: { address: string; data?: IPAddress }[][] = []
  for (let i = 0; i < allIPs.value.length; i += 16) {
    result.push(allIPs.value.slice(i, i + 16))
  }
  return result
})

// 跨多个 /24 时，在第三个八位组变化处插入分组标题（如 192.168.9.x）
const rowHeader = (rowIndex: number): string | null => {
  if (cidrInfo.value.totalHosts <= 256) return null
  const first = rows.value[rowIndex]?.[0]?.address
  if (!first) return null
  const o = first.split('.')
  if (rowIndex === 0) return `${o[0]}.${o[1]}.${o[2]}.x`
  const prev = rows.value[rowIndex - 1]?.[0]?.address.split('.')
  return prev && prev[2] !== o[2] ? `${o[0]}.${o[1]}.${o[2]}.x` : null
}

// 获取状态颜色
const getStatusColor = (ip: { address: string; data?: IPAddress }) => {
  if (!ip.data) return '#f5f5f5' // 灰色 - 未分配
  
  const status = ip.data.status
  const isOnline = ip.data.isOnline
  
  if (status === '已分配') {
    return isOnline === true ? '#52c41a' : isOnline === false ? '#ff4d4f' : '#1890ff'
  }
  if (status === '预留') return '#faad14'
  
  return '#f5f5f5'
}

// 获取工具提示内容
const getTooltipContent = (ip: { address: string; data?: IPAddress }) => {
  if (!ip.data) {
    return `<div><strong>${ip.address}</strong></div><div>状态: 未分配（点击分配）</div>`
  }
  
  const { data } = ip
  return `
    <div><strong>${data.address}</strong></div>
    <div>状态: ${data.status}</div>
    ${data.isOnline !== undefined ? `<div>在线: ${data.isOnline ? '是' : '否'}</div>` : ''}
    ${data.usage ? `<div>用途: ${data.usage}</div>` : ''}
    ${data.owner ? `<div>负责人: ${data.owner}</div>` : ''}
    ${data.expireAt ? `<div>到期: ${data.expireAt}</div>` : ''}
    ${data.macAddress ? `<div>MAC: ${data.macAddress}</div>` : ''}
    ${data.openPorts ? `<div>开放端口: ${data.openPorts.join(', ')}</div>` : ''}
  `
}

// 处理点击
const handleClick = (ip: { address: string; data?: IPAddress }) => {
  if (ip.data) {
    emit('view', ip.data)
  } else {
    emit('assign', ip.address)
  }
}

// ==================== 扫描动画 ====================
const isScanning = computed(() => !!props.scanningCurrentIp)

const isCurrentScanning = (address: string) => props.scanningCurrentIp === address

const getScanResultClass = (address: string) => {
  const r = props.scanResults?.[address]
  if (r === true) return 'scan-hit'
  if (r === false) return 'scan-miss'
  return ''
}

// 自动滚动到正在扫描的格子
const gridRef = ref<HTMLElement | null>(null)
watch(() => props.scanningCurrentIp, async (ip) => {
  if (!ip || !gridRef.value) return
  await nextTick()
  gridRef.value.querySelector(`[data-ip="${ip}"]`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'nearest',
  })
})
</script>

<template>
  <div class="ip-matrix-container">
    <!-- 扫描中：顶部进度条 -->
    <div v-if="isScanning" class="scan-progress-bar">
      <div class="scan-progress-track">
        <div class="scan-progress-fill" :style="{ width: `${scanPercent || 0}%` }"></div>
      </div>
      <span class="scan-progress-text">扫描中 {{ Math.round(scanPercent || 0) }}%</span>
    </div>

    <!-- 矩阵网格 -->
    <div class="matrix-scroll" :class="{ 'matrix-scroll-large': isLargeNetwork }">
      <div class="matrix-grid" ref="gridRef" :class="{ 'matrix-scanning': isScanning }">
        <template v-for="(row, rowIndex) in rows" :key="rowIndex">
          <div v-if="rowHeader(rowIndex)" class="matrix-row-header">{{ rowHeader(rowIndex) }}</div>
          <div class="matrix-row">
            <ElTooltip
              v-for="ip in row"
              :key="ip.address"
              :content="getTooltipContent(ip)"
              placement="top"
              effect="dark"
              raw-content
              :show-after="150"
              :hide-after="0"
            >
              <div 
                :data-ip="ip.address"
                class="ip-block" 
                :class="[
                  { 'ip-block-assigned': !!ip.data, 'ip-block-scanning': isCurrentScanning(ip.address), 'ip-block-small': isLargeNetwork },
                  getScanResultClass(ip.address),
                ]"
                :style="{ backgroundColor: getStatusColor(ip) }"
                @click="handleClick(ip)"
              >
                <span class="ip-last-octet">{{ ip.address.split('.').pop() }}</span>
              </div>
            </ElTooltip>
          </div>
        </template>
      </div>
    </div>
    
    <!-- 图例 -->
    <div class="matrix-legend">
      <div class="legend-item">
        <span class="legend-color" style="background-color: #52c41a"></span>
        <span class="legend-label">已分配(在线)</span>
      </div>
      <div class="legend-item">
        <span class="legend-color" style="background-color: #1890ff"></span>
        <span class="legend-label">已分配(未知)</span>
      </div>
      <div class="legend-item">
        <span class="legend-color" style="background-color: #ff4d4f"></span>
        <span class="legend-label">已分配(离线)</span>
      </div>
      <div class="legend-item">
        <span class="legend-color" style="background-color: #faad14"></span>
        <span class="legend-label">预留</span>
      </div>
      <div class="legend-item">
        <span class="legend-color" style="background-color: #f5f5f5"></span>
        <span class="legend-label">未分配</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ip-matrix-container {
  padding: 16px;
}

.matrix-grid {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 大网络（>512 主机）：限高限宽滚动 */
.matrix-scroll-large {
  max-height: 520px;
  overflow-y: auto;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 8px;
}

.matrix-row-header {
  font-size: 12px;
  font-weight: 600;
  color: rgba(0, 0, 0, 0.45);
  margin-top: 8px;
  padding-bottom: 2px;
  border-bottom: 1px dashed #e8e8e8;
}

.matrix-row {
  display: flex;
  gap: 4px;
}

/* 大网络小格子（隐藏末段数字改为 hover 显示） */
.ip-block-small {
  width: 20px;
  height: 20px;
  border-radius: 3px;
}

.ip-block-small .ip-last-octet {
  display: none;
}

.ip-block-small:hover .ip-last-octet {
  display: block;
}

.ip-block {
  width: 32px;
  height: 32px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.ip-block:hover {
  transform: scale(1.15);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  z-index: 10;
}

.ip-last-octet {
  font-size: 10px;
  font-weight: 600;
  color: rgba(0, 0, 0, 0.55);
  line-height: 1;
  user-select: none;
}

.ip-block-assigned .ip-last-octet {
  color: #fff;
}

/* ==================== 扫描动画 ==================== */

/* 顶部进度条 */
.scan-progress-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.scan-progress-track {
  flex: 1;
  height: 8px;
  background: #f0f0f0;
  border-radius: 4px;
  overflow: hidden;
}

.scan-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #69c0ff, #1890ff);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.scan-progress-text {
  font-size: 13px;
  font-weight: 600;
  color: #1890ff;
  white-space: nowrap;
}

/* 正在探测的格子：实心蓝色 + 大脉冲光环 */
.ip-block-scanning {
  background-color: #1890ff !important;
  animation: scan-pulse 0.8s ease-out infinite;
  z-index: 5;
}

.ip-block-scanning .ip-last-octet {
  color: #fff !important;
}

@keyframes scan-pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(24, 144, 255, 0.9);
  }
  70% {
    box-shadow: 0 0 0 12px rgba(24, 144, 255, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(24, 144, 255, 0);
  }
}

/* 扫描命中（在线）：亮绿实心闪烁 */
.scan-hit {
  background-color: #52c41a !important;
  animation: hit-flash 0.6s ease-out;
}

.scan-hit .ip-last-octet {
  color: #fff !important;
}

@keyframes hit-flash {
  0% {
    box-shadow: 0 0 0 0 rgba(82, 196, 26, 0.9);
    transform: scale(1.4);
  }
  60% {
    box-shadow: 0 0 0 10px rgba(82, 196, 26, 0);
    transform: scale(1.1);
  }
  100% {
    transform: scale(1);
  }
}

/* 扫描未命中（离线/无响应）：明显变暗 */
.scan-miss {
  filter: grayscale(1);
  opacity: 0.45;
}

.matrix-legend {
  display: flex;
  gap: 20px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f0f0f0;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-color {
  width: 16px;
  height: 16px;
  border-radius: 3px;
}

.legend-label {
  font-size: 12px;
  color: #666;
}
</style>
