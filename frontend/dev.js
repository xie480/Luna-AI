/**
 * Electron 开发环境启动脚本
 * 解决 ELECTRON_RUN_AS_NODE 环境变量导致 Electron 以 Node.js 模式运行的问题
 */
const { spawnSync } = require('child_process');

// 删除 ELECTRON_RUN_AS_NODE 环境变量，确保 Electron 以正常模式运行
delete process.env.ELECTRON_RUN_AS_NODE;

// 显式传递清理后的环境变量给子进程
spawnSync('npx', ['electron-vite', 'dev'], { 
  stdio: 'inherit', 
  shell: true,
  env: process.env  // 显式传递清理后的环境变量
});