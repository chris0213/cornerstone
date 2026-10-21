<template>
  <div class="knowledge-page">
    <div class="page-head">
      <div class="page-desc">{{ t('knowledge.description') }}</div>
      <div class="page-actions">
        <el-tooltip :content="t('knowledge.exportTip')" placement="top">
          <el-button :disabled="total === 0" :loading="exporting" @click="handleExport">
            <el-icon><Download /></el-icon>
            {{ t('knowledge.export') }}
          </el-button>
        </el-tooltip>
        <el-button v-if="canWrite" :loading="importing" @click="triggerImport">
          <el-icon><Upload /></el-icon>
          {{ t('knowledge.import') }}
        </el-button>
        <el-button v-if="canWrite" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          {{ t('knowledge.newArticle') }}
        </el-button>
        <input
          ref="fileInputRef"
          type="file"
          accept=".md,.markdown,.txt,.docx,.xlsx,.xlsm"
          style="display: none"
          @change="handleImport"
        >
      </div>
    </div>

    <div class="kb-layout">
      <!-- 分类侧栏 -->
      <aside class="kb-sidebar">
        <div class="cat-head">
          <span>{{ t('knowledge.catGroup') }}</span>
          <el-icon v-if="canWrite" class="cat-add" :title="t('knowledge.catNew')" @click="openCatDialog()"><Plus /></el-icon>
        </div>
        <div
          class="cat-item"
          :class="{ active: !activeCategory }"
          @click="selectCategory('')"
        >
          <span>{{ t('knowledge.all') }}</span>
          <span class="cat-count">{{ totalCount }}</span>
        </div>
        <div
          v-for="c in categories"
          :key="c.id"
          class="cat-item"
          :class="{ active: activeCategory === c.name }"
          @click="selectCategory(c.name)"
        >
          <span class="cat-name">{{ categoryLabel(c.name) }}</span>
          <span class="cat-item-right">
            <span v-if="canWrite && c.name !== '其他'" class="cat-ops">
              <el-icon class="cat-op" :title="t('knowledge.catRename')" @click.stop="openCatDialog(c)"><Edit /></el-icon>
              <el-icon class="cat-op cat-op-danger" :title="t('common.delete')" @click.stop="handleDeleteCategory(c)"><Delete /></el-icon>
            </span>
            <span class="cat-count">{{ c.count }}</span>
          </span>
        </div>
      </aside>

      <!-- 主内容 -->
      <main class="kb-main">
        <div class="kb-toolbar">
          <el-input
            v-model="keyword"
            :placeholder="t('knowledge.searchPlaceholder')"
            clearable
            style="width: 260px"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </div>

        <div v-loading="loading" class="kb-list">
          <div v-if="!loading && articles.length === 0" class="empty-state">
            <el-icon :size="48" color="#ccc"><Files /></el-icon>
            <p>{{ activeCategory ? t('knowledge.emptyCategory') : t('knowledge.empty') }}</p>
            <div v-if="canWrite" class="empty-actions">
              <el-button type="primary" @click="openCreate">
                <el-icon><Plus /></el-icon>
                {{ t('knowledge.newArticle') }}
              </el-button>
              <el-button :loading="importing" @click="triggerImport">
                <el-icon><Upload /></el-icon>
                {{ t('knowledge.import') }}
              </el-button>
            </div>
          </div>

          <div
            v-for="article in articles"
            :key="article.id"
            class="kb-card"
            @click="openRead(article)"
          >
            <div class="kb-card-head">
              <span class="kb-title">{{ article.title }}</span>
              <el-tag v-if="!article.is_published" size="small" type="info" effect="plain">
                {{ t('knowledge.draft') }}
              </el-tag>
              <div v-if="canWrite" class="kb-card-actions" @click.stop>
                <el-button link type="primary" size="small" @click="openEdit(article)">
                  {{ t('knowledge.editArticle') }}
                </el-button>
                <el-button
                  link
                  type="danger"
                  size="small"
                  @click="handleDelete(article)"
                >{{ t('common.delete') }}</el-button>
              </div>
            </div>
            <p v-if="article.summary" class="kb-summary">{{ article.summary }}</p>
            <div class="kb-meta">
              <el-tag size="small" effect="plain" class="kb-cat">{{ categoryLabel(article.category) }}</el-tag>
              <span v-for="tag in tagList(article.tags)" :key="tag" class="kb-tag">#{{ tag }}</span>
              <span class="kb-meta-right">
                {{ authorName(article.author) }} · {{ formatDateTime(article.updated_at || '') }}
                · {{ t('knowledge.views', { count: article.view_count }) }}
              </span>
            </div>
          </div>
        </div>

        <div v-if="total > 0" class="kb-pagination">
          <span class="kb-total">{{ t('knowledge.totalArticles', { count: total }) }}</span>
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[10, 20, 50]"
            layout="sizes, prev, pager, next, jumper"
            background
            @size-change="onPageChange"
            @current-change="onPageChange"
          />
        </div>
      </main>
    </div>

    <!-- 阅读弹窗 -->
    <el-dialog
      v-model="showReader"
      :title="reading?.title"
      width="760px"
      top="6vh"
      destroy-on-close
    >
      <div class="reader-meta">
        <el-tag size="small" effect="plain">{{ categoryLabel(reading?.category || '') }}</el-tag>
        <span v-for="tag in tagList(reading?.tags)" :key="tag" class="kb-tag">#{{ tag }}</span>
        <span class="reader-meta-right">
          {{ authorName(reading?.author || '') }} · {{ formatDateTime(reading?.updated_at || '') }}
          · {{ t('knowledge.views', { count: reading?.view_count || 0 }) }}
        </span>
      </div>
      <div class="reader-body" v-html="renderedContent"></div>
      <template #footer>
        <el-button @click="showReader = false">{{ t('common.close') }}</el-button>
        <el-button v-if="canWrite" type="primary" @click="editFromReader">{{ t('knowledge.editArticle') }}</el-button>
      </template>
    </el-dialog>

    <!-- 编辑弹窗 -->
    <el-dialog
      v-model="showEditor"
      :title="editingId ? t('knowledge.editArticle') : t('knowledge.newArticle')"
      width="min(1200px, 92vw)"
      top="3vh"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item :label="t('knowledge.titleField')" required>
          <el-input v-model="form.title" :placeholder="t('knowledge.titlePlaceholder')" maxlength="200" show-word-limit />
        </el-form-item>
        <div class="editor-row">
          <el-form-item :label="t('knowledge.category')" class="editor-row-item">
            <el-select v-model="form.category" style="width: 100%">
              <el-option v-for="c in categories" :key="c.id" :label="categoryLabel(c.name)" :value="c.name" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('knowledge.tags')" class="editor-row-item">
            <el-input v-model="form.tags" :placeholder="t('knowledge.tagsPlaceholder')" />
          </el-form-item>
        </div>
        <el-form-item :label="t('knowledge.summary')">
          <el-input v-model="form.summary" type="textarea" :rows="2" :placeholder="t('knowledge.summaryPlaceholder')" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item :label="t('knowledge.content')">
          <el-alert
            v-if="sensitiveHits.length"
            type="warning"
            :closable="false"
            show-icon
            class="editor-hint"
            :title="t('knowledge.sensitiveHitTitle')"
            :description="t('knowledge.sensitiveHitDesc', { types: sensitiveHits.map(h => h.label).join('、') })"
          />
          <div class="editor-split">
            <!-- 左侧：根据内容类型自动切换 -->
            <div class="editor-pane">
              <div class="pane-label">{{ tableEditMode ? t('knowledge.modeTable') : t('knowledge.modeEdit') }}</div>
              <!-- 表格编辑模式：正文仅含单个表格 -->
              <div v-if="tableEditMode" class="table-editor">
                <div class="table-editor-toolbar">
                  <el-button size="small" @click="addTableRow">{{ t('knowledge.tableAddRow') }}</el-button>
                  <el-button size="small" @click="addTableCol">{{ t('knowledge.tableAddCol') }}</el-button>
                  <el-button size="small" :disabled="tableSelectedRow === null" @click="delTableRow">{{ t('knowledge.tableDelRow') }}</el-button>
                  <el-button size="small" :disabled="tableSelectedCol === null" @click="delTableCol">{{ t('knowledge.tableDelCol') }}</el-button>
                  <el-button size="small" @click="toggleTableSource">{{ t('knowledge.tableSwitchSource') }}</el-button>
                </div>
                <el-table
                  :data="tableBody"
                  :row-key="(_row: string[], i: number) => i"
                  @row-click="(_row: string[], col: any) => (tableSelectedRow = col?.rowIndex ?? null)"
                  highlight-current-row
                  border
                  size="small"
                  class="editor-table"
                >
                  <el-table-column
                    v-for="(h, ci) in tableHeader"
                    :key="ci"
                    :label="h"
                    :min-width="120"
                    align="center"
                  >
                    <template #header>
                      <el-input
                        size="small"
                        :model-value="tableHeader[ci]"
                        @update:model-value="(v: string) => setTableHeader(ci, v)"
                        placeholder="表头"
                      />
                    </template>
                    <template #default="{ row }">
                      <el-input
                        size="small"
                        :model-value="row[ci]"
                        @update:model-value="(v: string) => setTableCell(tableBody.indexOf(row), ci, v)"
                        @focus="() => { tableSelectedCol = ci; tableSelectedRow = tableBody.indexOf(row) }"
                      />
                    </template>
                  </el-table-column>
                </el-table>
              </div>
              <!-- 源码模式 -->
              <el-input
                v-else
                v-model="form.content"
                type="textarea"
                class="editor-textarea"
                :placeholder="t('knowledge.contentPlaceholder')"
              />
            </div>
            <!-- 右侧：渲染预览 -->
            <div class="editor-pane">
              <div class="pane-label">{{ t('knowledge.modePreview') }}</div>
              <div class="reader-body editor-preview" v-html="editorPreview"></div>
            </div>
          </div>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.is_published">{{ t('knowledge.isPublished') }}</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditor = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">
          {{ t('knowledge.save') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 分类新增/改名弹窗 -->
    <el-dialog
      v-model="showCatDialog"
      :title="catEditing ? t('knowledge.catRename') : t('knowledge.catNew')"
      width="420px"
      destroy-on-close
    >
      <el-form label-position="top" @submit.prevent="handleCatSubmit">
        <el-form-item :label="t('knowledge.catName')" required>
          <el-input
            v-model="catForm.name"
            :placeholder="t('knowledge.catNamePlaceholder')"
            maxlength="50"
            show-word-limit
            @keyup.enter="handleCatSubmit"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCatDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="catSaving" @click="handleCatSubmit">
          {{ t('common.confirm') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Search, Plus, Files, Upload, Download, Edit, Delete } from '@element-plus/icons-vue'
import DOMPurify from 'dompurify'
import {
  listArticles, listCategories, getArticle, createArticle, updateArticle, deleteArticle, importArticle,
  createCategory, updateCategory, deleteCategory,
  type KnowledgeArticle, type KnowledgeCategory,
} from '@/api/knowledge'
import { getUsers } from '@/api/users'
import { useAuthStore } from '../../store/auth'
import { formatDateTime } from '@/lib/utils'
import { confirmAndRun } from '@/lib/confirm'
import { parseAllMdTables, parseFirstMdTable, replaceMdTable } from '@/lib/md-table'

const { t } = useI18n()
const authStore = useAuthStore()
// 与后端对齐：POST/PUT/DELETE 文章与分类管理均需 knowledge:write（读/导出仅登录即可）
const canWrite = computed(() => authStore.hasPermission('knowledge', 'write'))

const loading = ref(false)
const saving = ref(false)
const articles = ref<KnowledgeArticle[]>([])
const categories = ref<KnowledgeCategory[]>([])
const activeCategory = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)

// 作者 username → 显示名（优先 full_name）
const authorNameMap = ref<Record<string, string>>({})

async function loadAuthorNames() {
  try {
    const users = await getUsers()
    const map: Record<string, string> = {}
    for (const u of users) map[u.username] = u.full_name || u.username
    authorNameMap.value = map
  } catch {
    /* 映射失败时回退显示用户名 */
  }
}

function authorName(username: string): string {
  return authorNameMap.value[username] || username
}

const showReader = ref(false)
const reading = ref<KnowledgeArticle | null>(null)

const showEditor = ref(false)
const editingId = ref<number | null>(null)
const editorPreview = computed(() => renderMarkdown(form.value.content))

// 表格编辑模式状态
const tableForceSource = ref(false)  // 用户手动切到源码
const tableSelectedRow = ref<number | null>(null)
const tableSelectedCol = ref<number | null>(null)

/** 正文是否可切换到表格编辑：仅含一个 Markdown 表格块（前后允许空行） */
const tableEditMode = computed(() => {
  if (tableForceSource.value) return false
  const content = form.value.content
  const stripped = content.replace(/^\s*\n|\n\s*$/g, '')
  const tables = parseAllMdTables(stripped)
  if (tables.length !== 1) return false
  const t = tables[0]
  // 表格块占据正文绝大部分（允许前后少量空行/单行说明）
  const lines = stripped.split('\n')
  if (t.startLine > 2 || lines.length - t.endLine - 1 > 2) return false
  return true
})

const tableHeader = computed<string[]>(() => {
  const parsed = parseFirstMdTable(form.value.content)
  return parsed?.header ?? []
})

const tableBody = computed<string[][]>(() => {
  const parsed = parseFirstMdTable(form.value.content)
  return parsed?.body ?? []
})

/** 把当前 header/body 同步写回 form.content（替换第一个表格块） */
function commitTableToContent(header: string[], body: string[][]) {
  form.value.content = replaceMdTable(form.value.content, 0, header, body)
}

function setTableHeader(col: number, val: string) {
  const h = [...tableHeader.value]
  h[col] = val
  commitTableToContent(h, tableBody.value)
}

function setTableCell(row: number, col: number, val: string) {
  const body = tableBody.value.map(r => [...r])
  body[row][col] = val
  commitTableToContent(tableHeader.value, body)
}

function addTableRow() {
  const body = tableBody.value
  const cols = tableHeader.value.length
  body.push(new Array(cols).fill(''))
  commitTableToContent(tableHeader.value, body)
}

function addTableCol() {
  const header = [...tableHeader.value, `列${tableHeader.value.length + 1}`]
  const body = tableBody.value.map(r => [...r, ''])
  commitTableToContent(header, body)
}

function delTableRow() {
  if (tableSelectedRow.value === null) return
  const body = tableBody.value.filter((_, i) => i !== tableSelectedRow.value)
  commitTableToContent(tableHeader.value, body)
  tableSelectedRow.value = null
}

function delTableCol() {
  if (tableSelectedCol.value === null) return
  const colIdx = tableSelectedCol.value
  const header = tableHeader.value.filter((_, i) => i !== colIdx)
  const body = tableBody.value.map(r => r.filter((_, i) => i !== colIdx))
  commitTableToContent(header, body)
  tableSelectedCol.value = null
}

function toggleTableSource() {
  tableForceSource.value = !tableForceSource.value
}
const form = ref({
  title: '',
  category: '其他',
  tags: '',
  summary: '',
  content: '',
  is_published: true,
})

// ===== 敏感信息命中检测（键值形式，只提示不阻止保存，不回显命中内容）=====
const SENSITIVE_PATTERNS: Array<{ key: string; re: RegExp }> = [
  { key: 'password', re: /\b(?:password|passwd)\s*[=:]\s*\S+/i },
  { key: 'secret', re: /\bsecret\s*[=:]\s*\S+/i },
  { key: 'apiKey', re: /\bapi[_-]?key\s*[=:]\s*\S+/i },
  { key: 'token', re: /\btoken\s*[:=]\s*\S+/i },
  { key: 'privateKey', re: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
]

const sensitiveHits = computed(() => {
  const content = form.value.content
  if (!content) return []
  return SENSITIVE_PATTERNS
    .filter(p => p.re.test(content))
    .map(p => ({ key: p.key, label: t(`knowledge.sensitiveType_${p.key}`) }))
})

/** 后端 403 统一映射为 i18n 文案，不显示后端原文 */
function errorMessageOf(error: any): string {
  if (error?.response?.status === 403) return t('knowledge.noPermission')
  return error?.response?.data?.detail || t('common.error')
}

const totalCount = computed(() => categories.value.reduce((sum, c) => sum + c.count, 0))

// 预设分类的标签名（数据库存中文，显示映射）
function categoryLabel(cat: string): string {
  const map: Record<string, string> = {
    '故障处理': t('knowledge.catTroubleshoot'),
    '配置手册': t('knowledge.catConfig'),
    '操作SOP': t('knowledge.catSop'),
    '常见问题': t('knowledge.catFaq'),
    '其他': t('knowledge.catOther'),
  }
  return map[cat] || cat
}

function tagList(tags: string | undefined): string[] {
  if (!tags) return []
  return tags.split(/[,，]/).map(s => s.trim()).filter(Boolean)
}

async function loadArticles() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      skip: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
    }
    if (activeCategory.value) params.category = activeCategory.value
    if (keyword.value) params.keyword = keyword.value
    const res = await listArticles(params)
    articles.value = res.items
    total.value = res.total
  } catch (error) {
    console.error('Failed to load articles:', error)
  } finally {
    loading.value = false
  }
}

// 关键词 300ms 防抖即时搜索（clearable 清空时同样触发）
let keywordTimer: ReturnType<typeof setTimeout> | null = null
watch(keyword, () => {
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => {
    page.value = 1
    loadArticles()
  }, 300)
})

function onPageChange() {
  loadArticles()
}

async function loadCategories() {
  try {
    categories.value = await listCategories()
  } catch (error) {
    console.error('Failed to load categories:', error)
  }
}

function selectCategory(cat: string) {
  activeCategory.value = cat
  page.value = 1
  loadArticles()
}

// ===== 分类管理（新增/改名/删除，需 knowledge:write）=====
const showCatDialog = ref(false)
const catSaving = ref(false)
const catEditing = ref<KnowledgeCategory | null>(null)  // null=新增
const catForm = ref({ name: '' })

function openCatDialog(cat?: KnowledgeCategory) {
  catEditing.value = cat || null
  catForm.value.name = cat?.name || ''
  showCatDialog.value = true
}

async function handleCatSubmit() {
  const name = catForm.value.name.trim()
  if (!name) {
    ElMessage.error(t('knowledge.catNameRequired'))
    return
  }
  if (name.length > 50) {
    ElMessage.error(t('knowledge.catNameTooLong'))
    return
  }
  // 提交前本地判重（后端 409 兜底）
  const dup = categories.value.some(c => c.name === name && c.id !== catEditing.value?.id)
  if (dup) {
    ElMessage.error(t('knowledge.catDuplicate'))
    return
  }
  catSaving.value = true
  try {
    if (catEditing.value) {
      await updateCategory(catEditing.value.id, { name })
      // 改名后同步当前选中分类名，保持筛选连续
      if (activeCategory.value === catEditing.value.name) activeCategory.value = name
      ElMessage.success(t('knowledge.catRenameSuccess'))
    } else {
      await createCategory({ name })
      ElMessage.success(t('knowledge.catNewSuccess'))
    }
    showCatDialog.value = false
    await Promise.all([loadCategories(), loadArticles()])
  } catch (error: any) {
    console.error('Failed to save category:', error)
    ElMessage.error(errorMessageOf(error))
  } finally {
    catSaving.value = false
  }
}

async function handleDeleteCategory(cat: KnowledgeCategory) {
  // 删除前预检文章数，409 仅作兜底
  if (cat.count > 0) {
    ElMessage.warning(t('knowledge.catInUse', { count: cat.count }))
    return
  }
  await confirmAndRun({
    message: t('knowledge.catDeleteConfirm', { name: categoryLabel(cat.name) }),
    title: t('common.confirm'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    danger: true,
    action: async () => {
      await deleteCategory(cat.id)
      // 删除的是当前选中分类时切回「全部」；侧栏与列表始终刷新，避免残留已删分类
      if (activeCategory.value === cat.name) {
        activeCategory.value = ''
        page.value = 1
      }
      await Promise.all([loadCategories(), loadArticles()])
    },
    successMessage: t('knowledge.catDeleteSuccess'),
    errorMessage: (error: any) => {
      // 兜底：预检后被使用/默认分类保护等 409
      if (error?.response?.status === 409) return t('knowledge.catDeleteConflict')
      return errorMessageOf(error)
    },
  })
}

// ===== 阅读 =====
async function openRead(article: KnowledgeArticle) {
  try {
    reading.value = await getArticle(article.id)
    showReader.value = true
    // 本地列表计数同步
    const local = articles.value.find(a => a.id === article.id)
    if (local) local.view_count = reading.value.view_count
  } catch (error) {
    console.error('Failed to load article:', error)
  }
}

function editFromReader() {
  if (!reading.value) return
  showReader.value = false
  openEdit(reading.value)
}

// 极简 Markdown 渲染：先全量转义防 XSS，再叠加有限标签
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inlineMd(s: string): string {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function renderMarkdown(raw: string): string {
  if (!raw) return ''
  const escaped = escapeHtml(raw)
  const lines = escaped.split('\n')
  const out: string[] = []
  let inCode = false
  let tableBuffer: string[] = []

  const flushTable = () => {
    if (!tableBuffer.length) return
    const rows = tableBuffer
      .filter(l => !/^\s*\|[\s\-:|]+\|\s*$/.test(l))  // 去掉 --- 分隔行
      .map(l => l.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim()))
    if (rows.length) {
      const head = rows[0]
      const body = rows.slice(1)
      out.push('<table><thead><tr>' + head.map(c => `<th>${inlineMd(c)}</th>`).join('') + '</tr></thead><tbody>')
      for (const r of body) {
        out.push('<tr>' + r.map(c => `<td>${inlineMd(c)}</td>`).join('') + '</tr>')
      }
      out.push('</tbody></table>')
    }
    tableBuffer = []
  }

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      flushTable()
      inCode = !inCode
      out.push(inCode ? '<pre><code>' : '</code></pre>')
      continue
    }
    if (inCode) {
      out.push(line + '\n')
      continue
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      tableBuffer.push(line)
      continue
    }
    flushTable()

    if (line.startsWith('### ')) out.push(`<h4>${inlineMd(line.slice(4))}</h4>`)
    else if (line.startsWith('## ')) out.push(`<h3>${inlineMd(line.slice(3))}</h3>`)
    else if (line.startsWith('# ')) out.push(`<h2>${inlineMd(line.slice(2))}</h2>`)
    else if (/^\s*[-*] /.test(line)) out.push(`<li>${inlineMd(line.replace(/^\s*[-*] /, ''))}</li>`)
    else if (/^\s*\d+\.\s/.test(line)) out.push(`<li class="ordered">${inlineMd(line.replace(/^\s*\d+\.\s/, ''))}</li>`)
    else if (line.trim() === '') out.push('')
    else out.push(`<p>${inlineMd(line)}</p>`)
  }
  flushTable()

  // 相邻列表项合并包裹（先有序后无序，避免吞掉 class），DOMPurify 兜底防 XSS
  const merged = out.join('\n')
    .replace(/(<li class="ordered">[\s\S]*?<\/li>\n?)+/g, m => `<ol>${m.replace(/ class="ordered"/g, '')}</ol>`)
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
  return DOMPurify.sanitize(merged, { USE_PROFILES: { html: true } })
}

const renderedContent = computed(() => renderMarkdown(reading.value?.content || ''))

// ===== 编辑 =====
function openCreate() {
  editingId.value = null
  form.value = { title: '', category: '其他', tags: '', summary: '', content: '', is_published: true }
  showEditor.value = true
}

async function openEdit(article: KnowledgeArticle) {
  try {
    // 列表接口不含正文，必须拉详情，否则保存会清空 content；编辑回读不累加阅读量
    const detail = await getArticle(article.id, false)
    editingId.value = detail.id
    form.value = {
      title: detail.title,
      category: detail.category,
      tags: detail.tags,
      summary: detail.summary,
      content: detail.content || '',
      is_published: detail.is_published,
    }
    showEditor.value = true
  } catch (error) {
    console.error('Failed to load article:', error)
  }
}

async function handleSave() {
  if (!form.value.title.trim()) {
    ElMessage.error(t('knowledge.titleRequired'))
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await updateArticle(editingId.value, { ...form.value })
    } else {
      await createArticle({ ...form.value })
    }
    ElMessage.success(t('knowledge.saveSuccess'))
    showEditor.value = false
    await Promise.all([loadArticles(), loadCategories()])
  } catch (error: any) {
    console.error('Failed to save article:', error)
    ElMessage.error(errorMessageOf(error))
  } finally {
    saving.value = false
  }
}

// ===== 导出 =====
const exporting = ref(false)

/** 导出当前筛选结果为 Markdown（文章之间用 --- 分隔） */
function articleToMarkdown(a: KnowledgeArticle): string {
  const tags = tagList(a.tags).map(tag => `#${tag}`).join(' ')
  const head = `# ${a.title}\n\n- ${t('knowledge.category')}: ${categoryLabel(a.category)}${tags ? `\n- ${tags}` : ''}\n- ${t('knowledge.author')}: ${authorName(a.author)} · ${t('knowledge.updatedAt')}: ${formatDateTime(a.updated_at || '')}`
  const body = `---\n\n${a.content || a.summary || ''}`
  return `${head}\n\n${body}`
}

async function handleExport() {
  exporting.value = true
  try {
    // 分页拉全量（单页上限 1000，硬上限 5000 篇），按当前分类/关键词筛选，含草稿
    const base = {
      category: activeCategory.value || undefined,
      keyword: keyword.value || undefined,
    }
    const PAGE = 1000
    const HARD_LIMIT = 5000
    const items: KnowledgeArticle[] = []
    let totalAll = 0
    for (let skip = 0; ; skip += PAGE) {
      const res = await listArticles({ ...base, skip, limit: PAGE })
      totalAll = res.total
      items.push(...res.items)
      if (items.length >= totalAll || items.length >= HARD_LIMIT || res.items.length < PAGE) break
    }
    if (!items.length) {
      ElMessage.info(t('knowledge.exportEmpty'))
      return
    }
    // 逐篇补正文
    const parts: string[] = []
    for (const item of items) {
      try {
        const detail = await getArticle(item.id, false)
        parts.push(articleToMarkdown(detail))
      } catch {
        parts.push(articleToMarkdown(item))
      }
    }
    const banner = `> ${t('knowledge.exportBanner', { count: items.length })} · ${formatDateTime(new Date().toISOString())}\n\n`
    const blob = new Blob([banner + parts.join('\n\n---\n\n')], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `knowledge-${new Date().toISOString().slice(0, 10)}.md`
    link.click()
    URL.revokeObjectURL(url)
    // 超过硬上限时明确告知仅导出前 N 篇
    if (totalAll > items.length) {
      ElMessage.warning(t('knowledge.exportTruncated', { count: items.length, total: totalAll }))
    } else {
      ElMessage.success(t('knowledge.exportSuccess', { count: items.length }))
    }
  } catch (error: any) {
    console.error('Failed to export articles:', error)
    ElMessage.error(errorMessageOf(error))
  } finally {
    exporting.value = false
  }
}

// ===== 导入 =====
const fileInputRef = ref<HTMLInputElement | null>(null)
const importing = ref(false)

function triggerImport() {
  fileInputRef.value?.click()
}

async function handleImport(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''  // 允许重复选择同一文件
  if (!file) return
  const ext = file.name.toLowerCase().split('.').pop()
  if (!['md', 'markdown', 'txt', 'docx', 'xlsx', 'xlsm'].includes(ext || '')) {
    ElMessage.error(t('knowledge.importUnsupported'))
    return
  }
  importing.value = true
  try {
    const articles = await importArticle(file, activeCategory.value || undefined)
    await Promise.all([loadArticles(), loadCategories()])
    if (articles && articles.length) {
      const msg = articles.length > 1
        ? t('knowledge.importSuccessMulti', { title: articles[0].title, count: articles.length })
        : t('knowledge.importSuccess', { title: articles[0].title })
      ElMessage.success(msg)
      openRead(articles[0])  // 打开第一篇，方便核对排版
    }
  } catch (error: any) {
    console.error('Failed to import article:', error)
    ElMessage.error(errorMessageOf(error))
  } finally {
    importing.value = false
  }
}

async function handleDelete(article: KnowledgeArticle) {
  await confirmAndRun({
    message: t('knowledge.deleteConfirm', { title: article.title }),
    title: t('common.confirm'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    action: async () => {
      await deleteArticle(article.id)
      await Promise.all([loadArticles(), loadCategories()])
    },
    successMessage: t('knowledge.deleteSuccess'),
    errorMessage: t('common.error'),
  })
}

onMounted(() => {
  loadArticles()
  loadCategories()
  loadAuthorNames()
})
</script>

<style scoped>
.knowledge-page {
  padding: 0;
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.page-desc {
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.page-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.kb-layout {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.kb-sidebar {
  width: 180px;
  flex-shrink: 0;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 8px;
}

.cat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 6px;
}

.cat-add {
  cursor: pointer;
  color: var(--el-text-color-secondary);
  border-radius: 4px;
  padding: 2px;
  transition: all 0.15s;
}

.cat-add:hover {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
}

.cat-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.cat-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cat-item-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.cat-ops {
  display: none;
  align-items: center;
  gap: 2px;
}

.cat-item:hover .cat-ops {
  display: inline-flex;
}

.cat-op {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  border-radius: 3px;
  padding: 2px;
  transition: all 0.15s;
}

.cat-op:hover {
  color: var(--el-color-primary);
  background: var(--el-fill-color);
}

.cat-op-danger:hover {
  color: var(--el-color-danger);
}

.cat-item:hover {
  background: var(--el-fill-color-light);
}

.cat-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 500;
}

.cat-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.kb-main {
  flex: 1;
  min-width: 0;
}

.kb-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.kb-list {
  min-height: 200px;
}

.kb-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.kb-total {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.empty-state {
  text-align: center;
  padding: 60px 0;
  color: var(--el-text-color-secondary);
}

.empty-actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}

.kb-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.kb-card:hover {
  border-color: var(--el-color-primary-light-7);
}

.kb-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.kb-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.kb-card-actions {
  margin-left: auto;
  display: flex;
}

.kb-summary {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.kb-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.kb-tag {
  color: var(--el-color-primary);
}

.kb-meta-right {
  margin-left: auto;
}

/* 阅读弹窗 */
.reader-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.reader-meta-right {
  margin-left: auto;
}

.editor-split {
  display: flex;
  gap: 12px;
  width: 100%;
}

.editor-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.pane-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
  padding-left: 2px;
}

.editor-textarea :deep(.el-textarea__inner) {
  min-height: 420px !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
  tab-size: 2;
}

/* 表格编辑器 */
.table-editor {
  width: 100%;
  overflow-x: auto;
}

.table-editor-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.editor-table :deep(th),
.editor-table :deep(td) {
  padding: 4px 6px !important;
}

.editor-table :deep(.el-input__wrapper) {
  box-shadow: none !important;
  background: transparent !important;
  padding: 2px 6px !important;
  min-height: 30px;
}

.editor-table :deep(.el-input__wrapper:hover),
.editor-table :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--el-color-primary) inset !important;
  background: var(--el-fill-color-blank) !important;
}

.editor-preview {
  min-height: 420px;
  max-height: 560px;
  padding: 10px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  overflow-y: auto;
}

.reader-body {
  max-height: 60vh;
  overflow-y: auto;
  font-size: 14px;
  line-height: 1.7;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.reader-body :deep(h2),
.reader-body :deep(h3),
.reader-body :deep(h4) {
  margin: 16px 0 8px;
}

.reader-body :deep(p) {
  margin: 6px 0;
}

.reader-body :deep(ul) {
  margin: 6px 0;
  padding-left: 22px;
}

.reader-body :deep(li) {
  margin: 2px 0;
}

.reader-body :deep(code) {
  background: var(--el-fill-color);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 13px;
}

.reader-body :deep(pre) {
  background: var(--el-fill-color);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}

.reader-body :deep(pre code) {
  background: transparent;
  padding: 0;
}

.reader-body :deep(table) {
  border-collapse: collapse;
  margin: 10px 0;
  width: 100%;
}

.reader-body :deep(th),
.reader-body :deep(td) {
  border: 1px solid var(--el-border-color-lighter);
  padding: 6px 10px;
  font-size: 13px;
  text-align: left;
}

.reader-body :deep(th) {
  background: var(--el-fill-color-light);
  font-weight: 500;
}

.reader-body :deep(ol) {
  margin: 6px 0;
  padding-left: 22px;
}

.reader-body :deep(ol li) {
  margin: 2px 0;
}

/* 编辑弹窗 */
.editor-row {
  display: flex;
  gap: 16px;
}

.editor-row-item {
  flex: 1;
}

.editor-hint {
  width: 100%;
  margin-bottom: 8px;
  padding: 6px 12px;
}

/* 移动端 */
@media (max-width: 768px) {
  .kb-layout {
    flex-direction: column;
  }

  .kb-sidebar {
    width: 100%;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .cat-item {
    flex: 0 0 auto;
  }

  .kb-toolbar {
    flex-direction: column;
  }

  .kb-toolbar .el-input {
    width: 100% !important;
  }

  .page-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }

  .page-actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .editor-row {
    flex-direction: column;
    gap: 0;
  }

  .kb-meta-right {
    margin-left: 0;
    width: 100%;
  }
}
</style>
