# Event Horizon Lensing Loader — 完整实现方案

## 概述

本文档包含基于 React + TypeScript + WebGL2 的引力透镜全屏加载动画的完整实现代码。
所有文件需要在 Code 模式下创建到 `frontend/src/renderer/components/LoadingScreen/` 目录下。

---

## 一、文件清单与结构

```
frontend/src/renderer/components/LoadingScreen/
├── EventHorizonLoader.tsx          # React 组件入口
├── eventHorizonShader.glsl         # 着色器源码（可选，推荐内联）
├── EventHorizonLoader.module.css   # CSS Modules 样式
├── useBackendReady.ts              # 后端就绪监听 Hook
```

---

## 二、核心着色器：`eventHorizonShader.glsl`

> **文件路径**: `frontend/src/renderer/components/LoadingScreen/eventHorizonShader.glsl`
>
> 也可以直接内联在 `EventHorizonLoader.tsx` 中，以避免 Webpack/vite 对 GLSL 文件的配置。

```glsl
#version 300 es
precision highp float;

uniform vec2 u_resolution;
uniform float u_time;
uniform float u_progress;  // 0.0 → 1.0，引力强度
uniform float u_release;   // 0.0 → 1.0，释放回弹

out vec4 fragColor;

float hash(vec2 p) {
    vec3 p3  = fract(vec3(p.xyx) * .1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

float noise(vec2 x) {
    vec2 i = floor(x);
    vec2 f = fract(x);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

// 多层星空背景
vec3 starfield(vec2 uv) {
    vec3 color = vec3(0.0);
    for(float i = 1.0; i < 4.0; i++) {
        vec2 q = uv * (20.0 * i);
        float n = noise(q);
        float star = smoothstep(0.95, 1.0, n);
        vec3 starColor = mix(vec3(0.8, 0.9, 1.0), vec3(1.0, 0.8, 0.9), hash(floor(q)));
        float twinkle = 0.5 + 0.5 * sin(u_time * 2.0 + hash(floor(q)) * 10.0);
        color += star * starColor * twinkle * (1.0 / i);
    }
    // 微弱的星云尘埃
    float dust = noise(uv * 3.0 + u_time * 0.05) * 0.5 + 0.5;
    dust *= noise(uv * 6.0 - u_time * 0.02) * 0.5 + 0.5;
    color += vec3(0.05, 0.08, 0.15) * dust * 0.3;
    return color;
}

void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / min(u_resolution.x, u_resolution.y);
    float r = length(uv);

    // 引力质量：随进度增加，释放时归零
    float mass = mix(0.05, 0.3, u_progress) * (1.0 - u_release);

    // 引力透镜位移
    vec2 displacement = vec2(0.0);
    if (r > 0.01) {
        float deflection = mass / r;
        deflection *= smoothstep(0.0, 0.1, r);
        displacement = -normalize(uv) * deflection;
    }

    // 色散（Chromatic Aberration）
    float caStrength = 0.02 * mass;
    vec2 uvR = uv + displacement * (1.0 - caStrength);
    vec2 uvG = uv + displacement;
    vec2 uvB = uv + displacement * (1.0 + caStrength);

    // 采样星空
    vec3 col;
    col.r = starfield(uvR).r;
    col.g = starfield(uvG).g;
    col.b = starfield(uvB).b;

    // 事件视界阴影
    float shadowR = mass * 1.5;
    float shadow = smoothstep(shadowR * 0.9, shadowR * 1.1, r);
    col *= shadow;

    // 吸积盘微弱光晕
    float glow = exp(-(r - shadowR * 1.2) * 10.0) * 0.5 * mass;
    glow = max(0.0, glow);
    col += vec3(0.2, 0.5, 1.0) * glow * shadow;

    // 暗角
    col *= 1.0 - 0.3 * dot(uv, uv);

    fragColor = vec4(col, 1.0);
}
```

---

## 三、CSS Modules：`EventHorizonLoader.module.css`

> **文件路径**: `frontend/src/renderer/components/LoadingScreen/EventHorizonLoader.module.css`

```css
/* 全屏容器 */
.container {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: #000000;
  z-index: 9999;
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: hidden;

  /* 离场过渡 */
  opacity: 1;
  visibility: visible;
  transition:
    opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1),
    visibility 0.8s cubic-bezier(0.16, 1, 0.3, 1),
    transform 0.8s cubic-bezier(0.16, 1, 0.3, 1);
}

/* 离场状态：透明度归零 + 轻微放大模拟空间回弹 */
.container.fadeOut {
  opacity: 0;
  visibility: hidden;
  transform: scale(1.05);
  pointer-events: none;
}

/* Canvas 填满全屏 */
.canvas {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

/* 底部文字叠加层 */
.textOverlay {
  position: absolute;
  bottom: 10%;
  left: 50%;
  transform: translateX(-50%);
  font-family: 'Inter', 'SF Pro Display', 'Segoe UI', sans-serif;
  font-size: 12px;
  letter-spacing: 8px;
  font-weight: 300;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase;
  pointer-events: none;
  user-select: none;

  /* 呼吸脉冲 */
  animation: pulseText 3s ease-in-out infinite alternate;
}

/* 文字淡出 */
.textOverlay.fadeOut {
  opacity: 0;
  transition: opacity 0.3s ease-out;
}

@keyframes pulseText {
  0% {
    opacity: 0.2;
    text-shadow: 0 0 4px rgba(255, 255, 255, 0);
  }
  100% {
    opacity: 0.6;
    text-shadow: 0 0 8px rgba(255, 255, 255, 0.3);
  }
}
```

---

## 四、后端就绪监听 Hook：`useBackendReady.ts`

> **文件路径**: `frontend/src/renderer/components/LoadingScreen/useBackendReady.ts`

```typescript
/**
 * 监听后端服务就绪状态的自定义 Hook
 *
 * 设计逻辑：
 * 1. 从 systemStore 中读取 connectionStatus (Go Runtime) 与
 *    aiConnectionStatus (Python AI Service)
 * 2. 当两者均为 'connected' 时认为后端就绪
 * 3. minLoadingTimeMs 参数确保动画至少展示指定时长，避免闪烁
 */
import { useState, useEffect } from 'react';
import { useSystemStore } from '../../stores/systemStore';

export const useBackendReady = (minLoadingTimeMs = 2000) => {
  const [isReady, setIsReady] = useState(false);
  const [timeElapsed, setTimeElapsed] = useState(false);

  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const aiConnectionStatus = useSystemStore((state) => state.aiConnectionStatus);

  // 最小加载计时器
  useEffect(() => {
    const timer = setTimeout(() => setTimeElapsed(true), minLoadingTimeMs);
    return () => clearTimeout(timer);
  }, [minLoadingTimeMs]);

  // 状态监听
  useEffect(() => {
    const backendConnected =
      connectionStatus === 'connected' &&
      aiConnectionStatus === 'connected';

    if (backendConnected && timeElapsed) {
      setIsReady(true);
    }
  }, [connectionStatus, aiConnectionStatus, timeElapsed]);

  return isReady;
};
```

---

## 五、React 组件：`EventHorizonLoader.tsx`

> **文件路径**: `frontend/src/renderer/components/LoadingScreen/EventHorizonLoader.tsx`

```typescript
/**
 * EventHorizonLoader — 事件视界引力透镜全屏加载组件
 *
 * 核心机制：
 * - 使用 WebGL2 实时渲染引力透镜效应
 * - 内置两阶段状态机：INITIALIZING → FADING_OUT → UNMOUNTED
 * - 通过 useBackendReady 监听后端就绪信号
 * - 触发后先执行 CSS 离场过渡，再彻底卸载 DOM
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import styles from './EventHorizonLoader.module.css';
import { useBackendReady } from './useBackendReady';

// ---------- WebGL Shader 源码 ----------
const vertexShaderSource = `#version 300 es
in vec4 a_position;
void main() {
  gl_Position = a_position;
}
`;

const fragmentShaderSource = `#version 300 es
precision highp float;

uniform vec2 u_resolution;
uniform float u_time;
uniform float u_progress;
uniform float u_release;

out vec4 fragColor;

float hash(vec2 p) {
    vec3 p3  = fract(vec3(p.xyx) * .1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

float noise(vec2 x) {
    vec2 i = floor(x);
    vec2 f = fract(x);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

vec3 starfield(vec2 uv) {
    vec3 color = vec3(0.0);
    for(float i = 1.0; i < 4.0; i++) {
        vec2 q = uv * (20.0 * i);
        float n = noise(q);
        float star = smoothstep(0.95, 1.0, n);
        vec3 starColor = mix(vec3(0.8, 0.9, 1.0), vec3(1.0, 0.8, 0.9), hash(floor(q)));
        float twinkle = 0.5 + 0.5 * sin(u_time * 2.0 + hash(floor(q)) * 10.0);
        color += star * starColor * twinkle * (1.0 / i);
    }
    float dust = noise(uv * 3.0 + u_time * 0.05) * 0.5 + 0.5;
    dust *= noise(uv * 6.0 - u_time * 0.02) * 0.5 + 0.5;
    color += vec3(0.05, 0.08, 0.15) * dust * 0.3;
    return color;
}

void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / min(u_resolution.x, u_resolution.y);
    float r = length(uv);
    float mass = mix(0.05, 0.3, u_progress) * (1.0 - u_release);

    vec2 displacement = vec2(0.0);
    if (r > 0.01) {
        float deflection = mass / r;
        deflection *= smoothstep(0.0, 0.1, r);
        displacement = -normalize(uv) * deflection;
    }

    float caStrength = 0.02 * mass;
    vec2 uvR = uv + displacement * (1.0 - caStrength);
    vec2 uvG = uv + displacement;
    vec2 uvB = uv + displacement * (1.0 + caStrength);

    vec3 col;
    col.r = starfield(uvR).r;
    col.g = starfield(uvG).g;
    col.b = starfield(uvB).b;

    float shadowR = mass * 1.5;
    float shadow = smoothstep(shadowR * 0.9, shadowR * 1.1, r);
    col *= shadow;

    float glow = exp(-(r - shadowR * 1.2) * 10.0) * 0.5 * mass;
    glow = max(0.0, glow);
    col += vec3(0.2, 0.5, 1.0) * glow * shadow;

    col *= 1.0 - 0.3 * dot(uv, uv);
    fragColor = vec4(col, 1.0);
}
`;

// ---------- WebGL 工具函数 ----------
function createShader(gl: WebGL2RenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error('[EventHorizon] Shader compile error:', gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function createProgram(gl: WebGL2RenderingContext, vs: WebGLShader, fs: WebGLShader) {
  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error('[EventHorizon] Program link error:', gl.getProgramInfoLog(program));
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

// ---------- React 组件 ----------
export const EventHorizonLoader: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const requestRef = useRef<number>();

  // 状态管理器
  const isBackendReady = useBackendReady(2500); // 至少展示 2.5 秒
  const [isFadingOut, setIsFadingOut] = useState(false);
  const [isMounted, setIsMounted] = useState(true);

  // 动画参数（使用 ref 避免引起不必要的 re-render）
  const progressRef = useRef(0.0);
  const releaseRef = useRef(0.0);

  /**
   * WebGL 初始化与动画循环
   * 仅在组件挂载时运行一次，不依赖 React 状态变化
   */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext('webgl2');
    if (!gl) {
      console.error('[EventHorizon] WebGL2 not supported by this browser');
      return;
    }

    // 编译着色器
    const vs = createShader(gl, gl.VERTEX_SHADER, vertexShaderSource);
    const fs = createShader(gl, gl.FRAGMENT_SHADER, fragmentShaderSource);
    if (!vs || !fs) return;

    const program = createProgram(gl, vs, fs);
    if (!program) return;

    // 全屏三角形顶点
    const positionLoc = gl.getAttribLocation(program, 'a_position');
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );

    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.enableVertexAttribArray(positionLoc);
    gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);

    // Uniform 位置
    const uResolution = gl.getUniformLocation(program, 'u_resolution');
    const uTime = gl.getUniformLocation(program, 'u_time');
    const uProgress = gl.getUniformLocation(program, 'u_progress');
    const uRelease = gl.getUniformLocation(program, 'u_release');

    // 响应式 Canvas 尺寸
    const resize = () => {
      canvas.width = window.innerWidth * window.devicePixelRatio;
      canvas.height = window.innerHeight * window.devicePixelRatio;
      gl.viewport(0, 0, canvas.width, canvas.height);
    };
    window.addEventListener('resize', resize);
    resize();

    // 渲染循环
    const startTime = performance.now();
    const render = (time: number) => {
      const elapsed = (time - startTime) * 0.001;

      // 更新动画参数
      if (!isFadingOut) {
        progressRef.current = Math.min(1.0, progressRef.current + 0.002);
      } else {
        // 释放：指数衰减 ease-out
        releaseRef.current += (1.0 - releaseRef.current) * 0.15;
      }

      gl.useProgram(program);
      gl.bindVertexArray(vao);
      gl.uniform2f(uResolution, canvas.width, canvas.height);
      gl.uniform1f(uTime, elapsed);
      gl.uniform1f(uProgress, progressRef.current);
      gl.uniform1f(uRelease, releaseRef.current);
      gl.drawArrays(gl.TRIANGLES, 0, 6);

      requestRef.current = requestAnimationFrame(render);
    };

    requestRef.current = requestAnimationFrame(render);

    // 清理
    return () => {
      window.removeEventListener('resize', resize);
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      gl.deleteBuffer(buffer);
      gl.deleteVertexArray(vao);
    };
  }, [isFadingOut]);

  /**
   * 监听后端就绪 → 触发两阶段卸载
   */
  useEffect(() => {
    if (isBackendReady && !isFadingOut) {
      setIsFadingOut(true);
      const timer = setTimeout(() => setIsMounted(false), 800);
      return () => clearTimeout(timer);
    }
  }, [isBackendReady, isFadingOut]);

  if (!isMounted) return null;

  return (
    <div className={`${styles.container} ${isFadingOut ? styles.fadeOut : ''}`}>
      <canvas ref={canvasRef} className={styles.canvas} />
      <div className={`${styles.textOverlay} ${isFadingOut ? styles.fadeOut : ''}`}>
        LUNA V3 INITIALIZING
      </div>
    </div>
  );
};
```

---

## 六、systemStore 扩展方案

如果希望将后端就绪状态作为独立的显式状态管理（而不是依赖 `connectionStatus` 的组合），
可以在 `frontend/src/renderer/stores/systemStore.ts` 中做如下扩展：

### 新增字段

在 `SystemState` 接口中添加：

```typescript
isBackendReady: boolean;
```

### 初始化值

```typescript
isBackendReady: false,
```

### 新增 Action

```typescript
setBackendReady: (ready: boolean) => void;
```

### 实现

```typescript
setBackendReady: (ready) => set({ isBackendReady: ready }),
```

### 调用时机

当 Go Runtime 或 Python AI Service 的健康检查通过时，在对应的服务管理器（如 `healthService.ts` 或 `wsManager.ts`）中调用：

```typescript
import { useSystemStore } from '../stores/systemStore';
useSystemStore.getState().setBackendReady(true);
```

然后更新 `useBackendReady.ts` 的逻辑，直接读取 `isBackendReady` 字段：

```typescript
const isBackendReady = useSystemStore((state) => state.isBackendReady);
```

---

## 七、使用示例：在主入口挂载

在 `frontend/src/renderer/index.tsx` 或 `App.tsx` 中使用：

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { EventHorizonLoader } from './components/LoadingScreen/EventHorizonLoader';
import { MainLayout } from './components/MainLayout';

const App = () => (
  <>
    {/* 加载屏覆盖在最上层，就绪后自动销毁 */}
    <EventHorizonLoader />
    {/* 主应用界面 */}
    <MainLayout />
  </>
);

ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
```

---

## 八、集成注意事项

| 项目 | 说明 |
|------|------|
| WebGL2 兼容性 | 现代浏览器均已支持。若需兼容旧版，可降级为 WebGL1 或使用纯 CSS 替代方案。 |
| 性能 | 所有计算在 GPU 完成，CPU 负载极低，不会拖慢后端服务初始化。 |
| 最小加载时间 | `useBackendReady` 的 `minLoadingTimeMs` 参数默认为 2500ms，可根据实际启动速度调整。 |
| 离场过渡时长 | CSS `transition-duration: 0.8s` 与 `setTimeout(800)` 必须保持一致，否则画面会闪烁。 |
| GLSL 文件引入 | 若使用独立的 `.glsl` 文件，需要配置 vite 或 webpack 的 raw-loader，建议直接内联避免额外配置。 |
