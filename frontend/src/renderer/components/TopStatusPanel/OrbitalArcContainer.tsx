import React from 'react';
import { VisualStateItem } from '../../stores/visualStatusQueueStore';
import { TrackBackground } from './TrackBackground';
import { StarEntity, determinePhase } from './StarEntity';
import { FlexibleTypoContainer } from './FlexibleTypoContainer';

interface OrbitalArcContainerProps {
    currentVisualState: VisualStateItem | null;
    queueLength: number;
}

export const OrbitalArcContainer: React.FC<OrbitalArcContainerProps> = ({ currentVisualState, queueLength }) => {

    const phase = determinePhase(currentVisualState, queueLength);

    return (
        <div className="orbital-arc-container">
            {/* 1. 轨道背景层 (SVG) */}
            <TrackBackground phase={phase} colorTheme={currentVisualState?.colorTheme} />

            {/* 2. 主星动效层 (Framer Motion) */}
            <StarEntity 
                currentVisualState={currentVisualState} 
                queueLength={queueLength} 
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
