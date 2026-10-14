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
}>()

const emit = defineEmits<{
  (e: 'assign', address: string): void
  (e: 'view', ip: IPAddress): void
}>()

// 生成所有254个IP地址
const allIPs = computed(() => {
  const ips: { address: string; data?: IPAddress }[] = []
  // 从网络地址中提取前三个八位组
  const parts = props.network.split('/')[0].split('.')
  if (parts.length >= 3) {
    const base = parts.slice(0, 3).join('.')
    for (let i = 1; i <= 254; i++) {
      const address = `${base}.${i}`
      // 尝试匹配，同时处理可能的字段名不一致问题
      const found = props.ipList.find(ip => 
        ip.address === address || 
        (ip as any).Address === address ||
        (ip as any).ip === address
      )
      ips.push({ address, data: found })
    }
  }
  return ips
})

// 按16列分组
const rows = computed(() => {
  const result: { address: string; data?: IPAddress }[][] = []
  for (let i = 0; i < 254; i += 16) {
    result.push(allIPs.value.slice(i, Math.min(i + 16, 254)))
  }
  return result
})

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
    <!-- 矩阵网格 -->
    <div class="matrix-grid" ref="gridRef" :class="{ 'matrix-scanning': isScanning }">
      <div v-for="(row, rowIndex) in rows" :key="rowIndex" class="matrix-row">
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
              { 'ip-block-assigned': !!ip.data, 'ip-block-scanning': isCurrentScanning(ip.address) },
              getScanResultClass(ip.address),
            ]"
            :style="{ backgroundColor: getStatusColor(ip) }"
            @click="handleClick(ip)"
          >
            <span class="ip-last-octet">{{ ip.address.split('.').pop() }}</span>
          </div>
        </ElTooltip>
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

.matrix-row {
  display: flex;
  gap: 4px;
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
