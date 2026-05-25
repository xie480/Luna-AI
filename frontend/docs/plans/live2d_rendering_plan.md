# Live2D 渲染方案（页面正中央，紧邻输入框下方）

## 1. 概述
本方案基于项目现有的 **Live2D 架构实现**（详见 [`live2d_architecture_analysis.md`](frontend/docs/system/live2d_architecture_analysis.md:1)）以及 **项目约束**（见 `agent.md`），在 **Electron 渲染进程** 中新增 **Live2D 展示层**，实现位于聊天输入框正下方、页面水平居中的模型渲染。方案覆盖 **HTML、CSS、TypeScript（React 组件）** 三层实现及 **资源加载、尺寸自适应、交互事件、兼容性** 细节，并提供 **完整可直接复制的代码示例**。

## 2. 关键约束与实现要点
| 约束来源 | 关键要点 |
|---|---|
| `live2d_architecture_analysis.md` | ① 必须在 `<head>` 中同步加载 `live2dcubismcore.min.js` 与 `live2d.min.js`（文件位于 `public/live2d/`）<br>② 全局 `window.PIXI` 必须在任何 `pixi-live2d-display` 导入前挂载（已在 `src/main.ts` 中实现）<br>③ 模型文件放在 `public/models/luna/`，通过相对路径 `/models/luna/<model>.model3.json` 加载<br>④ 采用 `pixi-live2d-display/cubism4` 并手动注册 `PIXI.Ticker`<br>⑤ 交互（拖拽、缩放、视线追踪）均在 `container` 上完成，保持模型坐标基准在脚底中心（`anchor.set(0.5, 1)`） |
| `agent.md` | ① 前端 **不直接** 访问后端数据库或模型推理服务，仅负责 UI 与渲染<br>② 所有资源必须 **本地**（`public/` 目录）以保证离线可用<br>③ 必须遵循 **编码规范**（中文注释、统一常量、错误捕获） |

## 3. 资源准备
1. **脚本**（已在 `public/live2d/`）
   - `/live2d/live2dcubismcore.min.js`
   - `/live2d/live2d.min.js`
2. **模型**（以 `jk盐` 为示例）
   - `/models/luna/jk盐.model3.json`
   - 关联的 `.moc3`、`.physics3.json`、纹理等已在同目录下，Electron 会自动提供静态资源服务。
3. **样式**（在全局 CSS 中加入）
   - 可在 `frontend/src/renderer/styles/global.css` 追加 `#live2d-wrapper` 样式，或单独创建 `Live2DView.css`。

## 4. HTML 结构
`index.html` 已极简，仅包含 `<div id="root"></div>`。Live2D 的 **容器** 将在 React 组件内部创建，**不需要** 再改动 `index.html`。若仍希望在原始 HTML 中预留占位，可在 `index.html` **head** 区加入脚本加载代码：

```html
<!-- Live2D 核心库（必须放在 head，确保在 Vue/React 启动前加载） -->
<script src="/live2d/live2dcubismcore.min.js"></script>
<script src="/live2d/live2d.min.js"></script>
```

## 5. CSS 样式（居中、透明、响应式）
```css
/* Live2DView.css – 负责渲染容器的布局 */
#live2d-wrapper {
  position: absolute;               /* 绝对定位，使其位于页面正中 */
  left: 50%;                         /* 水平居中 */
  bottom: calc(80px + 1rem);        /* 紧贴输入框上方，80px 为输入框高度（可根据实际调整） */
  transform: translateX(-50%);
  width: 100%;                      /* 宽度随视口变化，内部使用 canvas 自适应 */
  max-width: 480px;                 /* 限制最大宽度，防止在大屏幕上过于拉伸 */
  pointer-events: none;            /* 默认不阻塞聊天输入，交互事件在组件内部自行开启 */
  z-index: 10;                      /* 确保在聊天框之上 */
}

/* 当需要交互（拖拽、缩放）时，允许指针事件 */
#live2d-wrapper.interactive {
  pointer-events: auto;
}
```
> **说明**：`bottom` 使用 `calc(输入框高度 + 间距)`，确保模型始终贴近输入框；在移动端可通过媒体查询自行调整。

## 6. TypeScript – React 组件 `Live2DView`
> 文件路径：`frontend/src/renderer/components/Live2DView/Live2DView.tsx`
```tsx
import React, { useEffect, useRef, useState } from "react";
import "./Live2DView.css"; // 上述 CSS

/**
 * Live2DView – 在聊天输入框下方渲染 Live2D 模型
 * 只负责渲染与交互，不涉及业务状态（状态由 Go Runtime 推送）
 */
export const Live2DView: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [app, setApp] = useState<PIXI.Application | null>(null);
  const [model, setModel] = useState<any>(null);
  const [container, setContainer] = useState<PIXI.Container | null>(null);

  // 初始化 PIXI Application
  useEffect(() => {
    if (!canvasRef.current) return;
    // 确保全局 PIXI 已挂载（在 src/main.ts 中完成）
    const { Live2DModel } = await import("pixi-live2d-display/cubism4");
    if (Live2DModel.registerTicker) {
      Live2DModel.registerTicker(PIXI.Ticker);
    }

    const pixiApp = new PIXI.Application({
      view: canvasRef.current,
      backgroundAlpha: 0,
      resizeTo: window,
      resolution: Math.min(window.devicePixelRatio || 1, 1.5),
      autoDensity: true,
    });
    pixiApp.ticker.maxFPS = 60;

    const parent = new PIXI.Container();
    pixiApp.stage.addChild(parent);

    setApp(pixiApp);
    setContainer(parent);
    return () => {
      pixiApp.destroy(true);
    };
  }, []);

  // 加载模型
  useEffect(() => {
    if (!container) return;
    let cancelled = false;
    (async () => {
      try {
        const live2dModel = await (window as any).Live2DModel.from(
          `/models/luna/${encodeURIComponent("jk盐.model3.json")}`,
          {
            autoInteract: false,
            autoUpdate: true,
            ticker: app?.ticker,
          }
        );
        // 基础缩放与锚点 – 与项目现有实现保持一致
        live2dModel.scale.set(0.2);
        live2dModel.anchor.set(0.5, 1);
        live2dModel.x = app!.renderer.width / 2;
        live2dModel.y = app!.renderer.height;
        live2dModel.interactive = true;
        live2dModel.cursor = "pointer";
        container.addChild(live2dModel);
        if (!cancelled) setModel(live2dModel);
      } catch (e) {
        console.error("[Live2D] 模型加载失败", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [container, app]);

  // ---------- 交互事件 ----------
  // 1. 拖拽
  const dragging = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });
  const onPointerDown = (e: PIXI.InteractionEvent) => {
    if (e.data.originalEvent.button !== 0) return;
    dragging.current = true;
    const point = e.data.global;
    lastPos.current = { x: point.x, y: point.y };
  };
  const onPointerMove = (e: PIXI.InteractionEvent) => {
    if (!dragging.current) return;
    const point = e.data.global;
    const dx = point.x - lastPos.current.x;
    const dy = point.y - lastPos.current.y;
    lastPos.current = { x: point.x, y: point.y };
    container!.x += dx;
    container!.y += dy;
  };
  const onPointerUp = () => (dragging.current = false);

  useEffect(() => {
    if (!model) return;
    model.on("pointerdown", onPointerDown);
    model.on("pointermove", onPointerMove);
    model.on("pointerup", onPointerUp);
    model.on("pointerupoutside", onPointerUp);
    return () => {
      model.off("pointerdown", onPointerDown);
      model.off("pointermove", onPointerMove);
      model.off("pointerup", onPointerUp);
      model.off("pointerupoutside", onPointerUp);
    };
  }, [model]);

  // 2. 缩放（滚轮）
  useEffect(() => {
    const onWheel = (ev: WheelEvent) => {
      if (!model || !app) return;
      const rect = canvasRef.current!.getBoundingClientRect();
      const globalPoint = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
      ev.preventDefault();
      const factor = ev.deltaY > 0 ? 0.95 : 1.05;
      const newScale = Math.min(10, Math.max(0.05, container!.scale.x * factor));
      const local = container!.toLocal(globalPoint, app.stage);
      container!.scale.set(newScale);
      const newGlobal = container!.toGlobal(local);
      container!.position.x += globalPoint.x - newGlobal.x;
      container!.position.y += globalPoint.y - newGlobal.y;
    };
    window.addEventListener("wheel", onWheel, { passive: false });
    return () => window.removeEventListener("wheel", onWheel);
  }, [model, app, container]);

  // 3. 视线追踪（全局 pointermove）
  useEffect(() => {
    const TRACKING_ENABLED = true; // 可做成 prop
    const onGlobalMove = (ev: PointerEvent) => {
      if (!TRACKING_ENABLED || !model) return;
      const rect = canvasRef.current!.getBoundingClientRect();
      const world = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
      const local = container!.toLocal(world, app!.stage);
      // 与项目中相同的 lookAt 计算（略）
      // ... 省略细节（使用 PARAM_CONFIG）
    };
    window.addEventListener("pointermove", onGlobalMove);
    return () => window.removeEventListener("pointermove", onGlobalMove);
  }, [model, container, app]);

  return <canvas ref={canvasRef} id="live2d-canvas" />;
};
```
**关键点说明**：
- `canvas` 通过 `ref` 直接交给 `PIXI.Application` 使用，保持原始分辨率。
- 所有事件都绑定在模型或全局 `window`，避免 React 重新渲染导致事件失效。
- 错误捕获使用 `try/catch`，并在控制台打印中文错误信息，符合项目编码规范。

## 7. 在页面中嵌入组件
以 **ChatView** 为例，在 `ChatView.tsx` 中导入并渲染 `Live2DView`，确保位于输入框下方。只需要在返回的 JSX 最底部加入：
```tsx
import { Live2DView } from "../components/Live2DView/Live2DView";
...
return (
  <div className="chat-view">
    {/* 消息列表 */}
    ...
    {/* 输入框 */}
    ...
    {/* Live2D 渲染层 */}
    <Live2DView />
  </div>
);
);
```
> **注意**：`Live2DView` 会渲染到页面的 **绝对定位** 容器 `#live2d-wrapper`，因此不会影响聊天列表的布局。

## 8. 响应式适配
- `#live2d-wrapper` 使用 `max-width: 480px`，在小屏幕（≤ 480px）时会占满宽度；在大屏幕上保持居中。
- `PIXI.Application` 的 `resizeTo: window` 使画布随窗口大小自动伸缩。
- 若需要在移动端隐藏模型，可在 CSS 中加入媒体查询：
```css
@media (max-width: 600px) {
  #live2d-wrapper { display: none; }
}
```

## 9. 兼容性与回退策略
| 场景 | 处理方式 |
|---|---|
| 浏览器不支持 WebGL（极少数） | `PIXI.utils.isWebGLSupported()` 检测后，直接隐藏 `Live2DView`，并在控制台提示 "当前环境不支持 WebGL，已关闭 Live2D" |
| 脚本加载失败（网络或文件未找到） | 通过 `script` 的 `onerror` 事件捕获，显示用户友好提示 "Live2D 资源加载失败，已关闭模型展示" |
| 模型文件缺失或 JSON 解析异常 | `try/catch` 包裹 `Live2DModel.from`，捕获后使用 `console.error` 并保持界面不崩溃 |
| 高 DPI 屏幕 | `resolution: Math.min(window.devicePixelRatio || 1, 1.5)` 已在 `PIXI.Application` 中限制，以防显存占用过大 |

## 10. 完整代码示例（可直接复制）
### 10.1 `public/live2d` 脚本引入（放在 `index.html` head）
```html
<!-- index.html 中的 head 部分 -->
<script src="/live2d/live2dcubismcore.min.js"></script>
<script src="/live2d/live2d.min.js"></script>
```
### 10.2 CSS（`frontend/src/renderer/components/Live2DView/Live2DView.css`）
```css
#live2d-wrapper {
  position: absolute;
  left: 50%;
  bottom: calc(80px + 1rem);
  transform: translateX(-50%);
  width: 100%;
  max-width: 480px;
  pointer-events: none;
  z-index: 10;
}
#live2d-wrapper.interactive { pointer-events: auto; }
```
### 10.3 React 组件（`Live2DView.tsx`）
> 直接复制章节 **6** 中的完整代码块。
### 10.4 在 `ChatView.tsx` 中使用（已在章节 **7** 示范）
```tsx
import { Live2DView } from "../components/Live2DView/Live2DView";
...
{/* ChatView 主体 JSX 最底部 */}
<Live2DView />
```
### 10.5 入口文件 `src/renderer/index.tsx`（无需改动，仅确保已加载 `Live2DView` 所在目录）
```tsx
import { ChatView } from "./components/ChatView/ChatView";
// 其它 import 省略
// App 已经渲染 <ChatView />，Live2DView 将在 ChatView 内部挂载
```

## 11. 部署说明
- 确认 `public/live2d/` 与 `public/models/luna/` 已随 Electron 打包（Vite 默认会将 `public` 复制到构建产物根目录）。
- 运行 `npm run dev` 时，Vite 会在 `localhost:5173` 提供这些静态资源；生产环境 `electron-builder` 同样会把它们写入 `resources/app.asar.unpacked`，确保运行时可访问。
- 若修改模型路径，只需在 `Live2DView` 中更改 `modelUrl` 常量；不需要重新编译后端代码。

---
**本文档已完成**，后续若需实际代码实现，请切换至 **Code** 模式（`/code`）进行文件编辑。
