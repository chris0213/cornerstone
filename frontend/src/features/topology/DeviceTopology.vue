<template>
  <div class="device-topology">
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
        <el-select
          v-model="selectedSiteId"
          :placeholder="t('topology.selectSite')"
          class="site-select"
          size="small"
          @change="onSiteChange"
        >
          <el-option :label="t('topology.allSites')" :value="null" :disabled="allSitesDisabled" />
          <el-option
            v-for="site in sites"
            :key="site.id"
            :label="site.name"
            :value="site.id"
          />
        </el-select>
        <el-switch
          v-model="showIsolatedDevices"
          :active-text="t('topology.showIsolated')"
          :inactive-text="t('topology.hideIsolated')"
          size="small"
          class="isolated-switch"
        />
        <el-tooltip :content="t('topology.refreshData')" placement="bottom">
          <el-button :icon="Refresh" @click="loadDeviceData()" class="toolbar-btn" />
        </el-tooltip>
        <el-tooltip :content="t('topology.forceLayout')" placement="bottom">
          <el-button :icon="MagicStick" @click="runForceLayout" :loading="isLayoutRunning" class="toolbar-btn" />
        </el-tooltip>
        <el-tooltip :content="t('topology.gridLayout')" placement="bottom">
          <el-button :icon="Grid" @click="resetLayout" class="toolbar-btn" />
        </el-tooltip>
        <el-tooltip :content="t('topology.zoomIn')" placement="bottom">
          <el-button :icon="ZoomIn" @click="zoomIn" class="toolbar-btn" />
        </el-tooltip>
        <el-tooltip :content="t('topology.zoomOut')" placement="bottom">
          <el-button :icon="ZoomOut" @click="zoomOut" class="toolbar-btn" />
        </el-tooltip>
        <el-tooltip :content="t('topology.fullscreen')" placement="bottom">
          <el-button :icon="FullScreen" @click="toggleFullscreen" class="toolbar-btn" />
        </el-tooltip>
        <el-dropdown :trigger="'click'" class="toolbar-btn">
          <el-tooltip :content="t('topology.export')" placement="bottom">
            <el-button :icon="Download" class="toolbar-btn" />
          </el-tooltip>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="exportAsPNG">
                <el-icon><PictureFilled /></el-icon>
                {{ t('topology.exportPNG') }}
              </el-dropdown-item>
              <el-dropdown-item @click="exportAsJPG">
                <el-icon><Picture /></el-icon>
                {{ t('topology.exportJPG') }}
              </el-dropdown-item>
              <el-dropdown-item @click="exportAsPDF">
                <el-icon><Document /></el-icon>
                {{ t('topology.exportPDF') }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- 右侧详情面板 -->
    <div v-if="selectedNode" class="detail-panel">
      <div class="panel-header">
        <div class="panel-title">{{ selectedNode.name }}</div>
        <el-button :icon="Close" class="close-btn" @click="closeDetailPanel" />
      </div>
      <div class="panel-content">
        <div class="info-row">
          <span class="info-label">{{ t('topology.deviceType') }}</span>
          <span class="info-value">{{ getDeviceTypeText((selectedNode as DeviceNode).type) }}</span>
        </div>
        
        <template v-if="isInternetNode">
          <div class="info-row" v-if="(selectedNode as DeviceNode).provider">
            <span class="info-label">{{ t('topology.provider') }}</span>
            <span class="info-value">{{ (selectedNode as DeviceNode).provider }}</span>
          </div>
          <div class="info-row" v-if="(selectedNode as DeviceNode).bandwidth">
            <span class="info-label">{{ t('topology.bandwidth') }}</span>
            <span class="info-value">{{ (selectedNode as DeviceNode).bandwidth }} Mbps</span>
          </div>
        </template>
        
        <div class="info-row" v-if="!isInternetNode">
          <span class="info-label">{{ t('topology.vendor') }}</span>
          <span class="info-value">{{ (selectedNode as DeviceNode).vendor }}</span>
        </div>
        <div class="info-row" v-if="!isInternetNode">
          <span class="info-label">{{ t('topology.managementIp') }}</span>
          <span class="info-value">{{ (selectedNode as DeviceNode).ip_address }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">{{ t('topology.status') }}</span>
          <span class="info-value" :class="getStatusClass(selectedNode.status)">{{ getStatusText(selectedNode.status) }}</span>
        </div>
        <div class="info-row" v-if="!isInternetNode">
          <span class="info-label">{{ t('topology.site') }}</span>
          <span class="info-value">{{ (selectedNode as DeviceNode).site_name || '-' }}</span>
        </div>
        <div class="info-row" v-if="!isInternetNode">
          <span class="info-label">{{ t('topology.packetLoss') }}</span>
          <span class="info-value">{{ (selectedNode as DeviceNode).packet_loss != null ? (selectedNode as DeviceNode).packet_loss + '%' : '-' }}</span>
        </div>
        
        <!-- 对端连接设备和端口信息 -->
        <template v-if="connectedDevices.length > 0">
          <div class="connection-section">
            <div class="connection-label">{{ t('topology.connectedDevices') }}</div>
            <div class="connection-list">
              <div v-for="conn in connectedDevices" :key="conn.id" class="connection-item">
                <div class="connection-device">{{ conn.name }}</div>
                <div class="connection-ports">
                  <span v-if="conn.sourceInterface" class="port-info">{{ t('topology.localPort') }}: {{ conn.sourceInterface }}</span>
                  <span v-if="conn.targetInterface" class="port-info">{{ t('topology.peerPort') }}: {{ conn.targetInterface }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <div class="topology-main">
      <div class="topology-canvas" ref="canvasWrapper">
        <!-- 加载中 -->
        <div v-if="isLoading" class="canvas-state">
          <el-icon class="state-icon is-loading"><Loading /></el-icon>
          <div class="state-text">{{ t('topology.loadingGraph') }}</div>
        </div>
        <!-- 空状态：未选站点 / 无数据 -->
        <div v-else-if="showEmptyState" class="canvas-state">
          <el-icon class="state-icon"><Share /></el-icon>
          <div class="state-title">{{ emptyStateTitle }}</div>
          <div class="state-text">{{ emptyStateHint }}</div>
        </div>
        <!-- 数据异常提示：链路对端节点缺失 -->
        <div v-else-if="missingEdgeCount > 0" class="canvas-alert">
          <el-icon><WarningFilled /></el-icon>
          {{ t('topology.missingEdgeNodes', { count: missingEdgeCount }) }}
        </div>
        <svg
          v-show="!showEmptyState && !isLoading"
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
            <filter id="glow-blue">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          <g :transform="`translate(${panX}, ${panY}) scale(${scale})`">
            <!-- 连接线 -->
            <g v-for="edge in filteredEdges" :key="'edge-' + edge.id">
              <line
                :x1="getNodePosition(edge.source).x"
                :y1="getNodePosition(edge.source).y"
                :x2="getNodePosition(edge.target).x"
                :y2="getNodePosition(edge.target).y"
                class="topology-edge"
                :class="getEdgeClass(edge)"
              />
              <text
                :x="(getNodePosition(edge.source).x + getNodePosition(edge.target).x) / 2"
                :y="(getNodePosition(edge.source).y + getNodePosition(edge.target).y) / 2 - 8"
                text-anchor="middle"
                class="edge-bandwidth"
              >
                {{ getBandwidthLabel(edge) }}
              </text>
            </g>

            <!-- 节点 -->
            <g
              v-for="node in filteredNodes"
              :key="'node-' + node.id"
              :transform="`translate(${getNodePosition(node.id).x}, ${getNodePosition(node.id).y})`"
              class="topology-node"
              :class="{ 'node-selected': selectedNodeId === node.id }"
              @mousedown.stop="startDrag(node.id, $event)"
              @click.stop="onNodeClick(node.id)"
              @mouseenter="onNodeHover(node, $event)"
              @mouseleave="onNodeLeave"
            >
              <rect
                :width="nodeWidth"
                :height="nodeHeight"
                :x="-nodeWidth / 2"
                :y="-nodeHeight / 2"
                rx="10"
                class="node-box"
                :style="getNodeStyle(node as DeviceNode)"
              />
              <!-- 状态点：右上角内嵌 -->
              <circle
                :cx="nodeWidth / 2 - 10"
                :cy="-nodeHeight / 2 + 10"
                r="5"
                class="status-dot"
                :fill="getStatusColor(node.status)"
                stroke="#1a2035"
                stroke-width="1.5"
              />
              <!-- 图标区域：左侧居中（纯 SVG 路径内联，支持 html2canvas 导出） -->
              <g :transform="`translate(${-nodeWidth / 2 + 6}, ${-24})`">
                <svg width="48" height="48" viewBox="0 0 24 24"
                     :color="getDeviceIconColor(getIconType((node as DeviceNode).type, (node as DeviceNode).vendor, node.name))">
                  <g v-html="getDeviceIconSvg(getIconType((node as DeviceNode).type, (node as DeviceNode).vendor, node.name))"
                     fill="none"
                     stroke="currentColor"
                     stroke-width="1.5"
                     stroke-linecap="round"
                     stroke-linejoin="round" />
                </svg>
              </g>
              <!-- 文本区域：图标右侧，统一左对齐 -->
              <g :transform="`translate(${-nodeWidth / 2 + 58}, ${-nodeHeight / 2 + 12})`">
                <text x="0" y="16" text-anchor="start" class="node-name">{{ node.name }}</text>
                <text v-if="!isCircuitNode(node)" x="0" y="34" text-anchor="start" class="node-ip">{{ (node as DeviceNode).ip_address }}</text>
                <text v-if="isCircuitNode(node) && (node as DeviceNode).bandwidth" x="0" y="34" text-anchor="start" class="node-ip">{{ (node as DeviceNode).bandwidth }} Mbps</text>
                <text v-if="!isCircuitNode(node)" x="0" y="52" text-anchor="start" class="node-status" :class="getStatusClass(node.status)">
                  {{ getStatusSummary(node as DeviceNode) }}
                </text>
              </g>
            </g>
          </g>
        </svg>

        <!-- Hover 提示框 -->
        <div v-if="hoveredNode" class="tooltip-panel" :style="tooltipStyle">
          <div class="tooltip-header">
            <span class="tooltip-name">{{ hoveredNode.name }}</span>
          </div>
          <div class="tooltip-divider"></div>
          <div class="tooltip-row">
            <span class="tooltip-label">{{ t('topology.deviceType') }}</span>
            <span class="tooltip-value">{{ getDeviceTypeText((hoveredNode as DeviceNode).type) }}</span>
          </div>
          <div class="tooltip-row">
            <span class="tooltip-label">IP</span>
            <span class="tooltip-value">{{ (hoveredNode as DeviceNode).ip_address }}</span>
          </div>
          <div class="tooltip-row">
            <span class="tooltip-label">{{ t('topology.status') }}</span>
            <span class="tooltip-value" :class="getStatusClass(hoveredNode.status)">
              <span class="tooltip-status-dot" :style="{ background: getStatusColor(hoveredNode.status) }"></span>
              {{ getStatusText(hoveredNode.status) }}
            </span>
          </div>
          <div class="tooltip-row" v-if="(hoveredNode as DeviceNode).site_name">
            <span class="tooltip-label">{{ t('topology.tooltipLocation') }}</span>
            <span class="tooltip-value">{{ (hoveredNode as DeviceNode).site_name }}</span>
          </div>
          <div class="tooltip-divider"></div>
          <div class="tooltip-hint">{{ t('topology.clickForDetail') }}</div>
        </div>
      </div>

      <!-- 图例 -->
      <div class="legend-panel">
        <div class="legend-title">{{ t('topology.legend') }}</div>
        <div class="legend-section">
          <div class="legend-item">
            <span class="legend-dot online"></span>
            <span>{{ t('topology.statusOnline') }}</span>
          </div>
          <div class="legend-item">
            <span class="legend-dot warning"></span>
            <span>{{ t('topology.statusWarning') }}</span>
          </div>
          <div class="legend-item">
            <span class="legend-dot offline"></span>
            <span>{{ t('topology.statusOffline') }}</span>
          </div>
        </div>
        <div class="legend-section">
          <div class="legend-item">
            <svg width="30" height="4" viewBox="0 0 30 4">
              <line x1="0" y1="2" x2="30" y2="2" stroke="#5B8DB8" stroke-width="2" />
            </svg>
            <span>{{ t('topology.legendNormalLink') }}</span>
          </div>
          <div class="legend-item">
            <svg width="30" height="4" viewBox="0 0 30 4">
              <line x1="0" y1="2" x2="30" y2="2" stroke="#F56C6C" stroke-width="2" stroke-dasharray="6,3" />
            </svg>
            <span>{{ t('topology.legendCriticalLink') }}</span>
          </div>
        </div>
        <div class="legend-section">
          <div class="legend-item" v-for="item in legendDeviceTypes" :key="item.type">
            <svg width="16" height="16" viewBox="0 0 24 24" class="legend-type-icon">
              <g v-html="getDeviceIconSvg(item.type)" fill="none" :stroke="getDeviceIconColor(item.type)"
                 stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <span>{{ item.label }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import { Search, Refresh, MagicStick, Grid, ZoomIn, ZoomOut, FullScreen, Close, Download, PictureFilled, Picture, Document, Loading, Share, WarningFilled } from '@element-plus/icons-vue'
import { getDeviceGraph, getSiteDevices, type DeviceNode, type DeviceEdge, type SiteDeviceOption } from '../../api/topology'
import { getSites as getSitesApi, type SiteResponse } from '../../api/sites'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { inferIconType, mapStatus } from '../../components/icons/networkIconTypes'
import { DEVICE_TYPE_CONFIG, STATUS_DOT_COLOR, DEVICE_RANK } from './topologyConfig'
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'

// 获取图标类型
function getIconType(deviceType: string | null | undefined, vendor: string | null | undefined, name: string | null | undefined): string {
  return inferIconType(deviceType, vendor, name)
}

// 获取设备图标颜色
function getDeviceIconColor(type: string): string {
  const config = DEVICE_TYPE_CONFIG[type] || DEVICE_TYPE_CONFIG['unknown']
  return config.color
}

// ── 设备 SVG 图标路径（内联路径，html2canvas 可正常渲染） ──
// 每个字符串是 <g> 的子元素集合，通过 v-html 注入，fill/stroke 由父级控制
const DEVICE_ICON_SVG: Record<string, string> = {
  'router': `<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M8 10v4M12 10v4M16 10v4M6 12h12" stroke-width="1.3"/>`,
  'core-switch': `<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9v6M10 9v6M13 9v6M16 9v6" stroke-width="1.3"/><circle cx="7" cy="12" r=".8" fill="currentColor"/><circle cx="10" cy="12" r=".8" fill="currentColor"/><circle cx="13" cy="12" r=".8" fill="currentColor"/><circle cx="16" cy="12" r=".8" fill="currentColor"/>`,
  'access-switch': `<rect x="4" y="6" width="16" height="12" rx="2"/><path d="M7 9v6M10 9v6M13 9v6M16 9v6" stroke-width="1.3"/><circle cx="7" cy="12" r=".8" fill="currentColor"/><circle cx="13" cy="12" r=".8" fill="currentColor"/><circle cx="16" cy="12" r=".8" fill="currentColor"/>`,
  'firewall': `<path d="M12 3C8 5 4 7 4 11v4a8 8 0 0 0 8 6 8 8 0 0 0 8-6v-4c0-4-4-6-8-8z"/><path d="M9 12l2 2 4-4" stroke-width="1.8"/>`,
  'load-balancer': `<path d="M4 5h16v4H4zM4 15h16v4H4z"/><path d="M12 9v6M8 9l-2 3 2 3M16 9l2 3-2 3" stroke-width="1.3"/>`,
  'ap': `<path d="M5 9a7 7 0 0 1 14 0M8 9a4 4 0 0 1 8 0"/><circle cx="12" cy="9" r="1.2" fill="currentColor"/><path d="M12 13v4M9 17h6"/>`,
  'ac': `<rect x="7" y="4" width="10" height="6" rx="1.5"/><path d="M12 10v4M7 14h10M4 18a8 8 0 0 1 16 0" stroke-width="1.3"/>`,
  'sdwan': `<circle cx="6" cy="7" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="6" cy="17" r="2.5"/><circle cx="18" cy="17" r="2.5"/><circle cx="12" cy="12" r="2"/><line x1="8.5" y1="8" x2="10.5" y2="10.5" stroke-width="1"/><line x1="15.5" y1="8" x2="13.5" y2="10.5" stroke-width="1"/><line x1="8.5" y1="16" x2="10.5" y2="13.5" stroke-width="1"/><line x1="15.5" y1="16" x2="13.5" y2="13.5" stroke-width="1"/>`,
  'server': `<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M5 8h14M5 16h14" stroke-width="1.3"/><circle cx="10" cy="5" r=".8" fill="currentColor"/><circle cx="10" cy="13" r=".8" fill="currentColor"/><circle cx="10" cy="19" r=".8" fill="currentColor"/>`,
  'pc': `<rect x="4" y="3" width="16" height="12" rx="1.5"/><path d="M9 15v4M15 15v4M7 19h10" stroke-width="1.3"/>`,
  'laptop': `<rect x="4" y="4" width="16" height="11" rx="1.5"/><path d="M2 17a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2" stroke-width="1.3"/>`,
  'printer': `<rect x="5" y="3" width="14" height="7" rx="1"/><path d="M7 10v5h10v-5M7 15v4h10v-4M9 7h6" stroke-width="1.3"/><rect x="9" y="17" width="6" height="2" rx=".5" fill="currentColor"/>`,
  'nas': `<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6" stroke-width="1.3"/>`,
  'camera': `<path d="M5 7h1.5l2-3h7l2 3H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z"/><circle cx="12" cy="13" r="3" stroke-width="1.3"/>`,
  'ids-ips': `<path d="M12 3c-4 2-8 4-8 8v3a8 8 0 0 0 16 0v-3c0-4-4-6-8-8z"/><circle cx="12" cy="12" r="3" stroke-width="1.3"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/>`,
  'vpn': `<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4" stroke-width="1.3"/><circle cx="12" cy="16" r="1.2" fill="currentColor"/><path d="M12 16v2" stroke-width="1.3"/>`,
  'waf': `<path d="M12 3C8 5 4 7 4 11v4a8 8 0 0 0 8 6 8 8 0 0 0 8-6v-4c0-4-4-6-8-8z"/><path d="M9 12l2 2 4-5" stroke-width="1.8"/>`,
  'internet': `<path d="M6 16a4 4 0 0 1-1-7.9A5.5 5.5 0 0 1 14.5 4a5.5 5.5 0 0 1 4.5 2.1A4 4 0 0 1 18 16z"/><path d="M9 12h6M12 9v6" stroke-width="1.3"/>`,
  'isp': `<path d="M12 2v4M12 9v2M5 12h14M8 16a4 4 0 0 1 8 0" stroke-width="1.3"/><circle cx="12" cy="20" r="1.2" fill="currentColor"/>`,
  'datacenter': `<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M4 8h16M4 14h16M4 19h16" stroke-width="1.3"/><rect x="8" y="4" width="3" height="2" rx=".5" fill="currentColor"/><rect x="8" y="10" width="3" height="2" rx=".5" fill="currentColor"/><rect x="8" y="16" width="3" height="2" rx=".5" fill="currentColor"/>`,
  'site': `<path d="M5 12l7-7 7 7M9 21V9h6v12M9 15h6"/>`,
  'unknown': `<circle cx="12" cy="12" r="9"/><path d="M10 9a2 2 0 1 1 4 0c0 1.5-2 2-2 3v1" stroke-width="1.3"/>`,
}

function getDeviceIconSvg(type: string): string {
  return DEVICE_ICON_SVG[type] || DEVICE_ICON_SVG['unknown']
}

const { t } = useI18n()

const canvasWrapper = ref<HTMLElement | null>(null)
const canvasWidth = ref(800)
const canvasHeight = ref(600)
const scale = ref(1)
const panX = ref(0)
const panY = ref(0)

const deviceNodes = ref<DeviceNode[]>([])
const deviceEdges = ref<DeviceEdge[]>([])
const sites = ref<SiteResponse[]>([])
const selectedSiteId = ref<number | null>(null)
const showIsolatedDevices = ref(false)
const selectedNodeId = ref<string | null>(null)
const searchKeyword = ref('')
const isLoading = ref(false)

// 「全部站点」可用阈值：全量节点超过该值时禁用全部站点选项（设备级拓扑无渲染意义）
const MAX_ALL_SITES_NODES = 500

// 站点设备列表（用于专线连接设置）
const siteDevices = ref<SiteDeviceOption[]>([])
// 专线连接选择的设备ID
const selectedConnectionDeviceId = ref<number | null>(null)

const isDragging = ref(false)
const draggingNodeId = ref<string | null>(null)
const dragOffset = ref({ x: 0, y: 0 })
const isPanning = ref(false)
const panOffset = ref({ x: 0, y: 0 })

const isLayoutRunning = ref(false)
const nodePositions = ref<Record<string, { x: number; y: number }>>({})

const refreshIntervalId = ref<number | null>(null)

const hoveredNode = ref<DeviceNode | null>(null)
const tooltipStyle = ref({ top: '0px', left: '0px' })

const nodeWidth = 220
const nodeHeight = 72

const searchFilteredNodes = computed(() => {
  if (!searchKeyword.value.trim()) return deviceNodes.value
  const query = searchKeyword.value.toLowerCase()
  return deviceNodes.value.filter(d => 
    d.name.toLowerCase().includes(query) || 
    (d as DeviceNode).ip_address?.toLowerCase().includes(query)
  )
})

// 「全部站点」模式下的节点总数（用于判断是否禁用全部站点选项）
const totalAllNodes = ref(0)

function getConnectedNodeIds(): Set<string> {
  const connectedIds = new Set<string>()
  deviceEdges.value.forEach(edge => {
    connectedIds.add(edge.source)
    connectedIds.add(edge.target)
  })
  return connectedIds
}

// 最终参与渲染的节点集合（搜索 + 孤立过滤之后）
const renderedNodeIds = computed(() => new Set(filteredNodes.value.map(n => n.id)))

// 链路两端节点必须同时存在于渲染集合且已有布局位置，否则不画（防止悬空线）
const filteredEdges = computed(() => {
  return deviceEdges.value.filter(edge =>
    renderedNodeIds.value.has(edge.source) &&
    renderedNodeIds.value.has(edge.target) &&
    nodePositions.value[edge.source] &&
    nodePositions.value[edge.target]
  )
})

// 因对端节点缺失（被过滤或数据缺失）而无法绘制的链路数
const missingEdgeCount = computed(() => {
  if (showEmptyState.value || isLoading.value) return 0
  const rendered = renderedNodeIds.value
  return deviceEdges.value.filter(edge => {
    const sourceExists = deviceNodes.value.some(n => n.id === edge.source)
    const targetExists = deviceNodes.value.some(n => n.id === edge.target)
    // 两端原始节点都在却因过滤/位置缺失画不出来，才算「数据不完整」
    return sourceExists && targetExists &&
      (!rendered.has(edge.source) || !rendered.has(edge.target) ||
       !nodePositions.value[edge.source] || !nodePositions.value[edge.target])
  }).length
})

const filteredNodes = computed(() => {
  let result = searchFilteredNodes.value
  if (!showIsolatedDevices.value) {
    const connectedIds = getConnectedNodeIds()
    result = result.filter(node => connectedIds.has(node.id))
  }
  return result
})

// 空状态：未选站点 / 无节点数据 / 节点全被过滤（如孤立节点隐藏后无可见节点）
const showEmptyState = computed(() =>
  selectedSiteId.value === null || deviceNodes.value.length === 0 || filteredNodes.value.length === 0
)

const emptyStateTitle = computed(() => {
  if (selectedSiteId.value === null) return t('topology.emptySelectSiteTitle')
  if (deviceNodes.value.length > 0 && filteredNodes.value.length === 0) {
    return t('topology.emptyAllHiddenTitle')
  }
  return t('topology.emptyNoDataTitle')
})

const emptyStateHint = computed(() => {
  if (selectedSiteId.value === null) return t('topology.emptySelectSiteHint')
  if (deviceNodes.value.length > 0 && filteredNodes.value.length === 0) {
    return t('topology.emptyAllHiddenHint')
  }
  return t('topology.emptyNoDataHint')
})

// 全量节点数超过阈值时禁用「全部站点」选项
const allSitesDisabled = computed(() => totalAllNodes.value > MAX_ALL_SITES_NODES)

// 图例设备类型（固定展示核心几类，中英文走 i18n）
const legendDeviceTypes = computed(() => [
  { type: 'internet', label: t('topology.legendInternetExit') },
  { type: 'router', label: t('topology.deviceRouter') },
  { type: 'firewall', label: t('topology.deviceFirewall') },
  { type: 'core-switch', label: t('topology.deviceCoreSwitch') },
  { type: 'access-switch', label: t('topology.deviceAccessSwitch') },
  { type: 'server', label: t('topology.deviceServer') }
])

const selectedNode = computed(() => {
  if (!selectedNodeId.value) return null
  return deviceNodes.value.find(n => n.id === selectedNodeId.value)
})

// 判断节点是否为专线节点（互联网/MPLS/SD-WAN）
function isCircuitNode(node: any): boolean {
  return node.type === 'internet' || node.type === 'isp' || node.type === 'sdwan' || node.id?.startsWith('internet_')
}

// 判断选中的节点是否为互联网出口
const isInternetNode = computed(() => {
  if (!selectedNode.value) return false
  // 判断是否为专线类型节点（internet/isp/sdwan）
  const nodeType = selectedNode.value.type
  const nodeId = selectedNode.value.id
  return nodeType === 'internet' || nodeType === 'isp' || nodeType === 'sdwan' ||
         nodeId.startsWith('internet_') || nodeId.startsWith('isp_') || nodeId.startsWith('sdwan_')
})

// 获取所有对端连接设备和端口信息
const connectedDevices = computed(() => {
  if (!selectedNode.value) return []
  
  const result: Array<{
    id: string
    name: string
    sourceInterface: string | null
    targetInterface: string | null
  }> = []
  
  const nodeId = selectedNode.value.id
  
  // 查找所有与当前节点相连的边
  const relatedEdges = deviceEdges.value.filter(e => e.source === nodeId || e.target === nodeId)
  
  for (const edge of relatedEdges) {
    const connectedNodeId = edge.source === nodeId ? edge.target : edge.source
    const connectedNode = deviceNodes.value.find(n => n.id === connectedNodeId)
    
    if (!connectedNode) continue
    
    // 根据当前节点在边中的位置确定端口方向
    let sourceInterface: string | null = null
    let targetInterface: string | null = null
    
    if (edge.source === nodeId) {
      // 当前节点是source端
      sourceInterface = edge.source_interface || null
      targetInterface = edge.target_interface || null
    } else {
      // 当前节点是target端，端口方向互换
      sourceInterface = edge.target_interface || null
      targetInterface = edge.source_interface || null
    }
    
    result.push({
      id: connectedNode.id,
      name: connectedNode.name,
      sourceInterface,
      targetInterface
    })
  }
  
  return result
})

function handleSearch() {}

function getNodePosition(nodeId: string): { x: number; y: number } {
  return nodePositions.value[nodeId] || { x: 0, y: 0 }
}

function getNodeStyle(node: DeviceNode) {
  const iconType = inferIconType(node.type, node.vendor, node.name)
  const config = DEVICE_TYPE_CONFIG[iconType] || DEVICE_TYPE_CONFIG.unknown
  const mappedStatus = mapStatus(node.status)
  const isOnline = mappedStatus === 'online'
  return {
    fill: '#162035',
    fillOpacity: isOnline ? 0.95 : 0.8,
    stroke: config.color,
    strokeWidth: isOnline ? 2 : 1.5,
    strokeOpacity: isOnline ? 0.8 : 0.5
  }
}

function getEdgeClass(edge: DeviceEdge): string {
  const sourceNode = deviceNodes.value.find(n => n.id === edge.source)
  const targetNode = deviceNodes.value.find(n => n.id === edge.target)
  const sourceStatus = sourceNode?.status || 'unknown'
  const targetStatus = targetNode?.status || 'unknown'
  
  if (sourceStatus === 'critical' || targetStatus === 'critical') return 'edge-critical'
  if (sourceStatus === 'offline' || targetStatus === 'offline') return 'edge-offline'
  if (sourceStatus === 'warning' || targetStatus === 'warning') return 'edge-warning'
  return 'edge-normal'
}

function getStatusColor(status: string): string {
  const mappedStatus = mapStatus(status)
  return STATUS_DOT_COLOR[mappedStatus] || '#909399'
}

function getStatusText(status: string): string {
  const map: Record<string, string> = {
    normal: t('topology.statusNormal'),
    online: t('topology.statusOnline'),
    warning: t('topology.statusWarning'),
    offline: t('topology.statusOffline'),
    critical: t('topology.statusCritical'),
    error: t('topology.statusError'),
    unknown: t('topology.statusUnknown')
  }
  return map[status] || status
}

function getStatusClass(status: string): string {
  return `status-${status}`
}

function getBandwidthLabel(edge: DeviceEdge): string {
  const bandwidths = ['100M', '1G', '10G', '100M', '1G', '10G', '1G']
  const index = parseInt(edge.id.replace('link_', '')) % bandwidths.length
  return index >= 0 ? bandwidths[index] : '100M'
}

function getDeviceTypeText(type: string): string {
  const map: Record<string, string> = {
    switch: t('topology.deviceSwitch'),
    router: t('topology.deviceRouter'),
    firewall: t('topology.deviceFirewall'),
    server: t('topology.deviceServer'),
    ap: t('topology.deviceAp'),
    'core-switch': t('topology.deviceCoreSwitch'),
    'access-switch': t('topology.deviceAccessSwitch'),
    'load-balancer': t('topology.deviceLoadBalancer'),
    ac: t('topology.deviceAc'),
    internet: t('topology.deviceInternetExit'),
    unknown: t('topology.deviceUnknown')
  }
  return map[type] || type
}

function getStatusSummary(node: DeviceNode): string {
  const mappedStatus = mapStatus(node.status)
  if (mappedStatus === 'offline') {
    return t('topology.statusOffline')
  }
  if (mappedStatus === 'warning') {
    return t('topology.statusWarning')
  }
  if (mappedStatus === 'online') {
    return t('topology.statusOnline')
  }
  return t('topology.statusUnknown')
}

function initializePositions() {
  // 只布局可见节点：隐藏节点不参与布局，避免把可见节点挤到视口外（悬空线根因）
  const nodes = filteredNodes.value
  const layers: Record<string, typeof nodes> = {}
  
  nodes.forEach(node => {
    const iconType = inferIconType((node as DeviceNode).type, (node as DeviceNode).vendor, node.name)
    const rank = DEVICE_RANK[iconType] ?? 3
    const rankKey = `rank_${rank}`
    if (!layers[rankKey]) layers[rankKey] = []
    layers[rankKey].push(node)
  })
  
  const rankOrder = ['rank_0', 'rank_1', 'rank_2', 'rank_3', 'rank_4']
  const activeRanks = rankOrder.filter(r => layers[r] && layers[r].length > 0)
  const totalLayers = activeRanks.length
  
  const usableHeight = canvasHeight.value / scale.value
  const layerSpacing = Math.min(140, (usableHeight - 120) / Math.max(totalLayers - 1, 1))
  const totalHeight = (totalLayers - 1) * layerSpacing
  const startY = (usableHeight - totalHeight) / 2
  
  activeRanks.forEach((rankKey, layerIndex) => {
    const group = layers[rankKey]
    const groupY = startY + layerIndex * layerSpacing
    const centerX = canvasWidth.value / 2 / scale.value
    
    group.forEach((node, index) => {
      const xOffset = (index - (group.length - 1) / 2) * 220
      nodePositions.value[node.id] = {
        x: centerX + xOffset,
        y: groupY
      }
    })
  })
}

function runForceLayout() {
  if (isLayoutRunning.value) return
  isLayoutRunning.value = true
  
  // 只对可见节点做力导布局
  const nodes = filteredNodes.value
  const k = Math.sqrt(canvasWidth.value * canvasHeight.value / Math.max(nodes.length, 1))
  const iterations = 100
  let iteration = 0

  function step() {
    const forces: Record<string, { x: number; y: number }> = {}

    nodes.forEach(node => {
      forces[node.id] = { x: 0, y: 0 }
    })
    
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
    
    deviceEdges.value.forEach(edge => {
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
    
    const centerX = canvasWidth.value / 2 / scale.value
    const centerY = canvasHeight.value / 2 / scale.value
    nodes.forEach(node => {
      const dx = centerX - nodePositions.value[node.id].x
      const dy = centerY - nodePositions.value[node.id].y
      forces[node.id].x += dx * 0.01
      forces[node.id].y += dy * 0.01
    })
    
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

function onNodeClick(nodeId: string) {
  selectedNodeId.value = selectedNodeId.value === nodeId ? null : nodeId
  
  // 如果点击的是互联网出口节点，加载站点设备列表
  const clickedNode = deviceNodes.value.find(n => n.id === nodeId)
  if (clickedNode && (clickedNode.type === 'internet' || nodeId.startsWith('internet_'))) {
    loadSiteDevicesForConnection(clickedNode.site_id)
  }
}

// 加载站点设备列表
async function loadSiteDevicesForConnection(siteId: number | null) {
  if (!siteId) return
  try {
    siteDevices.value = await getSiteDevices(siteId)
    // 从当前连接关系中获取已连接的设备
    const node = selectedNode.value
    if (node) {
      const edge = deviceEdges.value.find(e => e.source === node.id || e.target === node.id)
      if (edge) {
        const connectedNodeId = edge.source === node.id ? edge.target : edge.source
        const connectedDevice = deviceNodes.value.find(n => n.id === connectedNodeId)
        if (connectedDevice) {
          selectedConnectionDeviceId.value = connectedDevice.device_id > 0 ? connectedDevice.device_id : null
        }
      }
    }
  } catch (error) {
    console.error('Failed to load site devices:', error)
  }
}

function onNodeHover(node: DeviceNode, event: MouseEvent) {
  hoveredNode.value = node
  const canvasRect = canvasWrapper.value?.getBoundingClientRect()
  if (canvasRect) {
    const x = event.clientX - canvasRect.left + 16
    const y = event.clientY - canvasRect.top - 10
    tooltipStyle.value = {
      top: `${y}px`,
      left: `${x}px`
    }
  }
}

function onNodeLeave() {
  hoveredNode.value = null
}

function closeDetailPanel() {
  selectedNodeId.value = null
}

async function loadSiteData() {
  try {
    sites.value = await getSitesApi()
  } catch (error) {
    console.error('Failed to load sites:', error)
  }
}

async function loadDeviceData(keepPositions = false) {
  if (selectedSiteId.value === null) {
    // 未选站点不加载全量数据（数据量大时设备级拓扑无渲染意义）
    deviceNodes.value = []
    deviceEdges.value = []
    return
  }
  isLoading.value = true
  try {
    const data = await getDeviceGraph(selectedSiteId.value || undefined)
    deviceNodes.value = data.nodes
    deviceEdges.value = data.edges
    if (!keepPositions) {
      initializePositions()
    }
  } catch (error) {
    console.error('Failed to load device topology data:', error)
  } finally {
    isLoading.value = false
  }
}

function onSiteChange() {
  resetLayout()
  loadDeviceData()
}

// 切换「显示/隐藏孤立节点」后重新布局，让新出现的节点进入视口
watch(showIsolatedDevices, () => {
  if (!showEmptyState.value && !isLoading.value) {
    resetLayout()
  }
})

function startRefreshTimer() {
  if (refreshIntervalId.value) {
    clearInterval(refreshIntervalId.value)
  }
  refreshIntervalId.value = window.setInterval(async () => {
    try {
      await loadDeviceData(true)
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

// 导出为PNG
async function exportAsPNG() {
  const canvasEl = canvasWrapper.value
  if (!canvasEl) {
    ElMessage.error(t('topology.exportError'))
    return
  }
  
  try {
    ElMessage.info(t('topology.exporting'))
    const canvas = await html2canvas(canvasEl, {
      backgroundColor: '#0f1724',
      scale: 2,
      useCORS: true,
      logging: false
    })
    
    const link = document.createElement('a')
    link.download = `topology-${Date.now()}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
    ElMessage.success(t('topology.exportSuccess'))
  } catch (error) {
    console.error('Export PNG failed:', error)
    ElMessage.error(t('topology.exportError'))
  }
}

// 导出为JPG
async function exportAsJPG() {
  const canvasEl = canvasWrapper.value
  if (!canvasEl) {
    ElMessage.error(t('topology.exportError'))
    return
  }
  
  try {
    ElMessage.info(t('topology.exporting'))
    const canvas = await html2canvas(canvasEl, {
      backgroundColor: '#0f1724',
      scale: 2,
      useCORS: true,
      logging: false
    })
    
    const link = document.createElement('a')
    link.download = `topology-${Date.now()}.jpg`
    link.href = canvas.toDataURL('image/jpeg', 0.95)
    link.click()
    ElMessage.success(t('topology.exportSuccess'))
  } catch (error) {
    console.error('Export JPG failed:', error)
    ElMessage.error(t('topology.exportError'))
  }
}

// 导出为PDF
async function exportAsPDF() {
  const canvasEl = canvasWrapper.value
  if (!canvasEl) {
    ElMessage.error(t('topology.exportError'))
    return
  }
  
  try {
    ElMessage.info(t('topology.exporting'))
    const canvas = await html2canvas(canvasEl, {
      backgroundColor: '#0f1724',
      scale: 2,
      useCORS: true,
      logging: false
    })
    
    const imgData = canvas.toDataURL('image/png')
    const pdf = new jsPDF({
      orientation: canvas.width > canvas.height ? 'landscape' : 'portrait',
      unit: 'px',
      format: [canvas.width, canvas.height]
    })
    
    pdf.addImage(imgData, 'PNG', 0, 0, canvas.width, canvas.height)
    pdf.save(`topology-${Date.now()}.pdf`)
    ElMessage.success(t('topology.exportSuccess'))
  } catch (error) {
    console.error('Export PDF failed:', error)
    ElMessage.error(t('topology.exportError'))
  }
}

onMounted(async () => {
  handleResize()
  window.addEventListener('resize', handleResize)
  await loadSiteData()
  // 探测全量节点数：超过阈值时禁用「全部站点」选项
  try {
    const allData = await getDeviceGraph()
    totalAllNodes.value = allData.nodes.length
  } catch {
    totalAllNodes.value = 0
  }
  // 默认选中第一个站点，避免首次进入加载全量数据
  if (sites.value.length > 0) {
    selectedSiteId.value = sites.value[0].id
  }
  await loadDeviceData()
  startRefreshTimer()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  stopRefreshTimer()
})
</script>

<style scoped>
/* 拓扑页局部主题变量（深色画布专用） */
.device-topology {
  --topo-text-primary: rgba(255, 255, 255, 0.92);
  --topo-text-secondary: rgba(255, 255, 255, 0.65);
  --topo-text-muted: rgba(255, 255, 255, 0.45);
  --topo-accent: #409eff;
  --topo-warning: #e6a23c;
  --topo-success: #67c23a;
  --topo-danger: #f56c6c;
  --topo-unknown: #909399;
  --topo-border: rgba(64, 158, 255, 0.2);
}

.device-topology {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0a0e1a;
  position: relative;
}

.topology-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: rgba(22, 33, 62, 0.95);
  border-bottom: 1px solid rgba(45, 58, 79, 0.5);
  flex-wrap: wrap;
  gap: 8px;
}

.search-input {
  width: 240px;
}

.search-input :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(64, 158, 255, 0.3);
}

.search-input :deep(.el-input__inner) {
  color: #fff;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.site-select {
  width: 180px;
}

.site-select :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(64, 158, 255, 0.3);
  box-shadow: none;
}

.site-select :deep(.el-input__inner) {
  color: var(--topo-text-primary);
}

/* 孤立节点开关：文字外置不截断，适配深色背景 */
.isolated-switch :deep(.el-switch__label) {
  color: var(--topo-text-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.isolated-switch :deep(.el-switch__label.is-active) {
  color: var(--topo-accent);
}

.toolbar-btn {
  width: 36px;
  height: 36px;
  padding: 0;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(64, 158, 255, 0.2);
  color: var(--topo-text-primary);
}

.toolbar-btn:hover {
  background: rgba(64, 158, 255, 0.2);
  color: var(--topo-accent);
}

/* 画布状态层：加载中 / 空状态 */
.canvas-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  z-index: 10;
  pointer-events: none;
}

.canvas-state .state-icon {
  font-size: 48px;
  color: var(--topo-accent);
  opacity: 0.7;
}

.canvas-state .state-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--topo-text-primary);
}

.canvas-state .state-text {
  font-size: 14px;
  color: var(--topo-text-secondary);
}

.is-loading {
  animation: topo-rotate 1.2s linear infinite;
}

@keyframes topo-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 数据缺失提示 */
.canvas-alert {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 6px;
  background: rgba(230, 162, 60, 0.12);
  border: 1px solid rgba(230, 162, 60, 0.4);
  color: var(--topo-warning);
  font-size: 13px;
  z-index: 10;
  pointer-events: none;
}

.internet-control {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(64, 158, 255, 0.2);
  border-radius: 6px;
  padding: 4px 10px;
}

.control-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

.control-value {
  font-size: 14px;
  font-weight: 600;
  color: #40A9FF;
  min-width: 20px;
  text-align: center;
}

.internet-control .el-button {
  width: 24px;
  height: 24px;
  padding: 0;
  font-size: 14px;
  background: rgba(64, 158, 255, 0.15);
  border-color: rgba(64, 158, 255, 0.3);
  color: #40A9FF;
}

.internet-control .el-button:hover {
  background: rgba(64, 158, 255, 0.3);
}

.topology-main {
  flex: 1;
  display: flex;
  position: relative;
  overflow: hidden;
}

.topology-canvas {
  flex: 1;
  position: relative;
  background: 
    radial-gradient(ellipse at 20% 30%, rgba(64, 158, 255, 0.04) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 70%, rgba(100, 89, 234, 0.04) 0%, transparent 50%),
    #0a0e1a;
}

.topology-canvas::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-image: 
    linear-gradient(rgba(255, 255, 255, 0.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.015) 1px, transparent 1px);
  background-size: 30px 30px;
  pointer-events: none;
}

.topology-svg {
  cursor: grab;
}

.topology-svg:active {
  cursor: grabbing;
}

.topology-edge {
  fill: none;
  transition: all 0.3s ease;
}

.topology-edge.edge-normal {
  stroke: #5B8DB8;
  stroke-width: 2;
}

.topology-edge.edge-warning {
  stroke: #E6A23C;
  stroke-width: 2;
  stroke-dasharray: 8,3;
}

.topology-edge.edge-offline {
  stroke: #606266;
  stroke-width: 1.5;
  stroke-dasharray: 4,4;
}

.topology-edge.edge-critical {
  stroke: #F56C6C;
  stroke-width: 2;
  stroke-dasharray: 6,3;
}

.edge-bandwidth {
  fill: rgba(255, 255, 255, 0.6);
  font-size: 10px;
  font-weight: 500;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9);
  pointer-events: none;
}

.topology-node {
  cursor: pointer;
}

.topology-node:hover .node-box {
  stroke-width: 2.5;
  filter: drop-shadow(0 0 6px rgba(255, 255, 255, 0.15));
}

.topology-node text,
.topology-node circle {
  pointer-events: none;
}

.node-selected .node-box {
  stroke: #409eff;
  stroke-width: 2.5;
  filter: drop-shadow(0 0 8px rgba(64, 158, 255, 0.4));
}

.node-box {
  stroke-width: 1.5;
}

.node-icon {
  display: flex !important;
  align-items: center;
  justify-content: center;
  width: 100% !important;
  height: 100% !important;
  pointer-events: none;
  padding: 2px;
}

.status-dot {
  filter: drop-shadow(0 0 3px currentColor);
}

.node-name {
  fill: #fff;
  font-size: 14px;
  font-weight: 700;
}

.node-ip {
  fill: rgba(144, 147, 153, 0.7);
  font-size: 12px;
}

.node-status {
  font-size: 11px;
  font-weight: 600;
}

.node-status.status-online,
.node-status.status-normal {
  fill: #67C23A;
}

.node-status.status-warning {
  fill: #E6A23C;
}

.node-status.status-offline,
.node-status.status-critical,
.node-status.status-error {
  fill: #F56C6C;
}

.node-status.status-unknown {
  fill: #909399;
}

/* Tooltip */
.tooltip-panel {
  position: absolute;
  background: rgba(20, 30, 50, 0.96);
  border: 1px solid rgba(64, 158, 255, 0.25);
  border-radius: 8px;
  padding: 12px 16px;
  min-width: 220px;
  z-index: 200;
  pointer-events: none;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
}

.tooltip-header {
  margin-bottom: 4px;
}

.tooltip-name {
  font-size: 14px;
  font-weight: 600;
  color: #fff;
}

.tooltip-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
  margin: 8px 0;
}

.tooltip-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.tooltip-label {
  font-size: 12px;
  color: var(--topo-text-muted);
}

.tooltip-value {
  font-size: 12px;
  color: #fff;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tooltip-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.tooltip-hint {
  font-size: 11px;
  color: rgba(64, 158, 255, 0.7);
  margin-top: 4px;
}

/* Detail Panel */
.detail-panel {
  position: absolute;
  right: 0;
  top: 60px;
  bottom: 0;
  width: 260px;
  background: rgba(15, 23, 36, 0.98);
  border-left: 1px solid rgba(64, 158, 255, 0.2);
  display: flex;
  flex-direction: column;
  z-index: 100;
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.3);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(64, 158, 255, 0.2);
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
  color: #fff;
}

.close-btn {
  width: 32px;
  height: 32px;
  padding: 0;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.6);
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.panel-content {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.info-label {
  font-size: 12px;
  color: var(--topo-text-secondary);
}

.info-value {
  font-size: 12px;
  color: #fff;
  font-weight: 500;
}

.panel-footer {
  padding: 16px 20px;
  border-top: 1px solid rgba(64, 158, 255, 0.2);
}

.panel-footer .el-button {
  width: 100%;
}

/* Connection Setting */
.connection-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(64, 158, 255, 0.2);
}

.connection-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
  margin-bottom: 8px;
}

.connection-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.connection-item {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 6px;
  padding: 8px 12px;
}

.connection-device {
  font-size: 13px;
  color: #fff;
  font-weight: 500;
}

.connection-ports {
  display: flex;
  gap: 16px;
  margin-top: 4px;
}

.port-info {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
}

/* Legend */
.legend-panel {
  position: absolute;
  bottom: 20px;
  right: 20px;
  background: rgba(15, 23, 36, 0.95);
  border: 1px solid var(--topo-border);
  border-radius: 8px;
  padding: 12px 16px;
  z-index: 50;
  max-height: calc(100% - 40px);
  overflow-y: auto;
}

.legend-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--topo-text-primary);
  margin-bottom: 10px;
}

.legend-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.legend-section:last-child {
  margin-bottom: 0;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--topo-text-secondary);
}

.legend-type-icon {
  flex-shrink: 0;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.legend-dot.online {
  background: var(--topo-success);
}

.legend-dot.warning {
  background: var(--topo-warning);
}

.legend-dot.offline {
  background: var(--topo-danger);
}

.status-normal,
.status-online {
  color: #67C23A;
}

.status-warning {
  color: #E6A23C;
}

.status-offline,
.status-critical,
.status-error {
  color: #F56C6C;
}

.status-unknown {
  color: #909399;
}
</style>