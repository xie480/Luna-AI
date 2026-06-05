/**
 * Electron 主进程入口
 * 负责：窗口创建、系统托盘、系统能力桥接
 * 注意：主进程禁止直接访问本地 DB、Redis、Python 服务
 */
import { app, BrowserWindow, ipcMain } from 'electron';
import path from 'path';
import fs from 'fs';

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

/**
 * 注册 IPC 处理器，用于渲染进程请求读取模型目录下的可配置 JSON 文件
 * 返回去掉路径和扩展名的文件名列表
 */
function registerIpcHandlers(): void {
  ipcMain.handle('read-env-file', async () => {
    let envPath: string;
    if (process.env.NODE_ENV === 'development') {
      envPath = path.resolve(app.getAppPath(), '../.env');
    } else {
      envPath = path.resolve(process.resourcesPath, '../../.env');
    }
    
    if (fs.existsSync(envPath)) {
      return fs.readFileSync(envPath, 'utf-8');
    }
    return '';
  });

  ipcMain.handle('write-env-file', async (_, content: string) => {
    let envPath: string;
    if (process.env.NODE_ENV === 'development') {
      envPath = path.resolve(app.getAppPath(), '../.env');
    } else {
      envPath = path.resolve(process.resourcesPath, '../../.env');
    }
    
    fs.writeFileSync(envPath, content, 'utf-8');
    return true;
  });

  ipcMain.handle('restart-app', () => {
    app.relaunch();
    app.exit(0);
  });

  ipcMain.handle('get-model-config-files', async () => {
    // 模型目录相对于应用根目录，开发环境下是 public/models/luna
    // 生产环境下是 exe 同级的 resources/models/luna
    let modelsDir: string;

    if (process.env.NODE_ENV === 'development') {
      // 开发环境：从项目根目录的 public/models/luna 读取
      // __dirname 在 dev 环境下指向 src/main
      modelsDir = path.resolve(__dirname, '../../public/models/luna');
    } else {
      // 生产环境：从 resources/models/luna 读取
      modelsDir = path.resolve(process.resourcesPath, 'models/luna');
    }

    // 如果目录不存在，尝试备用路径
    if (!fs.existsSync(modelsDir)) {
      // 备用：尝试从 app 根目录查找
      modelsDir = path.resolve(__dirname, '../../models/luna');
    }

    if (!fs.existsSync(modelsDir)) {
      return [];
    }

    const files = fs.readdirSync(modelsDir);

    // 只返回 .exp3.json 文件，去掉 ".exp3.json" 后缀
    const configFiles = files
      .filter((f) => f.endsWith('.exp3.json'))
      .map((f) => f.replace(/\.exp3\.json$/, ''))
      .sort(); // 排序保持列表顺序稳定

    return configFiles;
  });
}

// 当 Electron 完成初始化后创建窗口
app.whenReady().then(() => {
  registerIpcHandlers();
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
