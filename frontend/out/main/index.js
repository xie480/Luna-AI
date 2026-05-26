"use strict";
const electron = require("electron");
const path = require("path");
const fs = require("fs");
let mainWindow = null;
function createWindow() {
  mainWindow = new electron.BrowserWindow({
    show: false,
    // 先隐藏窗口，等待最大化后再显示，避免视觉闪烁
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      // electron-vite 会将 preload 编译到 out/preload/index.js
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false
    },
    title: "Luna AI"
    // 设置窗口图标（可选，根据平台配置）
    // icon: path.join(__dirname, '../../resources/icon.png'),
  });
  mainWindow.maximize();
  mainWindow.show();
  if (process.env.NODE_ENV === "development") {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}
function registerIpcHandlers() {
  electron.ipcMain.handle("get-model-config-files", async () => {
    let modelsDir;
    if (process.env.NODE_ENV === "development") {
      modelsDir = path.resolve(__dirname, "../../public/models/luna");
    } else {
      modelsDir = path.resolve(process.resourcesPath, "models/luna");
    }
    if (!fs.existsSync(modelsDir)) {
      modelsDir = path.resolve(__dirname, "../../models/luna");
    }
    if (!fs.existsSync(modelsDir)) {
      return [];
    }
    const files = fs.readdirSync(modelsDir);
    const configFiles = files.filter((f) => f.endsWith(".exp3.json")).map((f) => f.replace(/\.exp3\.json$/, "")).sort();
    return configFiles;
  });
}
electron.app.whenReady().then(() => {
  registerIpcHandlers();
  createWindow();
  electron.app.on("activate", () => {
    if (electron.BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});
electron.app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    electron.app.quit();
  }
});
