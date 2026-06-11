/**
 * MCP 模块统一面板组件。
 *
 * 做什么：将"MCP 市场"和"已接入 MCP"合并为一个带 Tab 导航的统一面板，
 *         类似 SettingsPanel 的左-右双栏布局。左侧 Tab → 右侧内容区。
 *
 * 为什么这样做：减少侧栏菜单项数量，MCP 市场与已接入属于同一功能域，
 *              合并后用户可在两个视图间快速切换，无需反复打开/关闭模态窗口。
 *
 * 内部 Tab 页：
 *   - 'market'：MCP 市场（浏览、搜索、详情、接入）
 *   - 'installed'：已接入 MCP（管理、启停、卸载）
 *
 * 边界条件：
 *   - MCP 市场详情页通过 mcpMarketStore 的内部状态管理，不再依赖全局 openModal
 *   - MCPMarketPage / MCPMarketCard / MCPMarketDetailPage / MCPInstalledListPage
 *     将收到 onNavigateTo 回调用于内部跳转，而非调用系统 store 的 openModal
 */
import React, { useState, useCallback } from 'react';
import { MCPMarketPage } from '../MCPMarket/MCPMarketPage';
import { MCPMarketDetailPage } from '../MCPMarket/MCPMarketDetailPage';
import { MCPInstalledListPage } from '../MCPMarket/MCPInstalledListPage';
import './MCPPanel.css';

/** MCP 面板内部 Tab 类型 */
type MCPTab = 'market' | 'installed';

export const MCPPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<MCPTab>('market');
  /** 是否在 market tab 内展示详情页（替代原来的 mcpMarketDetail 面板） */
  const [showDetail, setShowDetail] = useState(false);

  /**
   * 内部导航回调：供子组件调用以在 MCP 面板内切换视图。
   * 替代原来直接调用 useSystemStore.getState().openModal(panelType) 的方式。
   */
  const handleNavigate = useCallback((target: 'market' | 'installed' | 'detail') => {
    if (target === 'detail') {
      setShowDetail(true);
    } else {
      setShowDetail(false);
      setActiveTab(target);
    }
  }, []);

  /** 渲染右侧内容区 */
  const renderContent = () => {
    // 如果在 market tab 内展示了详情页，则优先渲染详情
    if (activeTab === 'market' && showDetail) {
      return (
        <MCPMarketDetailPage
          onBackToMarket={() => handleNavigate('market')}
          onNavigateToInstalled={() => handleNavigate('installed')}
        />
      );
    }

    switch (activeTab) {
      case 'market':
        return (
          <MCPMarketPage
            onNavigateToDetail={() => handleNavigate('detail')}
          />
        );
      case 'installed':
        return (
          <MCPInstalledListPage
            onNavigateToMarket={() => handleNavigate('market')}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="mcp-panel-container">
      {/* 左侧 Tab 导航栏 */}
      <div className="mcp-panel-sidebar">
        <div
          className={`mcp-nav-item ${activeTab === 'market' ? 'active' : ''}`}
          onClick={() => {
            setShowDetail(false);
            setActiveTab('market');
          }}
        >
          <span className="mcp-nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path>
              <line x1="3" y1="6" x2="21" y2="6"></line>
              <path d="M16 10a4 4 0 0 1-8 0"></path>
            </svg>
          </span>
          <span className="mcp-nav-text">市场</span>
        </div>
        <div
          className={`mcp-nav-item ${activeTab === 'installed' ? 'active' : ''}`}
          onClick={() => {
            setShowDetail(false);
            setActiveTab('installed');
          }}
        >
          <span className="mcp-nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14"></path>
              <path d="M12 5l7 7-7 7"></path>
            </svg>
          </span>
          <span className="mcp-nav-text">已接入</span>
        </div>
      </div>

      {/* 右侧内容区 */}
      <div className="mcp-panel-content">
        {renderContent()}
      </div>
    </div>
  );
};
