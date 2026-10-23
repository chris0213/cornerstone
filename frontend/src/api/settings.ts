import api from './axios'

export interface NotificationSettings {
  // GET 响应：密钥字段只回 has_xxx + 尾 8 字符
  has_dingtalk_webhook_url?: boolean
  has_wechat_webhook_url?: boolean
  has_feishu_webhook_url?: boolean
  has_smtp_password?: boolean
  dingtalk_webhook_url_tail?: string
  wechat_webhook_url_tail?: string
  feishu_webhook_url_tail?: string
  smtp_password_tail?: string
  smtp_host?: string
  smtp_port?: number
  smtp_username?: string
  smtp_from_email?: string
  smtp_security?: 'none' | 'starttls' | 'ssl'
  channel_enabled?: Record<string, boolean>
  // PUT 请求：密钥字段传空 = 留空不修改
  dingtalk_webhook_url?: string
  wechat_webhook_url?: string
  feishu_webhook_url?: string
  smtp_password?: string
}

export interface TestNotificationResult {
  success: boolean
  message: string
  channel: string
  status: 'sent' | 'failed'
  error?: string
}

export const getNotificationSettings = async (): Promise<NotificationSettings> => {
  const response = await api.get('/settings/notification')
  return response.data
}

export const updateNotificationSettings = async (settings: NotificationSettings): Promise<NotificationSettings> => {
  const response = await api.put('/settings/notification', settings)
  return response.data
}

export const testNotification = async (channel: 'dingtalk' | 'wechat' | 'feishu' | 'email'): Promise<TestNotificationResult> => {
  const response = await api.post('/settings/notification/test', { channel })
  return response.data
}
