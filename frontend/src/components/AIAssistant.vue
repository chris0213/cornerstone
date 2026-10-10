<template>
  <el-drawer
    v-model="visible"
    :title="t('aiAssistant.title')"
    direction="rtl"
    size="420px"
    :z-index="2000"
    @closed="onClosed"
  >
    <div class="ai-assistant">
      <!-- 欢迎 / 示例 -->
      <div v-if="messages.length === 0" class="ai-welcome">
        <div class="ai-welcome-icon"><el-icon><MagicStick /></el-icon></div>
        <p class="ai-welcome-text">{{ t('aiAssistant.welcome') }}</p>
        <div class="ai-examples">
          <button
            v-for="(ex, i) in examples"
            :key="i"
            class="ai-example-chip"
            @click="send(ex)"
          >{{ ex }}</button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div ref="messagesRef" class="ai-messages">
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="ai-msg"
          :class="m.role === 'user' ? 'ai-msg--user' : 'ai-msg--ai'"
        >
          <div class="ai-msg-role">{{ m.role === 'user' ? t('aiAssistant.you') : t('aiAssistant.assistant') }}</div>
          <div class="ai-msg-content">{{ m.content }}</div>
          <div v-if="m.rows && m.rows.length" class="ai-msg-rows">
            <div v-for="(r, ri) in m.rows" :key="ri" class="ai-msg-row">
              <div class="ai-row-title">{{ r.title }}</div>
              <div v-if="r.sub" class="ai-row-sub">{{ r.sub }}</div>
            </div>
          </div>
          <div v-if="m.suggestions && m.suggestions.length" class="ai-msg-suggestions">
            <button
              v-for="(s, si) in m.suggestions"
              :key="si"
              class="ai-suggestion-chip"
              @click="send(s)"
            >{{ s }}</button>
          </div>
        </div>
        <div v-if="loading" class="ai-msg ai-msg--ai">
          <div class="ai-msg-role">{{ t('aiAssistant.assistant') }}</div>
          <div class="ai-msg-content ai-typing">{{ t('aiAssistant.thinking') }}</div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="ai-input-bar">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          :placeholder="t('aiAssistant.placeholder')"
          :disabled="loading"
          @keydown.enter.exact.prevent="onEnter"
        />
        <el-button type="primary" :loading="loading" :icon="Promotion" @click="onEnter" />
      </div>

      <div class="ai-history-link">
        <el-button link type="primary" @click="goHistory">
          <el-icon><Clock /></el-icon>
          {{ t('system.aiChatLogsMyHistory') }}
        </el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { MagicStick, Promotion, Clock } from '@element-plus/icons-vue'
import api from '../api/axios'

const { t } = useI18n()
const router = useRouter()
const visible = ref(false)
const input = ref('')
const loading = ref(false)
const messages = ref<Array<{ role: 'user' | 'ai'; content: string; suggestions?: string[]; rows?: AiRow[] }>>([])
const messagesRef = ref<HTMLElement | null>(null)
// 上一轮回答的数据类型，随下一次提问带给后端，让「都是什么」这类追问沿用上下文
const lastDataType = ref('')

interface AiRow {
  title: string
  sub?: string
}

// 把后端返回的原始记录压成「标题 + 副标题」，按数据类型取关键字段
function buildRows(dataType: string, rows: any[]): AiRow[] {
  return rows.slice(0, 6).map((r: any) => {
    switch (dataType) {
      case 'sites':
        return { title: r.name ?? '-', sub: [r.city, r.status].filter(Boolean).join(' · ') }
      case 'circuits':
        return {
          title: [r.name, r.provider].filter(Boolean).join(' · ') || '-',
          sub: [r.bandwidth, r.status, r.contract_end ? `合同至 ${String(r.contract_end).slice(0, 10)}` : '']
            .filter(Boolean).join(' · '),
        }
      case 'devices':
        return {
          title: r.name ?? '-',
          sub: [r.type, r.brand, r.status, r.location].filter(Boolean).join(' · '),
        }
      case 'ip_addresses':
        return { title: r.address ?? '-', sub: [r.status, r.usage].filter(Boolean).join(' · ') }
      case 'prefixes':
        return {
          title: r.network ?? '-',
          sub: `已用 ${r.used_ips ?? 0}/${r.total_ips ?? 0}（${r.usage_rate ?? 0}%）`,
        }
      case 'backups':
        return {
          title: `设备#${r.device_id} ${r.version ?? ''}`.trim(),
          sub: [r.status, r.has_change ? '有变更' : ''].filter(Boolean).join(' · '),
        }
      case 'inspection_results':
        return {
          title: r.ip_address ?? '-',
          sub: [r.is_online ? '在线' : '离线', r.sys_name, r.has_fingerprint_change ? '指纹变化' : '']
            .filter(Boolean).join(' · '),
        }
      case 'topology':
        return {
          title: `设备#${r.source_device_id}（${r.source_interface ?? '?'}）→ 设备#${r.target_device_id}（${r.target_interface ?? '?'}）`,
          sub: r.link_type ?? '',
        }
      case 'vlans':
        return { title: `VLAN ${r.vid} ${r.name ?? ''}`.trim(), sub: r.status ?? '' }
      case 'audit_logs':
        return {
          title: [r.user, r.action].filter(Boolean).join(' · ') || '-',
          sub: [r.resource, String(r.created_at ?? '').slice(0, 19)].filter(Boolean).join(' · '),
        }
      default:
        return { title: JSON.stringify(r).slice(0, 80) }
    }
  })
}

const examples = [
  t('aiAssistant.example1'),
  t('aiAssistant.example2'),
  t('aiAssistant.example3'),
  t('aiAssistant.example4'),
]

function open() {
  visible.value = true
}

function onClosed() {
  input.value = ''
  loading.value = false
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

async function send(q?: string) {
  const question = (q ?? input.value).trim()
  if (!question || loading.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: question })
  loading.value = true
  scrollToBottom()
  try {
    const res = await api.post('/ai/search', { question, last_data_type: lastDataType.value })
    const data = res.data?.data || res.data
    const answer = data?.answer_text || ''
    const suggestions = Array.isArray(data?.suggestions) ? data.suggestions : []
    const rawRows = Array.isArray(data?.data) ? data.data : []
    lastDataType.value = data?.data_type || ''
    const rows = rawRows.length ? buildRows(data.data_type, rawRows) : undefined
    messages.value.push({ role: 'ai', content: answer, suggestions, rows })
  } catch (e: any) {
    const msg = e?.response?.status === 401 ? t('aiSearch.loginRequired') : t('aiSearch.searchFailed')
    messages.value.push({ role: 'ai', content: msg })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function onEnter() {
  send()
}

function goHistory() {
  visible.value = false
  router.push('/system/ai-chat-logs')
}

defineExpose({ open })
</script>

<style scoped>
.ai-assistant {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.ai-welcome {
  text-align: center;
  padding: 24px 12px;
}
.ai-welcome-icon {
  width: 48px;
  height: 48px;
  margin: 0 auto 12px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: var(--accent-primary, #3b82f6);
  color: #fff;
  font-size: 24px;
}
.ai-welcome-text {
  font-size: 13px;
  color: #8c8c8c;
  line-height: 1.6;
  margin: 0 0 16px;
}
.ai-examples {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ai-example-chip {
  padding: 8px 12px;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  background: #fafafa;
  color: #595959;
  font-size: 13px;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}
.ai-example-chip:hover {
  border-color: var(--accent-primary, #3b82f6);
  color: var(--accent-primary, #3b82f6);
  background: var(--bg-tertiary, #f3f4f6);
}
.ai-messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 4px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ai-msg {
  max-width: 90%;
  padding: 10px 12px;
  border-radius: 10px;
}
.ai-msg--user {
  align-self: flex-end;
  background: #1890ff;
  color: #fff;
}
.ai-msg--ai {
  align-self: flex-start;
  background: #f6f8fa;
  border: 1px solid #eee;
  color: #333;
}
.ai-msg-role {
  font-size: 11px;
  opacity: 0.6;
  margin-bottom: 4px;
}
.ai-msg-content {
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.ai-typing {
  opacity: 0.7;
}
.ai-msg-suggestions {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ai-suggestion-chip {
  padding: 4px 10px;
  border: 1px solid #d9d9d9;
  border-radius: 16px;
  background: #fff;
  color: #595959;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.ai-suggestion-chip:hover {
  border-color: var(--accent-primary, #3b82f6);
  color: var(--accent-primary, #3b82f6);
}
.ai-msg-rows {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ai-msg-row {
  padding: 6px 8px;
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 6px;
  background: var(--bg-primary, #fff);
}
.ai-row-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-h, #111827);
}
.ai-row-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary, #6b7280);
}
.ai-input-bar {
  display: flex;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
  align-items: flex-end;
}
.ai-history-link {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}
.ai-history-link .el-icon {
  margin-right: 4px;
  vertical-align: -2px;
}
</style>
