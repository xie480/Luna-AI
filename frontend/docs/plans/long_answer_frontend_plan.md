# 长回答处理方案 - 前端交互架构与实施计划

## 1. 文档定位与设计目标

本方案用于规划 Luna 前端在复杂任务、长篇 RAG 问答和结构化资料整理场景下的长回答展示体验。

本方案只编写设计文档，不直接修改业务代码。

本方案遵循 [`agent.md`](agent.md) 的前后端职责边界：Electron/React 只负责展示和交互，不负责调度、记忆提交、工具执行或模型调用。

本方案参考现有 [`frontend/docs/plans/phase7_frontend_plan.md`](frontend/docs/plans/phase7_frontend_plan.md) 的组织方式。

本方案也参考后端 RAG 方案 [`backend/docs/plans/phase7_backend_plan.md`](backend/docs/plans/phase7_backend_plan.md)。

本方案核心目标是让短回答和长回答拥有完全不同的产品语义与 UI 容器。

短回答继续以聊天气泡自然呈现。

短回答不标明来源。

短回答不展示引用。

短回答不承担完整资料整理职责。

长回答则在主界面左侧磨砂玻璃面板中呈现。

长回答正文支持流式输出。

长回答正文在流式过程中实时 Markdown 渲染。

长回答面板支持拖拽移动。

长回答面板支持边框拖拽缩放。

长回答完成后，聊天气泡中只出现自然短通知。

---

## 2. 当前源码观察结论

### 2.1 主界面结构

当前主聊天界面组件位于 [`frontend/src/renderer/components/ChatView/ChatView.tsx`](frontend/src/renderer/components/ChatView/ChatView.tsx:41)。

当前主界面由背景层、Live2D 层、近期记忆面板层和交互层组成。

[`ChatView`](frontend/src/renderer/components/ChatView/ChatView.tsx:93) 当前渲染 [`BackgroundLayer`](frontend/src/renderer/components/BackgroundLayer/BackgroundLayer.tsx)。

[`ChatView`](frontend/src/renderer/components/ChatView/ChatView.tsx:99) 当前可渲染 [`Live2DView`](frontend/src/renderer/components/Live2DView/Live2DView.tsx)，但需要实现前确认该目录在当前完整源码中是否存在。

[`ChatView`](frontend/src/renderer/components/ChatView/ChatView.tsx:108) 当前渲染 [`RecentMemoryPanel`](frontend/src/renderer/components/RecentMemoryPanel/RecentMemoryPanel.tsx)。

[`ChatView`](frontend/src/renderer/components/ChatView/ChatView.tsx:113) 当前渲染 [`TopStatusPanel`](frontend/src/renderer/components/TopStatusPanel/TopStatusPanel.tsx)。

[`ChatView`](frontend/src/renderer/components/ChatView/ChatView.tsx:114) 当前渲染 [`BubbleStack`](frontend/src/renderer/components/BubbleStack/BubbleStack.tsx)。

[`ChatView`](frontend/src/renderer/components/ChatView/ChatView.tsx:115) 当前渲染 [`InputArea`](frontend/src/renderer/components/InputArea/InputArea.tsx)。

因此长回答面板适合挂载在 [`ChatView`](frontend/src/renderer/components/ChatView/ChatView.tsx:93) 的 `chat-view` 根容器内。

### 2.2 当前气泡机制

当前气泡栈组件位于 [`frontend/src/renderer/components/BubbleStack/BubbleStack.tsx`](frontend/src/renderer/components/BubbleStack/BubbleStack.tsx:20)。

[`BubbleStack`](frontend/src/renderer/components/BubbleStack/BubbleStack.tsx:27) 监听 `luna:show-bubble` 自定义事件。

[`BubbleStack`](frontend/src/renderer/components/BubbleStack/BubbleStack.tsx:32) 调用 `showBubble()` 展示独立气泡。

当前 [`useBubble`](frontend/src/renderer/hooks/useBubble.ts:39) 负责气泡队列和生命周期。

当前 [`useBubble`](frontend/src/renderer/hooks/useBubble.ts:52) 限制最多同时显示 3 个气泡。

当前 [`useBubble`](frontend/src/renderer/hooks/useBubble.ts:89) 在所有气泡完成后触发 `luna:all-bubbles-complete`。

当前 [`BubbleStack.css`](frontend/src/renderer/components/BubbleStack/BubbleStack.css:1) 让气泡位于底部输入框上方。

当前气泡机制适合短句、自然、轻量、陪伴式交流。

长回答正文不应通过该机制输出。

### 2.3 当前 SSE 消费机制

当前 SSE 管理器位于 [`frontend/src/renderer/services/sseManager.ts`](frontend/src/renderer/services/sseManager.ts:58)。

当前 [`SSEManager.connect()`](frontend/src/renderer/services/sseManager.ts:105) 使用 `EventSource` 连接 `/sse/notifications`。

当前 [`SSEManager.setupEventHandlers()`](frontend/src/renderer/services/sseManager.ts:129) 监听 `CHAT_STREAM` 事件。

当前 [`SSEManager.handleMessage()`](frontend/src/renderer/services/sseManager.ts:233) 根据 `WS_MSG_TYPE` 分发消息。

当前 [`SSEManager.handleChatStream()`](frontend/src/renderer/services/sseManager.ts:377) 处理聊天流式输出。

当前 `reply_chunk` 会在 [`sseManager.ts`](frontend/src/renderer/services/sseManager.ts:397) 中触发 `luna:show-bubble`。

长回答事件必须新增独立分支，不应伪装成 `reply_chunk`。

### 2.4 当前全局会话状态

当前会话 Store 位于 [`frontend/src/renderer/stores/sessionStore.ts`](frontend/src/renderer/stores/sessionStore.ts:95)。

当前 [`ChatMessage`](frontend/src/renderer/stores/sessionStore.ts:13) 包含 `messageId`、`sessionId`、`role`、`contentType`、`content`、`timestamp`、`status` 和 `metadata`。

当前 [`sessionStore.updateMessageChunk()`](frontend/src/renderer/stores/sessionStore.ts:115) 会拼接助手消息内容。

当前 [`sessionStore.updateMessageStatus()`](frontend/src/renderer/stores/sessionStore.ts:154) 更新消息状态。

长回答正文不应直接拼入普通助手消息 `content`。

建议在 `metadata` 中只存长回答关联信息，例如 `longAnswerId` 和 `hasLongAnswer`。

### 2.5 当前历史气泡爱心图标

当前聊天历史样式包含消息时间行和操作图标行，见 [`ChatHistoryView.css`](frontend/src/renderer/components/RecentMemoryPanel/ChatHistoryView.css:241)。

当前操作图标按钮类名为 `.action-icon-btn`，见 [`ChatHistoryView.css`](frontend/src/renderer/components/RecentMemoryPanel/ChatHistoryView.css:271)。

当前历史视图中已有爱心 SVG 与返回 SVG，搜索结果显示在 [`ChatHistoryView.tsx`](frontend/src/renderer/components/RecentMemoryPanel/ChatHistoryView.tsx:93) 附近。

需要在实现前确认主聊天实时气泡是否也有“爱心 SVG 图标旁边”的同类图标位置。

若实时气泡没有该图标，则应先在消息操作行抽象通用 `MessageActionRow`。

---

## 3. 产品语义：短回答与长回答分离

### 3.1 短回答 UI 规则

短回答继续通过 [`BubbleStack`](frontend/src/renderer/components/BubbleStack/BubbleStack.tsx:20) 展示。

短回答来源不显示。

短回答引用不显示。

短回答不渲染复杂 Markdown。

短回答应保持自然、亲密、轻量。

短回答可用于通知：

1. “我整理好啦。”
2. “左边那份弄好了，主人去看吧。”
3. “哼，整理这么多内容还挺累的，不过我弄完了。”

短回答本身只是一种交流反馈。

### 3.2 长回答 UI 规则

长回答展示在左侧磨砂玻璃面板。

长回答可包含来源或引用信息。

长回答可使用 Markdown。

长回答可使用标题、列表、表格、代码块和引用区。

长回答面板是主界面上的一个工作区，不是聊天历史的一部分。

长回答面板可以通过气泡旁图标重新打开。

长回答生成中时面板顶部显示“Luna正在整理中……”。

长回答完成后顶部切换为小总结或完成态标题。

---

## 4. 左侧磨砂玻璃长回答面板设计

### 4.1 面板视觉定位

面板应自然出现在主界面左侧。

面板不应遮挡输入框的主要交互区域。

面板应使用磨砂玻璃视觉。

建议基础样式：

1. `background: rgba(18, 24, 28, 0.58)`。
2. `backdrop-filter: blur(18px)`。
3. `border: 1px solid rgba(255,255,255,0.14)`。
4. `box-shadow: 0 18px 60px rgba(0,0,0,0.35)`。
5. `border-radius: 18px`。
6. 文本颜色使用柔和浅色。
7. 强调色沿用现有紫色 `#a082ff`。

### 4.2 默认位置和尺寸

桌面端默认位置：

1. `left: 32px`。
2. `top: 88px`。
3. `width: min(520px, 42vw)`。
4. `height: calc(100vh - 180px)`。
5. `z-index` 应高于 `interaction-layer` 但低于全局 Modal。

由于 [`ChatView.css`](frontend/src/renderer/components/ChatView/ChatView.css:20) 中 `.interaction-layer` 的 `z-index` 为 20，长回答面板建议使用 `z-index: 28`。

需要避免与 [`RecentMemoryPanel`](frontend/src/renderer/components/RecentMemoryPanel/RecentMemoryPanel.tsx) 发生遮挡冲突。

### 4.3 顶部栏

顶部栏承担状态、拖拽、关闭和操作按钮功能。

顶部栏内容：

1. 左侧状态点。
2. 标题文本。
3. 生成状态副标题。
4. 复制按钮。
5. 收起按钮。
6. 关闭按钮。

生成中标题：

```text
Luna正在整理中……
```

完成态标题：

```text
整理完成：<小总结标题>
```

失败态标题：

```text
整理中断了
```

顶部栏必须是拖动手柄。

按钮区域不能触发拖动。

### 4.4 正文区域

正文区域负责显示 Markdown。

正文区域支持滚动。

正文区域应默认自动跟随到底部。

当用户手动向上滚动后，应暂停自动跟随。

底部出现“回到底部”小按钮。

正文区域需要支持：

1. 标题。
2. 段落。
3. 有序列表。
4. 无序列表。
5. 引用块。
6. 表格横向滚动。
7. 代码块横向滚动。
8. 内联代码。
9. 分割线。
10. 引用角标。

---

## 5. 面板进入与退出动画

### 5.1 进入动画

面板出现时不能突兀。

建议使用 GSAP，因为当前 [`useBubble`](frontend/src/renderer/hooks/useBubble.ts:16) 已使用 `gsap`。

进入动画：

1. 初始 `opacity: 0`。
2. 初始 `x: -24px`。
3. 初始 `scale: 0.985`。
4. 动画到 `opacity: 1`、`x: 0`、`scale: 1`。
5. 时长 280ms。
6. easing 使用 `power2.out`。

背景可以同步出现轻微高光扫描。

### 5.2 退出动画

退出动画：

1. `opacity: 1 -> 0`。
2. `x: 0 -> -18px`。
3. `scale: 1 -> 0.985`。
4. 时长 180ms。
5. 动画结束后从 DOM 移除或设为隐藏。

### 5.3 状态切换动画

生成中到完成态：

1. 顶部状态点从呼吸紫色变为柔和绿色。
2. 标题文本交叉淡入淡出。
3. 正文区域停止显示尾部 Loading 光标。
4. 工具栏显示“复制全文”和“查看来源”。

失败态：

1. 状态点变为红色。
2. 顶部显示错误摘要。
3. 正文保留已生成草稿。
4. 底部显示“重试整理”。

---

## 6. 拖拽移动与边框缩放设计

### 6.1 拖拽移动

拖拽只允许从顶部栏触发。

实现可用 Pointer Events，不引入重型拖拽库。

拖拽数据存入前端局部 Store。

拖拽过程只更新 transform，不频繁写入 React 状态。

释放鼠标后再持久化位置。

边界约束：

1. 面板不能完全拖出视口。
2. 顶部至少保留 48px 可见。
3. 左右至少保留 80px 可见区域。
4. 不允许覆盖输入框超过一半。

### 6.2 边框缩放

面板四边和四角支持缩放。

初版可只支持右边、下边、右下角缩放。

缩放限制：

1. 最小宽度 360px。
2. 最大宽度 `min(900px, 90vw)`。
3. 最小高度 320px。
4. 最大高度 `calc(100vh - 72px)`。

移动端或窄屏下禁用自由缩放。

### 6.3 位置尺寸持久化

建议新增 Store 保存：

1. `x`
2. `y`
3. `width`
4. `height`
5. `isPinned`
6. `lastOpenedLongAnswerId`

可使用 Zustand `persist` 中间件。

需要注意：用户切换屏幕尺寸后应校正位置，避免面板出界。

---

## 7. 流式 Markdown 渲染策略

### 7.1 依赖选择

当前 [`frontend/package.json`](frontend/package.json:15) 未包含 `react-markdown`、`remark-gfm`、`rehype-sanitize`。

如果要实现完整 Markdown，需要新增轻量依赖。

推荐：

1. `react-markdown`
2. `remark-gfm`
3. `rehype-sanitize`

不建议引入大型富文本编辑器。

如果不希望新增依赖，初版可实现受限 Markdown 渲染器，但表格和代码块成本会更高。

### 7.2 流式 Markdown 的挑战

流式过程中 Markdown 可能未闭合。

例如代码块可能只收到开头 ``` 还没收到结尾。

表格可能行数未完整。

链接语法可能半截。

因此渲染器要容错。

策略：

1. 将原始 Markdown 累积到 Store。
2. 每 80ms 到 150ms 节流渲染一次。
3. 对未闭合代码块做临时闭合补全。
4. 对超长代码块使用虚拟滚动需要实现前确认。
5. 渲染失败时降级为纯文本展示。

### 7.3 安全渲染

Markdown 必须防止 XSS。

禁用原始 HTML。

若必须支持 HTML，则必须通过 sanitize 白名单。

外链点击应通过 Electron 安全策略打开，需要实现前确认当前项目是否已有外链打开服务。

代码块复制按钮只能复制代码文本。

不要使用 `dangerouslySetInnerHTML` 渲染模型输出。

---

## 8. 组件拆分建议

建议新增目录：

```text
frontend/src/renderer/components/LongAnswerPanel/
├── LongAnswerPanel.tsx
├── LongAnswerPanel.css
├── LongAnswerHeader.tsx
├── LongAnswerMarkdown.tsx
├── LongAnswerToolbar.tsx
├── LongAnswerResizeHandles.tsx
├── LongAnswerSourceList.tsx
├── LongAnswerStatusBadge.tsx
└── useLongAnswerDragResize.ts
```

组件职责：

1. `LongAnswerPanel.tsx`：面板容器，连接 Store。
2. `LongAnswerHeader.tsx`：顶部栏、拖拽区域、标题状态。
3. `LongAnswerMarkdown.tsx`：Markdown 流式渲染。
4. `LongAnswerToolbar.tsx`：复制、重试、关闭、回到底部。
5. `LongAnswerResizeHandles.tsx`：缩放热区。
6. `LongAnswerSourceList.tsx`：引用来源列表。
7. `LongAnswerStatusBadge.tsx`：生成中、完成、失败状态显示。
8. `useLongAnswerDragResize.ts`：封装 Pointer Events。

### 8.1 ChatView 接入点

在 [`ChatView`](frontend/src/renderer/components/ChatView/ChatView.tsx:93) 中新增：

```text
<LongAnswerPanel />
```

建议层级位于 `RecentMemoryPanel` 之后，`interaction-layer` 之前或之后需要实现时根据 z-index 验证。

如果需要面板覆盖交互层，则挂在 `chat-view` 根下并设置 `pointer-events: auto`。

---

## 9. 状态管理设计

### 9.1 新增 Store

建议新增：

```text
frontend/src/renderer/stores/longAnswerStore.ts
```

核心状态：

```typescript
interface LongAnswerState {
  activeId: string | null;
  byId: Record<string, LongAnswerItem>;
  panel: LongAnswerPanelState;
  openPanel: (id: string) => void;
  closePanel: () => void;
  appendChunk: (id: string, seq: number, chunk: string) => void;
  updateStatus: (id: string, patch: Partial<LongAnswerItem>) => void;
  bindMessage: (messageId: string, longAnswerId: string) => void;
}
```

`LongAnswerItem`：

```typescript
interface LongAnswerItem {
  id: string;
  sessionId: string;
  interactionMessageId: string;
  status: 'PENDING' | 'GENERATING' | 'SUMMARY_GENERATING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  title: string;
  markdown: string;
  shortSummary: string;
  errorMessage?: string;
  citations?: LongAnswerCitation[];
  updatedAt: number;
}
```

`LongAnswerPanelState`：

```typescript
interface LongAnswerPanelState {
  visible: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
  isDragging: boolean;
  isResizing: boolean;
}
```

### 9.2 与 sessionStore 的关系

[`sessionStore`](frontend/src/renderer/stores/sessionStore.ts:95) 仍然保存聊天消息。

长回答正文不保存到 `ChatMessage.content`。

`ChatMessage.metadata` 可记录：

```typescript
{
  hasLongAnswer: true,
  longAnswerId: '...',
  longAnswerStatus: 'COMPLETED'
}
```

需要新增 action：

1. `updateMessageMetadata(sessionId, msgId, metadataPatch)`。
2. 或通用 `patchMessage(sessionId, msgId, patch)`。

这样气泡旁图标可以根据消息 metadata 显示。

---

## 10. SSE 事件消费设计

### 10.1 新增事件常量

前端需要在 [`frontend/src/shared/enum.ts`](frontend/src/shared/enum.ts:36) 中新增：

1. `EVT_LONG_ANSWER_CREATED`
2. `EVT_LONG_ANSWER_CHUNK`
3. `EVT_LONG_ANSWER_STATUS`
4. `EVT_LONG_ANSWER_SUMMARY`
5. `EVT_LONG_ANSWER_COMPLETED`
6. `EVT_LONG_ANSWER_FAILED`

后端需在 [`backend/ai-service/app/types/constants.py`](backend/ai-service/app/types/constants.py:14) 同步。

### 10.2 SSEManager 分发

在 [`SSEManager.handleMessage()`](frontend/src/renderer/services/sseManager.ts:233) 中新增分支。

长回答事件不走 [`handleChatStream()`](frontend/src/renderer/services/sseManager.ts:377)。

示意：

```typescript
case WS_MSG_TYPE.EVT_LONG_ANSWER_CHUNK:
  useLongAnswerStore.getState().appendChunk(payload.long_answer_id, payload.seq, payload.chunk);
  break;
```

### 10.3 面板自动打开

收到 `EVT_LONG_ANSWER_CREATED` 后：

1. 写入 `longAnswerStore`。
2. 设置 `activeId`。
3. 打开面板。
4. 通过柔和动画出现在左侧。
5. 更新对应聊天消息 metadata。

如果用户手动关闭了生成中的面板，后续 chunk 仍要继续缓存。

完成时不强制重新打开，避免打扰用户。

---

## 11. 气泡旁新增 SVG 图标设计

### 11.1 显示条件

图标显示在爱心 SVG 图标旁边。

显示条件：

1. 当前消息是 assistant 消息。
2. `message.metadata.hasLongAnswer === true`。
3. `message.metadata.longAnswerId` 存在。
4. 或历史消息从后端返回时携带 `long_answer_id`。

短回答没有长回答关联时不显示。

用户消息不显示。

普通短聊天不显示。

### 11.2 图标形态

建议使用文档型 SVG 图标。

图标视觉应区别于爱心。

建议：

1. 描边文档图标。
2. 右下角小星点或折角。
3. 默认颜色 rgba 白色 0.4。
4. hover 色使用 `#a082ff`。
5. 生成中显示呼吸动画。
6. 失败时显示红色小点。

### 11.3 点击行为

点击图标后：

1. 如果 longAnswerStore 已有正文，直接打开面板。
2. 如果 Store 没有正文，通过 API 拉取。
3. 如果状态是 `GENERATING`，打开面板并显示流式进行中。
4. 如果状态是 `FAILED`，打开面板显示错误和重试按钮。
5. 如果状态是 `COMPLETED`，打开面板显示完整正文。

### 11.4 与历史面板的关系

当前历史视图操作图标样式在 [`ChatHistoryView.css`](frontend/src/renderer/components/RecentMemoryPanel/ChatHistoryView.css:271)。

可复用 `.action-icon-btn` 视觉体系。

建议抽象：

```text
frontend/src/renderer/components/MessageActions/MessageActionRow.tsx
```

但需要实现前确认当前主聊天实时气泡是否有 message action row。

若实时气泡不是历史列表式消息，而是 [`BubbleStack`](frontend/src/renderer/components/BubbleStack/BubbleStack.tsx:20) 临时气泡，则“图标旁边”主要出现在历史/近期记忆消息中。

对于主界面短气泡，由于气泡会自动消失，建议在完成后的近期记忆面板或消息记录中显示长回答图标。

如果产品强制要求主界面短气泡旁显示，需调整气泡生命周期，避免图标随气泡消失导致用户无法打开长回答。

---

## 12. 桌面端与移动端适配

### 12.1 桌面端

桌面端默认自动打开左侧面板。

面板可拖拽移动。

面板可缩放。

面板允许与 Live2D 共存。

面板默认不抢输入框焦点。

### 12.2 窄屏与移动端

当视口宽度小于 760px：

1. 面板进入全宽抽屉模式。
2. 从左侧滑入。
3. 宽度为 `calc(100vw - 24px)`。
4. 高度为 `calc(100vh - 96px)`。
5. 禁用自由拖拽和缩放。
6. 顶部栏保留关闭按钮。
7. 点击气泡旁文档图标打开抽屉。
8. 面板打开时可弱化背景。

### 12.3 历史消息打开

在移动端或窄屏历史面板中，用户点击文档图标时，应关闭或覆盖历史详情层。

需要实现前确认 [`RecentMemoryPanel`](frontend/src/renderer/components/RecentMemoryPanel/RecentMemoryPanel.tsx) 的层级和移动端结构。

---

## 13. UI 状态设计

### 13.1 生成中

顶部栏显示：

```text
Luna正在整理中……
```

状态点呼吸动画。

正文区域持续追加 Markdown。

底部显示小型 Loading 光标。

工具栏禁用“复制全文”或允许复制当前草稿。

关闭按钮只关闭面板，不取消生成。

### 13.2 完成态

顶部栏显示小总结标题。

状态点变为完成色。

工具栏显示：

1. 复制全文。
2. 查看来源。
3. 回到底部。
4. 收起面板。

聊天气泡中出现自然短回复。

短回复不显示来源。

### 13.3 失败态

顶部栏显示：

```text
整理中断了
```

正文保留已生成草稿。

错误区域显示简短错误。

工具栏显示：

1. 重试。
2. 复制草稿。
3. 关闭。

失败图标在消息操作区显示红点。

---

## 14. 长回答来源和引用边界

短回答气泡不显示来源。

长回答面板可显示引用。

引用展示位置：

1. 正文中的 `[1]` 角标。
2. 面板底部“参考来源”折叠区。
3. 右侧或底部来源列表。

如果正文没有 RAG 证据，不显示来源区。

如果后端返回引用元数据，前端根据 `citations` 渲染。

引用点击可滚动到对应正文段落。

不要在短回复气泡里显示 `[1]`。

不要在短回复气泡时间行显示来源按钮。

---

## 15. API 与数据拉取设计

除 SSE 外，需要提供按需拉取接口。

推荐 Service：

```text
frontend/src/renderer/services/longAnswerService.ts
```

方法：

1. `fetchLongAnswerById(id)`
2. `fetchLongAnswerByMessageId(messageId)`
3. `retryLongAnswer(id)`
4. `cancelLongAnswer(id)`

接口由后端新增：

1. `GET /api/long_answer/{id}`
2. `GET /api/long_answer/by_message/{message_id}`
3. `POST /api/long_answer/{id}/retry`
4. `POST /api/long_answer/{id}/cancel`

所有 ID 必须是 string，避免 Snowflake 精度丢失。

参考前端 Snowflake 约束 [`frontend/src/shared/utils/snowflake.ts`](frontend/src/shared/utils/snowflake.ts)。

---

## 16. Markdown 性能优化

### 16.1 节流渲染

流式 chunk 可能高频到达。

不要每个 chunk 都触发完整 Markdown parse。

Store 可立即累积字符串。

组件层使用 `requestAnimationFrame` 或 100ms 节流刷新显示。

### 16.2 大文本保护

当正文超过 50k 字符时：

1. 继续保存完整文本。
2. 渲染区可分段显示。
3. 代码块延迟高亮。
4. 表格区域单独滚动。

初版不建议引入虚拟列表库。

如果后续正文极长，再评估虚拟化。

### 16.3 自动滚动策略

如果用户在底部附近，自动滚动到底。

如果用户手动上滚超过 80px，则暂停自动滚动。

显示“回到底部”按钮。

生成完成时不强制滚动，尊重用户阅读位置。

---

## 17. 无障碍与键盘操作

面板顶部栏应有 `role="dialog"` 或合理语义。

关闭按钮支持 `Esc`。

复制按钮支持 `Enter` 和 `Space`。

拖拽不是唯一移动方式。

可提供键盘微调：

1. `Alt + Arrow` 移动面板。
2. `Alt + Shift + Arrow` 调整尺寸。

移动端需要确保按钮触控面积大于 36px。

颜色提示不能只依赖颜色，需配合文字状态。

---

## 18. 错误处理与重试入口

### 18.1 SSE 中断

如果 SSE 断开，面板显示：

```text
连接断开，正在等待后端恢复……
```

EventSource 原生会重连。

重连后可通过 `fetchLongAnswerById()` 拉取最新草稿。

### 18.2 生成失败

收到 `EVT_LONG_ANSWER_FAILED` 后：

1. 状态设为 `FAILED`。
2. 保留已有 Markdown。
3. 显示错误说明。
4. 提供重试按钮。

### 18.3 拉取失败

点击图标拉取长回答失败时：

1. Toast 提示。
2. 面板显示错误空态。
3. 不影响短聊天气泡。

错误上报复用 [`reportError`](frontend/src/renderer/services/errorLogService.ts)。

当前 [`ChatView`](frontend/src/renderer/components/ChatView/ChatView.tsx:72) 已监听 `luna:notification` 并上报错误。

---

## 19. 目录结构落地建议

建议新增：

```text
frontend/src/renderer/components/LongAnswerPanel/
frontend/src/renderer/stores/longAnswerStore.ts
frontend/src/renderer/services/longAnswerService.ts
frontend/src/renderer/types/longAnswer.ts
frontend/src/renderer/components/MessageActions/
```

建议修改：

1. [`frontend/src/renderer/components/ChatView/ChatView.tsx`](frontend/src/renderer/components/ChatView/ChatView.tsx:41)
2. [`frontend/src/renderer/services/sseManager.ts`](frontend/src/renderer/services/sseManager.ts:58)
3. [`frontend/src/renderer/stores/sessionStore.ts`](frontend/src/renderer/stores/sessionStore.ts:13)
4. [`frontend/src/shared/enum.ts`](frontend/src/shared/enum.ts:36)
5. [`frontend/src/shared/types.ts`](frontend/src/shared/types.ts:87)
6. 历史气泡相关组件，需要实现前确认具体图标插入点。

不建议重构整个聊天系统。

不建议替换 Zustand。

不建议替换 SSE。

不建议把长回答塞进 [`BubbleStack`](frontend/src/renderer/components/BubbleStack/BubbleStack.tsx:20)。

---

## 20. 与现有 Phase 7 前端计划的整合

建议在 [`frontend/docs/plans/phase7_frontend_plan.md`](frontend/docs/plans/phase7_frontend_plan.md) 的对话增强章节后追加“长回答面板链路”。

但本方案保持为独立文档，方便后续单独实施。

与 Phase 7 RAG 的关系：

1. RAG 检索负责证据。
2. 后端长回答链路负责生成 Markdown 正文。
3. 前端长回答面板负责阅读体验。
4. 短气泡只负责自然通知。
5. 引用只出现在长回答面板。

---

## 21. 测试方案

### 21.1 单元测试

1. `longAnswerStore.appendChunk()` 顺序拼接测试。
2. 重复 chunk `seq` 幂等测试。
3. 面板状态切换测试。
4. 拖拽边界计算测试。
5. 缩放边界计算测试。
6. Markdown 渲染降级测试。
7. 消息 metadata 绑定测试。

### 21.2 组件测试

1. 生成中顶部栏文案显示。
2. 完成态标题切换。
3. 失败态错误和重试按钮显示。
4. 文档图标显示条件。
5. 点击文档图标打开面板。
6. 移动端抽屉布局。
7. 桌面端拖拽缩放。

### 21.3 集成测试

1. 后端推送 `EVT_LONG_ANSWER_CREATED` 后面板自动出现。
2. 后端推送 chunk 后 Markdown 实时更新。
3. 后端完成后短回答气泡正常显示。
4. 短回答不显示来源。
5. 长回答面板显示来源。
6. 历史消息点击图标可重新打开长回答。
7. SSE 中断后恢复拉取草稿。

---

## 22. 实施 Roadmap

* [ ] **Step 1：类型和常量补齐**
  - 在 [`frontend/src/shared/enum.ts`](frontend/src/shared/enum.ts:36) 新增长回答事件常量。
  - 在 [`frontend/src/shared/types.ts`](frontend/src/shared/types.ts:87) 新增长回答事件 Payload 类型。

* [ ] **Step 2：新增 LongAnswerStore**
  - 新增 `longAnswerStore.ts`。
  - 管理正文、状态、面板位置和尺寸。
  - 支持 chunk 幂等拼接。

* [ ] **Step 3：新增面板组件**
  - 创建 `LongAnswerPanel` 目录。
  - 实现磨砂玻璃容器。
  - 实现顶部栏状态。
  - 实现进入和退出动画。

* [ ] **Step 4：实现拖拽和缩放**
  - 使用 Pointer Events。
  - 限制移动边界。
  - 限制最小最大尺寸。
  - 窄屏禁用自由拖拽缩放。

* [ ] **Step 5：实现流式 Markdown**
  - 接入 Markdown 渲染器。
  - 增加节流渲染。
  - 增加安全渲染和降级纯文本。

* [ ] **Step 6：接入 SSEManager**
  - 在 [`sseManager.ts`](frontend/src/renderer/services/sseManager.ts:233) 增增长回答事件处理分支。
  - 不复用 `luna:show-bubble`。
  - 更新消息 metadata。

* [ ] **Step 7：新增消息文档图标**
  - 在爱心 SVG 旁新增文档图标。
  - 根据 `hasLongAnswer` 显示。
  - 生成中、完成、失败三态视觉区分。

* [ ] **Step 8：补充 API Service**
  - 新增 `longAnswerService.ts`。
  - 支持按 ID 和 message ID 拉取。
  - 支持重试和取消。

* [ ] **Step 9：响应式和验收测试**
  - 桌面端面板共存 Live2D。
  - 窄屏抽屉模式。
  - 历史消息重新打开。
  - 短回答不显示来源。

---

## 23. 编码规范符合性说明

所有新增事件名必须集中定义，禁止魔法字符串。

所有跨层 Payload 必须包含 `schema_version`。

所有 ID 作为 string 处理，避免 Snowflake 精度丢失。

前端不直接访问数据库。

前端不直接访问 Redis。

前端不决定是否生成长回答，只响应后端事件。

前端只可基于后端返回的 metadata 决定显示图标。

所有组件、方法、关键逻辑块需要中文注释。

禁止提交 `console.log` 调试残留。

错误必须通过现有错误提示和上报链路处理。

长回答面板不能破坏当前短气泡陪伴式体验。

长回答链路应与 Phase 7 RAG 引用能力自然衔接。
