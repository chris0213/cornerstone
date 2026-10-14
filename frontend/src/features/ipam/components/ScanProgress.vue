<script setup lang="ts">import { ref, onMounted, onUnmounted, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { Clock, Check, CircleCheck, CircleClose } from '@element-plus/icons-vue';
const props = defineProps<{
 visible: boolean;
 network: string;
 taskId: string;
}>();
const emit = defineEmits<{
 (e: 'close'): void;
 (e: 'completed'): void;
 (e: 'progress', currentIp: string): void;
 (e: 'result', ip: string, isOnline: boolean): void;
}>();
const progress = ref(0);
const total = ref(0);
const scanned = ref(0);
const onlineCount = ref(0);
const currentIp = ref('');
const scanResults = ref<{
 ip: string;
 isOnline: boolean;
 method?: string;
}[]>([]);
let ws: WebSocket | null = null;
interface ScanResult {
 type: string;
 percent?: number;
 total?: number;
 scanned?: number;
 online?: number;
 current_ip?: string;
 ip?: string;
 is_online?: boolean;
 method?: string;
}
const connectWebSocket = () => {
  if (!props.taskId) return

  try {
    // 动态拼 WebSocket 地址：http→ws、https→wss，复用浏览器当前 host
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const token = localStorage.getItem('access_token') || ''
    const wsUrl = `${proto}//${host}/api/v1/ipam/ws/scan/${props.taskId}?token=${encodeURIComponent(token)}`
    console.log('WebSocket URL:', wsUrl)
    ws = new WebSocket(wsUrl)
    ws.onopen = () => {
      console.log('WebSocket connected')
    }
 ws.onmessage = (event) => {
 try {
 const data: ScanResult = JSON.parse(event.data);
 console.log('收到消息:', data)
 if (data.type === 'progress') {
 progress.value = data.percent || 0;
 total.value = data.total || 0;
 scanned.value = data.scanned || 0;
 onlineCount.value = data.online || 0;
 currentIp.value = data.current_ip || '';
 if (currentIp.value) emit('progress', currentIp.value);
 }
 else if (data.type === 'result') {
 if (data.ip !== undefined) {
 scanResults.value.push({
 ip: data.ip,
 isOnline: data.is_online === true,
 method: data.method
 });
 emit('result', data.ip, data.is_online === true);
 }
 }
 else if (data.type === 'done') {
 handleScanCompleted();
 }
 }
 catch (error) {
 console.error('WebSocket message parse error:', error);
 }
 };
 ws.onerror = (error) => {
 console.error('WebSocket error:', error);
 console.error('WebSocket readyState:', ws?.readyState);
 ElMessage.error('扫描连接出错');
 };
 ws.onclose = () => {
 console.log('WebSocket closed');
 };
 }
 catch (error) {
 console.error('Failed to connect WebSocket:', error);
 ElMessage.error('无法建立扫描连接');
 }
};
const handleScanCompleted = () => {
 if (ws) {
 ws.close();
 ws = null;
 }
 ElMessage.success(`扫描完成！在线主机: ${onlineCount.value} 台`);
 emit('completed');
};
const handleClose = () => {
 if (ws) {
 ws.close();
 ws = null;
 }
 emit('close');
};
watch(() => props.visible, (newVal) => {
 if (newVal && props.taskId) {
 connectWebSocket();
 }
});
onMounted(() => {
 if (props.visible && props.taskId) {
 connectWebSocket();
 }
});
onUnmounted(() => {
 if (ws) {
 ws.close();
 ws = null;
 }
});
</script>

<template>
  <el-dialog
    :visible="visible"
    title="IP扫描进度"
    width="560px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    @close="handleClose"
  >
    <div class="scan-content">
      <div class="scan-network">
        <el-icon><CircleCheck /></el-icon>
        <span>正在扫描: {{ network }}</span>
      </div>

      <!-- 进度条 -->
      <div class="progress-section">
        <div class="progress-header">
          <span>扫描进度</span>
          <span class="progress-text">{{ Math.round(progress) }}%</span>
        </div>
        <el-progress :percentage="progress" :status="progress === 100 ? 'success' : 'active'" />
        <div class="progress-stats">
          <span>已扫描: {{ scanned }} / {{ total }}</span>
          <span class="online-count">在线: {{ onlineCount }}</span>
        </div>
      </div>

      <!-- 当前扫描IP -->
      <div class="current-ip" v-if="currentIp">
        <el-icon><Clock /></el-icon>
        <span>正在探测: <code>{{ currentIp }}</code></span>
      </div>

      <!-- 扫描结果列表 -->
      <div class="results-section">
        <div class="results-header">
          <span>扫描结果</span>
          <span class="results-count">{{ scanResults.length }} 个结果</span>
        </div>
        <div class="results-list">
          <div 
            v-for="result in scanResults.slice(-10)" 
            :key="result.ip" 
            class="result-item"
          >
            <component 
              :is="result.isOnline ? CircleCheck : CircleClose" 
              :class="['result-icon', result.isOnline ? 'online' : 'offline']" 
            />
            <span class="result-ip">{{ result.ip }}</span>
            <span v-if="result.method" class="result-method">{{ result.method }}</span>
          </div>
          <div v-if="scanResults.length === 0" class="no-results">
            等待扫描结果...
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button :disabled="progress < 100" @click="handleClose">
        <el-icon><Check /></el-icon>
        {{ progress === 100 ? '完成' : '取消' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.scan-content {
  padding: 8px;
}

.scan-network {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #f6ffed;
  border-radius: 8px;
  margin-bottom: 16px;
  color: #52c41a;
  font-weight: 500;
}

.progress-section {
  margin-bottom: 16px;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.progress-text {
  font-weight: 600;
  color: #1890ff;
}

.progress-stats {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 13px;
  color: #666;
}

.online-count {
  color: #52c41a;
  font-weight: 500;
}

.current-ip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #e6f7ff;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
}

.current-ip code {
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  color: #1890ff;
  background: rgba(24, 144, 255, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
}

.results-section {
  max-height: 200px;
}

.results-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 500;
}

.results-count {
  font-size: 12px;
  color: #999;
  font-weight: normal;
}

.results-list {
  max-height: 160px;
  overflow-y: auto;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 8px;
}

.result-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 4px;
  margin-bottom: 4px;
  background: #fafafa;
}

.result-item:last-child {
  margin-bottom: 0;
}

.result-icon {
  font-size: 14px;
}

.result-icon.online {
  color: #52c41a;
}

.result-icon.offline {
  color: #bfbfbf;
}

.result-ip {
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  flex: 1;
}

.result-method {
  font-size: 11px;
  color: #999;
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 4px;
}

.no-results {
  text-align: center;
  padding: 20px;
  color: #999;
  font-size: 13px;
}
</style>
