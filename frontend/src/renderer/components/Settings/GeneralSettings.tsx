import React from 'react';
import { useSystemStore } from '../../stores/systemStore';

export const GeneralSettings: React.FC = () => {
  const isLive2dEnabled = useSystemStore((state) => state.isLive2dEnabled);
  const setLive2dEnabled = useSystemStore((state) => state.setLive2dEnabled);
  const theme = useSystemStore((state) => state.theme);
  const setTheme = useSystemStore((state) => state.setTheme);

  return (
    <div className="settings-content-section">
      <h3 className="settings-section-title">通用设置</h3>
      
      <div className="settings-item">
        <div className="settings-item-info">
          <div className="settings-item-title">Live2D 模型渲染</div>
          <div className="settings-item-desc">开启或关闭主界面的 Live2D 角色渲染。关闭后可降低系统资源消耗。</div>
        </div>
        <div className="settings-item-control">
          <label className="switch">
            <input
              type="checkbox"
              checked={isLive2dEnabled}
              onChange={(e) => setLive2dEnabled(e.target.checked)}
            />
            <span className="slider round"></span>
          </label>
        </div>
      </div>

      <div className="settings-item">
        <div className="settings-item-info">
          <div className="settings-item-title">界面主题</div>
          <div className="settings-item-desc">选择软件的界面颜色主题。</div>
        </div>
        <div className="settings-item-control">
          <select
            className="theme-select"
            value={theme}
            onChange={(e) => setTheme(e.target.value as 'dark' | 'light')}
          >
            <option value="dark">暗色 (Dark)</option>
            <option value="light">亮色 (Light)</option>
          </select>
        </div>
      </div>
    </div>
  );
};
