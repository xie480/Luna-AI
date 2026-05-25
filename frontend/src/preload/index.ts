/**
 * Electron 预加载脚本
 * 负责：在渲染进程暴露安全的 API 给主进程
 * 注意：预加载脚本运行在隔离的上下文中，通过 contextBridge 暴露有限接口
 */
import { contextBridge } from 'electron';

/**
 * 暴露给渲染进程的 API 接口
 * 通过 window.electronAPI 访问
 */
const electronAPI = {
  /**
   * 获取平台信息
   */
  getPlatform: (): string => process.platform,
};

// 通过 contextBridge 安全地暴露 API 给渲染进程
contextBridge.exposeInMainWorld('electronAPI', electronAPI);