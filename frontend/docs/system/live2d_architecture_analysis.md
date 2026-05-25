# Live2D 架构与实现深度解析文档

本文档对当前项目中 Live2D 相关的核心逻辑、业务代码及配置文件进行了深度静态扫描和上下文分析。内容涵盖了从环境准备、模型初始化、用户交互、动画与表情管理到资源释放的完整生命周期。

---

## 1. 环境准备与资源预加载

Live2D 的运行依赖于底层的 Cubism Core 和 PIXI.js 渲染引擎。在本项目中，环境准备分为 HTML 脚本引入和 Vue 全局变量挂载两步。

### 1.1 引入 Cubism Core 脚本
在 [`index.html`](index.html:8) 中，必须在 Vue 应用启动前加载 Live2D 的核心库。

```html
<!-- index.html -->
<!-- [Fix] 必須放在 head 中，確保在 Vue 應用啟動前加載完畢 -->
<script src="/live2d/live2dcubismcore.min.js"></script>
<script src="/live2d/live2d.min.js"></script>
```
**解析**：`live2dcubismcore.min.js` 是 Live2D 官方提供的底层 C++ 核心的 WebAssembly/JS 封装，负责解析 `.moc3` 模型文件和计算顶点数据。`live2d.min.js` 可能是旧版或辅助脚本。必须在 `<head>` 中同步加载，确保后续 `pixi-live2d-display` 插件初始化时能找到全局的 `Live2DCubismCore` 对象。

### 1.2 挂载 PIXI 全局变量
在 [`src/main.js`](src/main.js:7) 中，将 PIXI 暴露给全局 `window` 对象。

```javascript
// src/main.js
import * as PIXI from "pixi.js";

// 确保 PIXI 在全局可用，这是 pixi-live2d-display 正常工作的前提
// 必须在任何组件 import pixi-live2d-display 之前执行
window.PIXI = PIXI;
```
**解析**：`pixi-live2d-display` 插件在内部会尝试访问全局的 `PIXI` 对象来注册中间件和扩展功能。如果在引入插件前没有设置 `window.PIXI`，会导致插件初始化失败或报错。

---

## 2. 模型初始化与画布渲染

模型的核心渲染逻辑集中在 [`src/views/index/index.vue`](src/views/index/index.vue:1575) 中（注：`src/components/Live2DView.vue` 目前被注释掉，实际使用的是 `index.vue` 中的实现）。

### 2.1 PIXI Application 初始化
在 `onMounted` 生命周期中，创建 PIXI 应用并挂载到 DOM。

```javascript
// src/views/index/index.vue
onMounted(async () => {
  loadTheme();

  window.PIXI = PIXI;
  const { Live2DModel } = await import("pixi-live2d-display/cubism4");

  if (Live2DModel.registerTicker) {
    Live2DModel.registerTicker(PIXI.Ticker);
  }

  app = new PIXI.Application({
    view: canvasRef.value,
    backgroundAlpha: 0,
    resizeTo: window,
    resolution: Math.min(window.devicePixelRatio || 1, 1.5),
    autoDensity: true,
  });

  if (app.ticker) {
    app.ticker.maxFPS = 60;
  }

  container = new PIXI.Container();
  container.visible = modelVisible.value;
  app.stage.addChild(container);
  
  // ... 事件监听绑定 ...
});
```
**解析**：
- 动态导入 `pixi-live2d-display/cubism4`，按需加载 Cubism 4 版本的解析器。
- `registerTicker` 将 PIXI 的更新循环绑定到 Live2D 模型，驱动动画播放。
- 创建 `PIXI.Application`，绑定到 `<canvas ref="canvasRef">`，设置透明背景和自适应缩放。
- 创建一个 `PIXI.Container` 作为模型的父容器，方便统一控制缩放和位移。

### 2.2 模型加载与挂载
加载 `.model3.json` 配置文件，并设置初始状态。

```javascript
// src/views/index/index.vue
  try {
    model = await Live2DModel.from(`/models/luna/${encodeURIComponent("jk盐.model3.json")}`, {
      autoInteract: false,
      autoUpdate: true,
      ticker: app.ticker,
    });

    model.scale.set(0.2);
    model.anchor.set(0.5, 1);
    model.x = app.renderer.width / 2;
    model.y = app.renderer.height || window.innerHeight;
    model.interactive = true;
    model.cursor = "pointer";

    if (!lunaIntroVisible.value && loginSuccess.value) {
      model.alpha = 1;
    } else {
      model.alpha = 0;
      model.y += 60;
    }

    model
      .on("pointerdown", onPointerDown)
      .on("pointermove", onPointerMove)
      .on("pointerup", onPointerUp)
      .on("pointerupoutside", onPointerUp);

    model.on("pointerover", modelEnter);
    model.on("pointerout", modelLeave);

    container.addChild(model);

    const savedOrigin = localStorage.getItem(TRACKING_ORIGIN_KEY);
    if (savedOrigin) {
      try { trackingOriginOffset = JSON.parse(savedOrigin); } catch {}
    }

    await waitForModelReady(5000);
    loadModelTransform();

    appearance.loadAppearanceState();

    await nextTick();
    await appearance.applyAllEnabled(getCoreModel());
    await applyEmotionExpressions(INITIAL_EMOTION);
  } catch (e) {
    console.error("[Live2D] 妯″瀷鍔犺浇澶辫触", e);
    appearance.showAppearanceHint("模型加载失败，请检查文件路径");
  }
```
**解析**：
- `Live2DModel.from` 解析模型配置文件，自动加载纹理、物理、表情等依赖资源。
- `autoInteract: false` 关闭了插件自带的视线追踪，因为项目中实现了更精细的自定义视线追踪逻辑。
- 锚点 `(0.5, 1)` 确保模型以脚底中心为基准进行缩放和定位，符合人物站立的物理直觉。

---

## 3. 用户交互与事件监听

项目实现了丰富的交互功能，包括拖拽移动、滚轮缩放和视线追踪。

### 3.1 拖拽与缩放 (Transform)
通过监听 PIXI 容器和全局 DOM 事件实现。

```javascript
// src/views/index/index.vue
let dragging = false;
let lastPos = { x: 0, y: 0 };

function onPointerDown(e) {
  if (e.button !== 0) return;

  if (isTrackingSetupMode.value) {
    const localPoint = container.toLocal(e.global);
    trackingOriginOffset = { x: localPoint.x, y: localPoint.y };
    drawTrackingMarker();
    return;
  }

  dragging = true;
  lastPos = { x: e.global.x, y: e.global.y };
}

function onPointerMove(e) {
  if (!dragging) return;
  const dx = e.global.x - lastPos.x;
  const dy = e.global.y - lastPos.y;
  lastPos = { x: e.global.x, y: e.global.y };
  container.x += dx;
  container.y += dy;
}

function onPointerUp() {
  dragging = false;
}

function onWheel(ev) {
  if (!model || !app) return;
  if (!overModel) return;

  const rect = canvasRef.value.getBoundingClientRect();
  const globalPoint = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);

  ev.preventDefault();
  const factor = ev.deltaY > 0 ? 0.95 : 1.05;
  const newScale = Math.min(10, Math.max(0.05, container.scale.x * factor));
  const localPoint = container.toLocal(globalPoint, app.stage);
  container.scale.set(newScale);
  const newGlobal = container.toGlobal(localPoint);
  container.position.x += globalPoint.x - newGlobal.x;
  container.position.y += globalPoint.y - newGlobal.y;
}
```
**解析**：拖拽和缩放操作直接作用于 `container` 而不是 `model` 本身，这样可以保持模型相对于容器的局部坐标不变，便于管理。缩放逻辑包含了以鼠标当前位置为中心的复杂坐标换算。

### 3.2 视线追踪 (LookAt)
自定义的视线追踪逻辑，通过修改 Live2D 核心参数实现。

```javascript
// src/views/index/index.vue
const PARAM_CONFIG = {
  HEAD_X: { param: "ParamAngleX", range: [-30, 30] },
  HEAD_Y: { param: "ParamAngleY", range: [-30, 30] },
  EYE_X: { param: "ParamEyeBallX", range: [-1, 1] },
  EYE_Y: { param: "ParamEyeBallY", range: [-1, 1] },
  BREATH: { param: "ParamBreath", range: [0, 1] },
};

function applyLookAt(dx, dy) {
  const core = getCoreModel();
  if (!core) return;

  const targetX = dx - trackingOriginOffset.x;
  const targetY = dy - trackingOriginOffset.y;

  const nx = Math.max(-1, Math.min(1, targetX / (app.renderer.width / 2)));
  const ny = -Math.max(-1, Math.min(1, targetY / (app.renderer.height / 2)));
  const mapRange = (v, [min, max]) => min + ((v + 1) / 2) * (max - min);
  try {
    core.setParameterValueById(PARAM_CONFIG.EYE_X.param, mapRange(nx, PARAM_CONFIG.EYE_X.range));
    core.setParameterValueById(PARAM_CONFIG.EYE_Y.param, mapRange(ny, PARAM_CONFIG.EYE_Y.range));
    core.setParameterValueById(PARAM_CONFIG.HEAD_X.param, mapRange(nx, PARAM_CONFIG.HEAD_X.range));
    core.setParameterValueById(PARAM_CONFIG.HEAD_Y.param, mapRange(ny, PARAM_CONFIG.HEAD_Y.range));
  } catch {}
}

const LOOKAT_THROTTLE_MS = 33;
let lastLookAtAt = 0;
function onGlobalPointerMove(ev) {
  if (!trackingEnabled.value || !model || !modelVisible.value) return;

  const now = performance.now();
  if (now - lastLookAtAt < LOOKAT_THROTTLE_MS) return;
  lastLookAtAt = now;

  const rect = canvasRef.value.getBoundingClientRect();
  const world = new PIXI.Point(ev.clientX - rect.left, ev.clientY - rect.top);
  const local = container.toLocal(world, app.stage);
  applyLookAt(local.x, local.y);
}
```
**解析**：
- 监听全局 `pointermove` 事件，计算鼠标相对于模型的局部坐标。
- 将坐标归一化后，映射到头部角度 (`ParamAngleX/Y`) 和眼球位置 (`ParamEyeBallX/Y`) 的参数范围内。
- `trackingOriginOffset` 允许用户自定义视线追踪的中心点（例如设置在模型的眼睛位置），提升交互真实感。

---

## 4. 动画与表情管理

### 4.1 呼吸动画 (Idle Animation)
在没有音频律动时，通过 PIXI Ticker 驱动基础的呼吸动画。

```javascript
// src/views/index/index.vue
let breathTickerFn = null;
function startBreath() {
  if (breathTickerFn || !app?.ticker || rhythm.showSystemAudioListening.value) return;
  const breathStart = performance.now() / 1000;
  breathTickerFn = () => {
    const core = getCoreModel();
    if (!core) return;
    const t = performance.now() / 1000 - breathStart;
    const val = 0.5 + Math.sin(t * 0.9 * Math.PI * 2) * 0.15;
    try { core.setParameterValueById(PARAM_CONFIG.BREATH.param, val); } catch {}
  };
  app.ticker.add(breathTickerFn);
}
function stopBreath() {
  if (breathTickerFn && app?.ticker) {
    app.ticker.remove(breathTickerFn);
    breathTickerFn = null;
  }
}
```
**解析**：使用简单的正弦函数模拟平滑的呼吸节奏，直接操作 `ParamBreath` 参数。当开启音频律动时，会停止此基础呼吸，交由律动模块接管。

### 4.2 表情系统 (Emotion Expressions)
表情系统通过加载 `.exp3.json` 文件并动态补间参数实现。

```javascript
// src/views/index/index.vue
async function resetToSolemn() {
  const core = getCoreModel();
  if (!core) return;
  const keys = Object.keys(currentEmotionMeta);
  if (!keys.length) return;
  for (const id of keys) {
    try {
      core.setParameterValueById(id, typeof currentEmotionMeta[id] === "number" ? currentEmotionMeta[id] : 0);
    } catch {}
  }
  currentEmotionMeta = {};
  await new Promise((r) => requestAnimationFrame(r));
}

function tweenParameters(core, targetValues, duration = 220) {
  return new Promise((resolve) => {
    const startTime = performance.now();
    const fromValues = {};
    for (const id in targetValues) {
      fromValues[id] = core.getParameterValueById(id) ?? 0;
    }
    function step(now) {
      const t = Math.min((now - startTime) / duration, 1);
      const k = t * t * (3 - 2 * t);
      for (const id in targetValues) {
        core.setParameterValueById(id, fromValues[id] + (targetValues[id] - fromValues[id]) * k);
      }
      if (t < 1) requestAnimationFrame(step);
      else resolve();
    }
    requestAnimationFrame(step);
  });
}

async function applyEmotionExpressions(emotion) {
  const core = getCoreModel();
  if (!core) return;
  await resetToSolemn();
  await new Promise((r) => requestAnimationFrame(r));
  const names = EMOTION_EXPRESSIONS?.[emotion] || [];
  if (!names.length) return;
  const targetValues = {};
  const thisApplyPrev = {};
  for (const cnName of names) {
    const expJson = expressionCache.get(cnName);
    if (!expJson) continue;
    (expJson.Parameters || []).forEach(({ Id, Value, Blend }) => {
      const base = targetValues[Id] ?? core.getParameterValueById(Id) ?? 0;
      if (!(Id in thisApplyPrev)) thisApplyPrev[Id] = base;
      if (Blend === "Add") targetValues[Id] = base + Value;
      else if (Blend === "Multiply") targetValues[Id] = base * Value;
      else targetValues[Id] = Value;
    });
  }
  await tweenParameters(core, targetValues, 220);
  currentEmotionMeta = thisApplyPrev;
  await appearance.applyAllEnabled(getCoreModel());
}


// src\composables\useAppearance.js
import { ref } from "vue";

/** localStorage 鍵名 */
const APPEARANCE_STATE_KEY = "live2d:appearance-enabled";

/**
 * 外貌管理 composable
 * 負責外貌文件的加載、應用、移除、狀態持久化
 */
export function useAppearance() {
  // 所有可用外貌文件列表（与 public/models/luna 下文件名保持完全一致）
  const APPEARANCE_FILES = [
    "后发-右小啾啾隐藏.exp3.json",
    "后发-长发隐藏.exp3.json",
    "后发-左小啾啾隐藏.exp3.json",
    "肩发-缩小~隐藏.exp3.json",
    "肩发-位置收拢.exp3.json",
    "脸-绷带-血隐藏.exp3.json",
    "脸-绷带和血一起隐藏.exp3.json",
    "帽子隐藏.exp3.json",
    "前发-去掉半透.exp3.json",
    "身-毛衣.exp3.json",
    "身-腿绷带血隐藏.exp3.json",
    "身-腿绷带隐藏.exp3.json",
    "身-围巾.exp3.json",
    "手-抱猫.exp3.json",
    "手-手提包隐藏.exp3.json",
    "兽耳-隐藏.exp3.json",
    "兽尾-隐藏1.exp3.json",
    "兽尾-隐藏2.exp3.json",
    "眼-眼镜.exp3.json",
    "眼-右眼粉瞳色.exp3.json",
    "眼-左眼粉瞳色.exp3.json",
    "眼影隐藏.exp3.json",
  ];

  // 各文件启用状态（响应式）
  const appearanceEnabled = ref({});

  // 已应用文件的元数据，用于回退（非响应式，纯数据）
  const appearanceAppliedMeta = {};

  // 轻提示文本
  const appearanceHint = ref("");
  let appearanceHintTimer = null;

  /** 显示操作轻提示 */
  function showAppearanceHint(text, duration = 1500) {
    appearanceHint.value = text;
    clearTimeout(appearanceHintTimer);
    appearanceHintTimer = setTimeout(() => {
      appearanceHint.value = "";
    }, duration);
  }

  /** 将文件名转换为显示名称（界面使用简体） */
  function displayAppearanceName(file) {
    return file.replace(/\.exp3\.json$/i, "");
  }

  /** 从 localStorage 读取已保存的启用状态 */
  function loadAppearanceState() {
    const raw = localStorage.getItem(APPEARANCE_STATE_KEY);
    let saved = {};
    try {
      saved = raw ? JSON.parse(raw) : {};
    } catch {}
    APPEARANCE_FILES.forEach((f) => {
      appearanceEnabled.value[f] = !!saved[f];
    });
  }

  /** 将当前启用状态持久化到 localStorage */
  function saveAppearanceState() {
    const obj = {};
    for (const f of APPEARANCE_FILES) {
      obj[f] = !!appearanceEnabled.value[f];
    }
    localStorage.setItem(APPEARANCE_STATE_KEY, JSON.stringify(obj));
  }

  /**
   * 应用单个外貌文件
   * 会记录原始参数值，以便后续移除时回退
   */
  async function applyAppearanceFile(file, core) {
    if (!core) return;
    try {
      const res = await fetch(`/models/luna/${encodeURIComponent(file)}`);
      if (!res.ok) throw new Error("fetch fail");
      const expJson = await res.json();

      const meta = [];
      (expJson.Parameters || []).forEach(({ Id, Value, Blend }) => {
        try {
          const old = core.getParameterValueById(Id) || 0;
          if (Blend === "Add") {
            core.setParameterValueById(Id, old + Value);
            meta.push({ Id, Blend, value: Value });
          } else {
            core.setParameterValueById(Id, Value);
            meta.push({ Id, Blend, previous: old, value: Value });
          }
        } catch {}
      });

      appearanceAppliedMeta[file] = meta;
    } catch (e) {
      console.warn("[Appearance] applyAppearanceFile error:", file, e);
    }
  }

  /**
   * 移除单个外貌文件，根据 meta 回退参数
   */
  function removeAppearanceFile(file, core) {
    if (!core) return;
    const meta = appearanceAppliedMeta[file];
    if (!meta) return;

    meta.forEach((m) => {
      try {
        if (m.Blend === "Add") {
          const cur = core.getParameterValueById(m.Id) || 0;
          core.setParameterValueById(m.Id, cur - (m.value || 0));
        } else {
          core.setParameterValueById(m.Id, m.previous || 0);
        }
      } catch {}
    });

    delete appearanceAppliedMeta[file];
  }

  /**
   * 并行应用所有已启用的外貌文件
   * 使用 Promise.all 提升加载速度
   */
  async function applyAllEnabled(core) {
    const tasks = APPEARANCE_FILES
      .filter((f) => appearanceEnabled.value[f])
      .map((f) => applyAppearanceFile(f, core));
    await Promise.all(tasks);
    showAppearanceHint("已应用当前外貌设置");
  }

  /** 禁用所有外貌并清除状态 */
  async function disableAll(core) {
    for (const f of APPEARANCE_FILES.slice()) {
      if (appearanceAppliedMeta[f]) {
        removeAppearanceFile(f, core);
      }
      appearanceEnabled.value[f] = false;
    }
    saveAppearanceState();
    showAppearanceHint("已恢复默认外貌");
  }

  /** 切换单个外貌文件（由 checkbox 触发） */
  async function onAppearanceToggle(file, core) {
    saveAppearanceState();
    const name = displayAppearanceName(file);
    if (appearanceEnabled.value[file]) {
      await applyAppearanceFile(file, core);
      showAppearanceHint(`✓ 已启用 ${name}`);
    } else {
      removeAppearanceFile(file, core);
      showAppearanceHint(`✕ 已关闭 ${name}`);
    }
  }

  return {
    APPEARANCE_FILES,
    appearanceEnabled,
    appearanceAppliedMeta,
    appearanceHint,
    showAppearanceHint,
    displayAppearanceName,
    loadAppearanceState,
    saveAppearanceState,
    applyAppearanceFile,
    removeAppearanceFile,
    applyAllEnabled,
    disableAll,
    onAppearanceToggle,
  };
}

// src\utils\emotion-expressions.js
export const EMOTION_EXPRESSIONS = {
  Angry: ["眼-生气", "脸红2隐藏"],
  Annoyed: ["眼-生气", "脸黑", "脸红2隐藏"],
  Irritated: ["眼-生气"],
  Sad: ["眼-哭哭"],
  Lonely: ["眼-泪眼汪汪"],
  Despair: ["脸黑", "脸红2隐藏"],
  Broken: ["脸黑", "眼-眩晕流汗", "脸红2隐藏"],
  Uneasy: ["眼-哭哭"],
  Anxious: ["眼-眩晕流汗", "脸红"],
  Fearful: ["眼-哭哭", "脸黑"],
  Shocked: ["眼-眩晕流汗"],
  Tired: ["脸红2隐藏", "眼-平静死鱼眼"],
  Bored: ["眼-平静死鱼眼"],
  Confused: ["眼-眩晕流汗"],
  Disappointed: ["脸黑"],
  Frustrated: ["眼-哭哭"],
  Embarrassed: ["眼-平静死鱼眼", "嘴-平静v形（不可张开"],
  Flustered: ["眼-眩晕流汗", "脸红"],
  Affectionate: ["嘴-平静v形（不可张开", "脸红"],
  Clingy: ["眼-星星眼", "脸红"],
  Teasing: ["脸红-痴汉嘴（兼容吐舌", "脸红", "眼-平静死鱼眼"],
  Tsundere: ["脸红"],
  Yandere: ["脸黑", "脸红", "嘴-平静v形（不可张开", "眼-爱心眼"],
  Smile: ["嘴-平静v形（不可张开"],
  Soft: ["嘴-平静v形（不可张开", "脸红"],
  Shy: ["嘴-平静v形（不可张开", "脸红"],
  Hopeful: ["眼-星星眼"],
  Grateful: ["眼-泪眼汪汪", "脸红"],
  Solemn: [],
  Determined: ["眼-生气"],
  Proud: ["眼-星星眼"],
  Relieved: ["嘴-平静v形（不可张开", "眼-泪眼汪汪"],
  Resigned: ["眼-平静死鱼眼", "脸黑"]
};


```
**解析**：
- [`src/utils/emotion-expressions.js`](src/utils/emotion-expressions.js:1) 定义了情绪状态（如 `Angry`, `Sad`）到具体表情文件名的映射。
- 支持组合表情（如 `Angry` = `["眼-生气", "脸红2隐藏"]`）。
- `tweenParameters` 函数实现了一个 220ms 的缓动动画，避免表情切换过于生硬。

### 4.3 外貌系统 (Appearance/服装切换)
由 [`src/composables/useAppearance.js`](src/composables/useAppearance.js:10) 管理，用于切换服装、发型等部件。

```javascript
// src/composables/useAppearance.js
  async function applyAppearanceFile(file, core) {
    if (!core) return;
    try {
      const res = await fetch(`/models/luna/${encodeURIComponent(file)}`);
      if (!res.ok) throw new Error("fetch fail");
      const expJson = await res.json();

      const meta = [];
      (expJson.Parameters || []).forEach(({ Id, Value, Blend }) => {
        try {
          const old = core.getParameterValueById(Id) || 0;
          if (Blend === "Add") {
            core.setParameterValueById(Id, old + Value);
            meta.push({ Id, Blend, value: Value });
          } else {
            core.setParameterValueById(Id, Value);
            meta.push({ Id, Blend, previous: old, value: Value });
          }
        } catch {}
      });

      appearanceAppliedMeta[file] = meta;
    } catch (e) {
      console.warn("[Appearance] applyAppearanceFile error:", file, e);
    }
  }

  function removeAppearanceFile(file, core) {
    if (!core) return;
    const meta = appearanceAppliedMeta[file];
    if (!meta) return;

    meta.forEach((m) => {
      try {
        if (m.Blend === "Add") {
          const cur = core.getParameterValueById(m.Id) || 0;
          core.setParameterValueById(m.Id, cur - (m.value || 0));
        } else {
          core.setParameterValueById(m.Id, m.previous || 0);
        }
      } catch {}
    });

    delete appearanceAppliedMeta[file];
  }
```
**解析**：外貌切换本质上也是应用 `.exp3.json` 参数。关键在于它记录了 `appearanceAppliedMeta`，保存了修改前的参数值，这样在关闭某个外观部件时，可以精确地将参数回退到原始状态。

---

## 5. 资源释放与内存销毁

在组件卸载时，必须彻底清理 PIXI 和 Live2D 资源，防止内存泄漏。

```javascript
// src/views/index/index.vue
onBeforeUnmount(() => {
  stopBreath();
  rhythm.dispose(getCoreModel(), trackingEnabled);
  app?.destroy(true);
  callShutdown();
  removeStatusUpdateListener?.();
  removeAuthExpiredListener?.();

  window.removeEventListener("mousemove", onWindowMouseMove, true);

  statusQueue.length = 0;
  isConsumingStatusQueue = false;
  statusLastEnqueued = "";
  statusConsumeVersion = 0;

  if (planReconnectTimer) {
    clearTimeout(planReconnectTimer);
    planReconnectTimer = null;
  }

  if (snapshotSyncTimer) {
    clearTimeout(snapshotSyncTimer);
    snapshotSyncTimer = null;
  }

  resetBootLogScroll();
});
```
**解析**：
- `app.destroy(true)` 是最关键的一步，它会递归销毁 PIXI 舞台上的所有对象，包括 Live2D 模型，并释放 GPU 显存中的纹理数据。
- `rhythm.dispose` 会关闭 `AudioContext` 并停止媒体流（`MediaStreamTrack.stop()`），释放麦克风或系统音频的占用。

---

## 总结

本项目的 Live2D 架构设计非常成熟且模块化：
1. **核心渲染**：基于 `pixi.js` 和 `pixi-live2d-display`，利用 WebGL 提供高性能渲染。
2. **状态解耦**：将复杂的业务逻辑抽离为 Composables（`useAppearance.js` 管理静态外观，`useRhythm.js` 管理动态音频律动），保持了视图组件的相对整洁。
3. **精细控制**：没有完全依赖插件的内置功能（如自动视线追踪、内置口型同步），而是通过直接操作 Cubism Core 的底层参数（`setParameterValueById`），实现了高度自定义的交互（自定义追踪原点、多表情混合、基于 FFT 的高级音频律动）。
4. **性能优化**：限制了 PIXI 的最大帧率，音频分析采用了降频处理（`processEveryNFrames`），并妥善处理了生命周期销毁。