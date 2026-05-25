# Live2D 核心业务逻辑技术解析：模型初始化与视线追踪系统

## 1. 系统架构概述
本项目基于 `Vue 3` + `PIXI.js` + `pixi-live2d-display` 构建 Live2D 渲染与交互系统。整体架构分为渲染层、逻辑控制层和交互事件层。
- **渲染层**：由 `PIXI.Application` 提供 WebGL 渲染上下文，`PIXI.Container` 作为模型的挂载容器，支持全局的缩放与平移。
- **逻辑控制层**：负责 Live2D 模型的异步加载、尺寸设定、锚点分配以及状态（如位置、缩放比例）的本地持久化。
- **交互事件层**：通过监听 DOM 级别的 `pointermove` 事件，结合节流（Throttle）机制，将屏幕坐标转换为模型局部坐标，并映射到 Live2D Cubism Core 的具体参数（如 `ParamAngleX`, `ParamEyeBallX`）上，实现流畅的视线追踪。

## 2. 核心模块一：Live2D 模型初始化与坐标分配

### 2.1 渲染器与容器初始化
在组件挂载阶段（`onMounted`），系统首先初始化 PIXI 应用实例。为了保证高分屏下的清晰度，对 `resolution` 进行了适配，并限制了最大帧率以优化性能。

```javascript
// 挂载全局 PIXI 对象供 pixi-live2d-display 内部调用
window.PIXI = PIXI;
const { Live2DModel } = await import("pixi-live2d-display/cubism4");

if (Live2DModel.registerTicker) {
  Live2DModel.registerTicker(PIXI.Ticker);
}

// 初始化 PIXI 应用
app = new PIXI.Application({
  view: canvasRef.value,
  backgroundAlpha: 0, // 透明背景
  resizeTo: window,   // 自动响应窗口尺寸变化
  resolution: Math.min(window.devicePixelRatio || 1, 1.5), // 适配高分屏，限制最大分辨率防卡顿
  autoDensity: true,
});

if (app.ticker) {
  app.ticker.maxFPS = 60; // 限制最大帧率，降低 GPU 功耗
}

// 创建全局容器，用于承载模型并统一管理平移/缩放
container = new PIXI.Container();
container.visible = modelVisible.value;
app.stage.addChild(container);
```
**实现思路与上下文依赖**：
- 必须将 `PIXI` 挂载到 `window` 上，这是 `pixi-live2d-display` 插件的底层依赖要求。
- 使用独立的 `PIXI.Container` 而不是直接将模型挂载到 `app.stage`，是为了将“视口变换（平移、缩放）”与“模型自身属性”解耦。

### 2.2 模型加载与尺寸/位置设定
模型加载采用异步方式。加载完成后，系统会分配初始的缩放比例、锚点以及在画布中的绝对坐标。

```javascript
try {
  // 异步加载 Live2D 模型配置文件
  model = await Live2DModel.from(`/models/luna/${encodeURIComponent("jk盐.model3.json")}`, {
    autoInteract: false, // 关闭插件自带的交互，采用自定义视线追踪逻辑
    autoUpdate: true,
    ticker: app.ticker,
  });

  // 初始尺寸与位置分配
  model.scale.set(0.2); // 设定初始缩放比例
  model.anchor.set(0.5, 1); // 将锚点设置在模型底部中心 (x: 50%, y: 100%)
  
  // 坐标分配：水平居中，垂直贴底
  model.x = app.renderer.width / 2;
  model.y = app.renderer.height || window.innerHeight;
  
  model.interactive = true;
  model.cursor = "pointer";

  container.addChild(model);
} catch (e) {
  console.error("[Live2D] 模型加载失败", e);
  appearance.showAppearanceHint("模型加载失败，请检查文件路径");
}
```
**配置参数作用与边界条件**：
- `autoInteract: false`：关键配置。禁用了插件默认的鼠标跟随，以便我们在外部接管 `pointermove` 事件，实现更精细的节流控制和自定义坐标偏移（`trackingOriginOffset`）。
- `anchor.set(0.5, 1)`：将模型的原点定在底部中心。这确保了当窗口 `resize` 或模型 `scale` 变化时，模型始终“站”在屏幕底部，不会出现悬空或穿模现象。
- **异常处理**：使用 `try...catch` 包裹异步加载过程，若网络异常或 JSON 解析失败，会通过 `appearance.showAppearanceHint` 向用户抛出友好的 UI 提示，避免白屏死机。

### 2.3 状态持久化与恢复机制
为了保证用户体验，系统会将用户自定义的容器位置和缩放比例持久化到 `localStorage` 中。

```javascript
const TRANSFORM_KEY = "luna:transform";

function saveModelTransform() {
  if (!container) return;
  const data = { x: container.x, y: container.y, scale: container.scale.x };
  localStorage.setItem(TRANSFORM_KEY, JSON.stringify(data));
}

function loadModelTransform() {
  const raw = localStorage.getItem(TRANSFORM_KEY);
  if (raw && container) {
    try {
      const data = JSON.parse(raw);
      // 边界条件校验，防止脏数据导致渲染崩溃
      if (typeof data.x === "number" && !isNaN(data.x)) container.x = data.x;
      if (typeof data.y === "number" && !isNaN(data.y)) container.y = data.y;
      if (typeof data.scale === "number" && !isNaN(data.scale) && data.scale > 0) {
        container.scale.set(data.scale);
      }
    } catch {}
  }
}
```
**边界异常处理**：在 `loadModelTransform` 中，严格校验了反序列化后的数据类型（`typeof === "number"`）以及有效性（`!isNaN`，`scale > 0`）。这防止了由于本地存储被篡改或版本迭代导致的非法数值注入 PIXI 渲染管线，从而引发 `WebGL` 渲染崩溃。

---

## 3. 核心模块二：鼠标轨迹追踪与视线交互系统

### 3.1 事件绑定与节流控制
视线追踪属于高频触发事件，直接绑定会导致严重的性能问题（CPU 占用过高）。系统采用了基于 `performance.now()` 的时间戳节流方案。

```javascript
const LOOKAT_THROTTLE_MS = 33; // 约 30fps 的触发频率
let lastLookAtAt = 0;

function onGlobalPointerMove(ev) {
  // 前置状态校验
  if (!trackingEnabled.value || !model || !modelVisible.value) return;

  const now = performance.now();
  if (now - lastLookAtAt < LOOKAT_THROTTLE_MS) return;
  lastLookAtAt = now;

  // 获取画布在视口中的绝对位置
  const rect = canvasRef.value.getBoundingClientRect();
  // 计算鼠标在画布内的全局坐标
  const world = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
  // 将全局坐标转换为容器内的局部坐标
  const local = container.toLocal(world, app.stage);
  
  applyLookAt(local.x, local.y);
}

// 在 onMounted 中绑定事件
wrapperRef.value.addEventListener("pointermove", onGlobalPointerMove);
```
**数据流向解析**：
1. 捕获原生 DOM 事件 `ev.clientX/Y`。
2. 减去 Canvas 的边界偏移（`rect.left/top`），得到 PIXI 舞台（Stage）的全局坐标 `world`。
3. 通过 `container.toLocal(world, app.stage)` 将全局坐标转换为容器内部的局部坐标 `local`。这一步至关重要，它抵消了用户拖拽平移或缩放容器带来的坐标系偏移，确保视线追踪的焦点始终准确。

### 3.2 核心参数映射逻辑
获取到局部坐标后，需要将其归一化，并映射到 Live2D Cubism Core 的具体参数区间。

```javascript
const PARAM_CONFIG = {
  HEAD_X: { param: "ParamAngleX", range: [-30, 30] },
  HEAD_Y: { param: "ParamAngleY", range: [-30, 30] },
  EYE_X: { param: "ParamEyeBallX", range: [-1, 1] },
  EYE_Y: { param: "ParamEyeBallY", range: [-1, 1] },
  BREATH: { param: "ParamBreath", range: [0, 1] },
};

function applyLookAt(dx, dy) {
  const core = getCoreModel(); // 获取底层 Cubism Core 实例
  if (!core) return;

  // 引入自定义追踪原点偏移量
  const targetX = dx - trackingOriginOffset.x;
  const targetY = dy - trackingOriginOffset.y;

  // 坐标归一化处理，限制在 [-1, 1] 区间
  const nx = Math.max(-1, Math.min(1, targetX / (app.renderer.width / 2)));
  const ny = -Math.max(-1, Math.min(1, targetY / (app.renderer.height / 2))); // Y轴反转适配 Live2D 坐标系
  
  // 线性映射函数：将 [-1, 1] 映射到目标参数区间
  const mapRange = (v, [min, max]) => min + ((v + 1) / 2) * (max - min);
  
  try {
    core.setParameterValueById(PARAM_CONFIG.EYE_X.param, mapRange(nx, PARAM_CONFIG.EYE_X.range));
    core.setParameterValueById(PARAM_CONFIG.EYE_Y.param, mapRange(ny, PARAM_CONFIG.EYE_Y.range));
    core.setParameterValueById(PARAM_CONFIG.HEAD_X.param, mapRange(nx, PARAM_CONFIG.HEAD_X.range));
    core.setParameterValueById(PARAM_CONFIG.HEAD_Y.param, mapRange(ny, PARAM_CONFIG.HEAD_Y.range));
  } catch {}
}
```
**实现思路与边界条件**：
- **追踪原点偏移 (`trackingOriginOffset`)**：允许用户自定义模型的“视觉中心点”，而不是死板地以模型原点为中心。
- **归一化 (`nx`, `ny`)**：将屏幕坐标除以屏幕宽高的一半，得到 `[-1, 1]` 的相对坐标。注意 `ny` 进行了取反操作（`-Math.max(...)`），因为 Web 坐标系 Y 轴向下为正，而 Live2D 头部仰起的参数通常向上为正。
- **线性映射 (`mapRange`)**：将归一化后的 `[-1, 1]` 映射到 Live2D 规定的参数范围（如头部的 `[-30, 30]`，眼球的 `[-1, 1]`）。
- **异常处理**：`setParameterValueById` 被包裹在 `try...catch` 中。因为不同的 Live2D 模型可能缺少某些标准参数（如某些简易模型没有 `ParamEyeBallX`），静默捕获异常可以防止整个渲染循环崩溃。

## 4. 总结与开发建议
1. **性能优化**：当前的节流阈值设为 `33ms`（约 30fps），在保证交互流畅度的同时有效控制了性能开销。若在低端设备上运行，可考虑将阈值提升至 `50ms`。
2. **坐标系一致性**：在处理任何鼠标交互时，务必使用 `container.toLocal` 进行坐标系转换，这是兼容容器拖拽与缩放功能的核心基石。
3. **模型兼容性**：`PARAM_CONFIG` 中定义的参数 ID 为 Cubism 标准规范。若接入非标模型，需在加载后动态读取模型的参数列表，并建立参数别名映射表，以增强系统的鲁棒性。