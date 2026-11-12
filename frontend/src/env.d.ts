/// <reference types="vite/client" />

// Allow importing SVG files as Vue components via vite-svg-loader
declare module '*.svg?component' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

// 构建期注入的版本标识（见 vite.config.ts 的 define）
declare const __APP_VERSION__: string
declare const __BUILD_TIME__: string
