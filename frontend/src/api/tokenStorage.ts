// 登录 token 存储助手
//
// 「记住我」的真实实现：
// - 勾选：token 存 localStorage（含 remember_me 标记），浏览器重启后仍保持登录
// - 不勾选：token 存 sessionStorage，关闭浏览器即退出
// 所有读取点统一走 getToken/getRefreshToken（localStorage 优先，兼容旧会话）。
const ACCESS_KEY = 'access_token'
const REFRESH_KEY = 'refresh_token'
const REMEMBER_KEY = 'remember_me'

export function getToken(): string | null {
  return localStorage.getItem(ACCESS_KEY) ?? sessionStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY) ?? sessionStorage.getItem(REFRESH_KEY)
}

export function isRemembered(): boolean {
  return localStorage.getItem(REMEMBER_KEY) === '1'
}

export function setTokens(access: string, refresh: string | null | undefined, remember: boolean): void {
  clearTokens()
  const store = remember ? localStorage : sessionStorage
  store.setItem(ACCESS_KEY, access)
  store.setItem(REFRESH_KEY, refresh || '')
  if (remember) {
    localStorage.setItem(REMEMBER_KEY, '1')
  }
}

export function clearTokens(): void {
  for (const store of [localStorage, sessionStorage]) {
    store.removeItem(ACCESS_KEY)
    store.removeItem(REFRESH_KEY)
  }
  localStorage.removeItem(REMEMBER_KEY)
}
