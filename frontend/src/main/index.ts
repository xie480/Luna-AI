/**
 * Electron 主进程入口
 * 负责：窗口创建、系统托盘、系统能力桥接
 * 注意：主进程禁止直接访问本地 DB、Redis、Python 服务
 */
import { app, BrowserWindow } from 'electron';
import path from 'path';

// 主窗口引用
let mainWindow: BrowserWindow | null = null;

/**
 * 创建主窗口
 * 设置最小窗口尺寸，加载渲染进程入口页面
 */
function createWindow(): void {
  mainWindow = new BrowserWindow({
    show: false, // 先隐藏窗口，等待最大化后再显示，避免视觉闪烁
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      // electron-vite 会将 preload 编译到 out/preload/index.js
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    title: 'Luna AI',
    // 设置窗口图标（可选，根据平台配置）
    // icon: path.join(__dirname, '../../resources/icon.png'),
  });

  // 推荐使用最大化（保留 Windows/macOS 任务栏）
  mainWindow.maximize();
  mainWindow.show();

  // 开发环境加载 Vite 开发服务器，生产环境加载打包后的文件
  // vite-plugin-electron 会自动设置 NODE_ENV
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    // 生产环境加载打包后的 index.html
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// 当 Electron 完成初始化后创建窗口
app.whenReady().then(() => {
  createWindow();

  // macOS: 点击 dock 图标时如果没有窗口则重新创建
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// 所有窗口关闭时退出应用（macOS 除外）
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
