<script setup lang="ts">import { ref, computed } from 'vue';
import { ElMessage } from 'element-plus';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { testDeviceConnection, quickAddDevice, type TestConnectionRequest, type QuickAddDeviceRequest } from '@/api/quick_add';
import { getSites } from '@/api/sites';
import { getPrefixes } from '@/api/ipam';
const router = useRouter();
const { t } = useI18n();
const visible = defineModel<boolean>('visible');
const currentStep = ref(1);
const loading = ref(false);
const sites = ref<any[]>([]);
const prefixes = ref<any[]>([]);
const formData = ref<{
 name: string;
 ip_address: string;
 prefix_id: number | null;
 site_id: number | null;
 vendor: string;
 type: string;
 username: string;
 password: string;
 port: number;
 enable_password: string;
 location: string;
 owner: string;
}>({
 name: '',
 ip_address: '',
 prefix_id: null,
 site_id: null,
 vendor: 'huawei_vrp',
 type: 'switch',
 username: '',
 password: '',
 port: 22,
 enable_password: '',
 location: '',
 owner: '',
});
const testResult = ref<{
 success: boolean;
 message: string;
 device_info?: any;
} | null>(null);
const vendorOptions = [
 { value: 'huawei_vrp', label: '华为 VRP' },
 { value: 'cisco_ios', label: 'Cisco IOS' },
 { value: 'cisco_nxos', label: 'Cisco NX-OS' },
 { value: 'h3c', label: 'H3C Comware' },
 { value: 'juniper', label: 'Juniper Junos' },
 { value: 'fortinet', label: 'Fortinet' },
 { value: 'linux', label: 'Linux' },
 { value: 'ruijie_os', label: '锐捷' },
 { value: 'hillstone', label: '山石' },
 { value: 'aruba', label: 'Aruba' },
];
const typeOptions = computed(() => [
 { value: 'switch', label: t('devices.typeSwitch') },
 { value: 'router', label: t('devices.typeRouter') },
 { value: 'firewall', label: t('devices.typeFirewall') },
 { value: 'server', label: t('devices.typeServer') },
 { value: 'ap', label: t('devices.typeAP') },
 { value: 'other', label: t('devices.typeOther') },
]);
const steps = [
 { title: '基本信息', step: 1 },
 { title: '连接信息', step: 2 },
 { title: '测试连接', step: 3 },
 { title: '完成', step: 4 },
];
const canNext = computed(() => {
 if (currentStep.value === 1) {
 return formData.value.name && formData.value.ip_address && formData.value.vendor && formData.value.type;
 }
 if (currentStep.value === 2) {
 return formData.value.username && formData.value.password;
 }
 if (currentStep.value === 3) {
 return testResult.value?.success === true;
 }
 return false;
});
async function loadData() {
 try {
 const [siteData, prefixData] = await Promise.all([getSites(), getPrefixes()]);
 sites.value = siteData;
 prefixes.value = prefixData;
 }
 catch (error) {
 console.error('Failed to load data:', error);
 }
}
function nextStep() {
 if (!canNext.value)
 return;
 currentStep.value++;
}
function prevStep() {
 if (currentStep.value > 1) {
 currentStep.value--;
 }
}
async function handleTestConnection() {
 if (!formData.value.ip_address || !formData.value.username || !formData.value.password) {
 ElMessage.warning('请填写完整的连接信息');
 return;
 }
 loading.value = true;
 try {
 const request: TestConnectionRequest = {
 ip_address: formData.value.ip_address,
 vendor: formData.value.vendor,
 username: formData.value.username,
 password: formData.value.password,
 port: formData.value.port,
 enable_password: formData.value.enable_password || undefined,
 };
 const result = await testDeviceConnection(request);
 testResult.value = result;
 if (result.success) {
 ElMessage.success('连接测试成功');
 }
 else {
 ElMessage.error(result.message);
 }
 }
 catch (error) {
 testResult.value = { success: false, message: '测试连接失败，请检查网络和凭据' };
 ElMessage.error('测试连接失败');
 }
 finally {
 loading.value = false;
 }
}
async function handleQuickAdd() {
 loading.value = true;
 try {
 const request: QuickAddDeviceRequest = {
 name: formData.value.name,
 ip_address: formData.value.ip_address,
 prefix_id: formData.value.prefix_id || undefined,
 site_id: formData.value.site_id || undefined,
 vendor: formData.value.vendor,
 username: formData.value.username,
 password: formData.value.password,
 port: formData.value.port,
 enable_password: formData.value.enable_password || undefined,
 type: formData.value.type,
 location: formData.value.location || undefined,
 owner: formData.value.owner || undefined,
 };
 const result = await quickAddDevice(request);
 if (result.success) {
 ElMessage.success(result.message);
 visible.value = false;
 router.push('/devices');
 }
 else {
 ElMessage.error(result.message);
 }
 }
 catch (error) {
 ElMessage.error('添加设备失败');
 }
 finally {
 loading.value = false;
 }
}
function handleClose() {
 visible.value = false;
 currentStep.value = 1;
 testResult.value = null;
 formData.value = {
 name: '',
 ip_address: '',
 prefix_id: null,
 site_id: null,
 vendor: 'huawei_vrp',
 type: 'switch',
 username: '',
 password: '',
 port: 22,
 enable_password: '',
 location: '',
 owner: '',
 };
}
loadData();
</script>

<template>
  <el-dialog
    v-model="visible"
    title="快速添加设备"
    width="720px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <div class="wizard-container">
      <el-steps :active="currentStep" align-center class="wizard-steps">
        <el-step v-for="step in steps" :key="step.step" :title="step.title" />
      </el-steps>
      
      <div class="wizard-content">
        <!-- Step 1: 基本信息 -->
        <div v-if="currentStep === 1" class="step-content">
          <el-form label-position="top" :model="formData">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="设备名称" required>
                  <el-input v-model="formData.name" placeholder="请输入设备名称" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="管理IP" required>
                  <el-input v-model="formData.ip_address" placeholder="请输入管理IP地址" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="所属站点">
                  <el-select v-model="formData.site_id" placeholder="请选择站点">
                    <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="所属子网">
                  <el-select v-model="formData.prefix_id" placeholder="请选择子网">
                    <el-option v-for="prefix in prefixes" :key="prefix.id" :label="prefix.network" :value="prefix.id" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="设备厂商" required>
                  <el-select v-model="formData.vendor" placeholder="请选择厂商">
                    <el-option v-for="vendor in vendorOptions" :key="vendor.value" :label="vendor.label" :value="vendor.value" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="设备类型" required>
                  <el-select v-model="formData.type" placeholder="请选择类型">
                    <el-option v-for="type in typeOptions" :key="type.value" :label="type.label" :value="type.value" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="物理位置">
                  <el-input v-model="formData.location" placeholder="如：机房A-1号机架" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="负责人">
                  <el-input v-model="formData.owner" placeholder="如：网络组" />
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </div>
        
        <!-- Step 2: 连接信息 -->
        <div v-if="currentStep === 2" class="step-content">
          <el-form label-position="top" :model="formData">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="SSH用户名" required>
                  <el-input v-model="formData.username" placeholder="请输入用户名" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="SSH密码" required>
                  <el-input v-model="formData.password" type="password" placeholder="请输入密码" show-password />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="SSH端口">
                  <el-input-number v-model="formData.port" :min="1" :max="65535" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Enable密码（可选）">
                  <el-input v-model="formData.enable_password" type="password" placeholder="请输入enable密码" show-password />
                </el-form-item>
              </el-col>
            </el-row>
            <el-alert type="info" title="注意" :closable="false">
              请确保设备已配置SSH服务，并且当前服务器能够访问该设备的管理IP。
            </el-alert>
          </el-form>
        </div>
        
        <!-- Step 3: 测试连接 -->
        <div v-if="currentStep === 3" class="step-content">
          <div class="test-connection-section">
            <div class="connection-info">
              <el-descriptions :column="2" border>
                <el-descriptions-item label="设备IP">{{ formData.ip_address }}</el-descriptions-item>
                <el-descriptions-item label="厂商类型">{{ vendorOptions.find(v => v.value === formData.vendor)?.label }}</el-descriptions-item>
                <el-descriptions-item label="用户名">{{ formData.username }}</el-descriptions-item>
                <el-descriptions-item label="端口">{{ formData.port }}</el-descriptions-item>
              </el-descriptions>
            </div>
            
            <div class="test-action">
              <el-button 
                type="primary" 
                :loading="loading" 
                @click="handleTestConnection"
                style="width: 200px;"
              >
                <el-icon><Connection /></el-icon>
                测试连接
              </el-button>
            </div>
            
            <div v-if="testResult" class="test-result">
              <el-alert
                :type="testResult.success ? 'success' : 'error'"
                :title="testResult.success ? '连接成功' : '连接失败'"
                :description="testResult.message"
                :closable="false"
              />
              
              <div v-if="testResult.device_info" class="device-info">
                <h4>设备信息</h4>
                <pre>{{ testResult.device_info.output }}</pre>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Step 4: 完成 -->
        <div v-if="currentStep === 4" class="step-content">
          <div class="complete-section">
            <el-icon class="success-icon"><CircleCheck /></el-icon>
            <h3>连接测试通过</h3>
            <p>即将添加以下设备到系统：</p>
            
            <el-descriptions :column="2" border class="summary-descriptions">
              <el-descriptions-item label="设备名称">{{ formData.name }}</el-descriptions-item>
              <el-descriptions-item label="管理IP">{{ formData.ip_address }}</el-descriptions-item>
              <el-descriptions-item label="所属站点">{{ sites.find(s => s.id === formData.site_id)?.name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="所属子网">{{ prefixes.find(p => p.id === formData.prefix_id)?.network || '-' }}</el-descriptions-item>
              <el-descriptions-item label="设备厂商">{{ vendorOptions.find(v => v.value === formData.vendor)?.label }}</el-descriptions-item>
              <el-descriptions-item label="设备类型">{{ typeOptions.find(t => t.value === formData.type)?.label }}</el-descriptions-item>
              <el-descriptions-item label="物理位置">{{ formData.location || '-' }}</el-descriptions-item>
              <el-descriptions-item label="负责人">{{ formData.owner || '-' }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </div>
      </div>
      
      <div class="wizard-footer">
        <el-button v-if="currentStep > 1 && currentStep < 4" @click="prevStep">上一步</el-button>
        <el-button v-if="currentStep < 3" type="primary" :disabled="!canNext" @click="nextStep">下一步</el-button>
        <el-button v-if="currentStep === 3" type="primary" :disabled="!canNext" @click="nextStep">下一步</el-button>
        <el-button v-if="currentStep === 4" type="primary" :loading="loading" @click="handleQuickAdd">确认添加</el-button>
        <el-button @click="handleClose">取消</el-button>
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.wizard-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.wizard-steps {
  padding: 8px 0;
}

.wizard-content {
  min-height: 300px;
}

.step-content {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.test-connection-section {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.connection-info {
  background: #fafafa;
  padding: 16px;
  border-radius: 8px;
}

.test-action {
  display: flex;
  justify-content: center;
}

.test-result {
  margin-top: 16px;
}

.device-info {
  margin-top: 16px;
  background: #f5f5f5;
  padding: 16px;
  border-radius: 8px;
}

.device-info h4 {
  margin-bottom: 12px;
  font-size: 14px;
  color: #262626;
}

.device-info pre {
  font-family: 'SF Mono', monospace;
  font-size: 12px;
  color: #595959;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.complete-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 20px;
}

.success-icon {
  font-size: 64px;
  color: #67c23a;
  margin-bottom: 16px;
}

.complete-section h3 {
  font-size: 20px;
  color: #262626;
  margin-bottom: 8px;
}

.complete-section p {
  color: #8c8c8c;
  margin-bottom: 24px;
}

.summary-descriptions {
  width: 100%;
}

.wizard-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid #f0f0f0;
}
</style>