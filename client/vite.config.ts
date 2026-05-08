import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import path from 'path'
import { readFileSync } from 'fs'

const host = process.env.TAURI_DEV_HOST
const pkg = JSON.parse(readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'))

export default defineConfig(async () => ({
  define: {
    // 从 package.json 自动注入版本，避免硬编码 / VITE_CLIENT_VERSION env 漏配
    // sp-api ClientMetaMiddleware 用此 header 校验 MIN_CLIENT_VERSION
    'import.meta.env.VITE_CLIENT_VERSION': JSON.stringify(pkg.version),
  },
  plugins: [
    vue(),
    // Element Plus 按需 import：把 ElButton / ElMessage / ElMessageBox 等用到的组件 + 它们的 CSS
    // 自动注入到 build。配合 main.ts 移除全量 `app.use(ElementPlus)` + 全量 CSS import 后，
    // vendor-element-plus chunk 从 932 KB 砍到 < 200 KB（gzip 60-80 KB）。
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  // Tauri expects a fixed port, fail if that port is not available
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: 'ws',
          host,
          port: 5174,
        }
      : undefined,
    watch: {
      ignored: ['**/src-tauri/**'],
    },
  },
  build: {
    chunkSizeWarningLimit: 800,  // 单 chunk 警告阈值（kB），调高一点不被次要警告刷屏
    rollupOptions: {
      output: {
        // A2: 手动分块策略 — 拆 vendor 减小首屏 chunk
        // 之前 dist/assets/index-*.js 1.2MB（gzip 403KB），路由 dynamic import 已有但
        // vendor 都在主 bundle 里。拆完首屏只载用得到的 vendor。
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          // Vue 核心 + Pinia + Vue Router → 首屏必备
          if (
            id.includes('node_modules/vue/') ||
            id.includes('node_modules/@vue/') ||
            id.includes('node_modules/vue-router/') ||
            id.includes('node_modules/pinia/') ||
            id.includes('node_modules/@vueuse/')
          ) {
            return 'vendor-vue'
          }
          // Element Plus + 图标包 → 设置/项目页才会全量用
          if (
            id.includes('node_modules/element-plus/') ||
            id.includes('node_modules/@element-plus/')
          ) {
            return 'vendor-element-plus'
          }
          // Vis Network / Data → 知识图谱页才用，必须独立
          if (
            id.includes('node_modules/vis-network/') ||
            id.includes('node_modules/vis-data/') ||
            id.includes('node_modules/vis-util/')
          ) {
            return 'vendor-vis'
          }
          // Tauri 桥
          if (id.includes('node_modules/@tauri-apps/')) {
            return 'vendor-tauri'
          }
          // Markdown 渲染（笔记/对话气泡）
          if (
            id.includes('node_modules/markdown-it/') ||
            id.includes('node_modules/js-yaml/') ||
            id.includes('node_modules/entities/') ||
            id.includes('node_modules/linkify-it/') ||
            id.includes('node_modules/uc.micro/') ||
            id.includes('node_modules/mdurl/')
          ) {
            return 'vendor-markdown'
          }
          // axios + 网络相关
          if (
            id.includes('node_modules/axios/') ||
            id.includes('node_modules/follow-redirects/') ||
            id.includes('node_modules/form-data/')
          ) {
            return 'vendor-net'
          }
          // 其他 node_modules → 兜底 vendor
          return 'vendor-misc'
        },
      },
    },
  },
}))
