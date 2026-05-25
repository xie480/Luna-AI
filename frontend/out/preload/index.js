"use strict";
const electron = require("electron");
const electronAPI = {
  /**
   * 获取平台信息
   */
  getPlatform: () => process.platform
};
electron.contextBridge.exposeInMainWorld("electronAPI", electronAPI);
