/// <reference types="vitest" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import svgLoader from 'vite-svg-loader'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  // 仅生产构建移除 console.* 与 debugger（esbuild minify 复用此 transform 配置），
  // 防止错误信息与 token 泄漏到浏览器控制台；dev 模式保留便于调试
  esbuild: mode === 'production' ? { drop: ['console', 'debugger'] } : {},
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
    // 生产构建不生成 sourcemap：避免攻击者通过 .map 文件还原前端源码与 i18n key
    sourcemap: false,
    // 用 esbuild（Vite 内建）做压缩并移除 console/debugger；不选 terser，避免引入额外生产依赖
    minify: 'esbuild',
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
}))
