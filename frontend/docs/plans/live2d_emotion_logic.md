# Live2D 表情切换逻辑分析

本文档详细分析了项目中 Live2D 模型如何根据后端响应的 `emotion` 字段来动态切换表情的完整流程，并附带了所有相关的完整源码。

## 1. 核心流程概述

整个表情切换的流程可以概括为以下几个步骤：

1.  **接收响应**: 前端接收到后端大模型返回的响应数据，其中包含 `emotion` 字段。
2.  **提取情绪**: 从响应数据中提取出 `emotion` 字符串（如 "Angry", "Smile" 等）。
3.  **映射表情文件**: 根据提取出的 `emotion`，在预定义的映射表中查找对应的 Live2D 表情文件（`.exp3.json`）列表。
4.  **重置状态**: 在应用新表情前，先将模型恢复到默认的 "Solemn"（严肃/平静）状态，清除上一个表情的影响。
5.  **计算参数**: 读取目标表情文件中的参数变化（Add, Multiply, Overwrite），计算出模型各个参数的最终目标值。
6.  **平滑过渡**: 使用补间动画（Tweening）将模型参数从当前值平滑过渡到目标值，实现自然的表情切换。
7.  **重新应用外观**: 表情切换完成后，重新应用用户自定义的外观设置（如隐藏帽子、戴眼镜等），确保外观不被表情重置覆盖。

## 2. 完整源码分析

### 2.1 情绪到表情文件的映射

映射关系定义在 [`src/utils/emotion-expressions.js`](src/utils/emotion-expressions.js) 中。它将英文的情绪单词映射到一个或多个中文命名的表情文件前缀。

**完整源码 (`src/utils/emotion-expressions.js`):**

```javascript
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

### 2.2 核心逻辑实现 (位于 `src/views/index/index.vue`)

以下是 [`src/views/index/index.vue`](src/views/index/index.vue) 中涉及表情切换的所有完整函数源码。

#### 2.2.1 接收与提取情绪 (`handleModelReply`)

处理模型回复，提取 `emotion` 字段并触发表情应用。

```javascript
async function handleModelReply(res) {
  if (!res) throw new Error("Empty response");

  let replyText = "";
  let em = "";

  if (typeof res === "string") {
    replyText = res;
  } else {
    replyText =
      res.reply ||
      res.text ||
      res.message ||
      res.content ||
      res.answer ||
      res.raw ||
      res.rawResult ||
      res.data ||
      "";
    em = res.emotion || "";
    if (!replyText && typeof res === "object") {
      replyText = JSON.stringify(res);
    }
  }

  if (!replyText) throw new Error("No text content found in response");

  if (em) {
    currentEmotion.value = em;
    try { applyEmotionExpressions(em); } catch {}
  }

  if (showHistory.value && historyPanelRef.value) {
    historyPanelRef.value.refresh();
  }

  const chunks = splitReplyIntoChunks(replyText);
  const previewText = chunks.length > 0 ? chunks[0] : replyText;

  const effectPromise = playDecryptionEffect(previewText);
  const bubblePromise = sendReplyAsBubbles(replyText, { interval: 1100, duration: 5000 });

  await Promise.all([effectPromise, bubblePromise]);
}
```

#### 2.2.2 预加载表情文件 (`preloadExpressions`)

在组件挂载时，预先加载所有可能用到的表情 JSON 文件，并缓存到 `expressionCache` 中。

```javascript
const expressionCache = new Map();

async function preloadExpressions() {
  const allFiles = [
    "眼-生气",
    "脸红2隐藏",
    "脸黑",
    "眼-哭哭",
    "眼-泪眼汪汪",
    "眼-眩晕流汗",
    "脸红",
    "眼-平静死鱼眼",
    "嘴-平静v形（不可张开",
    "眼-星星眼",
    "脸红-痴汉嘴（兼容吐舌",
    "眼-爱心眼",
  ];
  await Promise.all(
    allFiles.map(async (name) => {
      try {
        const res = await fetch(`/models/luna/${encodeURIComponent(name)}.exp3.json`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const text = await res.text();
        if (text.trim().startsWith("<")) {
          throw new Error("鏂囦欢鏈壘鍒?(杩斿洖浜?HTML)");
        }

        expressionCache.set(name, JSON.parse(text));
      } catch {}
    }),
  );
}
```

#### 2.2.3 状态重置 (`resetToSolemn`)

在应用新表情前，将模型恢复到默认状态。

```javascript
const INITIAL_EMOTION = "Solemn";
let currentEmotionMeta = {};

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
```

#### 2.2.4 平滑过渡动画 (`tweenParameters`)

使用 `requestAnimationFrame` 实现参数的平滑过渡。

```javascript
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
```

#### 2.2.5 应用表情核心逻辑 (`applyEmotionExpressions`)

整合上述步骤，计算目标参数并应用。

```javascript
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
```

## 3. 总结

该项目实现了一套非常完善且平滑的 Live2D 表情控制系统。它没有依赖 Live2D SDK 内置的 ExpressionManager，而是自己实现了解析 `.exp3.json`、计算混合模式（Add/Multiply/Overwrite）以及参数补间动画的逻辑。这种做法的好处是可以更精细地控制表情的过渡时间，并且能够很好地与自定义的外观系统（`useAppearance`）兼容，防止表情切换时覆盖掉用户的换装设置。
