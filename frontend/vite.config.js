import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 后端地址：开发期通过 proxy 转发，避免跨域；生产期由 FastAPI 直接托管 dist
const BACKEND = 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/assets': { target: BACKEND, changeOrigin: true },
      '/health': { target: BACKEND, changeOrigin: true },
      '/metrics': { target: BACKEND, changeOrigin: true }
    }
  },
  build: {
    outDir: 'dist',
    // 后端已把素材目录挂载在 /assets（图片/视频），这里改用 app-assets 前缀避免静态资源路由冲突
    assetsDir: 'app-assets',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['vue', 'vue-router', 'pinia', 'axios']
        }
      }
    }
  }
})
