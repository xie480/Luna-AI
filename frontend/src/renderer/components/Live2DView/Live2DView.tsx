import React, { useEffect, useRef, useState } from "react";
// @ts-ignore
import "./Live2DView.css";
import * as PIXI from "pixi.js";
import { useSystemStore } from "../../stores/systemStore";
import { setLive2dModel, clearLive2dModel } from "../../stores/live2dRef";
import { EMOTION_EXPRESSIONS } from "../../constants/emotionExpressions";

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

  const currentEmotion = useSystemStore((state) => state.currentEmotion);
  const addSystemLog = useSystemStore((state) => state.addSystemLog);
  const live2dConfigMode = useSystemStore((state) => state.live2dConfigMode);
  const setLive2dConfigMode = useSystemStore((state) => state.setLive2dConfigMode);
  const showGlobalMessage = useSystemStore((state) => state.showGlobalMessage);

  const [trackingOriginOffset, setTrackingOriginOffset] = useState({ x: 0, y: 0 });

  /**
   * 应用服装配置到模型
   * 遍历 clothingConfig，对已启用的项加载对应的 .exp3.json 并设置参数
   */
  const applySavedClothingConfig = async (live2dModel: any) => {
    if (!live2dModel || !live2dModel.internalModel || !live2dModel.internalModel.coreModel) {
      return;
    }

    try {
      const raw = localStorage.getItem('luna:clothing');
      if (!raw) return;

      const config = JSON.parse(raw);
      const enabledItems = Object.entries(config)
        .filter(([, enabled]) => enabled)
        .map(([id]) => id);

      for (const itemId of enabledItems) {
        try {
          const response = await fetch(`/models/luna/${encodeURIComponent(itemId + '.exp3.json')}`);
          if (!response.ok) continue;

          const expData = await response.json();
          if (!expData.Parameters || !Array.isArray(expData.Parameters)) continue;

          const core = live2dModel.internalModel.coreModel;
          for (const param of expData.Parameters) {
            if (typeof core.setParameterValueById === 'function') {
              if (param.Blend === 'Add') {
                const currentValue = core.getParameterValueById(param.Id);
                core.setParameterValueById(param.Id, currentValue + param.Value);
              } else {
                core.setParameterValueById(param.Id, param.Value);
              }
            }
          }
        } catch (e) {
          // 单个配置项失败不影响其他项
        }
      }

      addSystemLog(`已应用 ${enabledItems.length} 项已保存的服装配置`);
    } catch (e) {
      // 忽略配置解析错误
    }
  };

  // ---------- 初始化 PIXI ----------
  useEffect(() => {
    if (!PIXI.utils.isWebGLSupported()) {
      setIsWebGLSupported(false);
      addSystemLog("当前环境不支持 WebGL，已关闭 Live2D");
      return;
    }
  }, [addSystemLog]);

  useEffect(() => {
    if (!canvasRef.current || !isWebGLSupported) return;

    let pixiApp: PIXI.Application | null = null;
    let isCancelled = false;

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
      addSystemLog(`[Live2D] 加载 pixi-live2d-display 失败: ${e.message}`);
    });

    return () => {
      isCancelled = true;
      if (pixiApp) {
        pixiApp.destroy(false, { children: true, texture: true, baseTexture: true });
        pixiApp = null;
      }
      setApp(null);
      setContainer(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isWebGLSupported]);

  // ---------- 加载模型 ----------
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

        live2dModel.scale.set(0.15);
        live2dModel.anchor.set(0.5, 0.5);
        live2dModel.x = app.renderer.width / 2;
        live2dModel.y = app.renderer.height / 2 + 150;

        // 加载持久化的变换配置
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
        
        live2dModel.interactive = false;
        
        container.addChild(live2dModel);
        currentModel = live2dModel;
        setModel(live2dModel);

        // === 将模型引用共享到模块级单例 ===
        setLive2dModel(live2dModel);

        // === 模型加载完成后，应用已保存的服装配置 ===
        await applySavedClothingConfig(live2dModel);

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
        currentModel.destroy({ children: true, texture: true, baseTexture: true });
        currentModel = null;
      }
      setModel(null);
      // 清除共享的模型引用
      clearLive2dModel();
    };
  }, [container, app, addSystemLog]);

  // ---------- 交互事件 ----------
  const dragging = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (!model || !container || !app) return;

    const onPointerDown = (e: PointerEvent) => {
      const wrapper = document.getElementById('live2d-wrapper');
      if (!wrapper || !wrapper.contains(e.target as Node)) return;

      if (e.pointerType === 'mouse' && e.button !== 0) return;

      const rect = canvasRef.current!.getBoundingClientRect();
      const point = new PIXI.Point(e.clientX - rect.left, e.clientY - rect.top);
      
      const bounds = model.getBounds();
      if (bounds.contains(point.x, point.y)) {
        if (live2dConfigMode === 'tracking') {
          const local = container.toLocal(point, app.stage);
          setTrackingOriginOffset({ x: local.x, y: local.y });
          
          const TRACKING_KEY = "luna:tracking";
          localStorage.setItem(TRACKING_KEY, JSON.stringify({ x: local.x, y: local.y }));
          
          showGlobalMessage('追踪锚点已更新', 2000);
          
          e.stopPropagation();
          e.preventDefault();
          return;
        }

        dragging.current = true;
        lastPos.current = { x: e.clientX, y: e.clientY };
        e.stopPropagation();
        e.preventDefault();
      }
    };

    const onPointerMove = (e: PointerEvent) => {
      if (!dragging.current || live2dConfigMode === 'tracking') return;
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

  // ---------- 滚轮缩放 ----------
  useEffect(() => {
    const onWheel = (ev: WheelEvent) => {
      if (!model || !app || !container || live2dConfigMode !== 'transform') return;
      const rect = canvasRef.current!.getBoundingClientRect();
      const globalPoint = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
      
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
    window.addEventListener("wheel", onWheel, { passive: false, capture: true });
    return () => window.removeEventListener("wheel", onWheel, { capture: true } as any);
  }, [model, app, container, live2dConfigMode]);

  // ---------- 视线追踪 ----------
  useEffect(() => {
    const TRACKING_ENABLED = true;
    const LOOKAT_THROTTLE_MS = 33;
    let lastLookAtAt = 0;

    const PARAM_CONFIG = {
      HEAD_X: { param: "ParamAngleX", range: [-30, 30] as [number, number] },
      HEAD_Y: { param: "ParamAngleY", range: [-30, 30] as [number, number] },
      EYE_X: { param: "ParamEyeBallX", range: [-1, 1] as [number, number] },
      EYE_Y: { param: "ParamEyeBallY", range: [-1, 1] as [number, number] },
    };

    const applyLookAt = (dx: number, dy: number) => {
      if (!model || !model.internalModel || !model.internalModel.coreModel) return;
      const core = model.internalModel.coreModel;

      const targetX = dx - trackingOriginOffset.x;
      const targetY = dy - trackingOriginOffset.y;

      const nx = Math.max(-1, Math.min(1, targetX / (app!.renderer.width / 2)));
      const ny = -Math.max(-1, Math.min(1, targetY / (app!.renderer.height / 2)));

      const mapRange = (v: number, [min, max]: [number, number]) => min + ((v + 1) / 2) * (max - min);

      try {
        if (typeof core.setParameterValueById === 'function') {
          core.setParameterValueById(PARAM_CONFIG.EYE_X.param, mapRange(nx, PARAM_CONFIG.EYE_X.range));
          core.setParameterValueById(PARAM_CONFIG.EYE_Y.param, mapRange(ny, PARAM_CONFIG.EYE_Y.range));
          core.setParameterValueById(PARAM_CONFIG.HEAD_X.param, mapRange(nx, PARAM_CONFIG.HEAD_X.range));
          core.setParameterValueById(PARAM_CONFIG.HEAD_Y.param, mapRange(ny, PARAM_CONFIG.HEAD_Y.range));
        }
      } catch (e) {
        // ignore
      }
    };

    const onGlobalMove = (ev: PointerEvent) => {
      if (!TRACKING_ENABLED || !model || !app || !container) return;
      
      const now = performance.now();
      if (now - lastLookAtAt < LOOKAT_THROTTLE_MS) return;
      lastLookAtAt = now;

      const rect = canvasRef.current!.getBoundingClientRect();
      const world = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
      const local = container.toLocal(world, app.stage);
      
      applyLookAt(local.x, local.y);
    };
    
    window.addEventListener("pointermove", onGlobalMove);
    return () => window.removeEventListener("pointermove", onGlobalMove);
  }, [model, container, app, trackingOriginOffset]);

  // ---------- 情绪状态监听 ----------
  useEffect(() => {
    if (!model) return;

    let isCancelled = false;

    const applyExpressions = async () => {
      try {
        // 根据情绪映射表应用对应的表情列表
        if (currentEmotion === 'neutral') {
          model.expression('neutral');
        } else {
          const expressions = EMOTION_EXPRESSIONS[currentEmotion as keyof typeof EMOTION_EXPRESSIONS] ?? [];
          for (const exp of expressions) {
            if (isCancelled) break;
            try {
              model.expression(exp);
              // 增加微小延迟，确保底层 ExpressionManager 能正确处理并发表情
              await new Promise(resolve => setTimeout(resolve, 50));
            } catch (e) {
              console.warn(`[Live2D] 表情 ${exp} 应用失败`, e);
            }
          }
        }
      } catch (e) {
        console.warn(`[Live2D] 无法应用情绪状态 ${currentEmotion}`, e);
      }
    };

    applyExpressions();

    return () => {
      isCancelled = true;
    };
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

  // 重置追踪起点
  const handleResetTracking = () => {
    setTrackingOriginOffset({ x: 0, y: 0 });
    const TRACKING_KEY = "luna:tracking";
    localStorage.setItem(TRACKING_KEY, JSON.stringify({ x: 0, y: 0 }));
    showGlobalMessage('追踪起点已重置', 2000);
  };

  // 退出配置模式
  const handleExitConfig = () => {
    setLive2dConfigMode('none');
    showGlobalMessage('已退出配置模式', 2000);
  };

  if (!isWebGLSupported) {
    return null;
  }

  return (
    <>
      <div id="live2d-wrapper" className={live2dConfigMode !== 'none' ? 'config-mode' : ''}>
        <canvas
          ref={canvasRef}
          id="live2d-canvas"
          className="live2d-canvas"
          onContextMenu={(e) => e.preventDefault()}
        />
        
        {live2dConfigMode === 'tracking' && container && app && (
          <div
            className="tracking-anchor-indicator"
            style={{
              left: container.toGlobal(new PIXI.Point(trackingOriginOffset.x, trackingOriginOffset.y)).x,
              top: container.toGlobal(new PIXI.Point(trackingOriginOffset.x, trackingOriginOffset.y)).y,
            }}
          />
        )}
      </div>

      {live2dConfigMode !== 'none' && (
        <>
          <div className="live2d-config-status-bar">
            {live2dConfigMode === 'transform' ? '当前正在配置立绘' : '当前正在配置鼠标追踪点'}
          </div>
          <div className="live2d-config-panel">
            {live2dConfigMode === 'transform' && (
              <button className="config-btn save-btn" onClick={handleSaveTransform}>
                保存配置
              </button>
            )}
            {live2dConfigMode === 'tracking' && (
              <button className="config-btn save-btn" onClick={handleResetTracking}>
                重置起点
              </button>
            )}
            <button className="config-btn exit-btn" onClick={handleExitConfig}>
              退出配置
            </button>
          </div>
        </>
      )}
    </>
  );
};
