import { reactive, watch } from 'vue'

export interface KbDisplaySettings {
  fontSize: 'small' | 'medium' | 'large'
  fontFamily: 'default' | 'serif' | 'mono'
  theme: 'light' | 'sepia' | 'dark'
  color: string
}

export const DISPLAY_DEFAULTS: KbDisplaySettings = {
  fontSize: 'medium',
  fontFamily: 'default',
  theme: 'light',
  color: '',
}

export const TEXT_COLORS = [
  { value: '', labelKey: 'knowledge.dsColorAuto' },
  { value: '#1f2d3d', labelKey: 'knowledge.dsColorInk' },
  { value: '#4a5568', labelKey: 'knowledge.dsColorGray' },
  { value: '#1e5eff', labelKey: 'knowledge.dsColorBlue' },
  { value: '#0a7d43', labelKey: 'knowledge.dsColorGreen' },
]

const STORAGE_KEY = 'kb_display_settings'

function load(): KbDisplaySettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...DISPLAY_DEFAULTS, ...JSON.parse(raw) }
  } catch {
    /* 损坏数据回退默认 */
  }
  return { ...DISPLAY_DEFAULTS }
}

// 模块级单例：阅读弹窗与编辑器预览两个面板实例共享同一份设置
export const kbDisplaySettings = reactive<KbDisplaySettings>(load())

watch(kbDisplaySettings, (val) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(val))
  } catch {
    /* 存储失败不影响使用 */
  }
}, { deep: true })
