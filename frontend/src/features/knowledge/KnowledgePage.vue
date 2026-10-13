<template>
  <div class="knowledge-page">
    <div class="page-desc">{{ t('knowledge.description') }}</div>

    <div class="kb-layout">
      <!-- 分类侧栏 -->
      <aside class="kb-sidebar">
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
          :key="c.category"
          class="cat-item"
          :class="{ active: activeCategory === c.category }"
          @click="selectCategory(c.category)"
        >
          <span>{{ categoryLabel(c.category) }}</span>
          <span class="cat-count">{{ c.count }}</span>
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
            @keyup.enter="loadArticles"
            @clear="loadArticles"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>
            {{ t('knowledge.newArticle') }}
          </el-button>
        </div>

        <div v-loading="loading" class="kb-list">
          <div v-if="!loading && articles.length === 0" class="empty-state">
            <el-icon :size="48" color="#ccc"><Files /></el-icon>
            <p>{{ activeCategory ? t('knowledge.emptyCategory') : t('knowledge.empty') }}</p>
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
              <div class="kb-card-actions" @click.stop>
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
                {{ article.author }} · {{ formatDateTime(article.updated_at || '') }}
                · {{ t('knowledge.views', { count: article.view_count }) }}
              </span>
            </div>
          </div>
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
          {{ reading?.author }} · {{ formatDateTime(reading?.updated_at || '') }}
          · {{ t('knowledge.views', { count: reading?.view_count || 0 }) }}
        </span>
      </div>
      <div class="reader-body" v-html="renderedContent"></div>
      <template #footer>
        <el-button @click="showReader = false">{{ t('common.close') }}</el-button>
        <el-button type="primary" @click="editFromReader">{{ t('knowledge.editArticle') }}</el-button>
      </template>
    </el-dialog>

    <!-- 编辑弹窗 -->
    <el-dialog
      v-model="showEditor"
      :title="editingId ? t('knowledge.editArticle') : t('knowledge.newArticle')"
      width="760px"
      top="5vh"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item :label="t('knowledge.titleField')" required>
          <el-input v-model="form.title" :placeholder="t('knowledge.titlePlaceholder')" maxlength="200" show-word-limit />
        </el-form-item>
        <div class="editor-row">
          <el-form-item :label="t('knowledge.category')" class="editor-row-item">
            <el-select v-model="form.category" style="width: 100%">
              <el-option :label="t('knowledge.catTroubleshoot')" value="故障处理" />
              <el-option :label="t('knowledge.catConfig')" value="配置手册" />
              <el-option :label="t('knowledge.catSop')" value="操作SOP" />
              <el-option :label="t('knowledge.catFaq')" value="常见问题" />
              <el-option :label="t('knowledge.catOther')" value="其他" />
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
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="14"
            :placeholder="t('knowledge.contentPlaceholder')"
          />
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Search, Plus, Files } from '@element-plus/icons-vue'
import {
  listArticles, listCategories, getArticle, createArticle, updateArticle, deleteArticle,
  type KnowledgeArticle, type KnowledgeCategory,
} from '@/api/knowledge'
import { formatDateTime } from '@/lib/utils'
import { confirmAndRun } from '@/lib/confirm'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const articles = ref<KnowledgeArticle[]>([])
const categories = ref<KnowledgeCategory[]>([])
const activeCategory = ref('')
const keyword = ref('')

const showReader = ref(false)
const reading = ref<KnowledgeArticle | null>(null)

const showEditor = ref(false)
const editingId = ref<number | null>(null)
const form = ref({
  title: '',
  category: '其他',
  tags: '',
  summary: '',
  content: '',
  is_published: true,
})

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
    const params: Record<string, unknown> = { limit: 100 }
    if (activeCategory.value) params.category = activeCategory.value
    if (keyword.value) params.keyword = keyword.value
    articles.value = await listArticles(params)
  } catch (error) {
    console.error('Failed to load articles:', error)
  } finally {
    loading.value = false
  }
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
  loadArticles()
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

const renderedContent = computed(() => {
  const raw = reading.value?.content || ''
  if (!raw) return ''
  const escaped = escapeHtml(raw)
  const lines = escaped.split('\n')
  const out: string[] = []
  let inCode = false

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      inCode = !inCode
      out.push(inCode ? '<pre><code>' : '</code></pre>')
      continue
    }
    if (inCode) {
      out.push(line + '\n')
      continue
    }
    if (line.startsWith('### ')) out.push(`<h4>${inlineMd(line.slice(4))}</h4>`)
    else if (line.startsWith('## ')) out.push(`<h3>${inlineMd(line.slice(3))}</h3>`)
    else if (line.startsWith('# ')) out.push(`<h2>${inlineMd(line.slice(2))}</h2>`)
    else if (/^\s*[-*] /.test(line)) out.push(`<li>${inlineMd(line.replace(/^\s*[-*] /, ''))}</li>`)
    else if (line.trim() === '') out.push('')
    else out.push(`<p>${inlineMd(line)}</p>`)
  }
  // 相邻 li 合并为 ul
  return out.join('\n').replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
})

// ===== 编辑 =====
function openCreate() {
  editingId.value = null
  form.value = { title: '', category: '其他', tags: '', summary: '', content: '', is_published: true }
  showEditor.value = true
}

async function openEdit(article: KnowledgeArticle) {
  try {
    // 列表接口不含正文，必须拉详情，否则保存会清空 content
    const detail = await getArticle(article.id)
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
    ElMessage.error(error.response?.data?.detail || t('common.error'))
  } finally {
    saving.value = false
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
})
</script>

<style scoped>
.knowledge-page {
  padding: 0;
}

.page-desc {
  margin-bottom: 16px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
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

.empty-state {
  text-align: center;
  padding: 60px 0;
  color: var(--el-text-color-secondary);
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

/* 编辑弹窗 */
.editor-row {
  display: flex;
  gap: 16px;
}

.editor-row-item {
  flex: 1;
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
