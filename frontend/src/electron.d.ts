/**
 * Electron API 全局类型声明
 * 定义 window.electronAPI 接口，供渲染进程使用
 */
interface ElectronAPI {
  /** 获取平台信息 */
  getPlatform: () => string;
  /** 获取模型目录下的 .exp3.json 配置文件列表（去掉后缀的文件名） */
  getModelConfigFiles: () => Promise<string[]>;
  /** 读取 .env 文件内容 */
  readEnvFile: () => Promise<string>;
  /** 写入 .env 文件内容 */
  writeEnvFile: (content: string) => Promise<boolean>;
  /** 重启应用 */
  restartApp: () => Promise<void>;
}

interface Window {
  electronAPI: ElectronAPI;
}
