/**
 * 告警实时推送 WebSocket 单例
 *
 * - 登录后建立连接，断线 3 秒后自动重连
 * - 收到新告警时以自定义事件 `alert:new` 向 window 派发，
 *   任意组件监听即可响应（App 弹通知、预警页刷新列表）
 */

let socket: WebSocket | null = null
let retryTimer: number | null = null
let started = false

function getAccessToken(): string | null {
  return localStorage.getItem('access_token')
}

function buildUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = getAccessToken() || ''
  return `${proto}//${window.location.host}/api/v1/alerts/ws?token=${encodeURIComponent(token)}`
}

function scheduleReconnect() {
  if (!started) return
  if (retryTimer !== null) window.clearTimeout(retryTimer)
  retryTimer = window.setTimeout(connect, 3000)
}

function connect() {
  if (!started || socket) return
  if (!getAccessToken()) {
    // 未登录：等登录后由 startAlertSocket 重新调起
    started = false
    return
  }

  try {
    socket = new WebSocket(buildUrl())
  } catch {
    scheduleReconnect()
    return
  }

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data?.type === 'new_alert') {
        window.dispatchEvent(new CustomEvent('alert:new', { detail: data }))
      }
    } catch {
      // 非 JSON 消息（如 error 文本）忽略
    }
  }

  socket.onclose = () => {
    socket = null
    scheduleReconnect()
  }

  socket.onerror = () => {
    // 交给 onclose 统一重连
  }
}

/** 启动推送（登录后调用；重复调用幂等） */
export function startAlertSocket() {
  if (started) return
  started = true
  connect()
}

/** 停止推送（登出时调用，不再重连） */
export function stopAlertSocket() {
  started = false
  if (retryTimer !== null) {
    window.clearTimeout(retryTimer)
    retryTimer = null
  }
  if (socket) {
    socket.onclose = null
    socket.close()
    socket = null
  }
}

/** 订阅新告警；返回取消订阅函数 */
export function onNewAlert(handler: (detail: any) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent).detail)
  window.addEventListener('alert:new', listener)
  return () => window.removeEventListener('alert:new', listener)
}
