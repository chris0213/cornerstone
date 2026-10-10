import api from './axios'

export interface ChatLogItem {
  id: number
  userId: number
  username: string
  question: string
  answerText: string
  dataType: string | null
  clientIp: string | null
  createdAt: string | null
}

export interface ChatLogResponse {
  total: number
  items: ChatLogItem[]
}

export interface ChatLogQuery {
  skip?: number
  limit?: number
  keyword?: string
  dataType?: string
  userId?: number
  days?: number
}

export async function getChatLogs(params: ChatLogQuery): Promise<ChatLogResponse> {
  const response = await api.get('/ai/chat-logs', { params })
  return response.data
}

/**
 * 流式导出 CSV：后端逐行产出，这里只负责触发浏览器下载。
 * 返回实际使用的文件名（取自后端 Content-Disposition，缺失时回退默认名）。
 */
export async function exportChatLogsCsv(params: Omit<ChatLogQuery, 'skip' | 'limit'>): Promise<string> {
  const response = await api.get('/ai/chat-logs/export', {
    params,
    responseType: 'blob',
  })

  let filename = `ai-chat-logs-${new Date().toISOString().slice(0, 10)}.csv`
  const disposition = response.headers?.['content-disposition']
  if (disposition) {
    const match = /filename="?([^";]+)"?/.exec(disposition)
    if (match?.[1]) filename = match[1]
  }

  const blobUrl = URL.createObjectURL(response.data as Blob)
  const link = document.createElement('a')
  link.href = blobUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(blobUrl)

  return filename
}
