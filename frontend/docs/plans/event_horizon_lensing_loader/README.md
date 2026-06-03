# Event Horizon Lensing Loader (事件视界引力透镜加载器)

## 概念与视觉风格
本加载器专为 Luna-AI 设计，完美契合“硬核科技、极客黑客、极简高级”的视觉定位。
它摒弃了传统的进度条或旋转动画，采用纯粹的 WebGL Fragment Shader 实时演算引力透镜效应（Gravitational Lensing）。
在纯黑的背景中，一个不可见的“质量点”产生极强的引力，将背景中极其微弱的星光扭曲成完美的同心圆弧（爱因斯坦环）。
当后端服务（Go Runtime & Python AI Service）就绪时，引力源瞬间消失，被扭曲的空间光线如同紧绷的橡皮筋瞬间回弹，完成一次极具爆发力的视觉 Wipe（擦除）转场，无缝展示主界面。

## 核心优势
1. **零 CPU 负担**：所有空间扭曲与色散计算全部下放到 GPU 硬件加速完成，绝不拖慢后端服务的极速启动。
2. **极致高级感**：克制、静谧、深邃，完美隐喻 Luna-AI 的本地化与绝对隐私安全。
3. **天然转场张力**：引力释放的瞬间回弹，自带物理张力，无需生硬的淡出动画。

## 目录结构
- `EventHorizonLoader.tsx`: React 组件入口，负责 WebGL 上下文初始化、动画循环与状态机流转。
- `eventHorizonShader.glsl`: 核心 Fragment Shader，实现引力透镜与色散算法。
- `EventHorizonLoader.module.css`: 样式文件，控制全屏布局与离场过渡。
- `useBackendReady.ts`: 自定义 Hook，监听系统状态（`systemStore`）判断后端是否就绪。

## 集成步骤

1. **复制文件**：将本目录下的所有文件复制到前端项目的合适位置，例如 `frontend/src/renderer/components/LoadingScreen/`。
2. **状态对接**：
   - 确保 `frontend/src/renderer/stores/systemStore.ts` 中存在能够反映后端就绪状态的标识。
   - 当前 `useBackendReady.ts` 默认监听 `connectionStatus === 'connected'` 且 `aiConnectionStatus === 'connected'`。可根据实际业务逻辑调整。
3. **入口挂载**：
   - 在 `frontend/src/renderer/index.tsx` 或 `App.tsx` 的最外层挂载 `<EventHorizonLoader />`。
   - 组件内部已实现“两阶段卸载”（Two-Stage Unmount），在离场动画结束后会自动从 React 树中销毁，不会阻挡底层主界面的交互。

```tsx
// 示例：在 App.tsx 中使用
import React from 'react';
import { EventHorizonLoader } from './components/LoadingScreen/EventHorizonLoader';
import { MainLayout } from './components/MainLayout';

export const App: React.FC = () => {
  return (
    <>
      <EventHorizonLoader />
      <MainLayout />
    </>
  );
};
```
