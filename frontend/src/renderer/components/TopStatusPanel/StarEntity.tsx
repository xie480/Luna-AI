import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence, Variants } from 'framer-motion';
import { VisualStateItem } from '../../stores/visualStatusQueueStore';
import './StarEntity.css';

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

export const determinePhase = (state: VisualStateItem | null, queueLength: number): StarPhase => {
  if (!state) return 'IDLE';
  if (state.state === 'ERROR') return 'ERROR';
  if (state.stage === 'MAIN_CHAT_LLM' || state.stage === 'CONCURRENT_LLM') return 'CONCURRENT_LLM';
  if (queueLength >= 3) return 'RUNNING_WARP';
  return 'RUNNING_NORMAL';
};

const starVariants = {
  IDLE: {
    scale: 0.2,
    opacity: 0.1,
    backgroundColor: themeColors.default,
    boxShadow: `0 0 0px ${themeColors.default}`,
    transition: { duration: 4, repeat: Infinity, repeatType: "mirror" as const, ease: "easeInOut" }
  },
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

export const StarEntity: React.FC<StarEntityProps> = ({ currentVisualState, queueLength }) => {
  const phase = determinePhase(currentVisualState, queueLength);
  const color = getColorTheme(currentVisualState?.colorTheme);

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
