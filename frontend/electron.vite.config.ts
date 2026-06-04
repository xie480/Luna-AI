import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// 项目根目录（.env 文件所在位置）
const PROJECT_ROOT = path.resolve(__dirname, '..')

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()]
  },
  preload: {
    plugins: [externalizeDepsPlugin()]
  },
  renderer: {
    plugins: [react()],
    publicDir: path.resolve(__dirname, 'public'),
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    // 指定 .env 文件的查找目录为项目根目录
    // 使前端代码可以通过 import.meta.env.VITE_AI_SERVICE_PORT 读取端口配置
    envDir: PROJECT_ROOT,
  },
})