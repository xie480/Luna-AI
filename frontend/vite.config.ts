import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  base: './',
  test: {
    // 使用 jsdom 模拟浏览器环境
    environment: 'jsdom',
    // 包含测试文件的 glob 模式
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
