import React from 'react';
import { VisualStateItem } from '../../stores/visualStatusQueueStore';
import { TrackBackground } from './TrackBackground';
import { StarEntity, determinePhase, StarPhase } from './StarEntity';
import { FlexibleTypoContainer } from './FlexibleTypoContainer';

interface OrbitalArcContainerProps {
    currentVisualState: VisualStateItem | null;
    queueLength: number;
    idleTheme?: 'blue' | 'gray'; // 接收父组件传入的空闲态主题
}

export const OrbitalArcContainer: React.FC<OrbitalArcContainerProps> = ({ currentVisualState, queueLength, idleTheme }) => {

    // 修复点：如果不传递 idleTheme 给 determinePhase，空闲时 phase 总是 IDLE，但颜色需要根据连接状态区分
    // 由于 TrackBackground 和 StarEntity 已经处理了 IDLE phase 下的主题色，这里只需透传即可。
    const phase = determinePhase(currentVisualState, queueLength);
    const resolvedTheme = currentVisualState?.colorTheme || idleTheme || 'blue';

    return (
        <div className="orbital-arc-container">
            {/* 1. 轨道背景层 (SVG) */}
            <TrackBackground phase={phase} colorTheme={resolvedTheme} />

            {/* 2. 主星动效层 (Framer Motion) */}
            <StarEntity 
                currentVisualState={currentVisualState} 
                queueLength={queueLength} 
                overrideColorTheme={idleTheme}
            />

            {/* 3. 多行柔性文本层 (Framer Motion AnimatePresence) */}
            <div className="orbital-text-layer">
                 <FlexibleTypoContainer 
                    currentText={currentVisualState?.text || null} 
                    phase={phase}
                 />
            </div>
        </div>
    );
};
