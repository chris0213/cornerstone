/// <reference types="vitest" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import svgLoader from 'vite-svg-loader'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), svgLoader()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        // 后端端口 8000（与 scripts/dev.sh 的 BE_PORT 默认值保持一致）
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        ws: true,
        configure: (proxy, _options) => {
          proxy.on('proxyReqWs', (_proxyReq, _req, _socket, _options, _head) => {
            console.log('WebSocket proxy request:', _req.url)
          })
        }
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 拆分 vendor：element-plus / echarts 独立成 chunk，业务代码更新不再使第三方缓存失效；
        // 其余第三方库不强制归并（跟随引用它的懒加载页面各自成 chunk），避免被拉进首屏
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
          if (id.includes('element-plus')) return 'vendor-element-plus'
          const coreVendors = ['node_modules/vue/', 'node_modules/vue-router/', 'node_modules/pinia/', 'node_modules/vue-i18n/', 'node_modules/axios/']
          if (coreVendors.some((d) => id.includes(d))) return 'vendor'
          return undefined
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/lib/', 'src/store/', 'src/api/'],
    },
  },
})
