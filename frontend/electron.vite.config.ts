import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'
import path from 'path'

/**
 * Electron-Vite 配置文件
 * 
 * electron-vite 默认目录结构：
 * - src/main/index.ts -> 主进程入口
 * - src/preload/index.ts -> 预加载脚本入口
 * - src/renderer/index.html -> 渲染进程入口
 * 
 * 输出目录：
 * - out/main/index.js
 * - out/preload/index.js
 * - out/renderer/
 */
export default defineConfig({
  main: {
    // 不使用 externalizeDepsPlugin，让 electron 模块被正确打包
  },
  preload: {
    // 不使用 externalizeDepsPlugin
  },
  renderer: {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
  },
})