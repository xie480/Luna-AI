import React from 'react';
import './TrackBackground.css';

interface TrackBackgroundProps {
  phase: 'IDLE' | 'RUNNING' | 'ERROR';
}

export const TrackBackground: React.FC<TrackBackgroundProps> = ({ phase }) => {
  // 定义一个简单的弧线，实际应用中可以根据需要调整控制点，
  // 或者利用 framer-motion 与 SVG path length 联动
  const pathData = "M 20 24 Q 180 48 340 24"; 

  let className = "track-path";
  if (phase === 'IDLE') className += " idle";
  else if (phase === 'ERROR') className += " error";
  else className += " running";

  return (
    <div className="track-background">
      <svg className="track-svg" viewBox="0 0 360 48" preserveAspectRatio="none">
        <path 
            d={pathData} 
            className={className} 
        />
      </svg>
    </div>
  );
};
