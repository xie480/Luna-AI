import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import './FlexibleTypoContainer.css';

const textRollVariants = {
  initial: { 
    opacity: 0, 
    y: 15, // 从下方 15px 处进入
    scale: 0.96,
    filter: 'blur(4px)' // 进场自带科技感微糊
  },
  enter: { 
    opacity: 1, 
    y: 0, 
    scale: 1,
    filter: 'blur(0px)',
    transition: { 
      type: 'spring', 
      damping: 25, 
      stiffness: 200, 
      mass: 0.5 
    } 
  },
  exit: { 
    opacity: 0, 
    y: -15, // 向上滚出
    scale: 0.96,
    filter: 'blur(4px)',
    transition: { duration: 0.2, ease: "easeOut" } 
  }
};

interface FlexibleTypoContainerProps {
    currentText: string | null;
}

export const FlexibleTypoContainer: React.FC<FlexibleTypoContainerProps> = ({ currentText }) => {
  return (
    <div className="flexible-typo-container">
      <AnimatePresence mode="popLayout">
        {currentText && (
          <motion.div
            key={currentText} // Key 变化触发 AnimatePresence 的动画
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
