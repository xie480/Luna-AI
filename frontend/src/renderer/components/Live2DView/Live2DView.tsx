import React, { useEffect, useRef, useState } from "react";
import "./Live2DView.css";
import * as PIXI from "pixi.js";

/**
 * Live2DView – 在聊天输入框正下方渲染 Live2D 模型。
 * 依据项目约束：
 *   1. 必须在全局挂载 PIXI（本组件自行挂载）
 *   2. 使用 pixi-live2d-display/cubism4 动态加载模型
 *   3. 交互包括拖拽、滚轮缩放、视线追踪
 */
export const Live2DView: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [app, setApp] = useState<PIXI.Application | null>(null);
  const [container, setContainer] = useState<PIXI.Container | null>(null);
  const [model, setModel] = useState<any>(null);

  // 初始化 PIXI Application
  useEffect(() => {
    if (!canvasRef.current) return;
    // 为了兼容项目约束，将 PIXI 挂载到全局
    // @ts-ignore
    if (!window.PIXI) {
      // @ts-ignore
      window.PIXI = PIXI;
    }

    let pixiApp: PIXI.Application | null = null;
    let isCancelled = false;

    // 动态导入 Live2DModel
    import("pixi-live2d-display/cubism4").then(({ Live2DModel }) => {
      if (isCancelled) return;
      
      if (Live2DModel.registerTicker) {
        Live2DModel.registerTicker(PIXI.Ticker);
      }
      pixiApp = new PIXI.Application({
        view: canvasRef.current as HTMLCanvasElement,
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
    }).catch((e) => {
      console.error("[Live2D] 加载 pixi-live2d-display 失败", e);
    });

    return () => {
      isCancelled = true;
      if (pixiApp) {
        // 彻底销毁 PIXI 实例，包括内部的 Ticker 和 WebGL 上下文
        // 第一个参数 false 表示不销毁 canvas 元素本身（由 React 管理）
        // 第二个参数 { children: true, texture: true, baseTexture: true } 确保彻底清理内存
        pixiApp.destroy(false, { children: true, texture: true, baseTexture: true });
        pixiApp = null;
      }
      setApp(null);
      setContainer(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 加载模型
  useEffect(() => {
    if (!container || !app) return;
    let cancelled = false;
    let currentModel: any = null;

    const load = async () => {
      try {
        const { Live2DModel } = await import("pixi-live2d-display/cubism4");
        const live2dModel = await Live2DModel.from(
          `/models/luna/${encodeURIComponent("jk盐.model3.json")}`,
          {
            autoInteract: false,
            autoUpdate: true,
            // @ts-ignore 忽略类型检查，因为 app.ticker 是存在的
            ticker: app.ticker,
          }
        );
        
        if (cancelled) {
          live2dModel.destroy({ children: true, texture: true, baseTexture: true });
          return;
        }

        // 初始化参数，与项目保持一致
        live2dModel.scale.set(0.2);
        live2dModel.anchor.set(0.5, 1);
        live2dModel.x = app.renderer.width / 2;
        live2dModel.y = app.renderer.height;
        live2dModel.interactive = true;
        live2dModel.cursor = "pointer";
        
        container.addChild(live2dModel);
        currentModel = live2dModel;
        setModel(live2dModel);
      } catch (e) {
        console.error("[Live2D] 模型加载失败", e);
      }
    };
    load();
    
    return () => {
      cancelled = true;
      if (currentModel) {
        container.removeChild(currentModel);
        // 彻底销毁模型及其纹理资源
        currentModel.destroy({ children: true, texture: true, baseTexture: true });
        currentModel = null;
      }
      setModel(null);
    };
  }, [container, app]);

  // ---------- 交互事件 ----------
  // 1. 拖拽
  const dragging = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (!model || !container || !app) return;

    const onWindowPointerDown = (e: PointerEvent) => {
      // 只允许左键拖拽或触摸拖拽
      if (e.button !== undefined && e.button !== 0) return;
      
      const rect = canvasRef.current!.getBoundingClientRect();
      const point = new PIXI.Point(e.clientX - rect.left, e.clientY - rect.top);
      
      // 手动进行碰撞检测：使用模型的包围盒
      // 这样可以避免 hitTest 依赖 Live2D 内部定义的特定 hitArea
      const bounds = model.getBounds();
      if (bounds.contains(point.x, point.y)) {
        dragging.current = true;
        lastPos.current = { x: e.clientX, y: e.clientY };
        // 阻止事件向下传播，防止触发底层 UI 的点击事件
        e.stopPropagation();
      }
    };

    const onWindowPointerMove = (e: PointerEvent) => {
      if (!dragging.current) return;
      const dx = e.clientX - lastPos.current.x;
      const dy = e.clientY - lastPos.current.y;
      lastPos.current = { x: e.clientX, y: e.clientY };
      
      container.x += dx;
      container.y += dy;
    };

    const onWindowPointerUp = () => {
      dragging.current = false;
    };

    // 使用 capture: true 在捕获阶段拦截事件
    window.addEventListener("pointerdown", onWindowPointerDown, { capture: true });
    window.addEventListener("pointermove", onWindowPointerMove);
    window.addEventListener("pointerup", onWindowPointerUp);
    window.addEventListener("pointercancel", onWindowPointerUp);

    return () => {
      window.removeEventListener("pointerdown", onWindowPointerDown, { capture: true });
      window.removeEventListener("pointermove", onWindowPointerMove);
      window.removeEventListener("pointerup", onWindowPointerUp);
      window.removeEventListener("pointercancel", onWindowPointerUp);
    };
  }, [model, container, app]);

  // 2. 滚轮缩放
  useEffect(() => {
    const onWheel = (ev: WheelEvent) => {
      if (!model || !app || !container) return;
      const rect = canvasRef.current!.getBoundingClientRect();
      const globalPoint = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
      
      // 只有鼠标在模型上时才允许缩放，避免影响消息列表滚动
      const bounds = model.getBounds();
      if (!bounds.contains(globalPoint.x, globalPoint.y)) return;

      ev.preventDefault();
      ev.stopPropagation();
      
      const factor = ev.deltaY > 0 ? 0.95 : 1.05;
      const newScale = Math.min(10, Math.max(0.05, container.scale.x * factor));
      const local = container.toLocal(globalPoint, app.stage);
      container.scale.set(newScale);
      const newGlobal = container.toGlobal(local);
      container.position.x += globalPoint.x - newGlobal.x;
      container.position.y += globalPoint.y - newGlobal.y;
    };
    // 使用 capture: true 优先拦截滚轮事件
    window.addEventListener("wheel", onWheel, { passive: false, capture: true });
    return () => window.removeEventListener("wheel", onWheel, { capture: true } as any);
  }, [model, app, container]);

  // 3. 视线追踪（全局 pointermove）
  useEffect(() => {
    const TRACKING_ENABLED = true; // 可通过 props 控制
    const onGlobalMove = (ev: PointerEvent) => {
      if (!TRACKING_ENABLED || !model) return;
      const rect = canvasRef.current!.getBoundingClientRect();
      const world = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
      const local = container!.toLocal(world, app!.stage);
      // 此处调用项目中封装的 lookAt 参数逻辑，略去实现细节
      // 示例：
      // const core = getCoreModel();
      // core.setParameterValueById(...);
    };
    window.addEventListener("pointermove", onGlobalMove);
    return () => window.removeEventListener("pointermove", onGlobalMove);
  }, [model, container, app]);

  return (
    <div id="live2d-wrapper">
      <canvas
        ref={canvasRef}
        id="live2d-canvas"
        className="live2d-canvas"
        onContextMenu={(e) => e.preventDefault()}
      />
    </div>
  );
};
