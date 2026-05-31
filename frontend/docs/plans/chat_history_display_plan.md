# 聊天记录展示功能前端实施计划

## 1. 需求概述
本计划旨在实现一个完整的聊天记录展示功能，包含顶部导航切换、高级日历面板以及拟物化沉浸式聊天记录展示区。严格遵循 `agent.md` 规范，所有数据交互均通过 WebSocket 经由 Go 控制面流转，绝对禁止前端直连数据库或 Redis，且全局禁止使用任何 Emoji。

## 2. 组件划分与设计

### 2.1 导航与布局组件 (`HistoryNavigation`)
- **位置**: 嵌入在现有的 `RecentMemoryPanel` 顶部。
- **内容**: 包含两个矢量图标（SVG）：近期记忆图标、历史日历图标。绝对禁止使用任何 Emoji。
- **交互**: 当用户点击日历图标时，触发状态切换，平滑隐藏当前的近期记忆面板，并带动画过渡替换为日历面板。

### 2.2 高级日历面板组件 (`CalendarPanel`)
- **年月切换**: 摒弃传统的原生 `<select>` 下拉框，采用具有现代感、高级且炫酷的交互切换方式，例如基于 `framer-motion` 或纯 CSS 实现的平滑滚动选择器（Smooth Scroll Selector）或带视差效果的滑动切换。
- **日期渲染**:
  - 渲染所需的日期高亮状态必须依赖从 Go 后端获取的 Redis `history` 状态元数据。
  - **有记录**: 若某日存在历史记录，则高亮显示且允许点击（`cursor: pointer`）。
  - **无记录**: 若无记录，则置灰变暗并禁用点击（`cursor: not-allowed`）。
  - **当天**: 为当天的日期增加独特的视觉强调标记（如底部高亮小圆点或特殊边框）。

### 2.3 拟物化手机容器 (`PhoneMockup`)
- **视觉设计**: 纯 CSS 或 SVG 实现的 iPhone 17 Pro Max 正面外观（包含灵动岛、圆角边框、屏幕内阴影等高级质感）。
- **作用**: 作为聊天记录的沉浸式展示容器，仅在用户点击日历上高亮且有记录的日期后，渲染于日历面板下方。

### 2.4 聊天记录展示区 (`ChatHistoryView` & `HistoryBubble`)
- **风格**: 在手机屏幕区域内，高度还原 LINE 风格的聊天界面，整体视觉要求极简、具备高级质感且绝对禁止使用 Emoji。
- **布局**:
  - AI 角色 LUNA 的消息居左展示。
  - 用户的消息居右展示。
  - 双方均无需显示头像。
  - 消息的发送时间必须排版在聊天气泡的正下方。
- **数据源**: 详细聊天数据必须直接从 PostgreSQL 数据库中查询获取（通过 WS 请求 Go 后端），禁止从 Redis 获取详细记录。

## 3. 状态管理 (Zustand)

在 `frontend/src/renderer/stores/` 下新建或扩展 `historyStore.ts`：

```typescript
interface HistoryState {
  currentView: 'RECENT' | 'CALENDAR';
  selectedDate: string | null; // 格式: YYYY-MM-DD
  calendarMetadata: Record<string, boolean>; // 某日是否有记录的映射，来源于 Redis
  chatHistory: ChatMessage[]; // 选定日期的详细聊天记录，来源于 PostgreSQL
  isLoadingHistory: boolean;
  
  // Actions
  switchView: (view: 'RECENT' | 'CALENDAR') => void;
  setSelectedDate: (date: string) => void;
  fetchCalendarMetadata: (yearMonth: string) => void; // 触发 WS 请求获取 Redis 元数据
  fetchChatHistory: (date: string) => void; // 触发 WS 请求获取 PG 详细数据
}
```

## 4. WebSocket 接口协议设计

在 `frontend/src/shared/enum.ts` 中新增事件枚举：

```typescript
export enum WsEvent {
  // ... 现有事件
  REQ_GET_CALENDAR_METADATA = 'REQ_GET_CALENDAR_METADATA',
  RES_CALENDAR_METADATA = 'RES_CALENDAR_METADATA',
  REQ_GET_CHAT_HISTORY = 'REQ_GET_CHAT_HISTORY',
  RES_CHAT_HISTORY = 'RES_CHAT_HISTORY',
}
```

### 4.1 获取日历元数据 (Redis)
- **请求 (REQ_GET_CALENDAR_METADATA)**: `{ yearMonth: "2026-05" }`
- **响应 (RES_CALENDAR_METADATA)**: `{ yearMonth: "2026-05", activeDates: ["2026-05-01", "2026-05-15"] }`

### 4.2 获取详细聊天记录 (PostgreSQL)
- **请求 (REQ_GET_CHAT_HISTORY)**: `{ date: "2026-05-15" }`
- **响应 (RES_CHAT_HISTORY)**: `{ date: "2026-05-15", messages: [{ id: "snowflake_id", role: "user", content: "...", timestamp: "..." }, ...] }`

## 5. 实施步骤

1. **Phase 1: 基础骨架与导航**
   - 创建 `HistoryNavigation` 组件，引入 SVG 矢量图标。
   - 在 Zustand 中增加视图切换状态。
   - 实现近期记忆与日历面板的平滑切换动画。
2. **Phase 2: 高级日历面板**
   - 实现炫酷的年月切换器（视差滑动或平滑滚动）。
   - 接入 WS 请求获取 Redis 元数据。
   - 根据元数据渲染日期网格（高亮/置灰/当天标记）。
3. **Phase 3: 拟物化容器与聊天 UI**
   - 绘制 iPhone 17 Pro Max CSS 容器。
   - 实现 LINE 风格的无头像气泡布局（时间在下方）。
   - 接入 WS 请求获取 PostgreSQL 详细数据并渲染。
4. **Phase 4: 联调与打磨**
   - 确保所有交互无卡顿，动画平滑。
   - 严格审查代码，确保无 Emoji，无直接 DB 访问，所有 ID 使用 Snowflake。

## 6. 规范约束检查
- **禁止 Emoji**: UI 和代码注释中均不使用 Emoji。
- **单向数据流**: 前端只负责发送请求和监听响应，不处理复杂业务逻辑，Go 为唯一调度权威。
- **ID 规范**: 渲染列表时的 `key` 必须使用后端返回的 Snowflake ID。
