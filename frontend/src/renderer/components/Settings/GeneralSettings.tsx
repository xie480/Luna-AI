import React from 'react';
import { useSystemStore } from '../../stores/systemStore';
import { TTS_LANGUAGE, TTS_LANGUAGE_LABEL } from '../../../shared/enum';


export const GeneralSettings: React.FC = () => {
  const showBubbleRender = useSystemStore((state) => state.showBubbleRender);
  const setShowBubbleRender = useSystemStore((state) => state.setShowBubbleRender);
  const isLive2dEnabled = useSystemStore((state) => state.isLive2dEnabled);
  const setLive2dEnabled = useSystemStore((state) => state.setLive2dEnabled);
  const isLive2dIdleThrottlingEnabled = useSystemStore((state) => state.isLive2dIdleThrottlingEnabled);
  const setLive2dIdleThrottlingEnabled = useSystemStore((state) => state.setLive2dIdleThrottlingEnabled);
  const isLive2dBackgroundSuspensionEnabled = useSystemStore((state) => state.isLive2dBackgroundSuspensionEnabled);
  const setLive2dBackgroundSuspensionEnabled = useSystemStore((state) => state.setLive2dBackgroundSuspensionEnabled);
  const live2dMaxFPS = useSystemStore((state) => state.live2dMaxFPS);
  const setLive2dMaxFPS = useSystemStore((state) => state.setLive2dMaxFPS);
  const theme = useSystemStore((state) => state.theme);
  const setTheme = useSystemStore((state) => state.setTheme);
  const isTTSEnabled = useSystemStore((state) => state.isTTSEnabled);
  const setTTSEnabled = useSystemStore((state) => state.setTTSEnabled);
  const ttsLanguage = useSystemStore((state) => state.ttsLanguage);
  const setTTSLanguage = useSystemStore((state) => state.setTTSLanguage);

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
          <div className="settings-item-title">Live2D 空闲降频</div>
          <div className="settings-item-desc">无交互待机时自动降低帧率，事件触发时恢复。大幅降低待机资源消耗。</div>
        </div>
        <div className="settings-item-control">
          <label className="switch">
            <input
              type="checkbox"
              checked={isLive2dIdleThrottlingEnabled}
              onChange={(e) => setLive2dIdleThrottlingEnabled(e.target.checked)}
            />
            <span className="slider round"></span>
          </label>
        </div>
      </div>

      <div className="settings-item">
        <div className="settings-item-info">
          <div className="settings-item-title">Live2D 后台挂起</div>
          <div className="settings-item-desc">应用进入后台或被遮挡时，彻底暂停渲染。恢复可见时自动继续。</div>
        </div>
        <div className="settings-item-control">
          <label className="switch">
            <input
              type="checkbox"
              checked={isLive2dBackgroundSuspensionEnabled}
              onChange={(e) => setLive2dBackgroundSuspensionEnabled(e.target.checked)}
            />
            <span className="slider round"></span>
          </label>
        </div>
      </div>

      <div className="settings-item">
        <div className="settings-item-info">
          <div className="settings-item-title">展示气泡渲染</div>
          <div className="settings-item-desc">开启或关闭聊天气泡的展示。关闭后对话仍正常进行，但不再显示气泡动画。</div>
        </div>
        <div className="settings-item-control">
          <label className="switch">
            <input
              type="checkbox"
              checked={showBubbleRender}
              onChange={(e) => setShowBubbleRender(e.target.checked)}
            />
            <span className="slider round"></span>
          </label>
        </div>
      </div>

      <div className="settings-item">
        <div className="settings-item-info">
          <div className="settings-item-title">本地 TTS 语音服务</div>
          <div className="settings-item-desc">开启或关闭本地语音合成。需要先在 .env 中正确配置 TTS_BAT_PATH。</div>
        </div>
        <div className="settings-item-control">
          <label className="switch">
            <input
              type="checkbox"
              checked={isTTSEnabled}
              onChange={(e) => setTTSEnabled(e.target.checked)}
            />
            <span className="slider round"></span>
          </label>
        </div>
      </div>

      {/* TTS 语言选择 */}
      <div className="settings-item">
        <div className="settings-item-info">
          <div className="settings-item-title">TTS 语音语言</div>
          <div className="settings-item-desc">选择 TTS 语音合成的语言。选择日语时，Luna 的回复将附带自然口语化的日语翻译。</div>
        </div>
        <div className="settings-item-control">
          <select
            className="theme-select"
            value={ttsLanguage}
            onChange={(e) => setTTSLanguage(e.target.value)}
          >
            <option value={TTS_LANGUAGE.ZH}>{TTS_LANGUAGE_LABEL[TTS_LANGUAGE.ZH]}</option>
            <option value={TTS_LANGUAGE.JA}>{TTS_LANGUAGE_LABEL[TTS_LANGUAGE.JA]}</option>
          </select>
        </div>
      </div>

      <div className="settings-item">
        <div className="settings-item-info">
          <div className="settings-item-title">Live2D 最大帧率</div>
          <div className="settings-item-desc">设置 Live2D 渲染的最大帧率。</div>
        </div>
        <div className="settings-item-control">
          <select
            className="theme-select"
            value={live2dMaxFPS}
            onChange={(e) => setLive2dMaxFPS(parseInt(e.target.value, 10) as 30 | 60 | 90 | 120)}
          >
            <option value="30">30 FPS</option>
            <option value="60">60 FPS</option>
            <option value="90">90 FPS</option>
            <option value="120">120 FPS</option>
          </select>
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
            onChange={(e) => setTheme(e.target.value as 'dark' | 'light' | 'cyberpunk')}
          >
            <option value="dark">暗色 (Dark)</option>
            <option value="light">亮色 (Light)</option>
            <option value="cyberpunk">赛博朋克 (Cyberpunk)</option>
          </select>
        </div>
      </div>
    </div>
  );
};
