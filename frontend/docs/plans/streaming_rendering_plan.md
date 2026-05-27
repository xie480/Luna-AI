# 前端流式气泡渲染与情绪同步方案

## 1. 背景与痛点

在之前的实现中，前端接收到的是大模型原始的 JSON 碎片（Chunk），由于无法解析，导致渲染出现乱码、闪烁，且无法及时提取情绪字段来驱动 Live2D 模型。
配合后端（Python 层）的流式解析与断句改造，前端将接收到结构化、语义完整的独立事件（情绪更新事件和句子级别的文本块）。本方案旨在基于这些新事件，优化前端的渲染逻辑，实现平滑的聊天气泡展示和零延迟的 Live2D 情绪同步。

## 2. 目标

1. **零延迟情绪同步**：接收到 `emotion_update` 事件后，立即驱动 Live2D 模型切换表情，实现音画/神态同步。
2. **平滑气泡渲染**：接收到 `reply_chunk`（按标点符号断句的完整小句）后，直接渲染为新的聊天气泡或追加到当前气泡组，消除逐字渲染带来的闪烁感。
3. **简化前端逻辑**：移除前端复杂的 JSON 拼接和打字机效果逻辑，专注于 UI 渲染和状态展示。

## 3. 核心设计

### 3.1 WebSocket 消息契约
前端将通过 WebSocket 接收来自 Go 网关的两种新消息类型：

**1. 情绪更新事件 (`EVT_EMOTION_UPDATE`)**
```json
{
  "type": "EVT_EMOTION_UPDATE",
  "payload": {
    "emotion": "Confused"
  }
}
```

**2. 句子文本块事件 (`EVT_REPLY_CHUNK`)**
```json
{
  "type": "EVT_REPLY_CHUNK",
  "payload": {
    "chunk": "121215？",
    "is_finished": false
  }
}
```

### 3.2 情绪同步逻辑 (Live2D)
- 在 `sessionStore` 或专门的 `live2dStore` 中监听 `EVT_EMOTION_UPDATE` 事件。
- 收到事件后，立即调用 Live2D SDK/封装库的 API（如 `setExpression("Confused")`）。
- 由于后端保证了 `emotion` 字段在 `reply` 之前输出并解析下发，前端可以在文本气泡出现前或同时完成表情切换，体验更加自然。

### 3.3 气泡渲染逻辑 (ChatView)
- 废弃原有的逐字打字机（Typewriter）效果，因为后端已经按语义（标点符号）进行了断句。
- 监听 `EVT_REPLY_CHUNK` 事件。
- **渲染策略**：
  - **策略 A（独立气泡）**：每个 `chunk` 渲染为一个独立的聊天气泡。这种方式类似微信/QQ的连续发送，适合短句，表现力强。
  - **策略 B（追加气泡）**：在当前 AI 回复的同一个大气泡内，按段落或行追加 `chunk`。可以使用 CSS 动画（如淡入）让新追加的句子平滑出现。
  - **推荐**：采用策略 B 的变体，即在同一个消息块中，每个 `chunk` 作为一个独立的 `<span>` 或 `<div>` 淡入显示，既保持了消息的整体性，又避免了闪烁。

### 3.4 状态管理 (Zustand)
更新 `sessionStore.ts` 中的状态处理逻辑：
```typescript
// 伪代码示例
const useSessionStore = create((set, get) => ({
  messages: [],
  currentEmotion: 'Neutral',
  
  handleWebSocketMessage: (msg) => {
    switch (msg.type) {
      case 'EVT_EMOTION_UPDATE':
        set({ currentEmotion: msg.payload.emotion });
        // 触发 Live2D 表情更新
        updateLive2DExpression(msg.payload.emotion);
        break;
      case 'EVT_REPLY_CHUNK':
        set((state) => {
          // 找到当前正在生成的 AI 消息，追加 chunk
          const lastMsg = state.messages[state.messages.length - 1];
          if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.isFinished) {
            return {
              messages: [
                ...state.messages.slice(0, -1),
                { ...lastMsg, content: lastMsg.content + msg.payload.chunk }
              ]
            };
          }
          // 如果没有正在生成的消息，则创建新消息
          return {
            messages: [
              ...state.messages,
              { role: 'assistant', content: msg.payload.chunk, isFinished: false }
            ]
          };
        });
        break;
      // ... 处理 is_finished 等其他逻辑
    }
  }
}));
```

## 4. 实施步骤

1. **Phase 1: 契约对齐**
   - 确认后端 WebSocket 消息格式，更新前端 `shared/types.ts` 中的消息类型定义。
2. **Phase 2: 状态与逻辑改造**
   - 修改 `sessionStore.ts`，移除旧的 JSON 碎片拼接逻辑，接入新的 `EVT_EMOTION_UPDATE` 和 `EVT_REPLY_CHUNK` 处理逻辑。
3. **Phase 3: UI 渲染优化**
   - 修改 `ChatView` 和 `BubbleStack` 组件，移除打字机效果，添加新 chunk 淡入的 CSS 动画。
   - 确保 Live2D 组件能够正确响应 `currentEmotion` 的变化并平滑过渡。
4. **Phase 4: 联调与测试**
   - 与后端进行全链路联调，验证情绪切换的及时性和气泡渲染的平滑度。