import request from './axios'

export interface ReportItem {
  id: number
  year: number
  month: number
  file_size: number
  status: string
  generated_by: string
  generated_at: string
  filename: string
}

export interface CompanyInfo {
  company_name: string
  company_short_name: string
  it_department_name: string
  it_contact_name: string
  it_contact_email: string
}

export async function listMonthlyReports(): Promise<ReportItem[]> {
  const response = await request.get('/reports/monthly/list')
  return response.data
}

export async function generateMonthlyReport(year: number, month: number): Promise<{ message: string; filename: string; file_size: number }> {
  const response = await request.post('/reports/monthly/generate', null, {
    params: { year, month }
  })
  return response.data
}

export async function downloadMonthlyReport(year: number, month: number): Promise<Blob> {
  const response = await request.get(`/reports/monthly/download/${year}/${month}`, {
    responseType: 'blob'
  })
  return response.data
}

export async function deleteMonthlyReport(year: number, month: number): Promise<void> {
  await request.delete(`/reports/monthly/${year}/${month}`)
}

export interface ReportSchedule {
  enabled: boolean
  day: number      // 每月 1-28 号
  hour: number     // 0-23
  minute: number   // 0-59
  email_to: string // 留空只生成不发送
  channels: string[]      // email/dingtalk/wechat/feishu
  include_link: boolean   // 聊天消息附下载链接
  include_summary: boolean // 聊天消息附关键指标
  link_base_url: string   // 系统访问地址（生成下载链接）
}

export async function getReportSchedule(): Promise<ReportSchedule> {
  const response = await request.get('/reports/schedule')
  return response.data
}

export async function updateReportSchedule(config: ReportSchedule): Promise<ReportSchedule> {
  const response = await request.put('/reports/schedule', config)
  return response.data
}

export async function getCompanyInfo(): Promise<CompanyInfo> {
  const response = await request.get('/settings/company')
  return response.data
}

export async function updateCompanyInfo(info: CompanyInfo): Promise<{ message: string }> {
  const response = await request.put('/settings/company', info)
  return response.data
}