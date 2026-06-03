// EventHorizonLoader.tsx
// ----------------------------------------
// React 组件实现事件视界引力透镜全屏加载动画。
// 依赖：React, Zustand (systemStore), WebGL2.
// 位置：frontend/src/renderer/components/LoadingScreen/
// ----------------------------------------
import React, { useEffect, useRef, useState } from 'react';
import styles from './EventHorizonLoader.module.css';
import { useBackendReady } from './useBackendReady';

// 顶点着色器（全屏三角形）
const vertexShaderSource = `#version 300 es
in vec4 a_position;
void main() {
  gl_Position = a_position;
}`;

// 片段着色器（方案1：Eclipse 日全食 - 优化版）
// 模拟日全食时，月球遮挡太阳后边缘漏出的绝美日冕（Corona）。
// 修复了极坐标接缝问题，并引入了边缘的有机波动。
const fragmentShaderSource = `#version 300 es
precision highp float;

uniform vec2 u_resolution;
uniform float u_time;
uniform float u_progress; // 0.0 -> 1.0
uniform float u_release;  // 0.0 -> 1.0，释放回弹

out vec4 fragColor;

// Hash 和 Noise 函数用于生成微观耀斑和边缘扭曲
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

// 分形布朗运动 (FBM) 生成更细腻的纹理
float fbm(vec2 x) {
    float v = 0.0;
    float a = 0.5;
    vec2 shift = vec2(100.0);
    mat2 rot = mat2(cos(0.5), sin(0.5), -sin(0.5), cos(0.50));
    for (int i = 0; i < 4; ++i) {
        v += a * noise(x);
        x = rot * x * 2.0 + shift;
        a *= 0.5;
    }
    return v;
}

void main() {
    // 归一化坐标，将原点移至屏幕中心
    vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / min(u_resolution.x, u_resolution.y);
    float r = length(uv);
    
    // 基础半径：设定得足够大，以便将文字包裹在中心
    float baseRadius = 0.35;
    
    // 释放效果：光环轻微膨胀并消散
    float currentRadius = baseRadius * (1.0 + u_release * 0.1);
    
    // 引入低频噪声，打破内部黑色圆形的规整感，使其边缘产生有机的波动
    // 使用 uv 坐标而不是极坐标角度，避免产生接缝
    float edgeDistortion = fbm(uv * 4.0 + u_time * 0.2) * 0.03;
    float distortedR = r - edgeDistortion;
    
    // 1. 黑色圆盘 (遮挡体 / 事件视界)
    // 边缘极其锐利，内部绝对纯黑
    float disk = smoothstep(currentRadius - 0.002, currentRadius, distortedR);
    
    // 2. 日冕辉光 (Corona Glow)
    // 计算到扭曲边缘的距离
    float dist = max(0.0, distortedR - currentRadius);
    
    // 多层高斯/指数衰减，模拟真实的光学辉光
    // 内层：极度高亮，纯白
    float innerGlow = exp(-dist * 60.0) * 1.2;
    // 中层：柔和过渡，带有一点冷蓝色调
    float midGlow = exp(-dist * 15.0) * 0.6;
    // 外层：极其微弱的深空光晕
    float outerGlow = exp(-dist * 5.0) * 0.2;
    
    // 3. 微观耀斑 (Solar Flares)
    // 修复左侧半圆分界线：不使用 atan(y,x) 极坐标，而是直接使用笛卡尔坐标 uv 进行 3D 噪声采样
    // 这样可以保证在 360 度方向上都是连续的，没有任何接缝
    vec2 flareUv = normalize(uv) * (distortedR * 15.0 - u_time * 0.8);
    // 叠加一个旋转的坐标来增加动态感
    float angle = u_time * 0.1;
    mat2 rotMat = mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
    vec2 rotatedUv = rotMat * uv * 8.0;
    
    float flareNoise = fbm(rotatedUv + vec2(u_time * 0.3, 0.0));
    
    // 耀斑只在靠近边缘的地方显现
    float flareMask = exp(-dist * 25.0);
    float flares = smoothstep(0.4, 0.7, flareNoise) * flareMask * 0.8;
    
    // 组合光晕颜色
    vec3 coronaColor = vec3(0.0);
    coronaColor += vec3(1.0, 1.0, 1.0) * innerGlow;       // 核心纯白
    coronaColor += vec3(0.7, 0.85, 1.0) * midGlow;        // 中层冷蓝
    coronaColor += vec3(0.15, 0.3, 0.6) * outerGlow;      // 外层深蓝
    coronaColor += vec3(0.9, 0.95, 1.0) * flares;         // 耀斑高光
    
    // 叠加黑色圆盘遮罩
    vec3 finalColor = coronaColor * disk;
    
    // 释放时的全局淡出
    finalColor *= (1.0 - u_release);
    
    fragColor = vec4(finalColor, 1.0);
}`;

// WebGL 辅助函数
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

export const EventHorizonLoader: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const requestRef = useRef<number>();

  // 后端就绪监控（最短展示 2.5s）
  const isBackendReady = useBackendReady(2500);
  const [fadeOut, setFadeOut] = useState(false);
  const [mounted, setMounted] = useState(true);

  // 动画进度（避免 setState 频繁触发）
  const progressRef = useRef(0.0);
  const releaseRef = useRef(0.0);

  // ---------- WebGL 初始化 & 渲染循环 ----------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    
    // 优化：添加 context 属性，禁用 alpha 和抗锯齿以提升性能
    const gl = canvas.getContext('webgl2', { alpha: false, antialias: false });
    if (!gl) {
      console.error('[EventHorizon] WebGL2 not supported');
      return;
    }

    // 编译着色器
    const vs = createShader(gl, gl.VERTEX_SHADER, vertexShaderSource);
    const fs = createShader(gl, gl.FRAGMENT_SHADER, fragmentShaderSource);
    if (!vs || !fs) return;
    const program = createProgram(gl, vs, fs);
    if (!program) return;

    // 全屏矩形 VAO
    const posLoc = gl.getAttribLocation(program, 'a_position');
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

    // uniform 位置
    const uResolution = gl.getUniformLocation(program, 'u_resolution');
    const uTime = gl.getUniformLocation(program, 'u_time');
    const uProgress = gl.getUniformLocation(program, 'u_progress');
    const uRelease = gl.getUniformLocation(program, 'u_release');

    // 处理窗口尺寸变化
    // 优化：降低分辨率比例以提升性能，特别是在高分屏上
    const resize = () => {
      // 使用 1.0 或更低的比例，避免高分屏卡顿
      const pixelRatio = Math.min(window.devicePixelRatio, 1.5); 
      canvas.width = window.innerWidth * pixelRatio;
      canvas.height = window.innerHeight * pixelRatio;
      gl.viewport(0, 0, canvas.width, canvas.height);
    };
    window.addEventListener('resize', resize);
    resize();

    const start = performance.now();
    const render = (now: number) => {
      const elapsed = (now - start) * 0.001; // 秒

      // 更新动画参数
      if (!fadeOut) {
        // 逐步增加引力强度
        progressRef.current = Math.min(1.0, progressRef.current + 0.002);
      } else {
        // 释放阶段的指数回弹
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

    // 清理资源
    return () => {
      window.removeEventListener('resize', resize);
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      gl.deleteBuffer(buffer);
      gl.deleteVertexArray(vao);
    };
  }, [fadeOut]);

  // ---------- 后端就绪监听 & 两阶段卸载 ----------
  useEffect(() => {
    if (isBackendReady && !fadeOut) {
      setFadeOut(true);
      // CSS 过渡 0.8s，与样式保持一致
      const timer = setTimeout(() => {
        setMounted(false);
        // 设置全局标记，供 ChatView 等组件同步检查加载动画是否已完成
        (window as any).__LUNA_LOADING_COMPLETE__ = true;
        // 关键修复：加载动画完全卸载后派发事件，通知其他组件清理陈旧 waiting 状态
        // 这解决了输入框在初始加载期间捕获到 sending/streaming 消息后永久显示加载动画的问题
        window.dispatchEvent(new CustomEvent('luna:loading-complete'));
      }, 800);
      return () => clearTimeout(timer);
    }
  }, [isBackendReady, fadeOut]);

  if (!mounted) return null;

  return (
    <div className={`${styles.container} ${fadeOut ? styles.fadeOut : ''}`}>
      <canvas ref={canvasRef} className={styles.canvas} />
      <div className={`${styles.textOverlay} ${fadeOut ? styles.fadeOut : ''}`}>LUNA V3 INITIALIZING</div>
    </div>
  );
};
