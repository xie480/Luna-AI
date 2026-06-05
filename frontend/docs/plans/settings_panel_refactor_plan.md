# 设置面板重构与功能扩展设计方案

## 1. 需求背景与目标
根据最新的 UI 设计与功能需求，现有的设置面板需要进行全面重构。目标是提供一个尺寸更大、结构更清晰（侧边栏导航）、功能更丰富的设置中心。

核心目标包括：
1. **扩大面板尺寸**：提供更宽敞的配置空间。
2. **侧边栏导航布局**：将设置项分类为“通用”、“API”和“环境配置”。
3. **通用设置**：包含 Live2D 渲染开关（持久化）和主题切换（默认暗色，支持亮色，持久化）。
4. **API 设置**：独立承载现有的 API 配置功能。
5. **环境配置**：支持纯前端读取、热修改本地 `.env` 文件，包含变更检测、重置、自定义确认弹窗以及保存后自动重启软件的完整闭环。

## 2. 架构与技术方案

### 2.1 IPC 通信层扩展 (主进程与预加载脚本)
由于纯前端（渲染进程）受限于浏览器安全沙箱，无法直接读写本地文件或控制应用重启，必须通过 Electron 的 IPC 机制实现。
需要在 `frontend/src/main/index.ts` 中新增以下 IPC 处理器，并在 `frontend/src/preload/index.ts` 中暴露给渲染进程：
- `read-env-file`: 读取项目根目录下的 `.env` 文件内容。
- `write-env-file`: 将修改后的内容写入项目根目录下的 `.env` 文件。
- `restart-app`: 调用 `app.relaunch()` 和 `app.exit(0)` 实现软件重启。

### 2.2 状态管理扩展 (`systemStore.ts`)
在 `useSystemStore` 中新增以下状态，并实现基于 `localStorage` 的持久化：
- `isLive2dEnabled`: boolean，默认 true。控制 Live2D 模型的渲染。
- `theme`: 'dark' | 'light'，默认 'dark'。控制全局主题。

### 2.3 UI 组件拆分与重构
重构 `frontend/src/renderer/components/Settings/SettingsPanel.tsx`，引入侧边栏布局。

#### 2.3.1 `SettingsPanel` (主容器)
- 维护当前激活的选项卡状态 (`activeTab`)。
- 左侧渲染导航菜单（通用、API、环境配置）。
- 右侧根据 `activeTab` 动态渲染对应的子组件。

#### 2.3.2 `GeneralSettings` (通用设置组件)
- **Live2D 渲染开关**：使用 Switch/Toggle UI 组件，绑定 `systemStore.isLive2dEnabled`。
- **主题切换**：使用 Select 或 Radio Group，绑定 `systemStore.theme`。切换时动态修改 `document.body` 的 class 或 data 属性以应用 CSS 变量。

#### 2.3.3 `ApiSettings` (API 设置组件)
- 直接引入并包裹现有的 `ApiConfigPresetPanel` 组件。

#### 2.3.4 `EnvSettings` (环境配置组件)
- **状态管理**：维护 `originalContent` 和 `currentContent`。
- **UI 布局**：
  - 顶部操作栏：包含“重置”和“保存”按钮。通过对比 `originalContent` 和 `currentContent` 决定是否显示。
  - 编辑区：使用 `<textarea>` 或简单的代码编辑器组件展示和编辑 `.env` 内容。
- **交互逻辑**：
  - 初始化时调用 `window.electronAPI.readEnvFile()` 获取内容。
  - 点击“重置”：将 `currentContent` 恢复为 `originalContent`。
  - 点击“保存”：弹出自定义确认弹窗（非系统原生 `window.confirm`，需使用 React 组件实现）。
  - 弹窗确认后：调用 `window.electronAPI.writeEnvFile()`，成功后调用 `window.electronAPI.restartApp()`。

### 2.4 样式调整
- 修改 `Modal.tsx` 中 `getDefaultSize` 方法，针对 `settings` 面板返回更大的默认尺寸（例如 `{ w: 900, h: 600 }`）。
- 编写 `SettingsPanel.css`，实现侧边栏布局（Flexbox 或 Grid），以及各子组件的样式。

## 3. 实施步骤

1. **扩展 IPC 接口**：修改主进程和预加载脚本，提供读写 `.env` 和重启应用的能力。
2. **更新状态管理**：在 `systemStore` 中增加 Live2D 开关和主题状态及持久化逻辑。
3. **调整模态窗口尺寸**：修改 `Modal.tsx`，增大设置面板的默认尺寸。
4. **开发子组件**：分别实现 `GeneralSettings`、`ApiSettings` 和 `EnvSettings` 组件及自定义确认弹窗。
5. **重构主面板**：修改 `SettingsPanel.tsx`，实现侧边栏导航和路由切换逻辑，并编写配套 CSS。
6. **联调与测试**：验证各项配置的持久化、`.env` 文件的热修改及重启逻辑。