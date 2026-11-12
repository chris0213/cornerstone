<template>
  <Teleport to="body">
    <transition name="search-fade">
      <div v-if="visible" class="global-search-overlay" @click.self="close">
        <div class="global-search-modal" :class="{ 'has-results': results.length > 0 || aiResult }">
          <!-- 搜索框 -->
          <div class="search-input-wrapper">
            <el-icon class="search-icon"><Search /></el-icon>
            <input
              ref="inputRef"
              v-model="query"
              type="text"
              class="search-input"
              :placeholder="t('aiSearch.placeholder')"
              @input="onInput"
              @keydown.enter="onEnter"
              @keydown.escape="close"
            />
            <span v-if="isAiMode" class="ai-badge" title="AI 自然语言搜索">
              <el-icon><MagicStick /></el-icon>
            </span>
            <span class="esc-hint">ESC</span>
          </div>

          <!-- 历史记录 -->
          <div v-if="!query && history.length > 0" class="search-history">
            <div class="history-header">
              <span class="history-label">{{ t('aiSearch.history') }}</span>
              <button class="clear-history" @click="clearHistory">{{ t('common.delete') }}</button>
            </div>
            <div class="history-list">
              <div
                v-for="(item, idx) in history"
                :key="idx"
                class="history-item"
                @click="query = item; doSearch(item)"
              >
                <el-icon><Clock /></el-icon>
                <span>{{ item }}</span>
              </div>
            </div>
          </div>

          <!-- 加载状态 -->
          <div v-if="loading" class="search-loading">
            <el-icon class="spinning"><Loading /></el-icon>
            <span>{{ t('aiSearch.aiThinking') }}</span>
          </div>

          <!-- 错误提示 -->
          <div v-if="error" class="search-error">
            <el-icon><WarningFilled /></el-icon>
            <span>{{ error }}</span>
          </div>

          <!-- AI 回答 -->
          <div v-if="aiResult" class="ai-answer-card">
            <div class="ai-answer-text">{{ aiResult.answer_text }}</div>
          </div>

          <!-- 普通搜索结果 -->
          <div v-if="results.length > 0" class="search-results">
            <!-- 设备 -->
            <template v-if="resultType === 'devices'">
              <div class="result-section-title">{{ t('devices.title') }}</div>
              <div class="device-cards">
              <div v-for="d in results.slice(0, 6)" :key="d.id" class="result-card" @click="navigateTo(`/devices?search=${d.name}`)">
                  <div class="card-primary">{{ d.name }}</div>
                  <div class="card-secondary">{{ d.type }} · {{ d.vendor }} {{ d.model }} · {{ d.status }}</div>
                </div>
              </div>
            </template>

            <!-- 专线 -->
            <template v-if="resultType === 'circuits'">
              <div class="result-section-title">{{ t('circuits.title') }}</div>
              <div class="device-cards">
                <div v-for="c in results.slice(0, 6)" :key="c.id" class="result-card" @click="navigateTo('/circuits')">
                  <div class="card-primary">{{ c.name }}</div>
                  <div class="card-secondary">{{ c.provider }} · {{ c.type }} · {{ c.bandwidth }}Mbps · {{ c.status }}</div>
                </div>
              </div>
            </template>

            <!-- IP 地址 -->
            <template v-if="resultType === 'ip_addresses'">
              <div class="result-section-title">{{ t('ipam.ipAddress') }}</div>
              <div class="device-cards">
                <div v-for="ip in results.slice(0, 6)" :key="ip.id" class="result-card" @click="navigateTo('/ipam')">
                  <div class="card-primary">{{ ip.address }}</div>
                  <div class="card-secondary">{{ t('common.status') }}: {{ ip.status }} · {{ ip.usage || '' }} · {{ ip.owner || '' }}</div>
                </div>
              </div>
            </template>

            <!-- 子网 -->
            <template v-if="resultType === 'prefixes'">
              <div class="result-section-title">{{ t('ipam.prefixes') }}</div>
              <div class="device-cards">
                <div v-for="p in results.slice(0, 6)" :key="p.id" class="result-card" @click="navigateTo('/ipam')">
                  <div class="card-primary">{{ p.network }}</div>
                  <div class="card-secondary">{{ t('ipam.usage') }}: {{ p.usage }} · {{ t('ipam.used') }}: {{ p.used_ips }}/{{ p.total_ips }} ({{ p.usage_rate }}%)</div>
                </div>
              </div>
            </template>

            <!-- 站点 -->
            <template v-if="resultType === 'sites'">
              <div class="result-section-title">{{ t('sites.title') }}</div>
              <div class="device-cards">
                <div v-for="s in results.slice(0, 6)" :key="s.id" class="result-card" @click="navigateTo('/sites')">
                  <div class="card-primary">{{ s.name }}</div>
                  <div class="card-secondary">{{ s.city }} · {{ s.status }} · {{ s.contact }}</div>
                </div>
              </div>
            </template>

            <!-- 备份 -->
            <template v-if="resultType === 'backups'">
              <div class="result-section-title">{{ t('backups.title') }}</div>
              <div class="device-cards">
                <div v-for="b in results.slice(0, 6)" :key="b.id" class="result-card" @click="navigateTo('/backups')">
                  <div class="card-primary">{{ t('backups.backup') }} #{{ b.id }}</div>
                  <div class="card-secondary">{{ t('common.status') }}: {{ b.status }} · {{ b.has_change ? t('backups.hasChange') : t('backups.noChange') }}</div>
                </div>
              </div>
            </template>

            <!-- 巡检 -->
            <template v-if="resultType === 'inspection_results'">
              <div class="result-section-title">{{ t('inspection.title') }}</div>
              <div class="device-cards">
                <div v-for="r in results.slice(0, 6)" :key="r.id" class="result-card" @click="navigateTo('/inspection')">
                  <div class="card-primary">{{ r.ip_address }}</div>
                  <div class="card-secondary">{{ r.is_online ? t('common.online') : t('common.offline') }} · {{ r.sys_name || '' }}</div>
                </div>
              </div>
            </template>

            <!-- 通用 fallback -->
            <template v-if="!resultType">
              <div class="result-section-title">{{ t('common.searchResults') }}</div>
              <div v-for="item in results.slice(0, 8)" :key="item.id" class="result-row">
                <span class="result-field">{{ item.name || item.network || item.address }}</span>
                <span class="result-hint">{{ item.status || item.type || '' }}</span>
              </div>
            </template>
          </div>

          <!-- 追问建议 -->
          <div v-if="suggestions.length > 0" class="search-suggestions">
            <span class="suggestions-label">{{ t('aiSearch.followUp') }}</span>
            <div class="suggestion-chips">
              <button
                v-for="(s, idx) in suggestions.slice(0, 3)"
                :key="idx"
                class="suggestion-chip"
                @click="query = s; doSearch(s)"
              >
                {{ s }}
              </button>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="!loading && !error && query && results.length === 0 && !aiResult" class="search-empty">
            <el-icon><Search /></el-icon>
            <span>{{ t('aiSearch.noResult') }}</span>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Search, Clock, Loading, WarningFilled, MagicStick } from '@element-plus/icons-vue'
import api from '../api/axios'

const { t } = useI18n()
const router = useRouter()

const visible = ref(false)
const query = ref('')
const loading = ref(false)
const error = ref('')
const results = ref<any[]>([])
const resultType = ref('')
const aiResult = ref<any>(null)
const suggestions = ref<string[]>([])
const history = ref<string[]>(loadHistory())
const inputRef = ref<HTMLInputElement | null>(null)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

const isAiMode = ref(false)

function loadHistory(): string[] {
  try {
    return JSON.parse(localStorage.getItem('ai_search_history') || '[]')
  } catch { return [] }
}

function saveHistory(q: string) {
  const arr = loadHistory()
  const filtered = arr.filter((h: string) => h !== q)
  filtered.unshift(q)
  if (filtered.length > 10) filtered.length = 10
  localStorage.setItem('ai_search_history', JSON.stringify(filtered))
  history.value = filtered
}

function clearHistory() {
  localStorage.removeItem('ai_search_history')
  history.value = []
}

function open() {
  visible.value = true
  query.value = ''
  results.value = []
  aiResult.value = null
  error.value = ''
  suggestions.value = []
  isAiMode.value = false
  nextTick(() => inputRef.value?.focus())
}

function close() {
  visible.value = false
  query.value = ''
  results.value = []
  aiResult.value = null
  error.value = ''
  suggestions.value = []
  isAiMode.value = false
}

function navigateTo(path: string) {
  close()
  router.push(path)
}

function onInput() {
  if (debounceTimer) clearTimeout(debounceTimer)
  const q = query.value.trim()
  isAiMode.value = isNaturalLanguageQuery(q)

  if (!q) {
    results.value = []
    aiResult.value = null
    error.value = ''
    return
  }

  debounceTimer = setTimeout(() => {
    if (isAiMode.value) {
      doSearch(q)
    } else {
      doLocalSearch(q)
    }
  }, 300)
}

function onEnter() {
  const q = query.value.trim()
  if (!q) return
  doSearch(q)
}

function isNaturalLanguageQuery(q: string): boolean {
  if (q.length < 4) return false
  const questionWords = ['哪些', '多少', '什么', '怎么', '有没有', '什么时候', '为啥', '为什么', '哪个', '多久', '快到期', '过期', '还有', '谁']
  return questionWords.some(w => q.includes(w)) || q.endsWith('？') || q.endsWith('?')
}

async function doLocalSearch(q: string) {
  try {
    loading.value = true
    error.value = ''
    aiResult.value = null

    // 搜索设备
    const devRes = await api.get('/devices/', { params: { search: q, limit: 3 } })
    const devs = devRes.data?.results || devRes.data || []
    if (Array.isArray(devs)) {
      results.value = devs
      resultType.value = 'devices'
    }
  } catch (e) {
    // 静默失败
    results.value = []
  } finally {
    loading.value = false
  }
}

async function doSearch(q: string) {
  if (!q.trim()) return
  saveHistory(q.trim())

  // 判断是否自然语言
  if (!isNaturalLanguageQuery(q)) {
    await doLocalSearch(q)
    return
  }

  try {
    loading.value = true
    error.value = ''
    results.value = []
    aiResult.value = null

    const res = await api.post('/ai/search', { question: q })
    const data = res.data?.data || res.data

    if (data) {
      aiResult.value = {
        answer_text: data.answer_text || '',
      }
      results.value = Array.isArray(data.data) ? data.data : []
      resultType.value = data.data_type || ''
      suggestions.value = Array.isArray(data.suggestions) ? data.suggestions : []
    }
  } catch (e: any) {
    if (e.response?.status === 401) {
      error.value = t('aiSearch.loginRequired')
    } else {
      error.value = t('aiSearch.searchFailed')
    }
  } finally {
    loading.value = false
  }
}

function doSearchQuery(q: string) {
  query.value = q
  doSearch(q)
}

// 暴露 open 方法
defineExpose({ open, doSearchQuery })
</script>

<style scoped>
.global-search-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  justify-content: center;
  padding-top: 12vh;
  z-index: 9999;
}

.global-search-modal {
  width: 620px;
  max-height: 70vh;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.25);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.global-search-modal.has-results {
  max-height: 75vh;
}

.search-input-wrapper {
  display: flex;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #eee;
  gap: 12px;
}

.search-icon {
  font-size: 20px;
  color: #999;
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 16px;
  line-height: 24px;
  color: #333;
  background: transparent;
}

.search-input::placeholder {
  color: #bbb;
}

.ai-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  font-size: 14px;
  flex-shrink: 0;
}

.esc-hint {
  font-size: 11px;
  color: #ccc;
  padding: 2px 8px;
  border: 1px solid var(--color-line-1);
  border-radius: 4px;
  font-family: monospace;
  flex-shrink: 0;
}

.search-history {
  padding: 12px 20px;
}

.history-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.history-label {
  font-size: 12px;
  color: #999;
  font-weight: 600;
  text-transform: uppercase;
}

.clear-history {
  font-size: 12px;
  color: var(--color-accent);
  background: none;
  border: none;
  cursor: pointer;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: var(--color-text-2);
}

.history-item:hover {
  background: var(--color-surface-1);
}

.history-item .el-icon {
  font-size: 14px;
  color: #bbb;
}

.search-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: #666;
  font-size: 14px;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.search-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 20px;
  color: var(--color-danger);
  font-size: 14px;
  background: var(--color-danger-soft);
}

.ai-answer-card {
  margin: 12px 20px;
  padding: 16px;
  background: #f6f8fa;
  border-left: 4px solid #667eea;
  border-radius: 8px;
  line-height: 1.6;
  font-size: 14px;
  color: #333;
  white-space: pre-wrap;
}

.search-results {
  padding: 8px 20px 12px;
  overflow-y: auto;
  flex: 1;
}

.result-section-title {
  font-size: 12px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  margin-bottom: 8px;
  padding: 0 4px;
}

.device-cards {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.result-card {
  padding: 10px 14px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}

.result-card:hover {
  background: var(--color-surface-1);
}

.card-primary {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-1);
}

.card-secondary {
  font-size: 12px;
  color: var(--color-text-3);
  margin-top: 2px;
}

.result-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
}

.result-row:hover {
  background: var(--color-surface-1);
}

.result-field {
  font-size: 14px;
  color: var(--color-text-1);
}

.result-hint {
  font-size: 12px;
  color: var(--color-text-3);
}

.search-suggestions {
  padding: 12px 20px;
  border-top: 1px solid var(--color-surface-1);
}

.suggestions-label {
  font-size: 12px;
  color: #999;
  margin-right: 8px;
}

.suggestion-chips {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}

.suggestion-chip {
  padding: 6px 14px;
  border: 1px solid var(--color-line-1);
  border-radius: 20px;
  font-size: 13px;
  color: var(--color-text-2);
  background: var(--color-surface-1);
  cursor: pointer;
  transition: all 0.15s;
}

.suggestion-chip:hover {
  border-color: #667eea;
  color: #667eea;
  background: #f0f0ff;
}

.search-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 20px;
  color: #bbb;
  font-size: 14px;
}

.search-empty .el-icon {
  font-size: 32px;
}

/* 过渡动画 */
.search-fade-enter-active,
.search-fade-leave-active {
  transition: opacity 0.2s ease;
}

.search-fade-enter-from,
.search-fade-leave-to {
  opacity: 0;
}
</style>
