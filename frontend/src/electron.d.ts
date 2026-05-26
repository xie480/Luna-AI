/**
 * Electron API 全局类型声明
 * 定义 window.electronAPI 接口，供渲染进程使用
 */
interface ElectronAPI {
  /** 获取平台信息 */
  getPlatform: () => string;
  /** 获取模型目录下的 .exp3.json 配置文件列表（去掉后缀的文件名） */
  getModelConfigFiles: () => Promise<string[]>;
}

interface Window {
  electronAPI: ElectronAPI;
}
