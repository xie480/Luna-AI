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
            className="flexible-text-block"
            variants={textRollVariants}
            initial="initial"
            animate="enter"
            exit="exit"
          >
            {currentText}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
