# 记忆面板前端重构设计方案

## 1. 目标
将现有的记忆面板（MemoryPanel）重构为与设置面板（SettingsPanel）一致的布局风格，包含侧边导航栏，并实现“手动记忆”和“记忆查看”两个核心功能模块。

## 2. 整体布局设计

### 2.1 容器与尺寸
- 记忆面板将作为 `Modal` 组件中的一个独立 Panel 渲染。
- 初始尺寸设定为与设置面板一致：`width: 900px`, `height: 600px`。
- 需在 `Modal.tsx` 的 `getDefaultSize` 方法中，为 `memory` 面板返回 `{ w: 900, h: 600 }`。

### 2.2 侧边导航栏 (Sidebar)
- 采用左侧固定宽度（如 `200px`），右侧自适应填充的 Flex 布局。
- 侧边栏包含两个菜单项：
  1. **手动记忆** (Manual Memory)
  2. **记忆查看** (Memory Viewer)
- 菜单项点击时切换右侧内容区的渲染组件。

## 3. 核心功能模块设计

### 3.1 手动记忆 (Manual Memory)
**功能描述**：展示积压的未压缩聊天记录，并提供手动触发压缩入库的功能。

**UI 元素**：
- **状态展示区**：动态展示 Redis 中积压的未压缩且未入库的聊天记录天数（排除当天）。
- **操作区**：一个“开始压缩”按钮。
- **进度展示区**：在按钮下方展示精确的实时压缩进度条（如 `正在压缩 20231001 (1/5)...`）。

**交互逻辑**：
1. 组件挂载时，请求后端 `GET /api/memory/uncompressed` 接口，获取积压的 `session_ids` 列表。
2. 用户点击“开始压缩”按钮后，前端进入循环，**串行**遍历 `session_ids` 列表。
3. 针对每个 `session_id`，发送 `POST /api/memory/compress` 请求。
4. 等待当前请求成功响应后，更新进度条状态，再发起下一个请求。
5. 串行执行机制确保不会触发大模型接口的并发限流。
6. 全部完成后，刷新状态展示区，提示压缩完成。

### 3.2 记忆查看 (Memory Viewer)
**功能描述**：以表格形式完整呈现长期记忆 SQL 数据表（`long_term_memories`）的底层结构，并提供 CRUD 操作。

**UI 元素**：
- **工具栏**：包含“新增记忆”按钮和刷新按钮。
- **数据表格**：
  - 表头字段中文化：
    - `id` -> 记忆 ID
    - `session_id` -> 会话 ID
    - `summary` -> 记忆摘要
    - `status` -> 状态
    - `created_at` -> 创建时间
    - `updated_at` -> 更新时间
    - 操作列（编辑、删除）
  - 样式要求：固定列宽，对于 `summary` 等长文本内容，设置 `word-break: break-all` 和 `white-space: normal` 实现自动换行渲染。
- **分页控件**：支持翻页浏览。
- **编辑/新增弹窗**：用于输入或修改 `session_id` 和 `summary`。

**交互逻辑**：
1. **查询 (Read)**：组件挂载及翻页时，请求 `GET /api/memory/long_term` 获取分页数据并渲染表格。
2. **新增 (Create)**：点击新增按钮，弹出表单，填写后请求 `POST /api/memory/long_term`，成功后刷新表格。
3. **修改 (Update)**：点击行操作列的编辑按钮，弹出表单回显数据，修改后请求 `PUT /api/memory/long_term/{id}`，成功后刷新表格。
4. **删除 (Delete)**：点击行操作列的删除按钮，二次确认后请求 `DELETE /api/memory/long_term/{id}`，成功后刷新表格。

## 4. 目录结构规划

建议在 `frontend/src/renderer/components/MemoryPanel/` 目录下创建以下文件：
- `MemoryPanel.tsx`: 主容器组件，包含侧边栏和路由逻辑。
- `MemoryPanel.css`: 样式文件，复用 SettingsPanel 的部分样式变量。
- `ManualMemory.tsx`: 手动记忆子组件。
- `MemoryViewer.tsx`: 记忆查看子组件（包含表格和 CRUD 逻辑）。

## 5. 接口对接准备
前端需要封装对应的 API 请求服务（如 `memoryService.ts`），包含上述提到的所有 HTTP 接口调用方法。
