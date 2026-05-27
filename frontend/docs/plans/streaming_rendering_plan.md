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
- 结合现有的 Live2D 架构（参考 `live2d_architecture_analysis.md`），前端已经具备了完善的表情系统（`applyEmotionExpressions` 和 `tweenParameters`）。
- 在 `sessionStore` 或专门的 `live2dStore` 中监听 `EVT_EMOTION_UPDATE` 事件。
- 收到事件后，立即调用现有的 `applyEmotionExpressions(msg.payload.emotion)` 方法。
- 该方法会根据 `EMOTION_EXPRESSIONS` 映射表，加载对应的 `.exp3.json` 参数，并通过 `tweenParameters` 实现 220ms 的平滑缓动过渡。
- 由于后端保证了 `emotion` 字段在 `reply` 之前输出并解析下发，前端可以在文本气泡出现前或同时完成表情切换，体验更加自然。

### 3.3 气泡渲染逻辑 (BubbleStack)
- 结合现有的气泡架构（参考 `bubble_text_architecture_analysis.md`），前端已经具备了基于 `useBubble.js` 的独立气泡栈渲染能力。
- 废弃原有的在前端进行 `splitReplyIntoChunks` 的逻辑，因为后端已经按语义（标点符号）进行了断句并下发 `EVT_REPLY_CHUNK`。
- 监听 `EVT_REPLY_CHUNK` 事件。
- **渲染策略**：
  - 沿用现有的**独立气泡策略**（策略 A）。每个 `chunk` 作为一个独立的聊天气泡弹出。
  - 收到 `EVT_REPLY_CHUNK` 后，直接调用 `useBubble.js` 暴露的 `showChatBubble(chunk, duration)` 方法。
  - `showChatBubble` 会自动处理气泡的入场动画（`bubbleIn`）、旧气泡的 FLIP 向上推移动画（基于 GSAP），以及气泡的定时自动销毁（`bubbleOut`）。
  - 这种方式类似微信/QQ的连续发送，适合短句，表现力强，且完全复用了现有的复杂动画逻辑。

### 3.4 状态管理与事件分发
更新 `sessionStore.ts` 或 WebSocket 消息处理中心：
```typescript
// 伪代码示例
import { useBubble } from '../hooks/useBubble';
// 假设 applyEmotionExpressions 已经暴露或可以通过事件总线调用

const handleWebSocketMessage = (msg) => {
  switch (msg.type) {
    case 'EVT_EMOTION_UPDATE':
      // 触发 Live2D 表情更新，利用现有的 220ms 缓动逻辑
      applyEmotionExpressions(msg.payload.emotion);
      break;
    case 'EVT_REPLY_CHUNK':
      // 直接调用 useBubble 的方法显示气泡
      // duration 可以根据 chunk 长度动态计算，或者使用默认值
      const duration = Math.max(3000, msg.payload.chunk.length * 200);
      showChatBubble(msg.payload.chunk, duration);
      
      // 同时，如果需要将完整对话保存到历史记录，可以追加到 sessionStore 的 messages 中
      appendChunkToCurrentMessage(msg.payload.chunk);
      break;
    // ... 处理 is_finished 等其他逻辑
  }
};
```

## 4. 实施步骤

1. **Phase 1: 契约对齐**
   - 确认后端 WebSocket 消息格式，更新前端 `shared/types.ts` 中的消息类型定义。
2. **Phase 2: 状态与逻辑改造**
   - 修改 WebSocket 消息处理逻辑，移除旧的 JSON 碎片拼接逻辑。
   - 接入 `EVT_EMOTION_UPDATE`，直接桥接到现有的 `applyEmotionExpressions` 方法。
   - 接入 `EVT_REPLY_CHUNK`，直接桥接到现有的 `showChatBubble` 方法。
3. **Phase 3: 冗余代码清理**
   - 移除 `useBubble.js` 中不再需要的 `splitReplyIntoChunks` 和 `sendReplyAsBubbles` 方法（因为拆分和循环发送逻辑已移至后端）。
4. **Phase 4: 联调与测试**
   - 与后端进行全链路联调，验证情绪切换的及时性（220ms 缓动是否自然）和气泡渲染的平滑度（FLIP 动画是否正常触发）。