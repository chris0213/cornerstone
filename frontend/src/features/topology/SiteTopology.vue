<template>
  <div class="site-topology">
    <div class="topology-header">
      <el-input
        v-model="searchKeyword"
        :placeholder="t('topology.searchPlaceholder')"
        class="search-input"
        clearable
        @keyup.enter="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <div class="toolbar">
        <el-button :icon="Refresh" :title="t('topology.refreshData')" @click="loadSiteData" class="toolbar-btn" />
        <el-button :icon="Refresh" :title="t('topology.forceLayout')" @click="runForceLayout" :loading="isLayoutRunning" class="toolbar-btn" />
        <el-button :icon="Grid" :title="t('topology.gridLayout')" @click="resetLayout" class="toolbar-btn" />
        <el-button :icon="ZoomIn" :title="t('topology.zoomIn')" @click="zoomIn" class="toolbar-btn" />
        <el-button :icon="ZoomOut" :title="t('topology.zoomOut')" @click="zoomOut" class="toolbar-btn" />
        <el-button :icon="FullScreen" :title="t('topology.fullscreen')" @click="toggleFullscreen" class="toolbar-btn" />
      </div>
    </div>

    <div class="topology-canvas" ref="canvasWrapper">
      <svg
        :width="canvasWidth"
        :height="canvasHeight"
        class="topology-svg"
        @mousedown="startPan"
        @mousemove="onMouseMove"
        @mouseup="endMouseUp"
        @mouseleave="endMouseUp"
        @wheel="onWheel"
      >
        <defs>
          <marker
            id="arrow"
            markerWidth="10"
            markerHeight="10"
            refX="9"
            refY="3"
            orient="auto"
            markerUnits="strokeWidth"
          >
            <path d="M0,0 L0,6 L9,3 z" fill="#666" />
          </marker>
          <marker
            id="arrow-red"
            markerWidth="10"
            markerHeight="10"
            refX="9"
            refY="3"
            orient="auto"
            markerUnits="strokeWidth"
          >
            <path d="M0,0 L0,6 L9,3 z" fill="var(--color-danger)" />
          </marker>
        </defs>

        <g :transform="`translate(${panX}, ${panY}) scale(${scale})`">
          <!-- 渲染站点专线边 -->
          <g v-for="edge in topologyEdges" :key="'edge-' + edge.id">
            <line
              :x1="getNodePosition(edge.source).x"
              :y1="getNodePosition(edge.source).y"
              :x2="getNodePosition(edge.target).x"
              :y2="getNodePosition(edge.target).y"
              class="topology-edge"
              :class="[edge.type, edge.status]"
              :marker-end="edge.status === 'offline' || edge.status === 'critical' ? 'url(#arrow-red)' : 'url(#arrow)'"
            />
            <!-- 边标签 -->
            <text
              :x="(getNodePosition(edge.source).x + getNodePosition(edge.target).x) / 2"
              :y="(getNodePosition(edge.source).y + getNodePosition(edge.target).y) / 2 - 5"
              text-anchor="middle"
              class="edge-label"
            >
              {{ edge.bandwidth_label || edge.type }}
            </text>
          </g>

          <!-- 渲染站点节点 -->
          <g
            v-for="node in topologyNodes"
            :key="'node-' + node.id"
            :transform="`translate(${getNodePosition(node.id).x}, ${getNodePosition(node.id).y})`"
            class="topology-node site-node"
            :class="{ 'node-selected': selectedNodeId === node.id, 'node-filtered': isFiltered(node.id) }"
            @mousedown.stop="startDrag(node.id, $event)"
            @mouseenter="showSiteTooltip(node as TopologyNode, $event)"
            @mouseleave="hideTooltip"
            @click="selectNode(node as TopologyNode)"
          >
            <circle
              :r="nodeRadius"
              class="node-circle"
              :class="getNodeClass(node as TopologyNode)"
            />
            <!-- 状态指示灯 -->
            <circle
              :cx="nodeRadius - 8"
              :cy="-nodeRadius + 8"
              r="6"
              class="status-dot"
              :fill="getStatusColor(node.status)"
            />
            <text
              :x="0"
              :y="-8"
              text-anchor="middle"
              class="node-name"
            >
              {{ node.name }}
            </text>
            <text
              :x="0"
              :y="12"
              text-anchor="middle"
              class="node-city"
            >
              {{ (node as TopologyNode).city }}
            </text>
          </g>
        </g>
      </svg>

      <div class="tooltip" v-if="tooltipVisible" :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }">
        <div class="tooltip-title">
          {{ t('topology.tooltipTitle') }}
        </div>
        <div class="tooltip-content">
          <div>{{ t('topology.tooltipCity') }} {{ (tooltipData as TopologyNode).city }}</div>
          <div>{{ t('topology.tooltipStatus') }} {{ getStatusText((tooltipData as TopologyNode).status) }}</div>
          <div>{{ t('topology.tooltipDevices') }} {{ (tooltipData as TopologyNode).device_count }}</div>
          <div>{{ t('topology.tooltipCircuits') }} {{ (tooltipData as TopologyNode).circuit_count }}</div>
        </div>
      </div>
    </div>

    <div class="topology-legend">
      <div class="legend-item">
        <span class="status-dot" style="background: var(--color-success)"></span> {{ t('topology.normal') }}
      </div>
      <div class="legend-item">
        <span class="status-dot" style="background: var(--color-warning)"></span> {{ t('topology.warning') }}
      </div>
      <div class="legend-item">
        <span class="status-dot" style="background: var(--color-text-3)"></span> {{ t('topology.offline') }}
      </div>
      <div class="legend-item">
        <span class="status-dot" style="background: var(--color-danger)"></span> {{ t('topology.critical') }}
      </div>
      <!-- 专线类型 -->
      <div class="legend-section">{{ t('topology.circuitType') }}</div>
      <div class="legend-item">
        <span class="legend-line internet"></span> {{ t('topology.internet') }}
      </div>
      <div class="legend-item">
        <span class="legend-line mpls"></span> MPLS
      </div>
      <div class="legend-item">
        <span class="legend-line sdwan"></span> SD-WAN
      </div>
      <div class="legend-item">
        <span class="legend-line fiber"></span> {{ t('topology.fiber') }}
      </div>
    </div>

    <!-- 站点详情抽屉 -->
    <el-drawer
      :title="selectedNode?.name || t('topology.siteDetail')"
      :visible="drawerVisible"
      direction="rtl"
      @close="drawerVisible = false"
    >
      <el-descriptions :column="2" border>
        <el-descriptions-item :label="t('topology.siteName')">{{ selectedNode?.name || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('topology.city')">{{ selectedNode?.city || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('topology.status')">
          <el-tag :type="getStatusTagType(selectedNode?.status || '')">
            {{ getStatusText(selectedNode?.status || '') }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item :label="t('topology.contact')">{{ selectedNode?.contact || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('topology.phone')">{{ selectedNode?.phone || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('topology.deviceCount')">{{ selectedNode?.device_count || 0 }}</el-descriptions-item>
        <el-descriptions-item :label="t('topology.circuitCount')">{{ selectedNode?.circuit_count || 0 }}</el-descriptions-item>
      </el-descriptions>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search, Refresh, Grid, ZoomIn, ZoomOut, FullScreen } from '@element-plus/icons-vue'
import { getSiteGraph, type TopologyNode, type TopologyEdge } from '../../api/topology'

const { t } = useI18n()

// 画布状态
const canvasWrapper = ref<HTMLElement | null>(null)
const canvasWidth = ref(800)
const canvasHeight = ref(600)
const scale = ref(1)
const panX = ref(0)
const panY = ref(0)

// 数据状态
const topologyNodes = ref<TopologyNode[]>([])
const topologyEdges = ref<TopologyEdge[]>([])
const selectedNodeId = ref<string | null>(null)
const selectedNode = ref<TopologyNode | null>(null)

// 搜索状态
const searchKeyword = ref('')

// 拖拽状态
const isDragging = ref(false)
const draggingNodeId = ref<string | null>(null)
const dragOffset = ref({ x: 0, y: 0 })
const isPanning = ref(false)
const panOffset = ref({ x: 0, y: 0 })

// 布局状态
const isLayoutRunning = ref(false)
const nodePositions = ref<Record<string, { x: number; y: number }>>({})
const layoutAnimationId = ref<number | null>(null)

// 提示框状态
const tooltipVisible = ref(false)
const tooltipData = ref<TopologyNode>({} as TopologyNode)
const tooltipX = ref(0)
const tooltipY = ref(0)

// 抽屉状态
const drawerVisible = ref(false)

// 刷新定时器
const refreshIntervalId = ref<number | null>(null)

// 节点尺寸
const nodeRadius = 50

// 过滤后的节点
const filteredNodes = computed(() => {
  if (!searchKeyword.value.trim()) return topologyNodes.value
  const query = searchKeyword.value.toLowerCase()
  return topologyNodes.value.filter(n => 
    n.name.toLowerCase().includes(query) || 
    (n as TopologyNode).city?.toLowerCase().includes(query)
  )
})

function isFiltered(nodeId: string): boolean {
  if (!searchKeyword.value.trim()) return false
  return !filteredNodes.value.some(n => n.id === nodeId)
}

function handleSearch() {
  // 搜索逻辑已在 computed 中处理
}

function getNodePosition(nodeId: string): { x: number; y: number } {
  return nodePositions.value[nodeId] || { x: 0, y: 0 }
}

function getNodeClass(node: TopologyNode): string {
  return `node-${node.status}`
}

function getStatusColor(status: string): string {
  const map: Record<string, string> = {
    normal: '#67C23A',
    warning: '#E6A23C',
    offline: '#909399',
    critical: '#F56C6C',
    error: '#F56C6C',
    unknown: '#909399'
  }
  return map[status] || '#909399'
}

function getStatusText(status: string): string {
  const map: Record<string, string> = {
    normal: t('topology.normal'),
    online: t('topology.statusOnline'),
    warning: t('topology.warning'),
    offline: t('topology.offline'),
    critical: t('topology.critical'),
    error: t('topology.critical'),
    unknown: t('topology.offline')
  }
  return map[status] || status
}

function getStatusTagType(status: string): string {
  const map: Record<string, string> = {
    normal: 'success',
    warning: 'warning',
    offline: 'info',
    critical: 'danger',
    error: 'danger',
    unknown: 'info'
  }
  return map[status] || 'info'
}

function initializePositions() {
  const nodes = topologyNodes.value
  const cols = Math.ceil(Math.sqrt(nodes.length))
  const spacing = 250
  const startX = canvasWidth.value / 2 / scale.value
  const startY = canvasHeight.value / 2 / scale.value
  
  nodes.forEach((node, index) => {
    const row = Math.floor(index / cols)
    const col = index % cols
    nodePositions.value[node.id] = {
      x: startX + (col - cols / 2) * spacing,
      y: startY + (row - Math.ceil(nodes.length / cols) / 2) * spacing
    }
  })
}

function runForceLayout() {
  if (isLayoutRunning.value) return
  isLayoutRunning.value = true
  
  const k = Math.sqrt(canvasWidth.value * canvasHeight.value / topologyNodes.value.length)
  const iterations = 100
  let iteration = 0
  
  function step() {
    const nodes = topologyNodes.value
    const forces: Record<string, { x: number; y: number }> = {}
    
    nodes.forEach(node => {
      forces[node.id] = { x: 0, y: 0 }
    })
    
    // 节点间斥力
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const n1 = nodes[i]
        const n2 = nodes[j]
        const dx = nodePositions.value[n2.id].x - nodePositions.value[n1.id].x
        const dy = nodePositions.value[n2.id].y - nodePositions.value[n1.id].y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        
        const force = k * k / dist
        forces[n1.id].x -= (dx / dist) * force
        forces[n1.id].y -= (dy / dist) * force
        forces[n2.id].x += (dx / dist) * force
        forces[n2.id].y += (dy / dist) * force
      }
    }
    
    // 边的引力
    topologyEdges.value.forEach(edge => {
      const source = nodePositions.value[edge.source]
      const target = nodePositions.value[edge.target]
      if (!source || !target) return
      
      const dx = target.x - source.x
      const dy = target.y - source.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 1
      
      const force = dist / k
      forces[edge.source].x += (dx / dist) * force
      forces[edge.source].y += (dy / dist) * force
      forces[edge.target].x -= (dx / dist) * force
      forces[edge.target].y -= (dy / dist) * force
    })
    
    // 中心引力
    const centerX = canvasWidth.value / 2 / scale.value
    const centerY = canvasHeight.value / 2 / scale.value
    nodes.forEach(node => {
      const dx = centerX - nodePositions.value[node.id].x
      const dy = centerY - nodePositions.value[node.id].y
      forces[node.id].x += dx * 0.01
      forces[node.id].y += dy * 0.01
    })
    
    // 应用力
    nodes.forEach(node => {
      const pos = nodePositions.value[node.id]
      const fx = forces[node.id].x
      const fy = forces[node.id].y
      const maxForce = 10
      
      pos.x += Math.max(-maxForce, Math.min(maxForce, fx))
      pos.y += Math.max(-maxForce, Math.min(maxForce, fy))
    })
    
    iteration++
    if (iteration < iterations) {
      requestAnimationFrame(step)
    } else {
      isLayoutRunning.value = false
    }
  }
  
  requestAnimationFrame(step)
}

function resetLayout() {
  if (layoutAnimationId.value) {
    cancelAnimationFrame(layoutAnimationId.value)
  }
  isLayoutRunning.value = false
  initializePositions()
}

function zoomIn() {
  scale.value = Math.min(scale.value * 1.2, 3)
}

function zoomOut() {
  scale.value = Math.max(scale.value / 1.2, 0.3)
}

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen()
  } else {
    document.exitFullscreen()
  }
}

function startDrag(nodeId: string, event: MouseEvent) {
  isDragging.value = true
  draggingNodeId.value = nodeId
  dragOffset.value = {
    x: event.clientX - nodePositions.value[nodeId].x * scale.value - panX.value,
    y: event.clientY - nodePositions.value[nodeId].y * scale.value - panY.value
  }
}

function startPan(event: MouseEvent) {
  if (event.button !== 0) return
  isPanning.value = true
  panOffset.value = { x: event.clientX - panX.value, y: event.clientY - panY.value }
}

function onMouseMove(event: MouseEvent) {
  if (isDragging.value && draggingNodeId.value) {
    const pos = nodePositions.value[draggingNodeId.value]
    pos.x = (event.clientX - dragOffset.value.x - panX.value) / scale.value
    pos.y = (event.clientY - dragOffset.value.y - panY.value) / scale.value
  } else if (isPanning.value) {
    panX.value = event.clientX - panOffset.value.x
    panY.value = event.clientY - panOffset.value.y
  }
  
  if (tooltipVisible.value) {
    tooltipX.value = event.clientX + 15
    tooltipY.value = event.clientY + 15
  }
}

function endMouseUp() {
  isDragging.value = false
  isPanning.value = false
  draggingNodeId.value = null
}

function onWheel(event: WheelEvent) {
  event.preventDefault()
  const delta = event.deltaY > 0 ? 0.9 : 1.1
  scale.value = Math.max(0.3, Math.min(3, scale.value * delta))
}

function showSiteTooltip(node: TopologyNode, event: MouseEvent) {
  tooltipData.value = node
  tooltipX.value = event.clientX + 15
  tooltipY.value = event.clientY + 15
  tooltipVisible.value = true
}

function hideTooltip() {
  tooltipVisible.value = false
}

function selectNode(node: TopologyNode) {
  selectedNodeId.value = node.id
  selectedNode.value = node
  drawerVisible.value = true
}

async function loadSiteData() {
  try {
    const data = await getSiteGraph()
    topologyNodes.value = data.nodes
    topologyEdges.value = data.edges
    initializePositions()
  } catch (error) {
    console.error('Failed to load site topology data:', error)
  }
}

function startRefreshTimer() {
  if (refreshIntervalId.value) {
    clearInterval(refreshIntervalId.value)
  }
  refreshIntervalId.value = window.setInterval(async () => {
    try {
      await loadSiteData()
    } catch (error) {
      console.error('Auto refresh failed:', error)
    }
  }, 120000)
}

function stopRefreshTimer() {
  if (refreshIntervalId.value) {
    clearInterval(refreshIntervalId.value)
    refreshIntervalId.value = null
  }
}

function handleResize() {
  if (canvasWrapper.value) {
    canvasWidth.value = canvasWrapper.value.clientWidth
    canvasHeight.value = canvasWrapper.value.clientHeight
  }
}

onMounted(() => {
  handleResize()
  window.addEventListener('resize', handleResize)
  loadSiteData()
  startRefreshTimer()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  stopRefreshTimer()
})
</script>

<style scoped>
.site-topology {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: linear-gradient(135deg, #0a0e1a 0%, #1a1a2e 50%, #0f1724 100%);
}

.topology-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: linear-gradient(180deg, rgba(22, 33, 62, 0.95) 0%, rgba(22, 33, 62, 0.85) 100%);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(45, 58, 79, 0.5);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.search-input {
  width: 320px;
}

.search-input :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(37, 99, 235, 0.3);
  box-shadow: none;
  transition: all 0.3s ease;
}

.search-input :deep(.el-input__wrapper:hover) {
  border-color: rgba(37, 99, 235, 0.6);
  background: rgba(255, 255, 255, 0.12);
}

.search-input :deep(.el-input__wrapper.is-focus) {
  border-color: var(--color-accent);
  background: rgba(255, 255, 255, 0.15);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2);
}

.search-input :deep(.el-input__inner) {
  color: #fff;
}

.search-input :deep(.el-input__prefix) {
  color: rgba(255, 255, 255, 0.6);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toolbar-btn {
  width: 40px;
  height: 40px;
  padding: 0;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(37, 99, 235, 0.2);
  color: #fff;
  transition: all 0.3s ease;
}

.toolbar-btn:hover {
  background: rgba(37, 99, 235, 0.2);
  border-color: rgba(37, 99, 235, 0.5);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

.toolbar-btn:active {
  transform: translateY(0);
}

.topology-canvas {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: 
    radial-gradient(ellipse at 20% 30%, rgba(37, 99, 235, 0.08) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 70%, rgba(100, 89, 234, 0.08) 0%, transparent 50%),
    linear-gradient(180deg, #0a0e1a 0%, #1a1a2e 100%);
}

.topology-canvas::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-image: 
    linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
  opacity: 0.5;
}

.topology-svg {
  cursor: grab;
}

.topology-svg:active {
  cursor: grabbing;
}

.topology-edge {
  stroke: #4a5568;
  stroke-width: 3;
  fill: none;
  transition: all 0.3s ease;
  filter: drop-shadow(0 0 4px rgba(0, 0, 0, 0.5));
}

.topology-edge.normal {
  stroke: var(--color-success);
  stroke-width: 3.5;
  filter: drop-shadow(0 0 8px rgba(103, 194, 58, 0.5));
}

.topology-edge.warning {
  stroke: var(--color-warning);
  stroke-width: 3.5;
  filter: drop-shadow(0 0 8px rgba(230, 162, 60, 0.5));
}

.topology-edge.offline,
.topology-edge.critical {
  stroke: var(--color-danger);
  stroke-width: 2.5;
  stroke-dasharray: 8,4;
  filter: drop-shadow(0 0 8px rgba(180, 35, 24, 0.5));
  animation: edge-pulse 2s ease-in-out infinite;
}

@keyframes edge-pulse {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
}

.topology-edge.internet {
  stroke: var(--color-success);
}

.topology-edge.mpls {
  stroke: var(--color-accent);
  filter: drop-shadow(0 0 8px rgba(37, 99, 235, 0.5));
}

.topology-edge.sdwan {
  stroke: #9b59b6;
  filter: drop-shadow(0 0 8px rgba(155, 89, 182, 0.5));
}

.topology-edge.fiber {
  stroke: #3498db;
  filter: drop-shadow(0 0 8px rgba(52, 152, 219, 0.5));
}

.edge-label {
  fill: rgba(255, 255, 255, 0.9);
  font-size: 11px;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.8);
}

.topology-node {
  cursor: pointer;
  transition: all 0.3s ease;
}

.topology-node:hover .node-circle {
  stroke: var(--color-accent);
  stroke-width: 3;
  filter: drop-shadow(0 0 15px rgba(37, 99, 235, 0.4));
}

.node-selected .node-circle {
  stroke: var(--color-accent);
  stroke-width: 3;
  filter: drop-shadow(0 0 20px rgba(37, 99, 235, 0.6));
}

.node-filtered {
  opacity: 0.3;
}

.node-circle {
  fill: rgba(45, 58, 79, 0.9);
  stroke: rgba(74, 85, 104, 0.8);
  stroke-width: 2;
  transition: all 0.3s ease;
  backdrop-filter: blur(4px);
}

.node-normal .node-circle {
  fill: rgba(45, 58, 79, 0.9);
}

.node-warning .node-circle {
  fill: rgba(61, 58, 42, 0.9);
}

.node-offline .node-circle,
.node-critical .node-circle {
  fill: rgba(58, 45, 45, 0.9);
}

.status-dot {
  stroke: #fff;
  stroke-width: 2;
  filter: drop-shadow(0 0 6px currentColor);
}

.node-name {
  fill: #fff;
  font-size: 14px;
  font-weight: 600;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.8);
}

.node-city {
  fill: rgba(144, 147, 153, 0.9);
  font-size: 12px;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
}

.tooltip {
  position: fixed;
  background: rgba(15, 23, 36, 0.98);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(37, 99, 235, 0.3);
  border-radius: 12px;
  padding: 16px 20px;
  z-index: 10000;
  pointer-events: none;
  min-width: 240px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4), 0 0 20px rgba(37, 99, 235, 0.1);
}

.tooltip-title {
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(37, 99, 235, 0.2);
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.5);
}

.tooltip-content {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.85);
  line-height: 1.8;
}

.tooltip-content div {
  margin-bottom: 6px;
}

.tooltip-content div:last-child {
  margin-bottom: 0;
}

.topology-legend {
  display: flex;
  gap: 20px;
  padding: 16px 24px;
  background: linear-gradient(180deg, rgba(22, 33, 62, 0.85) 0%, rgba(22, 33, 62, 0.95) 100%);
  backdrop-filter: blur(10px);
  border-top: 1px solid rgba(45, 58, 79, 0.5);
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.3);
}

.legend-section {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
  margin-right: 8px;
  display: flex;
  align-items: center;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}

.legend-item .status-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  box-shadow: 0 0 8px currentColor;
}

.legend-line {
  width: 24px;
  height: 3px;
  border-radius: 2px;
  box-shadow: 0 0 6px currentColor;
}

.legend-line.internet {
  background: var(--color-success);
}

.legend-line.mpls {
  background: var(--color-accent);
}

.legend-line.sdwan {
  background: #9b59b6;
}

.legend-line.fiber {
  background: #3498db;
}
</style>