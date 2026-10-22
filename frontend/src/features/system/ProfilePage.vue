<template>
  <div class="profile-page">
    <el-card class="profile-card" shadow="never">
      <template #header>
        <div class="card-title">
          <User class="el-icon" />
          {{ t('system.profile') }}
        </div>
      </template>

      <div class="profile-content">
        <!-- 左侧头像区域 -->
        <div class="profile-left">
          <div class="avatar-wrapper" @click="showAvatarPicker = true">
            <img 
              v-if="authStore.user?.avatar" 
              :src="authStore.user.avatar" 
              class="avatar"
              alt="头像"
            />
            <div v-else class="avatar-placeholder">
              {{ authStore.user?.display_name?.charAt(0) || '?' }}
            </div>
            <div class="avatar-upload-btn" @click.stop="triggerUpload" :class="{ 'loading': uploading }">
              <svg v-if="uploading" class="upload-spinner" viewBox="0 0 24 24">
                <circle class="path" cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>
              </svg>
              <Camera v-else class="el-icon" />
            </div>
            <input 
              type="file" 
              ref="fileInput" 
              accept="image/*" 
              style="display: none"
              @change="handleFileSelect"
            />
          </div>
          <div class="user-info">
            <h2>{{ authStore.user?.display_name }}</h2>
            <el-badge :type="roleBadgeType" :value="authStore.user?.role_display_name" />
          </div>
        </div>

        <!-- 右侧内容区域 -->
        <div class="profile-right">
          <!-- 基本信息卡片 -->
          <el-card class="info-card" shadow="never">
            <template #header>
              <div class="card-subtitle">
                <InfoFilled class="el-icon" />
                {{ t('profile.basicInfo') }}
              </div>
            </template>
            <el-form :model="basicForm" label-width="120px">
              <el-form-item :label="t('profile.username')">
                <el-input v-model="basicForm.username" disabled />
              </el-form-item>
              <el-form-item :label="t('profile.displayName')">
                <el-input v-model="basicForm.display_name" />
              </el-form-item>
              <el-form-item :label="t('profile.email')">
                <el-input v-model="basicForm.email" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="saveBasicInfo">{{ t('common.save') }}</el-button>
              </el-form-item>
            </el-form>
          </el-card>


          <!-- 修改密码卡片 -->
          <el-card class="info-card" shadow="never">
            <template #header>
              <div class="card-subtitle">
                <Key class="el-icon" />
                {{ t('profile.changePassword') }}
              </div>
            </template>
            <el-form :model="passwordForm" label-width="120px">
              <el-form-item :label="t('profile.currentPassword')" prop="oldPassword">
                <el-input type="password" v-model="passwordForm.oldPassword" autocomplete="current-password" />
              </el-form-item>
              <el-form-item :label="t('profile.newPassword')" prop="newPassword">
                <el-input type="password" v-model="passwordForm.newPassword" autocomplete="new-password" />
                <div v-if="passwordForm.newPassword" class="password-strength">
                  <div class="strength-label">{{ t('profile.passwordStrength') }}:</div>
                  <div class="strength-bar">
                    <div 
                      v-for="i in 3" 
                      :key="i" 
                      :class="['strength-segment', getStrengthClass(i)]"
                    ></div>
                  </div>
                  <div class="strength-text">{{ passwordStrengthText }}</div>
                </div>
              </el-form-item>
              <el-form-item :label="t('profile.confirmPassword')" prop="confirmPassword">
                <el-input type="password" v-model="passwordForm.confirmPassword" autocomplete="new-password" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="changePassword">{{ t('common.save') }}</el-button>
              </el-form-item>
            </el-form>
          </el-card>

          <!-- 登录历史 -->
          <el-card class="info-card" shadow="never">
            <template #header>
              <div class="card-subtitle">
                <Clock class="el-icon" />
                {{ t('profile.loginHistory') }} ({{ t('profile.recentFive') }})
              </div>
            </template>
            <el-table class="profile-login-history-table" :data="loginHistory" border :show-header="false">
              <el-table-column prop="time" :label="t('profile.time')" min-width="180" />
              <el-table-column prop="ip" :label="t('profile.ipAddress')" min-width="150" />
              <el-table-column prop="device" :label="t('profile.device')" />
            </el-table>
          </el-card>
        </div>
      </div>
    </el-card>

    <!-- 头像选择器弹窗 -->
    <el-dialog v-model="showAvatarPicker" :title="t('profile.selectAvatar')" width="480px">
      <div class="avatar-picker-content">
        <div class="avatar-picker-section">
          <div class="section-title">{{ t('profile.builtinAvatars') }}</div>
          <div class="avatar-grid">
            <div 
              v-for="(avatar, index) in defaultAvatars" 
              :key="index"
              class="avatar-option"
              :class="{ 'selected': isSelectedAvatar(avatar) }"
              @click="selectDefaultAvatar(avatar)"
            >
              <img :src="avatar" alt="{{ t('profile.avatarOption') }}" />
            </div>
          </div>
        </div>
        <div class="avatar-picker-divider"></div>
        <div class="avatar-picker-section">
          <div class="section-title">{{ t('profile.uploadAvatar') }}</div>
          <div class="upload-upload-area" @click="triggerUpload">
            <div class="upload-icon">
              <Camera />
            </div>
            <div class="upload-text">{{ t('profile.clickToUpload') }}</div>
            <div class="upload-hint">{{ t('profile.uploadHint') }}</div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showAvatarPicker = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="confirmAvatar" :loading="selecting">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { User, Camera, InfoFilled, Key, Clock } from '@element-plus/icons-vue'
import { useAuthStore } from '../../store/auth'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const authStore = useAuthStore()
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const showAvatarPicker = ref(false)
const selecting = ref(false)
const selectedAvatar = ref<string | null>(null)

// 内置头像列表（使用一些 SVG 数据 URI）
const defaultAvatars = ref([
  'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect fill="%23667eea" width="100" height="100"/><circle cx="50" cy="40" r="20" fill="white"/><ellipse cx="50" cy="85" rx="30" ry="25" fill="white"/></svg>',
  'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect fill="%23f093fb" width="100" height="100"/><circle cx="50" cy="40" r="20" fill="white"/><ellipse cx="50" cy="85" rx="30" ry="25" fill="white"/></svg>',
  'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect fill="%234facfe" width="100" height="100"/><circle cx="50" cy="40" r="20" fill="white"/><ellipse cx="50" cy="85" rx="30" ry="25" fill="white"/></svg>',
  'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect fill="%2343e979" width="100" height="100"/><circle cx="50" cy="40" r="20" fill="white"/><ellipse cx="50" cy="85" rx="30" ry="25" fill="white"/></svg>',
  'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect fill="%23fa709a" width="100" height="100"/><circle cx="50" cy="40" r="20" fill="white"/><ellipse cx="50" cy="85" rx="30" ry="25" fill="white"/></svg>',
  'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect fill="%23fee140" width="100" height="100"/><circle cx="50" cy="40" r="20" fill="white"/><ellipse cx="50" cy="85" rx="30" ry="25" fill="white"/></svg>',
])

const basicForm = ref({
  username: '',
  display_name: '',
  email: ''
})

const passwordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const loginHistory = ref([
  { time: '2024-01-15 10:30:25', ip: '192.0.2.100', device: 'Chrome - Windows' },
  { time: '2024-01-14 15:45:12', ip: '192.0.2.100', device: 'Chrome - Windows' },
  { time: '2024-01-13 09:20:33', ip: '198.51.100.50', device: 'Safari - macOS' },
  { time: '2024-01-12 14:15:08', ip: '192.0.2.100', device: 'Chrome - Windows' },
  { time: '2024-01-11 11:00:45', ip: '203.0.113.101', device: 'Firefox - Linux' },
])

const roleBadgeType = computed(() => {
  switch (authStore.user?.role) {
    case 'super_admin': return 'danger'
    case 'engineer': return 'primary'
    case 'viewer': return 'info'
    default: return 'info'
  }
})

const passwordStrength = computed(() => {
  const pwd = passwordForm.value.newPassword
  let score = 0
  
  if (pwd.length >= 8) score++
  if (pwd.length >= 12) score++
  if (/[a-z]/.test(pwd)) score++
  if (/[A-Z]/.test(pwd)) score++
  if (/[0-9]/.test(pwd)) score++
  
  return Math.min(score, 3)
})

const passwordStrengthText = computed(() => {
  switch (passwordStrength.value) {
    case 0: return ''
    case 1: return t('profile.passwordStrengthWeak')
    case 2: return t('profile.passwordStrengthMedium')
    case 3: return t('profile.passwordStrengthStrong')
    default: return ''
  }
})

function getStrengthClass(index: number) {
  if (index <= passwordStrength.value) {
    switch (passwordStrength.value) {
      case 1: return 'weak'
      case 2: return 'medium'
      case 3: return 'strong'
      default: return ''
    }
  }
  return 'empty'
}

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  
  if (!file) return
  
  // 检查文件大小（限制 5MB）
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.error(t('profile.imageSizeLimit'))
    return
  }

  // Check file type
  if (!file.type.startsWith('image/')) {
    ElMessage.error(t('profile.invalidImage'))
    return
  }
  
  uploading.value = true
  
  try {
    const formData = new FormData()
    formData.append('avatar', file)
    
    const response = await fetch(`/api/v1/users/${authStore.user?.id}/avatar`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${authStore.token}`
      },
      body: formData
    })
    
    if (response.ok) {
      await authStore.fetchUser()
      ElMessage.success(t('profile.avatarUploadSuccess'))
    } else {
      const error = await response.json()
      ElMessage.error(error.detail || t('profile.uploadFailed'))
    }
  } catch (error) {
    ElMessage.error(t('profile.uploadFailedRetry'))
    console.error('Avatar upload error:', error)
  } finally {
    uploading.value = false
    // 清空文件输入
    if (fileInput.value) {
      fileInput.value.value = ''
    }
    showAvatarPicker.value = false
  }
}

function isSelectedAvatar(avatar: string) {
  return selectedAvatar.value === avatar
}

function selectDefaultAvatar(avatar: string) {
  selectedAvatar.value = avatar
}

async function confirmAvatar() {
  if (!selectedAvatar.value) {
    showAvatarPicker.value = false
    return
  }
  
  selecting.value = true
  try {
    // 将 data URI 转换为 Blob
    const response = await fetch(selectedAvatar.value)
    const blob = await response.blob()
    const file = new File([blob], 'avatar.svg', { type: 'image/svg+xml' })
    
    const formData = new FormData()
    formData.append('avatar', file)
    
    const apiResponse = await fetch(`/api/v1/users/${authStore.user?.id}/avatar`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${authStore.token}`
      },
      body: formData
    })
    
    if (apiResponse.ok) {
      await authStore.fetchUser()
      ElMessage.success(t('profile.avatarSetSuccess'))
      showAvatarPicker.value = false
    } else {
      const error = await apiResponse.json()
      ElMessage.error(error.detail || t('profile.setFailed'))
    }
  } catch (error) {
    ElMessage.error(t('profile.setFailedRetry'))
    console.error('Avatar select error:', error)
  } finally {
    selecting.value = false
  }
}

async function saveBasicInfo() {
  try {
    const response = await fetch(`/api/v1/users/${authStore.user?.id}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authStore.token}`
      },
      body: JSON.stringify({
        display_name: basicForm.value.display_name,
        email: basicForm.value.email
      })
    })
    
    if (response.ok) {
      await authStore.fetchUser()
      ElMessage.success(t('profile.infoSavedSuccess'))
    } else {
      const error = await response.json()
      ElMessage.error(error.detail || t('profile.saveFailed'))
    }
  } catch (error) {
    ElMessage.error(t('profile.saveFailed'))
  }
}

async function changePassword() {
  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    ElMessage.warning(t('profile.passwordMismatch'))
    return
  }
  
  const result = await authStore.changePassword(
    passwordForm.value.oldPassword,
    passwordForm.value.newPassword
  )
  
  if (result.success) {
    ElMessage.success(t('profile.passwordChangedSuccess'))
    passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } else {
    ElMessage.error(result.message)
  }
}

onMounted(() => {
  if (authStore.user) {
    basicForm.value = {
      username: authStore.user.username,
      display_name: authStore.user.display_name,
      email: authStore.user.email
    }
  }
})
</script>

<style scoped>
.profile-page {
  padding: 20px;
}

.profile-card {
  margin-bottom: 20px;
}

.card-title {
  font-size: 18px;
  font-weight: bold;
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-subtitle {
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.profile-content {
  display: flex;
  gap: 40px;
}

.profile-left {
  width: 280px;
  flex-shrink: 0;
}

.avatar-wrapper {
  position: relative;
  width: 180px;
  height: 180px;
  margin: 0 auto 20px;
}

.avatar {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  border: 4px solid #e4e7ed;
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 48px;
  color: white;
  font-weight: bold;
  border: 4px solid #e4e7ed;
}

.avatar-upload-btn {
  position: absolute;
  bottom: 5px;
  right: 5px;
  width: 40px;
  height: 40px;
  background: #409eff;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: white;
  border: 2px solid white;
  transition: background 0.2s;
}

.avatar-upload-btn:hover {
  background: #66b1ff;
}

.avatar-upload-btn.loading {
  cursor: not-allowed;
  background: #909399;
}

.upload-spinner {
  width: 20px;
  height: 20px;
  animation: rotate 1s linear infinite;
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.user-info {
  text-align: center;
}

.user-info h2 {
  margin: 0 0 10px 0;
  font-size: 20px;
}

.profile-right {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.info-card {
  margin-bottom: 0;
}

.password-strength {
  margin-top: 10px;
}

.strength-label {
  font-size: 12px;
  color: #999;
  margin-bottom: 5px;
}

.strength-bar {
  display: flex;
  gap: 4px;
  height: 8px;
}

.strength-segment {
  flex: 1;
  border-radius: 4px;
  transition: background 0.2s;
}

.strength-segment.empty {
  background: #e4e7ed;
}

.strength-segment.weak {
  background: #f56c6c;
}

.strength-segment.medium {
  background: #e6a23c;
}

.strength-segment.strong {
  background: #67c23a;
}

.strength-text {
  font-size: 12px;
  color: #666;
  margin-top: 5px;
}

/* 头像选择器样式 */
.avatar-picker-content {
  padding: 10px 0;
}

.avatar-picker-section {
  padding: 10px 0;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 15px;
}

.avatar-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 15px;
}

.avatar-option {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  overflow: hidden;
  cursor: pointer;
  border: 3px solid transparent;
  transition: all 0.2s;
}

.avatar-option:hover {
  transform: scale(1.1);
}

.avatar-option.selected {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.3);
}

.avatar-option img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-picker-divider {
  height: 1px;
  background: #ebeef5;
  margin: 20px 0;
}

.upload-upload-area {
  border: 2px dashed #dcdfe6;
  border-radius: 8px;
  padding: 30px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.upload-upload-area:hover {
  border-color: #409eff;
  background: #f5f7fa;
}

.upload-icon {
  font-size: 48px;
  color: #c0c4cc;
  margin-bottom: 15px;
}

.upload-text {
  font-size: 14px;
  color: #606266;
  margin-bottom: 8px;
}

.upload-hint {
  font-size: 12px;
  color: #909399;
}

.profile-login-history-table :deep(.cell) {
  line-height: 1.5;
}

.profile-login-history-table :deep(.el-table__cell) {
  padding: 8px 12px;
}

/* 移动端响应式 */
@media (max-width: 768px) {
  .profile-page {
    padding: 12px;
  }

  .profile-content {
    flex-direction: column;
    gap: 20px;
  }

  .profile-left {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .avatar-wrapper {
    width: 120px;
    height: 120px;
    margin-bottom: 16px;
  }

  .avatar-placeholder {
    font-size: 36px;
  }

  .avatar-upload-btn {
    width: 32px;
    height: 32px;
  }

  .user-info h2 {
    font-size: 18px;
  }

  .profile-right {
    width: 100%;
  }

  .el-form-item {
    margin-bottom: 16px;
  }

  :deep(.el-form-item__label) {
    width: 100px !important;
  }

  :deep(.el-form-item__content) {
    margin-left: 100px !important;
  }

  .profile-login-history-table {
    font-size: 12px;
  }

  :deep(.el-table__cell) {
    padding: 8px 4px;
  }
}
</style>
