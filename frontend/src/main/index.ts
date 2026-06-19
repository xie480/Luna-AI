/**
 * Electron 主进程入口
 * 负责：窗口创建、系统托盘、系统能力桥接
 * 注意：主进程禁止直接访问本地 DB、Redis、Python 服务
 */
import { app, BrowserWindow, ipcMain, shell, protocol } from 'electron';
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
    // .env 文件路径: 项目根目录 / 可执行文件同级目录
    // 开发环境: __dirname 为 out/main，向上三级到项目根目录（f:/YilenaCode/Luna-AI）
    //    out/main -> out -> frontend -> 项目根目录
    // 生产环境: 可执行文件同级目录
    let envPath: string;
    if (process.env.NODE_ENV === 'development') {
      envPath = path.resolve(__dirname, '../../../.env');
    } else {
      envPath = path.join(process.resourcesPath, '.env');
    }

    if (!fs.existsSync(envPath)) {
      return null;
    }

    const content = fs.readFileSync(envPath, 'utf-8');
    return content;
  });

  ipcMain.handle('write-env-file', async (_, content: string) => {
    let envPath: string;
    if (process.env.NODE_ENV === 'development') {
      envPath = path.resolve(__dirname, '../../../.env');
    } else {
      envPath = path.join(process.resourcesPath, '.env');
    }

    if (!fs.existsSync(envPath)) {
      return false;
    }

    fs.writeFileSync(envPath, content, 'utf-8');
    return true;
  });

  ipcMain.handle('restart-app', () => {
    app.relaunch();
    app.exit(0);
  });

  ipcMain.handle('open-external', async (_, externalUrl: string) => {
    // 在外部浏览器中打开链接，用于"查看源代码"等功能
    if (externalUrl && typeof externalUrl === 'string') {
      await shell.openExternal(externalUrl);
    }
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

/**
 * MIME 类型映射表，根据文件扩展名返回对应的 Content-Type。
 *
 * 做什么：根据音频文件扩展名返回标准 MIME 类型，确保浏览器正确解码音频。
 * 为什么这样做：不同音频格式需要不同的 MIME 类型才能被浏览器正确识别和播放。
 * 输入输出：输入文件扩展名（如 ".mp3"），输出 MIME 类型字符串。
 * 边界条件：未知扩展名返回 application/octet-stream 作为兜底。
 */
function getMimeType(ext: string): string {
  const mimeMap: Record<string, string> = {
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.ogg': 'audio/ogg',
    '.flac': 'audio/flac',
    '.aac': 'audio/aac',
    '.m4a': 'audio/mp4',
    '.webm': 'audio/webm',
  };
  return mimeMap[ext.toLowerCase()] || 'application/octet-stream';
}

/**
 * 注册自定义协议拦截器，用于读取后端生成的本地 TTS 音频。
 *
 * 做什么：拦截 luna:// 协议的 HTTP 请求，将 TTS 音频文件从后端缓存目录
 *         （backend/ai-service/data/tts_cache）以正确的 MIME 类型返回给渲染进程。
 * 为什么这样做：使用自定义协议可以避免跨域问题。使用 fs.readFileSync 直接读取
 *              本地文件比 net.fetch(file://) 更可靠，Windows 下 file:// 协议
 *              的 fetch 存在兼容性问题。同时设置正确的 MIME 类型确保浏览器正确解码。
 *
 * 修复说明（2026-06-18）：
 *   - 路径修正：app.getAppPath() 在开发环境返回 frontend 目录，../../backend 会跳到
 *               项目外（f:/YilenaCode/backend），修正为 ../backend（f:/YilenaCode/Luna-AI/backend）
 *   - 读取方式：net.fetch(file://) → fs.readFileSync()，解决 Windows 下自定义协议
 *               中 file:// fetch 返回空/错误响应的问题
 *   - MIME 类型：新增 Content-Type 响应头，让浏览器正确识别 mp3/wav 格式
 *
 * 输入输出：
 *   - 输入：luna://tts/{filename} 格式的 URL
 *   - 输出：包含音频二进制数据的 Response 对象，或 404/403 错误
 * 边界条件：
 *   - 路径穿越检查：验证解析出的绝对路径必须位于 ttsCacheDir 内
 *   - 文件不存在时返回 404
 *   - URL host 不为 tts 时（如 luna://other/xxx）返回 404
 */
function registerCustomProtocols(): void {
  protocol.handle('luna', async (request) => {
    // request.url 例如: "luna://tts/tts_123.wav"
    const parsedUrl = new URL(request.url);
    if (parsedUrl.host === 'tts') {
      const fileName = parsedUrl.pathname.replace(/^\//, ''); // 去除前导斜杠
      // Python AI service 将文件存放在 backend/ai-service/data/tts_cache
      // 开发环境下，app.getAppPath() 返回 frontend 目录，所以需要 ../backend
      // 生产环境下使用相对路径基于 app.getAppPath() 调整。
      const ttsCacheDir = path.resolve(app.getAppPath(), '../backend/ai-service/data/tts_cache');
      const absolutePath = path.join(ttsCacheDir, fileName);

      // 出于安全考虑，验证解析出的路径是否仍在预期的缓存目录内（防止目录穿越）
      if (!absolutePath.startsWith(ttsCacheDir)) {
        return new Response('Access Denied', { status: 403 });
      }

      // 使用 fs.readFileSync 直接读取本地文件并构造 Response，
      // 同时设置正确的 Content-Type 以便浏览器正确解码音频。
      try {
        const data = fs.readFileSync(absolutePath);
        const ext = path.extname(fileName);
        const mimeType = getMimeType(ext);
        return new Response(data, {
          status: 200,
          headers: { 'Content-Type': mimeType },
        });
      } catch (_err) {
        return new Response('File Not Found', { status: 404 });
      }
    }
    return new Response('Not Found', { status: 404 });
  });
}

// 必须在 app ready 之前注册 scheme 为 privileged（允许绕过跨域、媒体等限制）
protocol.registerSchemesAsPrivileged([
  { scheme: 'luna', privileges: { bypassCSP: true, stream: true, supportFetchAPI: true, corsEnabled: true } }
]);

// 当 Electron 完成初始化后创建窗口
app.whenReady().then(() => {
  registerCustomProtocols();
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
