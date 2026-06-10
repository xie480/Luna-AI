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

/**
 * 将后端 stage 名称映射到对应的 StarPhase。
 * 做什么：根据当前显示的 VisualStateItem 和队列长度，决定主星的动画阶段。
 * 为什么这样做：
 *   - "llm_streaming" 阶段对应 §1.1 的"并发输出态 (Concurrent LLM)"，
 *     主星应呈现高频脉冲的"神经连结供能"视觉主题（高饱和青绿色 #00FFCC）。
 *   - 之前误写了 "MAIN_CHAT_LLM" 作为匹配，这个字符串永远不会被后端推送，
 *     导致 LLM 流式生成期间主星一直停留在 RUNNING_NORMAL 而非激活态。
 * 边界条件：
 *   - state 为 null → IDLE
 *   - state.state === 'ERROR' → ERROR
 *   - stage 为 llm_streaming → CONCURRENT_LLM
 *   - queueLength >= 3 → RUNNING_WARP（拥塞加速态）
 *   - 其他 → RUNNING_NORMAL
 */
export const determinePhase = (state: VisualStateItem | null, queueLength: number): StarPhase => {
  if (!state) return 'IDLE';
  if (state.state === 'ERROR') return 'ERROR';
  // 匹配后端 ChatStatusStage.LLM_STREAMING = "llm_streaming"
  if (state.stage === 'llm_streaming') return 'CONCURRENT_LLM';
  if (queueLength >= 3) return 'RUNNING_WARP';
  return 'RUNNING_NORMAL';
};

const starVariants = {
  IDLE: (customColor: string) => ({
    scale: 0.2,
    opacity: 0.15,
    backgroundColor: customColor,
    boxShadow: `0 0 6px ${customColor}`,
    transition: { duration: 4, repeat: Infinity, repeatType: "mirror" as const, ease: "easeInOut" }
  }),
  RUNNING_NORMAL: (customColor: string) => ({
    scale: 1,
    opacity: 0.9,
    backgroundColor: customColor,
    boxShadow: `0 0 16px ${customColor}, 0 0 32px ${customColor}80`,
    transition: { type: 'spring', damping: 15, stiffness: 120 }
  }),
  RUNNING_WARP: (customColor: string) => ({
    scaleX: 2.5,
    scaleY: 0.6,
    opacity: 1,
    backgroundColor: customColor,
    boxShadow: `0 0 24px ${customColor}, 0 0 48px ${customColor}`,
    filter: 'blur(2px)',
    transition: { duration: 0.2, ease: "linear" }
  }),
  CONCURRENT_LLM: {
    scale: [1, 1.2, 1],
    opacity: 1,
    backgroundColor: themeColors.cyan,
    boxShadow: `0 0 20px ${themeColors.cyan}, 0 0 40px ${themeColors.cyan}80`,
    transition: { duration: 0.6, repeat: Infinity, ease: "easeInOut" }
  },
  ERROR: {
    scale: [1, 1.3, 0.8, 1.2, 1],
    x: [0, -6, 6, -3, 3, 0],
    opacity: [1, 0.8, 1, 0.5, 1],
    backgroundColor: themeColors.red,
    boxShadow: `0 0 24px ${themeColors.red}, 0 0 0px ${themeColors.red}`,
    transition: { duration: 0.3, repeat: Infinity, ease: "linear" }
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

export const StarEntity: React.FC<StarEntityProps> = ({ currentVisualState, queueLength, overrideColorTheme }) => {
  const phase = determinePhase(currentVisualState, queueLength);
  const effectiveColorTheme = currentVisualState?.colorTheme || overrideColorTheme;
  const color = getColorTheme(effectiveColorTheme);

  const [rippleKey, setRippleKey] = useState(0);

  useEffect(() => {
    if (currentVisualState) {
      setRippleKey(prev => prev + 1);
    }
  }, [currentVisualState]);

  return (
    <div className="star-entity-container">
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

      <motion.div
        className="star-core"
        variants={starVariants as Variants}
        initial="IDLE"
        animate={phase}
        custom={color}
      />
    </div>
  );
};
