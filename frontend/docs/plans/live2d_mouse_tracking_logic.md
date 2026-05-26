# Live2D 鼠标轨迹追踪与视线交互系统核心逻辑

本文档详细提取了项目中关于**鼠标轨迹追踪配置**与**视线交互系统**的完整代码实现，重点解析了用户配置追踪起点（追踪中心）后的鼠标追踪逻辑。

## 1. 核心状态与变量定义

在 `src/views/index/index.vue` 中，定义了用于控制追踪模式、存储追踪起点偏移量以及可视化标记的变量。

```javascript
// 是否处于追踪设置模式
const isTrackingSetupMode = ref(false); 
// 是否启用视线追踪
const trackingEnabled = ref(true);      

// 本地存储 Key，用于持久化追踪起点
const TRACKING_ORIGIN_KEY = "luna:tracking-origin"; 

// 追踪中心点偏移量（核心变量：记录用户设定的模型上的基准点）
let trackingOriginOffset = { x: 0, y: 0 }; 
// 追踪中心点的红色可视化标记 (PIXI.Graphics)
let trackingMarker = null;                 
```

## 2. 用户配置追踪起点逻辑

用户可以通过 UI 触发追踪设置模式。在设置模式下，点击模型表面即可设定新的追踪起点。

```javascript
// 切换追踪设置模式
function toggleTrackingSetupMode() {
  if (isSetupMode.value) isSetupMode.value = false;
  isTrackingSetupMode.value = !isTrackingSetupMode.value;
  
  if (isTrackingSetupMode.value) {
    drawTrackingMarker(); // 开启时绘制红色标记
  } else {
    if (trackingMarker) trackingMarker.visible = false; // 关闭时隐藏标记
    // 退出设置模式时，将当前设定的追踪起点保存到本地存储
    localStorage.setItem(TRACKING_ORIGIN_KEY, JSON.stringify(trackingOriginOffset));
  }
}

// 重置追踪中心点为默认值 (0, 0)
function resetTrackingOrigin() {
  trackingOriginOffset = { x: 0, y: 0 };
  localStorage.setItem(TRACKING_ORIGIN_KEY, JSON.stringify(trackingOriginOffset));
  if (isTrackingSetupMode.value) {
    drawTrackingMarker();
  }
  appearance.showAppearanceHint("追踪中心已重置");
}

// 绘制追踪中心标记（红点）
function drawTrackingMarker() {
  if (!container) return;
  if (!trackingMarker) {
    trackingMarker = new PIXI.Graphics();
    container.addChild(trackingMarker);
  }
  trackingMarker.clear();
  trackingMarker.beginFill(0xff0000);
  trackingMarker.drawCircle(0, 0, 10);
  trackingMarker.endFill();
  // 将标记放置在当前设定的偏移量位置
  trackingMarker.position.set(trackingOriginOffset.x, trackingOriginOffset.y);
  trackingMarker.visible = true;
}

// 监听模型点击事件，用于在设置模式下更新追踪中心点
function onPointerDown(e) {
  if (e.button !== 0) return;

  if (isTrackingSetupMode.value) {
    // 【关键】将全局鼠标坐标转换为模型容器内的局部坐标
    const localPoint = container.toLocal(e.global);
    // 更新追踪起点偏移量
    trackingOriginOffset = { x: localPoint.x, y: localPoint.y };
    drawTrackingMarker();
    return;
  }
  // ... 其他拖拽逻辑
}
```

## 3. 鼠标追踪核心逻辑（重点）

这是系统最核心的部分。当鼠标在屏幕上移动时，系统会计算鼠标当前位置相对于**用户配置的追踪起点 (`trackingOriginOffset`)** 的偏移，并将其映射到 Live2D 模型的头部和眼球参数上。

```javascript
// Live2D 视线相关参数配置及有效范围
const PARAM_CONFIG = {
  HEAD_X: { param: "ParamAngleX", range: [-30, 30] }, // 头部左右旋转
  HEAD_Y: { param: "ParamAngleY", range: [-30, 30] }, // 头部上下旋转
  EYE_X: { param: "ParamEyeBallX", range: [-1, 1] },  // 眼球左右转动
  EYE_Y: { param: "ParamEyeBallY", range: [-1, 1] },  // 眼球上下转动
};

// 应用视线跟随算法
// dx, dy 为鼠标当前在模型容器内的局部坐标
function applyLookAt(dx, dy) {
  const core = getCoreModel();
  if (!core) return;

  // 【核心逻辑 1：计算相对偏移】
  // 目标位置 = 当前鼠标局部坐标 - 用户设定的追踪起点坐标
  // 这样可以保证当鼠标停留在追踪起点时，模型视线正视前方 (偏移为 0)
  const targetX = dx - trackingOriginOffset.x;
  const targetY = dy - trackingOriginOffset.y;

  // 【核心逻辑 2：坐标归一化】
  // 将偏移量归一化到 [-1, 1] 的区间。
  // 除以 (app.renderer.width / 2) 是为了根据屏幕尺寸计算相对比例。
  // 注意 Y 轴方向通常是反的，所以加了负号。
  const nx = Math.max(-1, Math.min(1, targetX / (app.renderer.width / 2)));
  const ny = -Math.max(-1, Math.min(1, targetY / (app.renderer.height / 2)));
  
  // 【核心逻辑 3：参数映射】
  // 映射函数：将 [-1, 1] 的归一化值映射到 Live2D 参数的实际物理范围
  const mapRange = (v, [min, max]) => min + ((v + 1) / 2) * (max - min);
  
  try {
    // 将计算出的值应用到 Live2D 核心模型参数上
    core.setParameterValueById(PARAM_CONFIG.EYE_X.param, mapRange(nx, PARAM_CONFIG.EYE_X.range));
    core.setParameterValueById(PARAM_CONFIG.EYE_Y.param, mapRange(ny, PARAM_CONFIG.EYE_Y.range));
    core.setParameterValueById(PARAM_CONFIG.HEAD_X.param, mapRange(nx, PARAM_CONFIG.HEAD_X.range));
    core.setParameterValueById(PARAM_CONFIG.HEAD_Y.param, mapRange(ny, PARAM_CONFIG.HEAD_Y.range));
  } catch {}
}

// 节流控制，限制计算频率，避免性能问题 (33ms 约等于 30fps)
const LOOKAT_THROTTLE_MS = 33; 
let lastLookAtAt = 0;

// 全局鼠标移动监听器
function onGlobalPointerMove(ev) {
  // 如果未启用追踪、模型未加载或模型不可见，则不处理
  if (!trackingEnabled.value || !model || !modelVisible.value) return;

  const now = performance.now();
  if (now - lastLookAtAt < LOOKAT_THROTTLE_MS) return;
  lastLookAtAt = now;

  // 获取画布在视口中的边界信息
  const rect = canvasRef.value.getBoundingClientRect();
  
  // 计算鼠标在画布上的世界坐标 (相对于画布左上角)
  const world = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
  
  // 【关键】将世界坐标转换为模型容器内的局部坐标
  const local = container.toLocal(world, app.stage);
  
  // 执行视线跟随算法
  applyLookAt(local.x, local.y);
}
```

## 4. 初始化与事件绑定

在组件挂载时，需要恢复用户之前保存的追踪起点，并绑定相关的鼠标事件。

```javascript
onMounted(async () => {
  // ... PIXI 初始化代码 ...
  
  // 绑定全局鼠标移动事件到包裹层
  wrapperRef.value.addEventListener("pointermove", onGlobalPointerMove);
  
  // ... 模型加载代码 ...
  
  // 绑定模型点击事件，用于设置追踪起点
  model.on("pointerdown", onPointerDown); 

  // 【恢复配置】从本地存储读取并恢复用户设定的追踪起点
  const savedOrigin = localStorage.getItem(TRACKING_ORIGIN_KEY);
  if (savedOrigin) {
    try { 
      trackingOriginOffset = JSON.parse(savedOrigin); 
    } catch {}
  }
});
```

## 总结：追踪起点配置后的逻辑流转

1. **用户配置**：用户在设置模式下点击模型，触发 `onPointerDown`，系统记录点击位置的局部坐标到 `trackingOriginOffset`。
2. **鼠标移动**：用户移动鼠标，触发 `onGlobalPointerMove`。
3. **坐标转换**：系统将鼠标的屏幕坐标转换为模型容器的局部坐标 `local`。
4. **计算相对偏移**：在 `applyLookAt` 中，计算 `local` 与 `trackingOriginOffset` 的差值 (`targetX`, `targetY`)。这一步确保了视线是相对于用户设定的中心点进行偏移的。
5. **归一化与映射**：将偏移量归一化为 `[-1, 1]` 的比例值，然后映射到 Live2D 模型的头部和眼球参数范围内。
6. **应用参数**：调用 `core.setParameterValueById` 更新模型姿态，实现视线跟随。