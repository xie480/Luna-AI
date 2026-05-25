import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    electron([
      {
        // 主进程入口文件
        entry: 'src/main/index.ts',
        onstart(options) {
          // 主进程启动时的回调
          options.startup()
        },
        vite: {
          build: {
            outDir: 'dist/main',
            sourcemap: true,
            rollupOptions: {
              output: {
                format: 'cjs',
                entryFileNames: '[name].js',
              },
            },
          },
        },
      },
      {
        // 预加载脚本入口文件
        entry: 'src/main/preload.ts',
        onstart(options) {
          // 预加载脚本重新加载时通知渲染进程
          options.reload()
        },
        vite: {
          build: {
            outDir: 'dist/main',
            sourcemap: true,
            rollupOptions: {
              output: {
                format: 'cjs',
                entryFileNames: '[name].js',
              },
            },
          },
        },
      },
    ]),
  ],
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