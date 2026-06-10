import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import './FlexibleTypoContainer.css';
import { StarPhase } from './StarEntity';

interface FlexibleTypoContainerProps {
    currentText: string | null;
    phase: StarPhase;
}

export const FlexibleTypoContainer: React.FC<FlexibleTypoContainerProps> = ({ currentText, phase }) => {
  const isWarp = phase === 'RUNNING_WARP';
  const isError = phase === 'ERROR';
  
  let textClassName = 'flexible-text-block';
  if (isError) {
    textClassName += ' error-glow';
  } else if (isWarp) {
    textClassName += ' warp-text';
  } else if (phase === 'RUNNING_NORMAL' || phase === 'CONCURRENT_LLM') {
    textClassName += ' shimmer';
  }

  const textRollVariants = {
    initial: { 
      opacity: 0, 
      y: isWarp ? 25 : 15, 
      scale: 0.96,
      filter: isWarp ? 'blur(8px)' : 'blur(4px)'
    },
    enter: { 
      opacity: 1, 
      y: 0, 
      scale: 1,
      filter: 'blur(0px)',
      transition: isWarp 
        ? { duration: 0.1, ease: "linear" } 
        : { type: 'spring', damping: 25, stiffness: 200, mass: 0.5 } 
    },
    exit: { 
      opacity: 0, 
      y: isWarp ? -25 : -15, 
      scale: 0.96,
      filter: isWarp ? 'blur(8px)' : 'blur(4px)',
      transition: { duration: isWarp ? 0.1 : 0.2, ease: "easeOut" } 
    }
  };

  return (
    <div className="flexible-typo-container">
      <AnimatePresence mode="popLayout">
        {currentText && (
          <motion.div
            key={currentText}
            className="flexible-text-wrapper"
            variants={textRollVariants}
            initial="initial"
            animate="enter"
            exit="exit"
          >
            <motion.div 
              className={textClassName}
              animate={!isError && !isWarp ? { scale: [1, 1.02, 1] } : {}}
              transition={{ repeat: Infinity, duration: 4, ease: "easeInOut" }}
            >
              {currentText}
            </motion.div>
            
            {/* 全息扫光元素 (Holographic Sweep) */}
            {!isError && !isWarp && (
              <motion.div
                className="holographic-sweep"
                initial={{ left: '-50%' }}
                animate={{ left: '150%' }}
                transition={{
                  repeat: Infinity,
                  duration: 2.5,
                  ease: "easeInOut",
                  repeatDelay: 1.5
                }}
              />
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
