import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { StarPhase } from './StarEntity';
import './TrackBackground.css';

interface TrackBackgroundProps {
  phase: StarPhase;
  colorTheme?: string;
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

export const TrackBackground: React.FC<TrackBackgroundProps> = ({ phase, colorTheme }) => {
  // 核心轨道路径：向下弯曲的引力弧
  const pathData = "M 40 80 Q 200 120 360 80"; 
  const color = getColorTheme(colorTheme);

  const getStrokeDasharray = () => {
    if (phase === 'ERROR') return '4 8'; // 锯齿毛刺
    return '100% 0'; // 正常态为完整轨迹
  };

  const getOpacity = () => {
    if (phase === 'IDLE') return 0.05;
    if (phase === 'ERROR') return 0.6;
    return 0.4;
  };

  return (
    <div className="track-background">
      <svg className="track-svg" viewBox="0 0 400 160" preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="trackGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={color} stopOpacity="0" />
            <stop offset="50%" stopColor={color} stopOpacity="1" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
          <linearGradient id="errorGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={themeColors.red} stopOpacity="0.1" />
            <stop offset="50%" stopColor={themeColors.red} stopOpacity="1" />
            <stop offset="100%" stopColor={themeColors.red} stopOpacity="0.1" />
          </linearGradient>
        </defs>

        {/* 外层发光层 (Glow Layer) */}
        <motion.path 
          d={pathData} 
          className="track-path-glow"
          stroke={phase === 'ERROR' ? "url(#errorGradient)" : "url(#trackGradient)"}
          animate={{
            strokeDasharray: getStrokeDasharray(),
            opacity: getOpacity() * 0.6,
          }}
          transition={{ duration: 0.8 }}
        />

        {/* 核心实体线 (Core Line Layer) */}
        <motion.path 
          d={pathData} 
          className="track-path"
          stroke={phase === 'ERROR' ? "url(#errorGradient)" : "url(#trackGradient)"}
          animate={{
            strokeDasharray: getStrokeDasharray(),
            opacity: getOpacity(),
          }}
          transition={{ duration: 0.8 }}
        />
        
        {/* 流动能量片段 (Moving Energy Segment for warp/running) */}
        <AnimatePresence>
          {phase !== 'IDLE' && phase !== 'ERROR' && (
            <motion.path
              key="energy-segment"
              d={pathData}
              fill="none"
              stroke={color}
              strokeWidth="3"
              strokeLinecap="round"
              style={{ filter: `drop-shadow(0 0 8px ${color})` }}
              initial={{ strokeDasharray: "0 1000", strokeDashoffset: 0, opacity: 0 }}
              animate={{ 
                strokeDasharray: phase === 'RUNNING_WARP' ? ["0 1000", "150 1000"] : ["0 1000", "80 1000"],
                strokeDashoffset: phase === 'RUNNING_WARP' ? [0, -500] : [0, -400],
                opacity: 1
              }}
              exit={{ opacity: 0, transition: { duration: 0.3 } }}
              transition={{
                strokeDasharray: { duration: phase === 'RUNNING_WARP' ? 0.6 : 1.5, ease: "linear", repeat: Infinity },
                strokeDashoffset: { duration: phase === 'RUNNING_WARP' ? 0.6 : 1.5, ease: "linear", repeat: Infinity },
                opacity: { duration: 0.5 }
              }}
            />
          )}
        </AnimatePresence>
      </svg>
    </div>
  );
};
