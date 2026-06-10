import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence, Variants } from 'framer-motion';
import { VisualStateItem } from '../../stores/visualStatusQueueStore';
import './StarEntity.css';

export type StarPhase = 'IDLE' | 'RUNNING_NORMAL' | 'RUNNING_WARP' | 'CONCURRENT_LLM' | 'ERROR';

interface StarEntityProps {
  currentVisualState: VisualStateItem | null;
  queueLength: number;
  overrideColorTheme?: string;
}

const themeColors = {
  blue: '#3b82f6',
  purple: '#a855f7',
  red: '#ef4444',
  cyan: '#06b6d4',
  gray: '#999999',
  default: '#ffffff'
};

const getColorTheme = (colorTheme?: string) => {
  return themeColors[colorTheme as keyof typeof themeColors] || themeColors.default;
};

export const determinePhase = (state: VisualStateItem | null, queueLength: number): StarPhase => {
  if (!state) return 'IDLE';
  if (state.state === 'ERROR') return 'ERROR';
  if (state.stage === 'llm_streaming') return 'CONCURRENT_LLM';
  if (queueLength >= 3) return 'RUNNING_WARP';
  return 'RUNNING_NORMAL';
};

// 1. 父容器动画：处理 IDLE 的刚体共动漂浮，以及 ERROR 的抽搐震动
const containerVariants = {
  IDLE: {
    rotateX: [0, 360],
    rotateY: [0, 360],
    rotateZ: 0,
    x: 0,
    transition: { duration: 25, repeat: Infinity, ease: "linear" }
  },
  RUNNING_NORMAL: {
    rotateX: 0,
    rotateY: 0,
    rotateZ: 0,
    x: 0,
    transition: { type: "spring", stiffness: 40, damping: 20 }
  },
  RUNNING_WARP: {
    rotateX: 0,
    rotateY: 0,
    rotateZ: 0,
    x: 0,
    transition: { type: "spring", stiffness: 40, damping: 20 }
  },
  CONCURRENT_LLM: {
    rotateX: [-10, 10, -10],
    rotateY: [-10, 10, -10],
    rotateZ: [-5, 5, -5],
    x: 0,
    transition: { duration: 0.15, repeat: Infinity, ease: "linear" }
  },
  ERROR: {
    rotateX: 0,
    rotateY: 0,
    rotateZ: 0,
    x: [0, -3, 3, -1, 1, 0], // 横向错位故障闪烁
    transition: { duration: 0.2, repeat: Infinity, ease: "linear" }
  }
};

// 2. 外环动画：主控 Z 轴旋转
const outerVariants = {
  IDLE: () => ({
    rotateX: 45,
    rotateY: 30,
    rotateZ: 0,
    color: '#2C3E50',
    opacity: 0.4,
    filter: 'drop-shadow(0 0 0px transparent)',
    transition: { type: 'spring', damping: 20, stiffness: 40, color: { duration: 1.5 }, opacity: { duration: 1.5 } }
  }),
  RUNNING_NORMAL: (color: string) => ({
    rotateX: 45,
    rotateY: 0,
    rotateZ: [0, 360],
    color: color,
    opacity: 0.8,
    filter: `drop-shadow(0 0 3px ${color})`,
    transition: { 
      rotateZ: { duration: 4, repeat: Infinity, ease: "linear" },
      rotateX: { type: 'spring', damping: 20, stiffness: 40 },
      rotateY: { type: 'spring', damping: 20, stiffness: 40 },
      color: { duration: 0.6 },
      opacity: { duration: 0.6 }
    }
  }),
  RUNNING_WARP: (color: string) => ({
    rotateX: 45,
    rotateY: 0,
    rotateZ: [0, 360],
    color: color,
    opacity: 0.9,
    filter: `drop-shadow(0 0 5px ${color})`,
    transition: { 
      rotateZ: { duration: 1.5, repeat: Infinity, ease: "linear" },
      rotateX: { type: 'spring', damping: 20, stiffness: 40 },
      rotateY: { type: 'spring', damping: 20, stiffness: 40 }
    }
  }),
  CONCURRENT_LLM: {
    rotateX: [0, 360],
    rotateY: [0, 360],
    rotateZ: [0, 720],
    color: themeColors.cyan,
    opacity: 1,
    filter: `drop-shadow(0 0 6px ${themeColors.cyan})`,
    transition: {
      rotateX: { duration: 1.2, repeat: Infinity, ease: "linear" },
      rotateY: { duration: 1.5, repeat: Infinity, ease: "linear" },
      rotateZ: { duration: 0.8, repeat: Infinity, ease: "linear" }
    }
  },
  ERROR: {
    rotateX: 0,
    rotateY: 0,
    rotateZ: 0,
    color: themeColors.red,
    opacity: 1,
    filter: `drop-shadow(0 0 4px ${themeColors.red})`,
    transition: { duration: 0.1 } // 瞬间坍缩为 2D
  }
};

// 3. 中环动画：主控 Y 轴旋转
const middleVariants = {
  IDLE: () => ({
    rotateX: -30,
    rotateY: 45,
    rotateZ: 0,
    color: '#2C3E50',
    opacity: 0.4,
    filter: 'drop-shadow(0 0 0px transparent)',
    transition: { type: 'spring', damping: 20, stiffness: 40 }
  }),
  RUNNING_NORMAL: (color: string) => ({
    rotateX: 0,
    rotateY: [0, -360],
    rotateZ: 0,
    color: color,
    opacity: 0.8,
    filter: `drop-shadow(0 0 3px ${color})`,
    transition: { 
      rotateY: { duration: 3, repeat: Infinity, ease: "linear" },
      rotateX: { type: 'spring', damping: 20, stiffness: 40 },
      rotateZ: { type: 'spring', damping: 20, stiffness: 40 }
    }
  }),
  RUNNING_WARP: (color: string) => ({
    rotateX: 0,
    rotateY: [0, -360],
    rotateZ: 0,
    color: color,
    opacity: 0.9,
    filter: `drop-shadow(0 0 5px ${color})`,
    transition: { 
      rotateY: { duration: 1.2, repeat: Infinity, ease: "linear" }
    }
  }),
  CONCURRENT_LLM: {
    rotateX: [0, 360],
    rotateY: [0, -720],
    rotateZ: [0, -360],
    color: themeColors.cyan,
    opacity: 1,
    filter: `drop-shadow(0 0 6px ${themeColors.cyan})`,
    transition: {
      rotateX: { duration: 1.4, repeat: Infinity, ease: "linear" },
      rotateY: { duration: 0.9, repeat: Infinity, ease: "linear" },
      rotateZ: { duration: 1.2, repeat: Infinity, ease: "linear" }
    }
  },
  ERROR: {
    rotateX: 0,
    rotateY: 0,
    rotateZ: 0,
    color: themeColors.red,
    opacity: 1,
    filter: `drop-shadow(0 0 4px ${themeColors.red})`,
    transition: { duration: 0.1 }
  }
};

// 4. 内环动画：主控 X 轴翻滚与辅助能量色
const innerVariants = {
  IDLE: () => ({
    rotateX: 60,
    rotateY: -30,
    rotateZ: 0,
    color: '#2C3E50',
    opacity: 0.4,
    filter: 'drop-shadow(0 0 0px transparent)',
    transition: { type: 'spring', damping: 20, stiffness: 40 }
  }),
  RUNNING_NORMAL: () => ({
    rotateX: [0, 360],
    rotateY: 0,
    rotateZ: 0,
    color: themeColors.purple, // 内环在运行时呈现电光紫的辅助色
    opacity: 0.9,
    filter: `drop-shadow(0 0 3px ${themeColors.purple})`,
    transition: { 
      rotateX: { duration: 2, repeat: Infinity, ease: "linear" },
      rotateY: { type: 'spring', damping: 20, stiffness: 40 },
      rotateZ: { type: 'spring', damping: 20, stiffness: 40 }
    }
  }),
  RUNNING_WARP: () => ({
    rotateX: [0, 360],
    rotateY: 0,
    rotateZ: 0,
    color: themeColors.purple,
    opacity: 1,
    filter: `drop-shadow(0 0 5px ${themeColors.purple})`,
    transition: { 
      rotateX: { duration: 0.8, repeat: Infinity, ease: "linear" }
    }
  }),
  CONCURRENT_LLM: {
    rotateX: [0, -720],
    rotateY: [0, 360],
    rotateZ: [0, 180],
    color: '#00FA9A', // 极光青/薄荷绿
    opacity: 1,
    filter: `drop-shadow(0 0 6px #00FA9A)`,
    transition: {
      rotateX: { duration: 0.8, repeat: Infinity, ease: "linear" },
      rotateY: { duration: 1.1, repeat: Infinity, ease: "linear" },
      rotateZ: { duration: 1.3, repeat: Infinity, ease: "linear" }
    }
  },
  ERROR: {
    rotateX: 0,
    rotateY: 0,
    rotateZ: 0,
    color: themeColors.red,
    opacity: 1,
    filter: `drop-shadow(0 0 4px ${themeColors.red})`,
    transition: { duration: 0.1 }
  }
};

const rippleVariants = {
  initial: { scale: 0.5, opacity: 0.8, borderColor: 'transparent', filter: 'drop-shadow(0 0 0px transparent)' },
  animate: (color: string) => ({
    scale: 3,
    opacity: 0,
    borderColor: color,
    filter: `drop-shadow(0 0 8px ${color})`,
    transition: { duration: 0.8, ease: "easeOut" }
  })
};

// 动态构建带有缺口（Gap）的 SVG 细环
const RingSvg: React.FC<{ size: number, dasharray: string }> = ({ size, dasharray }) => {
  const strokeWidth = 1.5;
  const radius = (size - strokeWidth) / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="armillary-svg">
      <circle 
        cx={size / 2} 
        cy={size / 2} 
        r={radius} 
        fill="none" 
        stroke="currentColor" 
        strokeWidth={strokeWidth} 
        strokeDasharray={dasharray} 
        strokeLinecap="round" 
      />
    </svg>
  );
};

export const StarEntity: React.FC<StarEntityProps> = ({ currentVisualState, queueLength, overrideColorTheme }) => {
  const phase = determinePhase(currentVisualState, queueLength);
  const effectiveColorTheme = currentVisualState?.colorTheme || overrideColorTheme;
  const color = getColorTheme(effectiveColorTheme);

  const [rippleKey, setRippleKey] = useState(0);

  // 监听状态跃迁以触发 Ripple 涟漪
  useEffect(() => {
    if (currentVisualState) {
      setRippleKey(prev => prev + 1);
    }
  }, [currentVisualState]);

  return (
    <div className="star-entity-container">
      {/* 背景涟漪：在节点流转时触发 */}
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

      {/* 核心 3D 全息星轨仪 (Holographic Orbital Rings) */}
      <motion.div
        className="holographic-armillary"
        variants={containerVariants as Variants}
        initial="IDLE"
        animate={phase}
      >
        <motion.div className="armillary-ring outer" variants={outerVariants as Variants} initial="IDLE" animate={phase} custom={color}>
          <RingSvg size={16} dasharray="10 5.16" />
        </motion.div>
        <motion.div className="armillary-ring middle" variants={middleVariants as Variants} initial="IDLE" animate={phase} custom={color}>
          <RingSvg size={12} dasharray="10 6.5" />
        </motion.div>
        <motion.div className="armillary-ring inner" variants={innerVariants as Variants} initial="IDLE" animate={phase} custom={color}>
          <RingSvg size={8} dasharray="14 6.4" />
        </motion.div>
      </motion.div>
    </div>
  );
};
