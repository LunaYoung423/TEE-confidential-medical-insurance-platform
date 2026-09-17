import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    // ECS/局域网用公网或内网 IP 访问时须监听 0.0.0.0（等价于 npm run dev -- --host）
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8080', // 后端控制器地址
        changeOrigin: true
      }
    }
  }
})