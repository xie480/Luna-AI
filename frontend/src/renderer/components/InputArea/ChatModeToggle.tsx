/**
 * 赛博朋克胶囊指示器（ChatModeToggle）
 * 做什么：输入框左侧的模式选择胶囊按钮。点击后弹出模式选择抽屉（通过 Portal 渲染到 body），
 *        在抽屉中列出所有可用模式及详细描述，用户点击选择切换。
 * 为什么这样做：抽屉使用 React Portal 渲染到 document.body，彻底避开任何父容器
 *             overflow:hidden / backdrop-filter / transform 等 CSS 属性的影响。
 * 输入输出：胶囊显示当前模式名称；点击弹出抽屉；选择模式后关闭抽屉并更新 chatMode。
 * 边界条件：当前仅两种模式（普通日常助理、极速闲聊），深度模式为未来预留。
 *           抽屉打开时点击外部或再次点击胶囊可关闭。
 * 异常行为：无。
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useSystemStore } from '../../stores/systemStore';
import { CHAT_MODE } from '../../../shared/enum';
import type { ChatMode } from '../../../shared/types';
import './ChatModeToggle.css';

/**
 * 聊天模式的中文显示配置。
 */
interface ModeConfig {
  label: string;
  title: string;
  description: string;
  IconComponent: React.FC<React.SVGProps<SVGSVGElement>>;
  themeColor: string;
}

/**
 * 日常助理图标：齿轮 + 盾牌轮廓。
 */
const DailyChatIcon: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.5" />
    <path
      d="M12 2v3m0 14v3M2 12h3m14 0h3M4.93 4.93l2.12 2.12m9.9 9.9l2.12 2.12M4.93 19.07l2.12-2.12m9.9-9.9l2.12-2.12"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
    />
    <path
      d="M12 2a10 10 0 0 1 10 10M12 22a10 10 0 0 0 10-10M2 12a10 10 0 0 0 10 10M2 12a10 10 0 0 1 10-10"
      stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeDasharray="2 3" opacity="0.5"
    />
  </svg>
);

/**
 * 极速闲聊图标：闪电箭头 + 能量轨迹。
 */
const CasualChatIcon: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path
      d="M13 2L4 14h6l-1 8 9-12h-6l1-8z"
      stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"
    />
    <path d="M10 10l3-4M14 14l-3 4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
  </svg>
);

/**
 * 未来深度模式占位图标。
 */
const DeepChatIcon: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path
      d="M12 2l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-1.5L12 2z"
      stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"
    />
    <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="0.8" strokeDasharray="2 3" opacity="0.4" />
    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="0.8" opacity="0.5" />
  </svg>
);

/**
 * 万能循环模式图标：无限循环箭头 + 目标锚点。
 * 做什么：为 Agent Loop 模式提供赛博朋克风格的 SVG 图标。
 * 为什么这样做：agent.md 明确禁止使用 emoji，所有图标必须使用 SVG 实现。
 */
const AgentLoopIcon: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    {/* 外层循环箭头 */}
    <path
      d="M12 2a10 10 0 0 1 7.07 2.93"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
    />
    <path
      d="M19.07 4.93L22 2M19.07 4.93L22 8"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
    />
    <path
      d="M12 22a10 10 0 0 1-7.07-2.93"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
    />
    <path
      d="M4.93 19.07L2 22M4.93 19.07L2 16"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
    />
    {/* 中心目标锚点 */}
    <circle cx="12" cy="12" r="3.5" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
    {/* 装饰性虚线圆 */}
    <circle cx="12" cy="12" r="7" stroke="currentColor" strokeWidth="0.8" strokeDasharray="2 3" opacity="0.4" />
  </svg>
);

/**
 * 胶囊按钮的 CSS class 名映射。
 * 做什么：将 chatMode 值映射为对应的 CSS class 后缀。
 * 为什么这样做：避免简单字符串替换导致 daily_chat → mode-daily-chat（应为 mode-daily）。
 */
const CAPSULE_MODE_CLASS: Record<ChatMode, string> = {
  [CHAT_MODE.DAILY_CHAT]: 'mode-daily',
  [CHAT_MODE.CASUAL_CHAT]: 'mode-casual',
  [CHAT_MODE.PLAN_STATE_NODE]: 'mode-plan-state-node',
  [CHAT_MODE.AGENT_LOOP]: 'mode-agent-loop',
};

const MODE_DISPLAY: Record<ChatMode, ModeConfig> = {
  [CHAT_MODE.AGENT_LOOP]: {
    label: '万能',
    title: '万能循环模式',
    description: 'Luna 会锁定你的目标，制定全局计划，逐步执行并在失败时自动修复或重新规划。适合长程、复杂、需要反复修正的深度任务。',
    IconComponent: AgentLoopIcon,
    themeColor: '#a855f7',
  },
  [CHAT_MODE.PLAN_STATE_NODE]: {
    label: '深度',
    title: '深度分析模式',
    description: 'Luna 会认真帮你拆解任务，调用知识库和工具去做深度分析。过程可能有点慢，但每个细节 Luna 都会处理好的……交给 Luna 就好。',
    IconComponent: DeepChatIcon,
    themeColor: '#ff6b35',
  },
  [CHAT_MODE.DAILY_CHAT]: {
    label: '日常',
    title: '日常陪伴模式',
    description: 'Luna 会陪你聊天、记住你说过的话，讨论想法或者只是安静地待着。不会太严肃也不会太随意……大多数时候这样就好。',
    IconComponent: DailyChatIcon,
    themeColor: '#00f0ff',
  },
  [CHAT_MODE.CASUAL_CHAT]: {
    label: '闲聊',
    title: '轻松闲聊模式',
    description: 'Luna 直接回答问题，快速搞定。不搞那些花里胡哨的……问什么答什么。',
    IconComponent: CasualChatIcon,
    themeColor: '#c850ff',
  },
};

/**
 * 模式选择抽屉内容组件（渲染到 Portal 中）。
 */
const ModeDrawer: React.FC<{
  drawerStyle: React.CSSProperties;
  chatMode: ChatMode;
  onSelect: (mode: ChatMode) => void;
  onClose: () => void;
}> = ({ drawerStyle, chatMode, onSelect, onClose }) => {
  return (
    <div className="chat-mode-drawer" style={drawerStyle} role="dialog" aria-label="选择聊天模式">
      <div className="drawer-header">
        <span className="drawer-title">选择模式</span>
        <button className="drawer-close-btn" onClick={onClose} aria-label="关闭" type="button">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div className="drawer-mode-list">
        {Object.entries(MODE_DISPLAY).map(([key, cfg]) => {
          const mode = key as ChatMode;
          const isSelected = mode === chatMode;
          const Icon = cfg.IconComponent;
          return (
            <button
              key={mode}
              className={`drawer-mode-item ${isSelected ? 'mode-item-selected' : ''}`}
              onClick={() => onSelect(mode)}
              type="button"
              style={{ '--mode-accent': cfg.themeColor } as React.CSSProperties}
            >
              <span className="mode-item-icon" aria-hidden="true"><Icon width="18" height="18" /></span>
              <span className="mode-item-text">
                <span className="mode-item-title">{cfg.title}</span>
                <span className="mode-item-desc">{cfg.description}</span>
              </span>
              {isSelected && (
                <span className="mode-item-check" aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};

/**
 * 赛博朋克胶囊指示器组件。
 * 胶囊渲染在输入框左侧，抽屉通过 Portal 渲染到 document.body。
 */
export const ChatModeToggle: React.FC = () => {
  const chatMode = useSystemStore((state) => state.chatMode);
  const setChatMode = useSystemStore((state) => state.setChatMode);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerStyle, setDrawerStyle] = useState<React.CSSProperties>({});

  const containerRef = useRef<HTMLDivElement>(null);
  const capsuleBtnRef = useRef<HTMLButtonElement>(null);

  const currentMode = MODE_DISPLAY[chatMode];
  const CurrentIcon = currentMode.IconComponent;

  const toggleDrawer = useCallback(() => setDrawerOpen((prev) => !prev), []);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  const handleSelect = useCallback(
    (mode: ChatMode) => {
      if (mode !== chatMode) setChatMode(mode);
      closeDrawer();
    },
    [chatMode, setChatMode, closeDrawer],
  );

  /**
   * 计算抽屉 fixed 坐标。
   * 为什么这样做：Portal 渲染到 body，必须手动计算胶囊的屏幕坐标来放置抽屉。
   * 定位策略：使用 bottom 属性将抽屉置于胶囊正上方。
   */
  useEffect(() => {
    if (drawerOpen && capsuleBtnRef.current) {
      const rect = capsuleBtnRef.current.getBoundingClientRect();
      const drawerW = Math.min(320, window.innerWidth - 24);
      const left = rect.left + rect.width / 2 - drawerW / 2;

      // 使用 bottom 定位：窗口高度 - 胶囊顶部 + 12px 间距
      // 即抽屉底部 = 胶囊顶部上方 12px
      const bottom = window.innerHeight - rect.top + 12;

      setDrawerStyle({
        position: 'fixed',
        left: Math.max(12, left),
        bottom: Math.max(12, bottom),
        width: drawerW,
      });
    }
  }, [drawerOpen]);

  /**
   * 外部点击关闭，Portal 中的元素不算 containerRef 的后代，
   * 因此通过 document 级 mousedown 检测。
   */
  useEffect(() => {
    if (!drawerOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      // 如果点击在胶囊上，不处理（由 toggleDrawer 管理）
      if (capsuleBtnRef.current?.contains(target)) return;
      // 如果点击在抽屉内，不处理
      const drawerEl = document.querySelector('.chat-mode-drawer');
      if (drawerEl?.contains(target)) return;
      closeDrawer();
    };
    // 使用 setTimeout 延迟绑定，避免当前 click 事件冒泡导致立即关闭
    const timerId = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
    }, 0);
    return () => {
      clearTimeout(timerId);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [drawerOpen, closeDrawer]);

  /** Escape 关闭 */
  useEffect(() => {
    if (!drawerOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeDrawer();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [drawerOpen, closeDrawer]);

  return (
    <div className="chat-mode-toggle-container" ref={containerRef}>
      {/* 胶囊按钮 */}
      <button
        ref={capsuleBtnRef}
        className={`chat-mode-capsule ${CAPSULE_MODE_CLASS[chatMode]} ${drawerOpen ? 'capsule-active' : ''}`}
        onClick={toggleDrawer}
        aria-label={`当前模式：${currentMode.title}。点击展开模式选择`}
        aria-expanded={drawerOpen}
        aria-haspopup="dialog"
        type="button"
      >
        <span className="capsule-icon" aria-hidden="true"><CurrentIcon width="14" height="14" /></span>
        <span className="capsule-label">{currentMode.label}</span>
        <span className={`capsule-arrow ${drawerOpen ? 'arrow-up' : ''}`} aria-hidden="true">
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
            <path
              d={drawerOpen ? 'M1 5L4 2L7 5' : 'M1 3L4 6L7 3'}
              stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"
            />
          </svg>
        </span>
      </button>

      {/* 通过 Portal 渲染抽屉到 document.body */}
      {drawerOpen && createPortal(
        <ModeDrawer
          drawerStyle={drawerStyle}
          chatMode={chatMode}
          onSelect={handleSelect}
          onClose={closeDrawer}
        />,
        document.body,
      )}
    </div>
  );
};
