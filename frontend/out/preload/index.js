"use strict";
const electron = require("electron");
const electronAPI = {
  /**
   * 获取平台信息
   */
  getPlatform: () => process.platform,
  /**
   * 获取模型目录下的可配置文件列表（.exp3.json）
   * 返回去掉后缀的文件名数组
   */
  getModelConfigFiles: () => electron.ipcRenderer.invoke("get-model-config-files")
};
electron.contextBridge.exposeInMainWorld("electronAPI", electronAPI);
