import React, { useEffect, useRef, useState } from "react";
// @ts-ignore
import "./Live2DView.css";
import * as PIXI from "pixi.js";
import { useSystemStore } from "../../stores/systemStore";

/**
 * Live2DView – 全屏渲染 Live2D 模型。
 * 依据项目约束：
 *   1. 必须在全局挂载 PIXI（已在 src/renderer/index.tsx 中完成）
 *   2. 使用 pixi-live2d-display/cubism4 动态加载模型
 *   3. 交互包括拖拽、滚轮缩放、视线追踪（全屏范围自由移动）
 *   4. 监听系统情绪状态，触发表情与动作
 *   5. 指针事件穿透：Canvas 自身不拦截事件，通过 window 捕获阶段精确碰撞检测，不影响底层 UI
 */
export const Live2DView: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [app, setApp] = useState<PIXI.Application | null>(null);
  const [container, setContainer] = useState<PIXI.Container | null>(null);
  const [model, setModel] = useState<any>(null);
  const [isWebGLSupported, setIsWebGLSupported] = useState<boolean>(true);
  const [isScriptLoaded, setIsScriptLoaded] = useState<boolean>(true);

  const currentEmotion = useSystemStore((state) => state.currentEmotion);
  const addSystemLog = useSystemStore((state) => state.addSystemLog);
  const live2dConfigMode = useSystemStore((state) => state.live2dConfigMode);
  const setLive2dConfigMode = useSystemStore((state) => state.setLive2dConfigMode);
  const showGlobalMessage = useSystemStore((state) => state.showGlobalMessage);

  const [trackingOriginOffset, setTrackingOriginOffset] = useState({ x: 0, y: 0 });

  // 1. 检查 WebGL 支持
  useEffect(() => {
    if (!PIXI.utils.isWebGLSupported()) {
      setIsWebGLSupported(false);
      addSystemLog("当前环境不支持 WebGL，已关闭 Live2D");
      return;
    }
  }, [addSystemLog]);


  // 初始化 PIXI Application
  useEffect(() => {
    if (!canvasRef.current || !isWebGLSupported || !isScriptLoaded) return;

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
        resizeTo: window, // 绑定到 window，实现全屏自适应
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
      addSystemLog(`[Live2D] 加载 pixi-live2d-display 失败: ${e.message}`);
    });

    return () => {
      isCancelled = true;
      if (pixiApp) {
        // 彻底销毁 PIXI 实例，包括内部的 Ticker 和 WebGL 上下文
        pixiApp.destroy(false, { children: true, texture: true, baseTexture: true });
        pixiApp = null;
      }
      setApp(null);
      setContainer(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isWebGLSupported, isScriptLoaded]);

  // 加载模型
  useEffect(() => {
    if (!container || !app) return;
    let cancelled = false;
    let currentModel: any = null;

    const TRANSFORM_KEY = "luna:transform";
    const TRACKING_KEY = "luna:tracking";

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

        // 初始化参数，调整为视觉协调的正常比例
        live2dModel.scale.set(0.15); // 调整缩放比例
        live2dModel.anchor.set(0.5, 0.5); // 使用中心锚点，方便全屏居中
        
        // 初始位置放在屏幕中下方
        live2dModel.x = app.renderer.width / 2;
        live2dModel.y = app.renderer.height / 2 + 150;

        // 尝试加载持久化的配置
        try {
          const rawTransform = localStorage.getItem(TRANSFORM_KEY);
          if (rawTransform) {
            const data = JSON.parse(rawTransform);
            if (typeof data.x === "number" && !isNaN(data.x)) container.x = data.x;
            if (typeof data.y === "number" && !isNaN(data.y)) container.y = data.y;
            if (typeof data.scale === "number" && !isNaN(data.scale) && data.scale > 0) {
              container.scale.set(data.scale);
            }
          }

          const rawTracking = localStorage.getItem(TRACKING_KEY);
          if (rawTracking) {
            const data = JSON.parse(rawTracking);
            if (typeof data.x === "number" && !isNaN(data.x) && typeof data.y === "number" && !isNaN(data.y)) {
              setTrackingOriginOffset({ x: data.x, y: data.y });
            }
          }
        } catch (e) {
          console.warn("[Live2D] 加载持久化配置失败", e);
        }
        
        // 关闭模型自带的交互，我们通过 window 捕获阶段手动处理
        live2dModel.interactive = false;
        
        container.addChild(live2dModel);
        currentModel = live2dModel;
        setModel(live2dModel);
        addSystemLog("Live2D 模型加载成功");
      } catch (e: any) {
        console.error("[Live2D] 模型加载失败", e);
        addSystemLog(`[Live2D] 模型加载失败: ${e.message}`);
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
  }, [container, app, addSystemLog]);

  // ---------- 交互事件（全屏范围自由移动，不影响底层 UI） ----------
  // 1. 拖拽
  const dragging = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (!model || !container || !app) return;

    const onPointerDown = (e: PointerEvent) => {
      if (e.pointerType === 'mouse' && e.button !== 0) return; // 仅响应鼠标左键或触摸
      
      const rect = canvasRef.current!.getBoundingClientRect();
      const point = new PIXI.Point(e.clientX - rect.left, e.clientY - rect.top);
      
      // 手动进行碰撞检测：使用模型的包围盒
      const bounds = model.getBounds();
      if (bounds.contains(point.x, point.y)) {
        if (live2dConfigMode === 'tracking') {
          // 鼠标追踪配置模式：记录点击位置为追踪锚点
          const local = container.toLocal(point, app.stage);
          setTrackingOriginOffset({ x: local.x, y: local.y });
          
          // 持久化追踪锚点
          const TRACKING_KEY = "luna:tracking";
          localStorage.setItem(TRACKING_KEY, JSON.stringify({ x: local.x, y: local.y }));
          
          showGlobalMessage('追踪锚点已更新', 2000);
          
          e.stopPropagation();
          e.preventDefault();
          return;
        }

        if (live2dConfigMode === 'transform') {
          dragging.current = true;
          lastPos.current = { x: e.clientX, y: e.clientY };
          // 阻止事件向下传播，防止触发底层 UI 的点击事件
          e.stopPropagation();
          e.preventDefault();
        }
      }
    };

    const onPointerMove = (e: PointerEvent) => {
      if (!dragging.current || live2dConfigMode !== 'transform') return;
      const dx = e.clientX - lastPos.current.x;
      const dy = e.clientY - lastPos.current.y;
      lastPos.current = { x: e.clientX, y: e.clientY };
      
      container.x += dx;
      container.y += dy;
      
      e.stopPropagation();
      e.preventDefault();
    };

    const onPointerUp = (e: PointerEvent) => {
      if (dragging.current) {
        dragging.current = false;
        e.stopPropagation();
        e.preventDefault();
      }
    };

    // 使用 capture: true 在捕获阶段拦截事件
    window.addEventListener("pointerdown", onPointerDown, { capture: true });
    window.addEventListener("pointermove", onPointerMove, { capture: true });
    window.addEventListener("pointerup", onPointerUp, { capture: true });
    window.addEventListener("pointercancel", onPointerUp, { capture: true });

    return () => {
      window.removeEventListener("pointerdown", onPointerDown, { capture: true });
      window.removeEventListener("pointermove", onPointerMove, { capture: true });
      window.removeEventListener("pointerup", onPointerUp, { capture: true });
      window.removeEventListener("pointercancel", onPointerUp, { capture: true });
    };
  }, [model, container, app, live2dConfigMode, showGlobalMessage]);

  // 2. 滚轮缩放
  useEffect(() => {
    const onWheel = (ev: WheelEvent) => {
      if (!model || !app || !container || live2dConfigMode !== 'transform') return;
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
  }, [model, app, container, live2dConfigMode]);

  // 3. 视线追踪（全局 pointermove）
  useEffect(() => {
    const TRACKING_ENABLED = true; // 可通过 props 控制
    const onGlobalMove = (ev: PointerEvent) => {
      if (!TRACKING_ENABLED || !model || !app || !container) return;
      const rect = canvasRef.current!.getBoundingClientRect();
      const world = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
      const local = container.toLocal(world, app.stage);
      
      // 引入自定义追踪原点偏移量
      const targetX = local.x - trackingOriginOffset.x;
      const targetY = local.y - trackingOriginOffset.y;

      // 调用 pixi-live2d-display 提供的 focus 方法实现视线追踪
      // focus 接受局部坐标 (x, y)
      model.focus(targetX, targetY);
    };
    window.addEventListener("pointermove", onGlobalMove);
    return () => window.removeEventListener("pointermove", onGlobalMove);
  }, [model, container, app, trackingOriginOffset]);

  // 4. 情绪状态监听与表情/动作触发
  useEffect(() => {
    if (!model) return;

    // 根据情绪状态映射到具体的表情或动作
    try {
      switch (currentEmotion) {
        case 'happy':
          model.expression('happy');
          break;
        case 'sad':
          model.expression('sad');
          break;
        case 'angry':
          model.expression('angry');
          break;
        case 'thinking':
          model.expression('thinking');
          break;
        case 'surprised':
          model.expression('surprised');
          break;
        case 'neutral':
        default:
          model.expression('neutral');
          break;
      }
    } catch (e) {
      console.warn(`[Live2D] 无法应用情绪状态 ${currentEmotion}`, e);
    }
  }, [model, currentEmotion]);

  // 保存立绘配置
  const handleSaveTransform = () => {
    if (!container) return;
    const TRANSFORM_KEY = "luna:transform";
    const data = { x: container.x, y: container.y, scale: container.scale.x };
    localStorage.setItem(TRANSFORM_KEY, JSON.stringify(data));
    showGlobalMessage('立绘配置已保存', 2000);
    setLive2dConfigMode('none');
  };

  // 退出配置模式
  const handleExitConfig = () => {
    setLive2dConfigMode('none');
    showGlobalMessage('已退出配置模式', 2000);
  };

  if (!isWebGLSupported || !isScriptLoaded) {
    return null; // 或者渲染一个兜底的 UI
  }

  return (
    <div id="live2d-wrapper" className={live2dConfigMode !== 'none' ? 'config-mode' : ''}>
      <canvas
        ref={canvasRef}
        id="live2d-canvas"
        className="live2d-canvas"
        onContextMenu={(e) => e.preventDefault()}
      />
      
      {/* 追踪锚点视觉反馈 */}
      {live2dConfigMode === 'tracking' && container && app && (
        <div
          className="tracking-anchor-indicator"
          style={{
            left: container.toGlobal(new PIXI.Point(trackingOriginOffset.x, trackingOriginOffset.y)).x,
            top: container.toGlobal(new PIXI.Point(trackingOriginOffset.x, trackingOriginOffset.y)).y,
          }}
        />
      )}

      {/* 配置模式操作面板 */}
      {live2dConfigMode !== 'none' && (
        <div className="live2d-config-panel">
          {live2dConfigMode === 'transform' && (
            <button className="config-btn save-btn" onClick={handleSaveTransform}>
              保存配置
            </button>
          )}
          <button className="config-btn exit-btn" onClick={handleExitConfig}>
            退出配置
          </button>
        </div>
      )}
    </div>
  );
};
