/**
 * MCP 市场卡片组件。
 *
 * 做什么：在网格中展示单个 MCP Server 的摘要信息，包含名称、描述和标签。
 * 为什么这样做：卡片式展示让用户快速浏览和筛选。
 * 边界条件：is_installed=true 时显示"已接入"标记而非"接入"按钮。
 *          onNavigateToDetail 回调由 MCPPanel 传入，用于内部导航。
 */
import React from 'react';
import { useMCPMarketStore } from '../../stores/mcpMarketStore';
import type { MCPMarketItem } from '../../types/mcpMarket';
import './MCPMarket.css';

interface MCPMarketCardProps {
  item: MCPMarketItem;
  /** 导航到详情页的回调（由 MCPPanel 传入） */
  onNavigateToDetail?: () => void;
}

export const MCPMarketCard: React.FC<MCPMarketCardProps> = ({ item, onNavigateToDetail }) => {
  const fetchMarketDetail = useMCPMarketStore((s) => s.fetchMarketDetail);

  /** 点击卡片时加载详情并通知父组件切换到详情视图。 */
  const handleCardClick = async () => {
    // 异步加载详情到 Store
    await fetchMarketDetail(item.id);
    // 通知 MCPPanel 切换到详情视图（不再依赖全局 openModal）
    onNavigateToDetail?.();
  };

  return (
    <div
      className="mcp-market-card"
      onClick={handleCardClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          handleCardClick();
        }
      }}
    >
      {/* 卡片头部：Logo + 名称 + 作者 */}
      <div className="card-header">
        <div className="card-logo">
          {item.logo_url ? (
            <img src={item.logo_url} alt={item.display_name} />
          ) : (
            <div className="card-logo-placeholder">🔧</div>
          )}
        </div>
        <div className="card-title-group">
          <h3 className="card-name">{item.display_name}</h3>
          <span className="card-author">@{item.author}</span>
        </div>
      </div>

      {/* 描述 */}
      <p className="card-description">{item.description}</p>

      {/* 标签 */}
      <div className="card-tags">
        {item.tags.slice(0, 3).map((tag) => (
          <span key={tag} className="tag-badge">
            {tag}
          </span>
        ))}
        {item.tags.length > 3 && (
          <span className="tag-more">+{item.tags.length - 3}</span>
        )}
      </div>

      {/* 卡片底部：接入状态 */}
      <div className="card-footer">
        {item.is_installed ? (
          <span className="installed-badge">✓ 已接入</span>
        ) : (
          <span className="install-hint">点击查看详情</span>
        )}
      </div>
    </div>
  );
};
