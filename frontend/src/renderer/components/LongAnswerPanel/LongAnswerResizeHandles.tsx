import React from 'react';

interface LongAnswerResizeHandlesProps {
  onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void;
}

export const LongAnswerResizeHandles: React.FC<LongAnswerResizeHandlesProps> = ({ onPointerDown }) => {
  return (
    <>
      <div 
        className="resize-handle resize-handle-e" 
        data-direction="e"
        onPointerDown={onPointerDown}
      />
      <div 
        className="resize-handle resize-handle-s" 
        data-direction="s"
        onPointerDown={onPointerDown}
      />
      <div 
        className="resize-handle resize-handle-se" 
        data-direction="se"
        onPointerDown={onPointerDown}
      />
    </>
  );
};
