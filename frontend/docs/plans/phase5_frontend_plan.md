# Phase 5: 短期会话记忆与上下文窗口管理实现方案 (前端)

## 1. 目标与设计理念

**目标**：
在主界面右上角（侧栏按钮下方）新增一个轻量级的“近期记忆”面板，用于展示当前会话（当天）的最后 3 轮 Q&A。

**设计理念**：
- **界面清爽**：不恢复全量聊天气泡，主聊天区保持干净。
- **平滑过渡**：新消息产生时，等待气泡渲染完成 1 秒后再平滑插入近期记忆面板，避免视觉突兀。
- **拟人化**：体现 Luna 脑海中保留着最近的对话印象。

## 2. 实施步骤

### 步骤 1：定义通信协议 (Schema)

在 `frontend/src/shared/types.ts` 中新增相关类型。

```typescript
export interface InteractionQA {
  msgId: string;
  userContent: string;
  assistantContent: string;
  timestamp: number;
}

export interface InitStatePayload {
  sessionId: string;
  recentQA: InteractionQA[];
}
```

### 步骤 2：状态管理 (`sessionStore.ts`)

在 `sessionStore` 中增加对 `recentQA` 的管理。

```typescript
interface SessionState {
  // ... 现有状态
  recentQA: InteractionQA[];
  setRecentQA: (qaList: InteractionQA[]) => void;
  addRecentQA: (qa: InteractionQA) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  // ... 现有状态
  recentQA: [],
  setRecentQA: (qaList) => set({ recentQA: qaList }),
  addRecentQA: (qa) => set((state) => {
    const newList = [...state.recentQA, qa];
    if (newList.length > 3) {
      newList.shift(); // 移除最旧的一条，保持最多 3 条
    }
    return { recentQA: newList };
  }),
}));
```

### 步骤 3：处理 WebSocket 事件

在 `wsManager.ts` 或相应的事件监听处，处理 `EVT_INIT_STATE`。

```typescript
wsManager.on(WS_MSG_TYPE.EVT_INIT_STATE, (payload: InitStatePayload) => {
  useSessionStore.getState().setRecentQA(payload.recentQA);
});
```

### 步骤 4：实现延迟插入逻辑

在处理流式响应结束的地方（例如监听到 `is_finished: true` 且当前气泡渲染完成时），触发延迟插入。

```typescript
// 伪代码：在处理完最后一条流式消息后
if (isFinished) {
  setTimeout(() => {
    const newQA: InteractionQA = {
      msgId: currentMsgId,
      userContent: currentUserMessage,
      assistantContent: fullAssistantReply,
      timestamp: Date.now() / 1000,
    };
    useSessionStore.getState().addRecentQA(newQA);
  }, 1000); // 延迟 1 秒
}
```

### 步骤 5：UI 组件实现 (`RecentMemoryPanel.tsx`)

在 `frontend/src/renderer/components/` 下新建 `RecentMemoryPanel` 组件。

- **位置**：绝对定位在右上角
- **样式**：半透明背景，毛玻璃效果，字体较小，颜色柔和，不干扰主视线。
- **动画**：新条目插入时使用简单的淡入或滑动动画。

```tsx
// 伪代码结构
const RecentMemoryPanel = () => {
  const recentQA = useSessionStore((state) => state.recentQA);

  if (recentQA.length === 0) return null;

  return (
    <div className="recent-memory-panel">
      <div className="panel-title">近期记忆</div>
      {recentQA.map((qa) => (
        <div key={qa.msgId} className="qa-item">
          <div className="user-text">U: {qa.userContent}</div>
          <div className="luna-text">L: {qa.assistantContent}</div>
        </div>
      ))}
    </div>
  );
};
```

将该组件引入到主页面（如 `ChatView.tsx` 或 `App.tsx`）的合适位置。

## 3. 总结

前端通过新增一个轻量级的悬浮面板，结合延迟 1 秒的平滑插入策略，完美实现了“保留近期记忆”与“保持界面清爽”的平衡。