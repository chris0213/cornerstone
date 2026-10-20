import { createApp } from 'vue'
import App from './App.vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import './style.css'
import router from './app/router'
import { createPinia } from 'pinia'
import { useAppStore } from './store'
import { STORE_KEY, LEGACY_STORE_KEYS } from './store/seed'
import { setupPermissionDirective } from './lib/directives/permission'
import i18n from './i18n'
import { useLocaleStore } from './store/locale'

// Element Plus 语言映射
const elementLocales: Record<string, () => Promise<any>> = {
  'zh-CN': () => import('element-plus/es/locale/lang/zh-cn'),
  'en-US': () => import('element-plus/es/locale/lang/en')
}

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(i18n)

// 注册权限指令
setupPermissionDirective(app)

// 初始化语言设置
const localeStore = useLocaleStore()
localeStore.initialize()

// 跨标签页数据同步
if (typeof window !== 'undefined') {
  // 旧版本 store key 一次性清理：旧数据含已废弃的演示记录，迁移代价高于重置
  for (const legacyKey of LEGACY_STORE_KEYS) {
    localStorage.removeItem(legacyKey)
  }
  window.addEventListener('storage', (event) => {
    if (event.key === STORE_KEY && event.newValue) {
      try {
        const newState = JSON.parse(event.newValue)
        const store = useAppStore()
        store.$patch(newState)
        console.log('Data synchronized from another tab')
      } catch (e) {
        console.error('Failed to synchronize data from another tab:', e)
      }
    }
  })
}

// 注册 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 启动应用
async function bootstrap() {
  // 动态加载 Element Plus 语言并注册
  const localeModule = await elementLocales[i18n.global.locale.value as string]()
  app.use(ElementPlus, { locale: localeModule.default })
  
  // 挂载应用
  app.mount('#app')
}

bootstrap()
