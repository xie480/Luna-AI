# 前端侧边栏与模态窗口交互重构方案

## 1. 目标
- 实现类似 ChatGPT 的左侧边栏动态收缩/展开效果。
- 废弃原有的右侧边栏弹出逻辑。
- 点击左侧边栏菜单项时，在屏幕正中央弹出模态窗口（Modal）展示对应内容（任务流、记忆、设置、日志）。

## 2. 状态管理调整 (`systemStore.ts`)
- **移除状态**: `isSidebarOpen`, `activeSidebarPanel`
- **移除方法**: `openSidebar`, `closeSidebar`, `toggleSidebar`
- **新增状态**:
  - `isLeftSidebarOpen`: boolean (控制左侧边栏展开/收起，默认 false)
  - `isModalOpen`: boolean (控制居中模态窗口显示/隐藏，默认 false)
  - `activeModalPanel`: `'dag' | 'memory' | 'settings' | 'logs' | null` (当前模态窗口展示的面板)
- **新增方法**:
  - `toggleLeftSidebar`: () => void
  - `openLeftSidebar`: () => void
  - `closeLeftSidebar`: () => void
  - `openModal`: (panel: ModalPanelType) => void
  - `closeModal`: () => void

## 3. 组件调整明细

### 3.1 `SidebarTrigger` 组件重构
- 位置固定在页面左上角，作为左侧边栏的展开/收起开关。
- 仅触发 `toggleLeftSidebar`，不再展示子菜单。
- 图标在展开/收起状态间切换（汉堡 ↔ X），并随侧栏移动。

### 3.2 `Sidebar` 组件重构 (左侧边栏)
- 固定在页面左侧，使用 `width` 动画实现平滑展开/收起。
- 只渲染导航按钮（任务流、记忆、设置、日志）。
- 点击按钮调用 `openModal(panel)`，打开居中模态窗口。

### 3.3 新增 `Modal` 组件 (居中模态窗口)
- 采用遮罩层 `.modal-overlay` 与居中容器 `.modal-container`。
- 根据 `isModalOpen` 与 `activeModalPanel` 渲染对应面板内容（复用原 Sidebar 中的 DAG、记忆、设置、日志 UI）。
- 支持点击遮罩层或右上角关闭按钮关闭。

### 3.4 `App` 组件 (`index.tsx`) 调整
- 引入并挂载 `Modal` 组件。
- `main-content` 根据 `isLeftSidebarOpen` 动态设置 `margin-left`，实现侧栏展开时页面内容平滑移动。

## 4. 状态流转说明
1. **展开/收起侧边栏**: 用户点击左上角 Trigger → 调用 `toggleLeftSidebar` → `isLeftSidebarOpen` 状态翻转 → 左侧边栏 CSS 动画执行。  
2. **打开功能面板**: 用户点击左侧边栏内的菜单项（如 “记忆”） → 调用 `openModal('memory')` → `isModalOpen` 设为 `true`，`activeModalPanel` 设为 `'memory'` → `Modal` 组件渲染并展示记忆面板内容。  
3. **关闭功能面板**: 用户点击 Modal 关闭按钮或遮罩层 → 调用 `closeModal()` → `isModalOpen` 设为 `false` → Modal 消失。

## 5. 具体代码变更细节

- **`frontend/src/renderer/stores/systemStore.ts`**
  - 替换原有的侧边栏状态与方法，新增左侧栏和模态窗口相关状态与 actions（`isLeftSidebarOpen`, `isModalOpen`, `activeModalPanel`, `toggleLeftSidebar`, `openModal`, `closeModal` 等）。
  - 引入 `ModalPanelType` 类型定义。

- **`frontend/src/renderer/components/Modal/Modal.tsx`**（新建）
  - 实现模态窗口的渲染逻辑，包含遮罩层点击关闭、标题栏、关闭按钮以及根据 `activeModalPanel` 渲染 DAG、记忆、设置、日志四个子面板。

- **`frontend/src/renderer/components/Modal/Modal.css`**（新建）
  - 定义 `.modal-overlay`, `.modal-container`, `.modal-header`, `.modal-close`, `.modal-content` 等样式以及动画 `fadeIn`、`scaleIn`。

- **`frontend/src/renderer/components/Sidebar/Sidebar.tsx`**（修改）
  - 重构为左侧导航栏，仅保留菜单按钮列表。
  - 移除原有的多面板渲染，改为调用 `openModal(panel)` 打开对应模态窗口。

- **`frontend/src/renderer/components/Sidebar/Sidebar.css`**（修改）
  - 将原右侧弹出式样式改为左侧固定布局，使用 `.left-sidebar`、`.open`、`.closed` 以及 `width` 的 transition 实现展开/收起动画。

- **`frontend/src/renderer/components/SidebarTrigger/SidebarTrigger.tsx`**（修改）
  - 从多按钮菜单改为单一汉堡图标按钮，调用 `toggleLeftSidebar` 控制左侧栏显示状态。

- **`frontend/src/renderer/components/SidebarTrigger/SidebarTrigger.css`**（修改）
  - 位置移动至页面左上角，添加 `.sidebar-open` 样式实现侧栏展开时的横向偏移。

- **`frontend/src/renderer/index.tsx`**（修改）
  - 引入 `Modal` 组件。
  - 在 `main-content` 上根据 `isLeftSidebarOpen` 动态计算 `marginLeft`，实现内容随侧栏平滑移动。
  - 将 `Modal` 组件加入根 JSX。

以上即为本次重构的全部代码改动与交互实现细节。
