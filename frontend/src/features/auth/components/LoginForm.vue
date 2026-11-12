<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/store/auth'
import { useRouter } from 'vue-router'
import { useNetworkAnimation } from '../composables/useNetworkAnimation'
import { setTokens, isRemembered } from '@/api/tokenStorage'

const { t } = useI18n()
const authStore = useAuthStore()
const router = useRouter()

const { setAnimationMode, triggerNodePulse } = useNetworkAnimation()

const username = ref('')
const password = ref('')
const captchaCode = ref('')
const captchaId = ref('')
const captchaImageUrl = ref('')
const loading = ref(false)
const ssoLoading = ref(false)
const error = ref('')
const showPassword = ref(false)
const captchaLoading = ref(false)
const ssoConfigLoaded = ref(false)
const ldapEnabled = ref(false)
const ldapConfigLoaded = ref(false)
const rememberMe = ref(isRemembered())
const capsLockOn = ref(false)

const loginMode = ref<'local' | 'ldap'>('local')

const hasSSO = computed(() => {
  return authStore.ssoConfig?.enabled && authStore.ssoConfig?.has_oauth2
})

const showLdapTab = computed(() => {
  return ldapEnabled.value && ldapConfigLoaded.value
})

async function refreshCaptcha() {
  captchaLoading.value = true
  try {
    const response = await fetch('/api/v1/auth/captcha')
    const newCaptchaId = response.headers.get('X-Captcha-ID')
    if (newCaptchaId) {
      captchaId.value = newCaptchaId
      const blob = await response.blob()
      captchaImageUrl.value = URL.createObjectURL(blob)
    }
  } catch (err) {
    console.error('获取验证码失败:', err)
  } finally {
    captchaLoading.value = false
  }
}

function checkCapsLock(e: KeyboardEvent) {
  capsLockOn.value = e.getModifierState?.('CapsLock') ?? false
}

async function handleLogin() {
  // 防重复：loading 中回车/点击不再触发（输入框回车绕过按钮 disabled，需在这里兜底）
  if (loading.value) return
  if (!username.value) {
    error.value = t('login.usernameRequired')
    return
  }
  if (!password.value) {
    error.value = t('login.passwordRequired')
    return
  }
  if (!captchaCode.value) {
    error.value = t('login.captchaRequired')
    return
  }

  loading.value = true
  error.value = ''
  setAnimationMode('login-loading')

  try {
    const success = await authStore.loginWithCaptcha(
      username.value,
      password.value,
      captchaId.value,
      captchaCode.value,
      rememberMe.value
    )
    if (success) {
      setAnimationMode('login-success')
      setTimeout(() => {
        router.push('/')
      }, 500)
    } else {
      setAnimationMode('login-fail')
      error.value = t('login.invalidCredentials')
      refreshCaptcha()
    }
  } catch (err: any) {
    setAnimationMode('login-fail')
    // 验证码类错误（400）：区分「已过期」与「错误」，其余按验证码错误处理
    if (err.response?.status === 400) {
      const detail = String(err.response?.data?.detail || '')
      error.value = detail.includes('过期') ? t('login.captchaExpired') : t('login.captchaError')
    } else if (err.response?.data?.detail) {
      // 401 账密错误 / 423 锁定 / 429 限流 / 403 白名单：透传后端明确提示
      error.value = err.response.data.detail
    } else {
      // 网络错误等无响应场景
      error.value = t('login.loginFailed')
    }
    // 任何失败都刷新验证码：后端校验通过即消费验证码，旧图已失效
    refreshCaptcha()
  } finally {
    loading.value = false
  }
}

function handleSubmit() {
  setAnimationMode('login-click')
  if (loginMode.value === 'local') handleLogin()
  else handleLDAPLogin()
}

async function handleSSOLogin() {
  ssoLoading.value = true
  try {
    const result = await authStore.getSSOAuthorizeUrl()
    if (result.authorize_url) {
      window.location.href = result.authorize_url
    }
  } catch (err: any) {
    error.value = t('login.ssoLoginFailed')
  } finally {
    ssoLoading.value = false
  }
}

async function handleLDAPLogin() {
  // 防重复：与 handleLogin 同样兜底
  if (loading.value) return
  if (!username.value) {
    error.value = t('login.usernameRequired')
    return
  }
  if (!password.value) {
    error.value = t('login.passwordRequired')
    return
  }

  loading.value = true
  error.value = ''
  setAnimationMode('login-loading')

  try {
    const response = await fetch('/api/v1/auth/ldap/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        username: username.value,
        password: password.value
      })
    })

    const data = await response.json()

    if (response.ok) {
      // LDAP 登录页无独立记住我逻辑，跟随「记住我」复选框
      setTokens(data.access_token, data.refresh_token, rememberMe.value)
      setAnimationMode('login-success')
      setTimeout(() => {
        router.push('/')
      }, 500)
    } else {
      setAnimationMode('login-fail')
      error.value = data.detail || t('login.loginFailed')
    }
  } catch (err: any) {
    setAnimationMode('login-fail')
    error.value = t('login.loginFailed')
  } finally {
    loading.value = false
  }
}

async function fetchLDAPConfig() {
  try {
    const response = await fetch('/api/v1/auth/ldap/enabled')
    const data = await response.json()
    ldapEnabled.value = data.enabled
  } catch (err) {
    console.error('获取LDAP配置失败:', err)
  } finally {
    ldapConfigLoaded.value = true
  }
}

onMounted(async () => {
  refreshCaptcha()
  await authStore.fetchSSOConfig()
  ssoConfigLoaded.value = true
  await fetchLDAPConfig()

  const urlParams = new URLSearchParams(window.location.search)
  const code = urlParams.get('code')
  if (code) {
    loading.value = true
    try {
      const result = await authStore.ssoCallback(code)
      if (result.success) {
        router.push('/')
      } else {
        error.value = result.message || t('login.loginFailed')
      }
    } catch (err: any) {
      error.value = t('login.ssoLoginFailed')
    } finally {
      loading.value = false
      urlParams.delete('code')
      window.history.replaceState({}, document.title, window.location.pathname)
    }
  }
})
</script>

<template>
  <div class="login-form-container">
    <div class="login-box">
      <div class="login-header">
        <div class="header-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 15v2m-6 4h12a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2zm10-10V7a4 4 0 0 0-8 0v4h8z" />
          </svg>
        </div>
        <h2>{{ t('login.title') }}</h2>
        <p>{{ t('login.rightSubtitle') }}</p>
      </div>

      <div v-if="showLdapTab" class="login-tabs">
        <button
          class="tab-btn"
          :class="{ active: loginMode === 'local' }"
          @click="loginMode = 'local'; refreshCaptcha()"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 15v2m-6 4h12a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2zm10-10V7a4 4 0 0 0-8 0v4h8z" />
          </svg>
          {{ t('login.localLogin') }}
        </button>
        <button
          class="tab-btn"
          :class="{ active: loginMode === 'ldap' }"
          @click="loginMode = 'ldap'"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
          {{ t('login.ldapLogin') }}
        </button>
      </div>

      <form class="login-form" @submit.prevent="handleSubmit">
        <Transition name="fade-slide">
          <div v-if="error" class="error-message">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>{{ error }}</span>
          </div>
        </Transition>

        <div class="form-group">
          <label class="form-label">
            <span class="label-text">{{ t('login.username') }}</span>
            <span class="label-required">*</span>
          </label>
          <div class="input-wrapper">
            <span class="input-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            </span>
            <input
              v-model="username"
              type="text"
              :placeholder="t('login.username')"
              class="form-input"
              autocomplete="username"
              @focus="setAnimationMode('username')"
              @blur="setAnimationMode('default')"
              @input="triggerNodePulse()"
            />
            <span class="input-focus-ring"></span>
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">
            <span class="label-text">{{ t('login.password') }}</span>
            <span class="label-required">*</span>
          </label>
          <div class="input-wrapper">
            <span class="input-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </span>
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              :placeholder="t('login.password')"
              class="form-input"
              :autocomplete="showPassword ? 'off' : 'current-password'"
              @focus="setAnimationMode('password')"
              @blur="capsLockOn = false; setAnimationMode('default')"
              @keydown="checkCapsLock"
              @keyup="checkCapsLock"
              @input="triggerNodePulse()"
            />
            <span
              class="input-suffix password-toggle"
              @click="showPassword = !showPassword"
            >
              <svg v-if="showPassword" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z" />
                <path d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-5.94 12.06" />
                <line x1="1" y1="1" x2="23" y2="23" />
              </svg>
            </span>
            <span class="input-focus-ring"></span>
          </div>
          <Transition name="fade-slide">
            <div v-if="capsLockOn" class="caps-lock-hint">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 4l7 7h-4v6h-6v-6H5l7-7z" />
              </svg>
              <span>{{ t('login.capsLockOn') }}</span>
            </div>
          </Transition>
        </div>

        <div v-if="loginMode === 'local'" class="form-group">
          <label class="form-label">
            <span class="label-text">{{ t('login.captcha') }}</span>
            <span class="label-required">*</span>
          </label>
          <div class="captcha-row">
            <div class="input-wrapper captcha-input">
              <input
                v-model="captchaCode"
                type="text"
                :placeholder="t('login.captchaPlaceholder')"
                class="form-input"
                autocomplete="off"
                maxlength="4"
                @focus="setAnimationMode('captcha')"
                @blur="setAnimationMode('default')"
                @input="triggerNodePulse()"
              />
              <span class="input-focus-ring"></span>
            </div>
            <div
              class="captcha-image-wrapper"
              @click="refreshCaptcha"
              :title="t('login.captchaExpired')"
            >
              <img
                v-if="captchaImageUrl"
                :src="captchaImageUrl"
                :alt="t('login.captcha')"
                class="captcha-image"
              />
              <div v-else class="captcha-loading">
                <svg class="loading-spinner" viewBox="0 0 24 24">
                  <circle class="path" cx="12" cy="12" r="10" fill="none" stroke-width="2" />
                </svg>
              </div>
            </div>
          </div>
        </div>

        <div class="form-group remember-me">
          <label class="checkbox-label">
            <input v-model="rememberMe" type="checkbox" class="checkbox" />
            <span class="checkbox-custom">
              <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3">
                <path d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span class="checkbox-text">{{ t('login.rememberMe') }}</span>
          </label>
        </div>

        <button
          type="submit"
          class="login-btn"
          :class="{ 'btn-loading': loading }"
          :disabled="loading"
        >
          <span v-if="loading" class="btn-loader">
            <svg class="loading-spinner" viewBox="0 0 24 24">
              <circle class="path" cx="12" cy="12" r="10" fill="none" stroke-width="2" />
            </svg>
          </span>
          <span v-else>
            {{ loginMode === 'local' ? t('login.loginButton') : t('login.ldapLoginButton') }}
          </span>
        </button>

        <template v-if="hasSSO">
          <div class="login-divider">
            <span class="divider-line"></span>
            <span class="divider-text">{{ t('login.or') }}</span>
            <span class="divider-line"></span>
          </div>
          <button
            type="button"
            class="sso-login-btn"
            :class="{ 'btn-loading': ssoLoading }"
            :disabled="ssoLoading"
            @click="handleSSOLogin"
          >
            <svg class="sso-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
            </svg>
            <span>{{ ssoLoading ? t('common.loading') : t('login.ssoLogin') }}</span>
          </button>
        </template>
      </form>
    </div>
  </div>
</template>

<style scoped>
/* 登录页强调色走主题变量（Element Plus），硬编码值仅作回退 */
.login-form-container {
  --lp-primary: var(--color-accent);
  --lp-primary-2: var(--color-accent-hover);
  /* 品牌蓝紫渐变终点（锁图标 / 登录按钮共用） */
  --lp-grad-end: #8b5cf6;
  --lp-danger: var(--color-danger);
  --lp-danger-bg: var(--color-danger-soft);
  --lp-danger-border: var(--color-danger);
  --lp-warn: var(--color-warning);
  /* 卡片固定 420px 宽（content-box），右侧留 64px 呼吸边距，左侧 48px 接插画 */
  width: 420px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  /* 上下留白随视口高度收缩，避让语言切换器 */
  padding: clamp(20px, 5vh, 56px) 64px clamp(16px, 4vh, 48px) 48px;
  background: transparent;
}

.login-box {
  width: 100%;
  box-sizing: border-box;
  background: var(--color-surface-0);
  border: 1px solid var(--color-line-1);
  border-radius: 16px;
  padding: clamp(26px, 3.8vh, 40px) clamp(24px, 2.4vw, 34px);
  box-shadow: 0 18px 40px -16px rgba(0, 0, 0, 0.45);
}

.login-header {
  text-align: center;
  margin-bottom: clamp(16px, 2.6vh, 34px);
}

.header-icon {
  width: clamp(36px, 4.8vh, 44px);
  height: clamp(36px, 4.8vh, 44px);
  margin: 0 auto clamp(8px, 1.4vh, 16px);
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--lp-primary) 0%, var(--lp-grad-end) 100%);
  border: none;
  border-radius: 12px;
  color: #fff;
  box-shadow: 0 10px 24px -10px color-mix(in srgb, var(--lp-primary) 65%, transparent);
}

.header-icon svg {
  width: clamp(18px, 2.4vh, 22px);
  height: clamp(18px, 2.4vh, 22px);
}

.login-header h2 {
  font-size: clamp(22px, 2.9vh, 26px);
  font-weight: 500;
  color: var(--color-text-1);
  margin-bottom: clamp(4px, 0.8vh, 8px);
  letter-spacing: 0;
}

.login-header p {
  font-size: 13px;
  color: var(--color-text-2);
}

.login-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 28px;
  padding: 4px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-line-1);
  border-radius: 10px;
}

.tab-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 16px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--color-text-2);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color var(--motion-base) var(--motion-ease),
    color var(--motion-base) var(--motion-ease);
}

.tab-btn:hover {
  color: var(--color-text-1);
}

.tab-btn.active {
  background: var(--color-surface-0);
  border-color: var(--color-line-1);
  color: var(--lp-primary);
}

.tab-btn svg {
  width: 18px;
  height: 18px;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: clamp(10px, 1.6vh, 20px);
}

.error-message {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--lp-danger);
  background: var(--lp-danger-bg);
  border-radius: 12px;
  padding: 14px 18px;
  font-size: 13px;
  border: 1px solid var(--lp-danger-border);
}

.error-message svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

/* Caps Lock 开启提示 */
.caps-lock-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--lp-warn);
}

.caps-lock-hint svg {
  width: 14px;
  height: 14px;
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity var(--motion-base) var(--motion-ease),
    transform var(--motion-base) var(--motion-ease);
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: clamp(5px, 0.9vh, 9px);
}

.form-label {
  display: flex;
  align-items: center;
  gap: 6px;
}

.label-text {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-2);
}

.label-required {
  color: var(--color-danger);
  font-weight: 500;
}

.input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.input-icon {
  position: absolute;
  left: 16px;
  width: 18px;
  height: 18px;
  color: var(--color-text-3);
  pointer-events: none;
  transition: color var(--motion-base) var(--motion-ease);
}

.input-focus-ring {
  display: none;
}

.form-input {
  width: 100%;
  height: clamp(42px, 5.6vh, 48px);
  padding: 0 16px 0 48px;
  border: 1px solid var(--color-line-1);
  border-radius: 10px;
  font-size: 14px;
  background: var(--color-surface-0);
  color: var(--color-text-1);
  transition: border-color var(--motion-base) var(--motion-ease),
    background-color var(--motion-base) var(--motion-ease),
    box-shadow var(--motion-base) var(--motion-ease);
}

.form-input:focus {
  outline: none;
  border-color: var(--lp-primary);
  background: var(--color-surface-0);
  box-shadow: 0 0 0 3px var(--color-accent-ring);
}

.form-input:focus ~ .input-icon {
  color: var(--lp-primary);
}

.form-input::placeholder {
  color: var(--color-text-3);
}

.input-suffix {
  position: absolute;
  right: 16px;
  width: 22px;
  height: 22px;
  color: var(--color-text-3);
  cursor: pointer;
  transition: color var(--motion-fast) var(--motion-ease);
  display: flex;
  align-items: center;
  justify-content: center;
}

.input-suffix:hover {
  color: var(--lp-primary);
}

.password-toggle svg {
  width: 20px;
  height: 20px;
}

.captcha-row {
  display: flex;
  gap: 14px;
}

.captcha-input {
  flex: 1;
}

.captcha-image-wrapper {
  cursor: pointer;
  border: 1px solid var(--color-line-1);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color var(--motion-fast) var(--motion-ease);
}

.captcha-image-wrapper:hover {
  border-color: var(--color-line-2);
}

.captcha-image {
  width: 130px;
  height: clamp(42px, 5.6vh, 48px);
  object-fit: cover;
}

.captcha-loading {
  width: 130px;
  height: clamp(42px, 5.6vh, 48px);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface-2);
  border-radius: 10px;
}

.loading-spinner {
  width: 22px;
  height: 22px;
}

.loading-spinner .path {
  stroke: var(--lp-primary);
  stroke-linecap: round;
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.remember-me {
  flex-direction: row;
  align-items: center;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 13px;
  color: var(--color-text-2);
  transition: color var(--motion-fast) var(--motion-ease);
}

.checkbox-label:hover {
  color: var(--color-text-1);
}

.checkbox {
  display: none;
}

.checkbox-custom {
  width: 18px;
  height: 18px;
  border: 1px solid var(--color-line-2);
  border-radius: 5px;
  position: relative;
  transition: background-color var(--motion-fast) var(--motion-ease),
    border-color var(--motion-fast) var(--motion-ease);
  display: flex;
  align-items: center;
  justify-content: center;
}

.checkbox:checked + .checkbox-custom {
  background: var(--lp-primary);
  border-color: var(--lp-primary);
}

.checkbox-custom svg {
  width: 12px;
  height: 12px;
  opacity: 0;
  transition: opacity 0.3s;
}

.checkbox:checked + .checkbox-custom svg {
  opacity: 1;
}

.checkbox-text {
  user-select: none;
}

.login-btn {
  height: clamp(42px, 5.6vh, 48px);
  border: 1px solid transparent;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--lp-primary) 0%, var(--lp-grad-end) 100%);
  color: #fff;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: filter var(--motion-fast) var(--motion-ease),
    box-shadow var(--motion-fast) var(--motion-ease);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  box-shadow: 0 10px 22px -12px color-mix(in srgb, var(--lp-primary) 70%, transparent);
}

.login-btn:hover:not(:disabled) {
  filter: brightness(1.07);
  box-shadow: 0 12px 26px -12px color-mix(in srgb, var(--lp-primary) 80%, transparent);
}

.login-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--color-accent-ring);
}

.login-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.login-btn svg {
  width: 18px;
  height: 18px;
}

.btn-loader {
  display: flex;
  align-items: center;
}

.login-divider {
  display: flex;
  align-items: center;
  gap: 16px;
  margin: 10px 0;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: var(--color-line-1);
}

.divider-text {
  font-size: 12px;
  color: var(--color-text-3);
  font-weight: 400;
}

.sso-login-btn {
  height: 48px;
  border: 1px solid var(--color-line-1);
  border-radius: 10px;
  background: var(--color-surface-0);
  color: var(--color-text-2);
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color var(--motion-fast) var(--motion-ease),
    color var(--motion-fast) var(--motion-ease),
    background-color var(--motion-fast) var(--motion-ease);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.sso-login-btn:hover:not(:disabled) {
  border-color: var(--lp-primary);
  color: var(--lp-primary);
  background: var(--color-accent-soft);
}

.sso-login-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.sso-icon {
  width: 20px;
  height: 20px;
}

@media (max-width: 1024px) {
  .login-form-container {
    width: 100%;
    justify-content: center;
    padding: 32px 20px;
  }

  .login-box {
    max-width: 420px;
    margin: 0 auto;
  }
}

@media (max-width: 480px) {
  .login-form-container {
    padding: 16px 12px;
  }

  .login-box {
    padding: 28px 20px;
    border-radius: 16px;
  }

  .login-header {
    margin-bottom: 28px;
  }

  .login-header h2 {
    font-size: 22px;
  }

  .login-form {
    gap: 16px;
  }
}
</style>