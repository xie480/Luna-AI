# 气泡文本输出功能技术分析文档

## 一、 整体架构说明

气泡文本输出功能是系统中负责将模型回复以动态、分段的视觉形式展示给用户的核心模块。该功能在架构上遵循了清晰的逻辑分层与组件拆分原则，确保了状态管理的独立性与视图渲染的高效性。

### 1. 逻辑分层与组件拆分原则

该功能主要分为三个逻辑层：
*   **状态与逻辑层 (Composable):** 由 `src/composables/useBubble.js` 承担。它封装了气泡的生命周期管理（创建、显示、自动销毁）、文本分段计算逻辑以及基于 GSAP 的 FLIP (First, Last, Invert, Play) 动画位移计算。这种设计将复杂的业务逻辑与 UI 组件解耦，提高了代码的可复用性和可测试性。
*   **视图渲染层 (View/Component):** 主要由 `src/views/index/index.vue` 承担。它负责监听状态层的变化，将气泡数据渲染为 DOM 元素，并处理气泡的锚点定位（如跟随输入框或固定在屏幕底部）。此外，`src/components/HistoryPanel.vue` 也包含静态气泡的渲染，用于展示历史对话记录。
*   **事件响应与协调层:** 同样在 `src/views/index/index.vue` 中处理。它负责接收底层模型或 API 的回复数据，调用逻辑层的方法进行文本拆分和气泡生成，并协调其他视觉效果（如打字机解密特效）。

### 2. 核心数据流向

1.  **接收回复:** 系统通过 API 接收到模型的回复文本（例如在 `handleModelReply` 函数中）。
2.  **文本拆分:** 调用 `useBubble.js` 中的 `splitReplyIntoChunks` 方法，根据标点符号将长文本拆分为适合气泡显示的短句数组。
3.  **逐句发送:** 调用 `sendReplyAsBubbles` 方法，通过异步循环和定时器，逐个将短句推入气泡显示队列。
4.  **状态更新:** `showChatBubble` 方法被调用，生成新的气泡对象（包含唯一 ID、文本内容和状态标记），并更新响应式数组 `chatBubbles`。
5.  **视图响应:** Vue 的响应式系统检测到 `chatBubbles` 的变化，触发 `index.vue` 中的 DOM 更新，渲染出新的气泡元素。
6.  **动画执行:** 在 DOM 更新后（`nextTick`），逻辑层计算新旧气泡的位置差异，并使用 GSAP 执行平滑的向上推移动画。
7.  **自动销毁:** 每个气泡在设定的持续时间后，其 `leaving` 状态被标记为 `true`，触发 CSS 消失动画，随后从 `chatBubbles` 数组中移除，完成生命周期。

### 3. 状态管理机制

气泡的状态管理主要依赖于 Vue 3 的 Composition API (`ref`)：
*   `chatBubbles`: 一个响应式数组，存储当前屏幕上所有活跃的气泡对象 `{ id, text, leaving }`。通过展开运算符 `[...chatBubbles.value]` 重新赋值来确保 Vue 能够精确追踪数组变化并触发视图更新。
*   `bubbleAnchor`: 响应式对象，存储气泡栈的基准坐标 `{ x, y }`，根据 UI 状态（如输入框是否显示）动态计算。
*   `bubbleEls`: 一个原生的 `Map` 对象，用于存储气泡 ID 到实际 DOM 元素的映射，这是执行 FLIP 动画计算位置所必需的，它不需要是响应式的，以避免性能开销。

---

## 二、 源代码完整汇总与标注

以下是涉及气泡文本输出功能的全部核心源代码，已按文件路径和模块进行分类标注。

### 1. 核心逻辑模块 (Composable)
**文件路径:** [`src/composables/useBubble.js`](src/composables/useBubble.js)

```javascript
import { ref, nextTick } from "vue";
import { gsap } from "gsap";

/**
 * 氣泡管理 composable
 * 負責聊天氣泡的創建、動畫、自動消失
 */
export function useBubble(messageBoxRef, showMessageBox) {
  const chatBubbles = ref([]);
  const bubbleAnchor = ref({ x: window.innerWidth / 2, y: window.innerHeight - 180 });
  const bubbleEls = new Map(); // id -> DOM element
  let bubbleId = 0;

  // 獲取氣泡錨點（輸入框上方 或 屏幕底部中間）
  // 僅在 messageBoxRef 或 showMessageBox 變化時重新計算，避免每次讀取 DOM
  function getBubbleAnchor() {
    if (showMessageBox.value && messageBoxRef.value) {
      try {
        const rect = messageBoxRef.value.getBoundingClientRect();
        return {
          x: rect.left + rect.width / 2,
          y: rect.top - 30, // 增加與輸入框的間距
        };
      } catch (e) {}
    }
    return {
      x: (window.innerWidth || 800) / 2,
      y: (window.innerHeight || 600) - 180, // 增加底部間距，避免與輸入框重疊
    };
  }

  // 記錄所有氣泡當前的頂部位置，用於 FLIP 動畫
  function recordBubblePositions() {
    const map = new Map();
    for (const [id, el] of bubbleEls.entries()) {
      try {
        map.set(id, el.getBoundingClientRect().top);
      } catch (e) {}
    }
    return map;
  }

  // 註冊氣泡 DOM 元素引用
  function registerBubble(el, id) {
    if (!el) {
      bubbleEls.delete(id);
      return;
    }
    bubbleEls.set(id, el);
  }

  /**
   * 顯示單個氣泡
   * @param {string} text - 氣泡文本
   * @param {number} duration - 顯示時長（ms）
   */
  async function showChatBubble(text, duration = 3000) {
    // 更新錨點
    bubbleAnchor.value = getBubbleAnchor();

    // 記錄舊氣泡位置（用於 FLIP 動畫）
    const prevPositions = recordBubblePositions();

    const id = bubbleId++;
    
    // [Fix] 使用展開運算符重新賦值，確保 Vue 100% 觸發響應式更新
    chatBubbles.value = [...chatBubbles.value, { id, text, leaving: false }];

    // 等待 DOM 更新
    await nextTick();

    // 對舊氣泡執行 FLIP 位移動畫
    for (const [bid, el] of bubbleEls.entries()) {
      if (!prevPositions.has(bid)) continue;
      try {
        const dy = prevPositions.get(bid) - el.getBoundingClientRect().top;
        if (Math.abs(dy) > 0.5) {
          gsap.fromTo(el, { y: dy }, { y: 0, duration: 0.22, ease: "power2.out" });
        }
      } catch (e) {
        console.warn("Bubble FLIP error", e);
      }
    }

    // 定時自動消失
    setTimeout(() => {
      const bubble = chatBubbles.value.find((b) => b.id === id);
      if (!bubble) return;
      bubble.leaving = true;
      
      // 觸發視圖更新以應用 leaving 動畫類
      chatBubbles.value = [...chatBubbles.value];

      setTimeout(() => {
        bubbleEls.delete(id);
        chatBubbles.value = chatBubbles.value.filter((b) => b.id !== id);
      }, 250); // 稍微大於 CSS 動畫時間 (0.2s)
    }, duration);
  }

  /**
   * 將長文本拆分為多個短句
   */
  function splitReplyIntoChunks(text) {
    if (!text) return [];
    text = String(text).replace(/\s+/g, " ").trim();
    if (!text) return [];

    const sentenceRe = /[^。！？!?~～…]+[。！？!?~～…]?/g;
    const sentences = text.match(sentenceRe) || [text];
    const parts = [];
    const commaRe = /[^，,、；;]+[，,、；;]?/g;

    for (let s of sentences) {
      s = s.trim();
      if (!s) continue;
      const subs = s.match(commaRe) || [s];
      for (let sub of subs) {
        sub = sub.replace(/[，,、；;]$/u, "").trim();
        if (sub) parts.push(sub);
      }
    }
    return parts;
  }

  /**
   * 將回复文本拆分後逐句顯示為氣泡
   * @param {string} reply - 完整回复文本
   * @param {object} opts - { interval: 間隔ms, duration: 每條顯示ms }
   */
  async function sendReplyAsBubbles(reply, opts = {}) {
    const interval = typeof opts.interval === "number" ? opts.interval : 450;
    const duration = typeof opts.duration === "number" ? opts.duration : 3500;
    const chunks = splitReplyIntoChunks(reply);
    if (!chunks.length) return;

    for (let i = 0; i < chunks.length; i++) {
      await showChatBubble(chunks[i], duration);
      if (i < chunks.length - 1) {
        await new Promise((r) => setTimeout(r, interval));
      }
    }
  }

  return {
    chatBubbles,
    bubbleAnchor,
    registerBubble,
    showChatBubble,
    sendReplyAsBubbles,
    splitReplyIntoChunks,
  };
}
```

### 2. 前端渲染与事件响应模块 (View)
**文件路径:** [`src/views/index/index.vue`](src/views/index/index.vue)

*(注：此处仅提取与气泡功能直接相关的代码片段，以保持文档的聚焦性)*

**模板部分 (Template):**
```html
    <div
      class="bubble-stack"
      :style="{ left: bubbleAnchor.x + 'px', top: bubbleAnchor.y + 'px' }"
    >
      <div
        v-for="bubble in chatBubbles"
        :key="bubble.id"
        class="css-chat-bubble"
        :class="{ leaving: bubble.leaving }"
        :ref="el => registerBubble(el, bubble.id)"
      >
        <span class="bubble-avatar">馃寵</span>
        {{ bubble.text }}
      </div>
    </div>

    <div
      ref="dummyBoxRef"
      class="css-chat-bubble"
      style="position: absolute; visibility: hidden; pointer-events: none; top: -9999px; left: -9999px; width: fit-content; max-width: 280px;"
    ></div>
```

**脚本部分 (Script):**
```javascript
import { useBubble } from "../../composables/useBubble.js";

// ... 其他代码 ...

const dummyBoxRef = ref(null);
const alwaysShowBubbles = ref(false);
const { chatBubbles, bubbleAnchor, registerBubble, sendReplyAsBubbles, splitReplyIntoChunks } = useBubble(dummyBoxRef, alwaysShowBubbles);

bubbleAnchor.value = { x: window.innerWidth / 2, y: window.innerHeight - 150 };

// ... 其他代码 ...

async function handleModelReply(res) {
  if (!res) throw new Error("Empty response");

  let replyText = "";
  // ... 提取 replyText 的逻辑 ...

  if (!replyText) throw new Error("No text content found in response");

  // ... 其他逻辑 ...

  const chunks = splitReplyIntoChunks(replyText);
  const previewText = chunks.length > 0 ? chunks[0] : replyText;

  const effectPromise = playDecryptionEffect(previewText);
  const bubblePromise = sendReplyAsBubbles(replyText, { interval: 1100, duration: 5000 });

  await Promise.all([effectPromise, bubblePromise]);
}
```

**样式部分 (Style):**
```css
.bubble-stack {
  position: fixed;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  transform: translate(-50%, -100%);
  pointer-events: none;
  z-index: 99999;
}
.css-chat-bubble {
  max-width: 280px;
  padding: 10px 16px;
  width: fit-content;
  background: linear-gradient(135deg, rgba(255,255,255,0.96), rgba(240,240,240,0.92));
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 20px 20px 20px 4px;
  color: #222;
  font-size: 13.5px;
  line-height: 1.6;
  display: flex;
  align-items: center;
  gap: 8px;
  word-break: break-word;
  box-shadow: 0 8px 24px rgba(0,0,0,0.13), 0 1.5px 4px rgba(0,0,0,0.07);
  animation: bubbleIn 0.28s cubic-bezier(0.34,1.56,0.64,1) both;
}
.bubble-avatar {
  font-size: 16px;
  flex-shrink: 0;
  animation: bubbleAvatarBounce 1.8s ease-in-out infinite;
}
@keyframes bubbleAvatarBounce {
  0%, 100% { transform: translateY(0);    }
  50%      { transform: translateY(-3px); }
}
@keyframes bubbleIn {
  from { opacity: 0; transform: scale(0.8) translateY(10px); }
  to   { opacity: 1; transform: scale(1)   translateY(0);    }
}
@keyframes bubbleOut {
  from { opacity: 1; transform: scale(1); }
  to   { opacity: 0; transform: scale(0.88) translateY(6px); }
}
.css-chat-bubble.leaving {
  animation: bubbleOut 0.2s ease-in forwards;
}
```

### 3. 历史记录静态气泡展示 (Component)
**文件路径:** [`src/components/HistoryPanel.vue`](src/components/HistoryPanel.vue)

*(注：此处提取历史记录面板中用于展示对话气泡的结构和样式)*

**模板部分 (Template):**
```html
            <div v-else class="line-msg-wrapper">
              <div class="line-bubble">{{ msg.content }}</div>
              <div class="line-time">{{ msg.time }}</div>
            </div>
```

**样式部分 (Style):**
```css
.line-bubble {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
  box-shadow: 0 2px 5px rgba(0,0,0,0.2);
  animation: bubbleIn 0.22s ease;
}
.luna .line-bubble {
  background: color-mix(in oklab, var(--bg-panel-soft, rgba(255,255,255,0.1)) 100%, transparent);
  color: var(--text-main, #e8fff8);
  border-top-left-radius: 2px;
}
.user .line-bubble {
  background: var(--primary, #00ffc8);
  color: #000;
  border-top-right-radius: 2px;
}
@keyframes bubbleIn {
  from { opacity: 0; transform: translateY(4px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
```

---

## 三、 依赖关系与调用链路梳理

气泡文本输出机制的完整实现路径和依赖关系如下：

### 1. 模块依赖关系

*   `src/views/index/index.vue` **依赖于** `src/composables/useBubble.js`：视图层通过引入 Composable 来获取气泡的状态数据（`chatBubbles`, `bubbleAnchor`）和操作方法（`registerBubble`, `sendReplyAsBubbles`, `splitReplyIntoChunks`）。
*   `src/composables/useBubble.js` **依赖于** `vue` (核心响应式 API: `ref`, `nextTick`) 和 `gsap` (用于执行复杂的 FLIP 动画)。

### 2. 核心调用链路

整个气泡输出的生命周期可以描述为以下调用链路：

1.  **触发源:** 用户发送消息后，系统调用 API 获取模型回复。
2.  **入口函数:** `index.vue` 中的 `handleModelReply(res)` 被调用，接收原始回复数据。
3.  **文本预处理:** `handleModelReply` 内部调用 `useBubble.js` 提供的 `splitReplyIntoChunks(replyText)`，将长文本解析为短句数组。
4.  **启动气泡序列:** `handleModelReply` 调用 `sendReplyAsBubbles(replyText, { interval: 1100, duration: 5000 })`。
5.  **循环生成气泡:** 在 `sendReplyAsBubbles` 内部，通过 `for` 循环和 `await new Promise(setTimeout)` 控制时间间隔，逐次调用 `showChatBubble(chunk, duration)`。
6.  **状态变更与 DOM 渲染:**
    *   `showChatBubble` 计算新的 `bubbleAnchor`。
    *   记录当前所有气泡的 Y 轴位置 (`recordBubblePositions`)。
    *   向 `chatBubbles.value` 数组追加新气泡对象。
    *   等待 Vue 完成 DOM 更新 (`await nextTick()`)。
7.  **动画执行:**
    *   新气泡通过 CSS 动画 (`@keyframes bubbleIn`) 出现。
    *   旧气泡通过 GSAP 计算位移差 (`dy`)，执行平滑的向上推移动画。
8.  **生命周期终结:**
    *   `showChatBubble` 内部设置 `setTimeout`，在 `duration` 到期后，将气泡的 `leaving` 属性设为 `true`。
    *   触发 CSS 消失动画 (`@keyframes bubbleOut`)。
    *   延迟 250ms 后，从 `bubbleEls` Map 和 `chatBubbles` 数组中彻底移除该气泡数据，完成清理。

通过上述严密的逻辑分层和清晰的调用链路，系统实现了流畅、动态且易于维护的气泡文本输出功能。
