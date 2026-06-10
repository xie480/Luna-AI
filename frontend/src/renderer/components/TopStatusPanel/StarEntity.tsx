import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence, Variants } from 'framer-motion';
import { VisualStateItem } from '../../stores/visualStatusQueueStore';
import './StarEntity.css';

// 定义全生命周期的状态枚举
export type StarPhase = 'IDLE' | 'RUNNING_NORMAL' | 'RUNNING_WARP' | 'CONCURRENT_LLM' | 'ERROR';

interface StarEntityProps {
  currentVisualState: VisualStateItem | null;
  queueLength: number;
}

const themeColors = {
  blue: '#3b82f6',
  purple: '#a855f7',
  red: '#ef4444',
  cyan: '#06b6d4',
  default: '#ffffff'
};

const getColorTheme = (colorTheme?: string) => {
  return themeColors[colorTheme as keyof typeof themeColors] || themeColors.default;
};

const determinePhase = (state: VisualStateItem | null, queueLength: number): StarPhase => {
  if (!state) return 'IDLE';
  if (state.state === 'ERROR') return 'ERROR';
  if (state.stage === 'LLM_OUTPUT' || state.stage === 'CONCURRENT_LLM') return 'CONCURRENT_LLM';
  if (queueLength >= 3) return 'RUNNING_WARP';
  return 'RUNNING_NORMAL';
};

const starVariants = {
  // 1. 空闲态：极简呼吸点，隐匿于桌面
  IDLE: {
    scale: 0.2,
    opacity: 0.1,
    backgroundColor: themeColors.default,
    boxShadow: `0 0 0px ${themeColors.default}`,
    transition: {
      duration: 4, // 极慢的 4秒呼吸周期
      repeat: Infinity,
      repeatType: "mirror" as const,
      ease: "easeInOut"
    }
  },

  // 2. 主链路流转态 (正常速度)：主星亮起，伴随微小跳动
  RUNNING_NORMAL: (customColor: string) => ({
    scale: 1,
    opacity: 0.9,
    backgroundColor: customColor,
    boxShadow: `0 0 16px ${customColor}, 0 0 32px ${customColor}80`, // 外发光光晕
    transition: {
      type: 'spring',
      damping: 15,
      stiffness: 120
    }
  }),

  // 3. 拥塞加速态 (Warp)：主星被拉长，产生动态模糊
  RUNNING_WARP: (customColor: string) => ({
    scaleX: 2.5, // 水平拉长，模拟光速残影
    scaleY: 0.6, // 垂直压扁
    opacity: 1,
    backgroundColor: customColor,
    boxShadow: `0 0 24px ${customColor}, 0 0 48px ${customColor}`,
    filter: 'blur(2px)', // 附加方向性模糊更佳
    transition: {
      duration: 0.2,
      ease: "linear"
    }
  }),

  // 4. 并发气泡渲染态 (LLM Output)：进入稳定供能状态
  CONCURRENT_LLM: {
    scale: [1, 1.1, 1], // 较高频的心跳脉冲，表示数据持续输出
    opacity: 1,
    backgroundColor: themeColors.cyan, // 设定数据流转的代表色（青色）
    boxShadow: `0 0 20px ${themeColors.cyan}, 0 0 40px ${themeColors.cyan}60`,
    transition: {
      duration: 0.8,
      repeat: Infinity,
      ease: "easeInOut"
    }
  },

  // 5. 离线/断连错误态：打破平滑，高频毛刺与警报色
  ERROR: {
    scale: [1, 1.2, 0.9, 1.1, 1], // 不规则的高频跳跃
    x: [0, -4, 4, -2, 2, 0], // 水平物理撕裂/抖动
    opacity: [1, 0.8, 1, 0.6, 1],
    backgroundColor: themeColors.red, // 危险红
    boxShadow: `0 0 24px ${themeColors.red}, 0 0 0px ${themeColors.red}`, // 光晕闪烁
    transition: {
      duration: 0.4,
      repeat: Infinity, // 持续警报
      ease: "linear"
    }
  }
};

const rippleVariants = {
  initial: { scale: 0.5, opacity: 0.8, borderColor: 'transparent' },
  animate: (color: string) => ({
    scale: 2.5,
    opacity: 0,
    borderColor: color,
    transition: { duration: 0.6, ease: "easeOut" }
  })
};

export const StarEntity: React.FC<StarEntityProps> = ({ currentVisualState, queueLength }) => {
  const phase = determinePhase(currentVisualState, queueLength);
  const color = getColorTheme(currentVisualState?.colorTheme);

  // 触发涟漪动画的 key
  const [rippleKey, setRippleKey] = useState(0);

  useEffect(() => {
    if (currentVisualState) {
      setRippleKey(prev => prev + 1);
    }
  }, [currentVisualState]);

  return (
    <div className="star-entity-container">
      {/* 涟漪层：状态切换时产生 */}
      <AnimatePresence mode="wait">
        {currentVisualState && phase !== 'ERROR' && phase !== 'IDLE' && (
          <motion.div
            key={`ripple-${rippleKey}`}
            className="star-ripple"
            custom={color}
            variants={rippleVariants}
            initial="initial"
            animate="animate"
          />
        )}
      </AnimatePresence>

      {/* 核心粒子层 */}
      <motion.div
        className="star-core"
        variants={starVariants as Variants}
        initial="IDLE"
        animate={phase}
        custom={color} // 传递动态主题色
      />
    </div>
  );
};
