/**
 * 知识库阅读端显示设置单元测试
 *
 * 覆盖三层：
 * 1. DisplaySettings.vue 面板组件（渲染 / 交互 / 双实例共享单例）
 * 2. displaySettings.ts 存储模块（默认值 / 部分合并 / 损坏兜底 / 持久化 / 存储异常）
 * 3. i18n key 完整性（zh-CN 与 en-US 同步，防止漂移）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import DisplaySettings from './DisplaySettings.vue'
import { kbDisplaySettings, DISPLAY_DEFAULTS, TEXT_COLORS } from './displaySettings'
import { i18n } from '../../i18n'
import zhCN from '../../locales/zh-CN.json'
import enUS from '../../locales/en-US.json'

const STORAGE_KEY = 'kb_display_settings'

function mountPanel(): VueWrapper {
  return mount(DisplaySettings, {
    global: { plugins: [ElementPlus, i18n] },
  })
}

/** 点击指定文案的字号/字体/主题单选按钮（通过内部 radio input 触发 change） */
async function clickRadio(wrapper: VueWrapper, text: string) {
  const btn = wrapper.findAll('.el-radio-button').find(w => w.text() === text)
  expect(btn, `找不到单选项「${text}」`).toBeTruthy()
  await btn!.find('input').setValue()
  await flushPromises()
}

function storedValue(): Record<string, unknown> | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  return raw ? JSON.parse(raw) : null
}

// ════════ 1. 面板组件 ════════
describe('DisplaySettings 面板组件', () => {
  beforeEach(() => {
    localStorage.clear()
    Object.assign(kbDisplaySettings, DISPLAY_DEFAULTS)
  })

  it('渲染四组设置标签（i18n 中文）', () => {
    const wrapper = mountPanel()
    const text = wrapper.find('.kb-display-settings').text()
    expect(text).toContain('字号')
    expect(text).toContain('字体')
    expect(text).toContain('阅读配色')
    expect(text).toContain('文字颜色')
  })

  it('色板渲染 5 个按钮，「自动」为空值默认选中', async () => {
    const wrapper = mountPanel()
    await nextTick()
    const colors = wrapper.findAll('.ds-color')
    expect(colors).toHaveLength(5)
    expect(colors[0].classes('active')).toBe(true)
    // 空值按钮用渐变占位背景
    expect(colors[0].attributes('style')).toContain('linear-gradient')
  })

  it('点击「大」更新设置并持久化 fontSize=large', async () => {
    const wrapper = mountPanel()
    await clickRadio(wrapper, '大')
    expect(kbDisplaySettings.fontSize).toBe('large')
    expect(storedValue()).toMatchObject({ fontSize: 'large' })
  })

  it('点击第 4 个色板持久化 color=#1e5eff，active 状态迁移', async () => {
    const wrapper = mountPanel()
    await nextTick()
    const colors = wrapper.findAll('.ds-color')
    await colors[3].trigger('click')
    await flushPromises()
    expect(kbDisplaySettings.color).toBe('#1e5eff')
    expect(storedValue()).toMatchObject({ color: '#1e5eff' })
    expect(colors[3].classes('active')).toBe(true)
    expect(colors[0].classes('active')).toBe(false)
  })

  it('两个面板实例共享同一单例状态', async () => {
    const w1 = mountPanel()
    const w2 = mountPanel()
    await nextTick()
    await clickRadio(w1, '夜间')
    expect(kbDisplaySettings.theme).toBe('dark')
    expect(w2.findAll('.el-radio-button').find(w => w.text() === '夜间')!.classes('is-active')).toBe(true)
  })

  it('主题单选持久化 theme=sepia', async () => {
    const wrapper = mountPanel()
    await clickRadio(wrapper, '护眼')
    expect(storedValue()).toMatchObject({ theme: 'sepia' })
  })
})

// ════════ 2. 存储模块逻辑（动态导入隔离） ════════
describe('displaySettings 存储模块', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  async function freshModule() {
    return await import('./displaySettings')
  }

  it('TEXT_COLORS：5 色、首项自动空值、labelKey 均为 knowledge.dsColor*', () => {
    expect(TEXT_COLORS).toHaveLength(5)
    expect(TEXT_COLORS[0]).toMatchObject({ value: '', labelKey: 'knowledge.dsColorAuto' })
    for (const c of TEXT_COLORS) {
      expect(c.labelKey.startsWith('knowledge.dsColor')).toBe(true)
    }
  })

  it('默认值：中号 / 默认字体 / 明亮 / 自动颜色', () => {
    expect(DISPLAY_DEFAULTS).toEqual({
      fontSize: 'medium',
      fontFamily: 'default',
      theme: 'light',
      color: '',
    })
  })

  it('无存储时加载默认值', async () => {
    const m = await freshModule()
    expect(m.kbDisplaySettings).toMatchObject(DISPLAY_DEFAULTS)
  })

  it('从 localStorage 加载已有值', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ fontSize: 'small', theme: 'dark' }))
    const m = await freshModule()
    expect(m.kbDisplaySettings).toMatchObject({ fontSize: 'small', theme: 'dark' })
  })

  it('部分存储字段与默认值合并', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ fontSize: 'large' }))
    const m = await freshModule()
    expect(m.kbDisplaySettings).toMatchObject({
      fontSize: 'large',
      fontFamily: 'default',
      theme: 'light',
      color: '',
    })
  })

  it('损坏 JSON 回退默认值', async () => {
    localStorage.setItem(STORAGE_KEY, '{broken json')
    const m = await freshModule()
    expect(m.kbDisplaySettings).toMatchObject(DISPLAY_DEFAULTS)
  })

  it('修改设置自动持久化到 localStorage', async () => {
    const m = await freshModule()
    m.kbDisplaySettings.fontSize = 'large'
    m.kbDisplaySettings.color = '#0a7d43'
    await nextTick()
    expect(storedValue()).toMatchObject({ fontSize: 'large', color: '#0a7d43' })
  })

  it('存储写入抛异常不影响使用', async () => {
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })
    try {
      const m = await freshModule()
      m.kbDisplaySettings.theme = 'dark'
      await flushPromises()
      expect(m.kbDisplaySettings.theme).toBe('dark')
    } finally {
      spy.mockRestore()
    }
  })
})

// ════════ 3. i18n key 完整性 ════════
describe('显示设置 i18n key 完整性', () => {
  const EXPECTED_KEYS = [
    'displaySettings', 'dsFontSize', 'dsFontSmall', 'dsFontMedium', 'dsFontLarge',
    'dsFontFamily', 'dsFontDefault', 'dsFontSerif', 'dsFontMono',
    'dsTheme', 'dsThemeLight', 'dsThemeSepia', 'dsThemeDark',
    'dsTextColor', 'dsColorAuto', 'dsColorInk', 'dsColorGray', 'dsColorBlue', 'dsColorGreen',
  ]

  it('zh-CN 与 en-US 的 knowledge 段均包含全部 key 且非空', () => {
    for (const [name, messages] of [['zh-CN', zhCN], ['en-US', enUS]] as const) {
      const knowledge = (messages as Record<string, any>).knowledge
      for (const key of EXPECTED_KEYS) {
        expect(typeof knowledge[key], `${name}.knowledge.${key} 缺失`).toBe('string')
        expect((knowledge[key] as string).length, `${name}.knowledge.${key} 为空`).toBeGreaterThan(0)
      }
    }
  })

  it('TEXT_COLORS 引用的 labelKey 全部存在于两个语言包', () => {
    const zh = (zhCN as Record<string, any>).knowledge
    const en = (enUS as Record<string, any>).knowledge
    for (const c of TEXT_COLORS) {
      const key = c.labelKey.split('.')[1]
      expect(zh[key], `zh-CN 缺 ${key}`).toBeTruthy()
      expect(en[key], `en-US 缺 ${key}`).toBeTruthy()
    }
  })
})
