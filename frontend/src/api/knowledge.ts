import request from './axios'

export interface KnowledgeArticle {
  id: number
  title: string
  category: string
  tags: string
  summary: string
  content?: string
  author: string
  is_published: boolean
  view_count: number
  created_at?: string
  updated_at?: string
}

export interface KnowledgeCategory {
  category: string
  count: number
}

export interface KnowledgeQuery {
  category?: string
  keyword?: string
  skip?: number
  limit?: number
}

export interface KnowledgeArticleList {
  items: KnowledgeArticle[]
  total: number
}

export async function listArticles(params: KnowledgeQuery = {}): Promise<KnowledgeArticleList> {
  const response = await request.get('/knowledge', { params })
  return response.data
}

export async function listCategories(): Promise<KnowledgeCategory[]> {
  const response = await request.get('/knowledge/categories')
  return response.data
}

export async function getArticle(id: number): Promise<KnowledgeArticle> {
  const response = await request.get(`/knowledge/${id}`)
  return response.data
}

export interface ArticlePayload {
  title: string
  category: string
  tags: string
  summary: string
  content: string
  is_published: boolean
}

export async function createArticle(payload: ArticlePayload): Promise<KnowledgeArticle> {
  const response = await request.post('/knowledge', payload)
  return response.data
}

export async function updateArticle(id: number, payload: Partial<ArticlePayload>): Promise<KnowledgeArticle> {
  const response = await request.put(`/knowledge/${id}`, payload)
  return response.data
}

export async function deleteArticle(id: number): Promise<void> {
  await request.delete(`/knowledge/${id}`)
}

export async function importArticle(file: File, category?: string): Promise<KnowledgeArticle[]> {
  const formData = new FormData()
  formData.append('file', file)
  if (category) formData.append('category', category)
  const response = await request.post('/knowledge/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data
}
