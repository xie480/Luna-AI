import React from 'react';
import { useSystemStore } from '../../stores/systemStore';
import './Live2DConfigPanel.css';

export const Live2DConfigPanel: React.FC = () => {
  const live2dConfigMode = useSystemStore((state) => state.live2dConfigMode);
  const setLive2dConfigMode = useSystemStore((state) => state.setLive2dConfigMode);
  const showGlobalMessage = useSystemStore((state) => state.showGlobalMessage);

  if (live2dConfigMode === 'none') return null;

  const handleSaveTransform = () => {
    window.dispatchEvent(new CustomEvent('luna:live2d-save-transform'));
    showGlobalMessage('立绘配置已保存', 2000);
    setLive2dConfigMode('none');
  };

  const handleResetTransform = () => {
    window.dispatchEvent(new CustomEvent('luna:live2d-reset-transform'));
    showGlobalMessage('立绘已重置到默认位置', 2000);
  };

  const handleResetTracking = () => {
    window.dispatchEvent(new CustomEvent('luna:live2d-reset-tracking'));
    showGlobalMessage('追踪起点已重置', 2000);
  };

  const handleExitConfig = () => {
    setLive2dConfigMode('none');
    showGlobalMessage('已退出配置模式', 2000);
  };

  return (
    <div className="live2d-config-portal">
      <div className="live2d-config-status-bar">
        {live2dConfigMode === 'transform' ? '当前正在配置立绘' : '当前正在配置鼠标追踪点'}
      </div>
      <div className="live2d-config-panel">
        {live2dConfigMode === 'transform' && (
          <>
            <button className="config-btn save-btn" onClick={handleSaveTransform}>
              保存配置
            </button>
            <button className="config-btn reset-btn" onClick={handleResetTransform}>
              重置立绘
            </button>
          </>
        )}
        {live2dConfigMode === 'tracking' && (
          <button className="config-btn save-btn" onClick={handleResetTracking}>
            重置起点
          </button>
        )}
        <button className="config-btn exit-btn" onClick={handleExitConfig}>
          退出配置
        </button>
      </div>
    </div>
  );
};
