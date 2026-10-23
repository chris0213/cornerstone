<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, reactive, computed } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Picture, Refresh, OfficeBuilding, Edit } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import api from '../../api/axios'
import { getCompanyInfo, updateCompanyInfo, type CompanyInfo } from '../../api/reports'
import { useI18n } from 'vue-i18n'
import { useBrandStore } from '../../store/brand'

const { t } = useI18n()
const brandStore = useBrandStore()
const currentLogo = ref<string>('')
const fileInputRef = ref<HTMLInputElement | null>(null)
const isLoading = ref(false)

const companyFormRef = ref<FormInstance | null>(null)
const companyForm = reactive<CompanyInfo>({
  company_name: '',
  company_short_name: '',
  it_department_name: '信息技术部',
  it_contact_name: '',
  it_contact_email: '',
})
const companyLoading = ref(false)

// 品牌设置表单
const brandForm = reactive({
  brand_name_zh: '基石',
  brand_name_en: 'Cornerstone',
  brand_slogan: '智能运维，尽在掌控',
  brand_subtitle: '企业级IT基础设施智能运维平台',
})
const brandLoading = ref(false)
const brandFetchLoading = ref(false)

// ============ 未保存提示（dirty 检测） ============
// 以「加载完成后的初始值」为基线，三个区块任一有改动即视为 dirty
const companyBaseline = ref('')
const brandBaseline = ref('')
const logoBaseline = ref('') // 初始 Logo（base64 data URL 或空）

const snapshot = (obj: Record<string, unknown>) => JSON.stringify(obj)

const companyDirty = computed(() => companyBaseline.value !== '' && snapshot({ ...companyForm }) !== companyBaseline.value)
const brandDirty = computed(() => brandBaseline.value !== '' && snapshot({ ...brandForm }) !== brandBaseline.value)
const logoDirty = computed(() => currentLogo.value !== logoBaseline.value)
const hasUnsavedChanges = computed(() => companyDirty.value || brandDirty.value || logoDirty.value)

const beforeUnloadHandler = (e: BeforeUnloadEvent) => {
  if (hasUnsavedChanges.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', beforeUnloadHandler)
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnloadHandler)
})

onBeforeRouteLeave(async (_to, _from, _from2) => {
  if (!hasUnsavedChanges.value) return true
  try {
    await ElMessageBox.confirm(
      t('settings.unsavedConfirm'),
      t('settings.unsavedTitle'),
      {
        confirmButtonText: t('settings.unsavedLeave'),
        cancelButtonText: t('settings.unsavedStay'),
        type: 'warning',
      }
    )
    window.removeEventListener('beforeunload', beforeUnloadHandler)
    return true
  } catch {
    return false
  }
})

const markCompanyClean = () => { companyBaseline.value = snapshot({ ...companyForm }) }
const markBrandClean = () => { brandBaseline.value = snapshot({ ...brandForm }) }
const markLogoClean = () => { logoBaseline.value = currentLogo.value }

const fetchBrandSettings = async () => {
  brandFetchLoading.value = true
  try {
    const res = await api.get('/api/v1/settings/brand')
    const data = res.data
    brandForm.brand_name_zh = data.brand_name_zh || '基石'
    brandForm.brand_name_en = data.brand_name_en || 'Cornerstone'
    brandForm.brand_slogan = data.brand_slogan || '智能运维，尽在掌控'
    brandForm.brand_subtitle = data.brand_subtitle || '企业级IT基础设施智能运维平台'
  } catch (error: any) {
    console.error('加载品牌设置失败:', error)
  } finally {
    brandFetchLoading.value = false
    markBrandClean()
  }
}

const brandRules: FormRules = {
  brand_slogan: [
    { required: true, message: t('settings.brandSloganRequired'), trigger: 'blur' },
    { max: 50, message: t('settings.brandSloganMax'), trigger: 'blur' },
  ],
  brand_subtitle: [
    { required: true, message: t('settings.brandSubtitleRequired'), trigger: 'blur' },
    { max: 100, message: t('settings.brandSubtitleMax'), trigger: 'blur' },
  ],
}

const saveBrandSettings = async () => {
  brandLoading.value = true
  try {
    await api.put('/api/v1/settings/brand', {
      brand_slogan: brandForm.brand_slogan,
      brand_subtitle: brandForm.brand_subtitle,
      brand_logo_url: '',
    })
    await brandStore.loadBrand()
    markBrandClean()
    ElMessage.success('品牌设置已更新')
  } catch (error: any) {
    console.error('保存品牌设置失败:', error)
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    brandLoading.value = false
  }
}

const resetBrandSettings = async () => {
  try {
    await ElMessageBox.confirm(
      `${t('settings.resetBrandConfirm')}\n${t('settings.resetBrandDefaults')}`,
      t('settings.resetBrandTitle'),
      { confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), type: 'warning' }
    )
    brandLoading.value = true
    try {
      await api.post('/api/v1/settings/brand/reset')
      await fetchBrandSettings()
      await brandStore.loadBrand()
      ElMessage.success('品牌设置已恢复默认')
    } catch (error: any) {
      console.error('恢复默认品牌设置失败:', error)
      ElMessage.error(error.response?.data?.detail || '恢复失败')
    } finally {
      brandLoading.value = false
    }
  } catch {
    // 用户取消
  }
}

onMounted(() => {
  fetchLogo()
  fetchCompanyInfo()
  fetchBrandSettings()
})

const fetchCompanyInfo = async () => {
  try {
    const data = await getCompanyInfo()
    Object.assign(companyForm, data)
  } catch (error: any) {
    console.error('Failed to load company info:', error)
  } finally {
    markCompanyClean()
  }
}

const companyRules: FormRules = {
  company_name: [
    { required: true, message: t('settings.companyNameRequired'), trigger: 'blur' },
    { max: 100, message: t('settings.companyNameMax'), trigger: 'blur' },
  ],
  company_short_name: [
    { max: 50, message: t('settings.companyShortNameMax'), trigger: 'blur' },
  ],
  it_department_name: [
    { max: 50, message: t('settings.itDeptMax'), trigger: 'blur' },
  ],
  it_contact_name: [
    { max: 50, message: t('settings.itContactMax'), trigger: 'blur' },
  ],
  it_contact_email: [
    { type: 'email', message: t('settings.itEmailInvalid'), trigger: 'blur' },
  ],
}

const saveCompanyInfo = async () => {
  const valid = await companyFormRef.value?.validate().catch(() => false)
  if (!valid) return
  companyLoading.value = true
  try {
    await updateCompanyInfo({ ...companyForm })
    markCompanyClean()
    ElMessage.success('公司信息已更新')
  } catch (error: any) {
    console.error('Failed to save company info:', error)
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    companyLoading.value = false
  }
}

const fetchLogo = async (retries = 3) => {
  for (let i = 0; i < retries; i++) {
    try {
      const response = await api.get('/api/v1/settings/logo')
      const data = response.data
      if (data.value) {
        currentLogo.value = `data:image/png;base64,${data.value}`
      }
      return
    } catch (error: any) {
      const isConnectionError = error.code === 'ECONNREFUSED' ||
        error.message?.includes('ECONNREFUSED') ||
        error.errno === 'ECONNREFUSED'
      if (i < retries - 1 && isConnectionError) {
        await new Promise(resolve => setTimeout(resolve, 1000))
        continue
      }
      console.log(t('settings.fetchLogoFailed'), error)
    } finally {
      if (i === retries - 1) markLogoClean()
    }
  }
}

const triggerFileInput = () => {
  fileInputRef.value?.click()
}

// 与后端白名单保持一致（后端会做魔数校验，SVG/BMP 等一律拒绝）
const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']

const handleFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]

  if (!file) {
    return
  }

  // 验证文件类型（严格白名单，与后端一致）
  const hasValidType = ALLOWED_IMAGE_TYPES.includes(file.type)

  if (!hasValidType) {
    ElMessage.error(t('settings.uploadImageError'))
    input.value = ''
    return
  }

  // 验证文件大小
  const maxSize = 2 * 1024 * 1024 // 2MB
  if (file.size > maxSize) {
    ElMessage.error(t('settings.imageSizeError'))
    input.value = ''
    return
  }

  isLoading.value = true

  try {
      const formData = new FormData()
      formData.append('file', file)

      await api.post('/settings/logo', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })

      currentLogo.value = URL.createObjectURL(file)
      markLogoClean()
      ElMessage.success(t('settings.logoUploadSuccess'))
    } catch (error: any) {
      console.error(t('settings.uploadFailed'), error)
      ElMessage.error(error.response?.data?.detail || t('settings.uploadFailed'))
    } finally {
      isLoading.value = false
      input.value = ''
    }
}

const handleLogoRemove = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.removeLogoConfirm'),
      t('settings.removeLogoTitle'),
      { confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), type: 'warning' }
    )
  } catch {
    return // 用户取消
  }
  try {
    await api.delete('/settings/logo')
    currentLogo.value = ''
    markLogoClean()
    ElMessage.success(t('settings.logoRemoved'))
  } catch (error: any) {
    console.error(t('settings.deleteFailed'), error)
    ElMessage.error(error.response?.data?.detail || t('settings.deleteFailed'))
  }
}
</script>

<template>
  <div class="settings-page">
    <div class="settings-section">
      <div class="section-header">
        <el-icon class="section-icon"><Picture /></el-icon>
        <h2 class="section-title">{{ t('settings.companyLogo') }}</h2>
        <p class="section-desc">{{ t('settings.companyLogoDesc') }}</p>
      </div>

      <div class="logo-upload-area">
        <div class="logo-preview">
          <div v-if="currentLogo" class="logo-image-container">
            <img :src="currentLogo" :alt="t('settings.companyLogo')" class="logo-image" />
          </div>
          <div v-else class="logo-placeholder">
            <div class="logo-placeholder-icon">
              <el-icon><Picture /></el-icon>
            </div>
            <p>{{ t('settings.noLogo') }}</p>
            <p class="hint">{{ t('settings.logoHint') }}</p>
          </div>
        </div>

        <div class="logo-upload">
          <input
            ref="fileInputRef"
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            class="upload-input"
            @change="handleFileChange"
          />
          <el-button type="primary" size="large" @click="triggerFileInput" :loading="isLoading">
            <el-icon><Picture /></el-icon>
            {{ t('settings.uploadLogo') }}
          </el-button>

          <div v-if="currentLogo" class="logo-actions">
            <el-button type="default" size="small" @click="handleLogoRemove">
              <el-icon><Refresh /></el-icon>
              {{ t('settings.restoreDefault') }}
            </el-button>
          </div>
          <p class="upload-hint">{{ t('settings.uploadHint') }}</p>
        </div>
      </div>

      <div class="logo-tips">
        <h3 class="tips-title">{{ t('settings.operationTips') }}</h3>
        <ul class="tips-list">
          <li>{{ t('settings.tip1') }}</li>
          <li>{{ t('settings.tip2') }}</li>
          <li>{{ t('settings.tip3') }}</li>
          <li>{{ t('settings.tip4') }}</li>
        </ul>
      </div>
    </div>

    <div class="settings-section">
      <div class="section-header">
        <el-icon class="section-icon"><Edit /></el-icon>
        <h2 class="section-title">品牌设置</h2>
        <p class="section-desc">系统名称已锁定，不可修改。您可以自定义标语和副标题</p>
      </div>

      <div class="brand-form" v-loading="brandFetchLoading">
        <el-form :model="brandForm" :rules="brandRules" label-width="140px" size="large">
          <el-form-item :label="t('settings.brandNameZh')">
            <el-input v-model="brandForm.brand_name_zh" disabled />
            <div class="form-tip">{{ t('settings.brandNameLocked') }}</div>
          </el-form-item>
          <el-form-item :label="t('settings.brandNameEn')">
            <el-input v-model="brandForm.brand_name_en" disabled />
          </el-form-item>
          <el-form-item :label="t('settings.brandSlogan')" prop="brand_slogan">
            <el-input v-model="brandForm.brand_slogan" :placeholder="t('settings.brandSloganPlaceholder')" :maxlength="50" show-word-limit />
          </el-form-item>
          <el-form-item :label="t('settings.brandSubtitle')" prop="brand_subtitle">
            <el-input v-model="brandForm.brand_subtitle" :placeholder="t('settings.brandSubtitlePlaceholder')" :maxlength="100" show-word-limit />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveBrandSettings" :loading="brandLoading">{{ t('common.save') }}</el-button>
            <el-button @click="resetBrandSettings" :loading="brandLoading" :disabled="brandFetchLoading">{{ t('settings.restoreDefault') }}</el-button>
          </el-form-item>
        </el-form>

        <div class="login-preview-card">
          <h3 class="preview-title">{{ t('settings.loginPreview') }}</h3>
          <div class="preview-body">
            <div class="preview-logo-row">
              <div class="preview-logo">
                <img v-if="currentLogo" :src="currentLogo" :alt="t('settings.companyLogo')" />
                <svg v-else viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M24 4L4 20v24l20 16 20-16V20L24 4z" fill="url(#previewLogoGradient)" />
                  <path d="M24 10L8 22v16l16 10 16-10V22L24 10z" fill="white" opacity="0.95" />
                  <defs>
                    <linearGradient id="previewLogoGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" style="stop-color:#3b82f6" />
                      <stop offset="100%" style="stop-color:#8b5cf6" />
                    </linearGradient>
                  </defs>
                </svg>
              </div>
              <span class="preview-brand-name">{{ brandForm.brand_name_zh }}&nbsp;&nbsp;{{ brandForm.brand_name_en }}</span>
            </div>
            <div class="preview-slogan">
              <h2>{{ brandForm.brand_slogan || t('login.leftTitle') }}</h2>
              <p>{{ t('login.leftSubtitle') }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="settings-section">
      <div class="section-header">
        <el-icon class="section-icon"><OfficeBuilding /></el-icon>
        <h2 class="section-title">公司信息</h2>
        <p class="section-desc">公司信息将用于运营月报封面、邮件通知落款等场景，请确保信息准确</p>
      </div>

      <div class="company-form">
        <el-form ref="companyFormRef" :model="companyForm" :rules="companyRules" label-width="120px" size="large">
          <el-form-item :label="t('settings.companyName')" prop="company_name">
            <el-input v-model="companyForm.company_name" :placeholder="t('settings.companyNamePlaceholder')" :maxlength="100" />
          </el-form-item>
          <el-form-item :label="t('settings.companyShortName')">
            <el-input v-model="companyForm.company_short_name" :placeholder="t('settings.companyShortNamePlaceholder')" :maxlength="50" />
          </el-form-item>
          <el-form-item :label="t('settings.itDeptName')">
            <el-input v-model="companyForm.it_department_name" :placeholder="t('settings.itDeptPlaceholder')" :maxlength="50" />
          </el-form-item>
          <el-form-item :label="t('settings.itContactName')">
            <el-input v-model="companyForm.it_contact_name" :placeholder="t('settings.itContactPlaceholder')" :maxlength="50" />
          </el-form-item>
          <el-form-item :label="t('settings.itContactEmail')">
            <el-input v-model="companyForm.it_contact_email" :placeholder="t('settings.itEmailPlaceholder')" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveCompanyInfo" :loading="companyLoading">{{ t('common.save') }}</el-button>
          </el-form-item>
        </el-form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.settings-section {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 24px;
  box-shadow: var(--shadow-sm);
}

.section-header {
  margin-bottom: 20px;
}

.section-icon {
  font-size: 20px;
  color: var(--accent-primary);
  margin-right: 8px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-h);
  margin-bottom: 4px;
}

.section-desc {
  font-size: 13px;
  color: var(--text-secondary);
}

.brand-form {
  max-width: 500px;
}

.company-form {
  max-width: 500px;
}

/* 登录页效果预览卡片 */
.login-preview-card {
  margin-top: 24px;
  max-width: 500px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.preview-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  padding: 8px 16px;
  margin: 0;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-color);
}

.preview-body {
  padding: 24px 24px 20px;
  background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
}

.preview-logo-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.preview-logo {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.preview-logo img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.preview-logo svg {
  width: 32px;
  height: 32px;
}

.preview-brand-name {
  color: var(--bg-primary);
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 1px;
}

.preview-slogan h2 {
  color: var(--bg-primary);
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 6px;
}

.preview-slogan p {
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
  margin: 0;
}

.logo-upload-area {
  display: flex;
  gap: 40px;
  align-items: flex-start;
}

.logo-preview {
  flex-shrink: 0;
}

.logo-image-container {
  position: relative;
  width: 120px;
  height: 120px;
  border-radius: 8px;
  overflow: hidden;
  border: 2px dashed var(--border-color);
}

.logo-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: var(--bg-secondary);
}

.logo-placeholder {
  width: 120px;
  height: 120px;
  border-radius: 8px;
  border: 2px dashed var(--border-color);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: var(--bg-secondary);
}

.logo-placeholder-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent-primary);
  font-size: 20px;
}

.logo-placeholder p {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.logo-placeholder .hint {
  font-size: 11px;
  color: var(--text-muted);
}

.logo-upload {
  flex: 1;
  padding-top: 20px;
}

.logo-actions {
  margin-top: 12px;
  display: flex;
  gap: 8px;
}

.upload-input {
  display: none;
}

.upload-hint {
  margin-top: 12px;
  font-size: 12px;
  color: var(--text-muted);
}

.logo-tips {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
}

.tips-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.tips-list {
  margin: 0;
  padding-left: 20px;
}

.tips-list li {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.form-tip {
  font-size: 12px;
  color: var(--accent-warning);
  margin-top: 4px;
  line-height: 1.5;
}

@media (max-width: 768px) {
  .logo-upload-area {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>