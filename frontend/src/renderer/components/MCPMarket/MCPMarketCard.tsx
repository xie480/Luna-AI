/**
 * MCP 市场卡片组件。
 *
 * 做什么：在网格中展示单个 MCP Server 的摘要信息，包含名称、描述、
 *         健康状态、信誉评分、工具数量等。
 * 为什么这样做：卡片式展示让用户快速浏览和筛选。
 * 边界条件：is_installed=true 时显示"已接入"标记而非"接入"按钮。
 */
import React from 'react';
import { useMCPMarketStore } from '../../stores/mcpMarketStore';
import { useSystemStore } from '../../stores/systemStore';
import type { MCPMarketItem } from '../../types/mcpMarket';
import { MCP_HEALTH_STATUS_LABEL } from '../../../shared/enum';
import './MCPMarket.css';

interface MCPMarketCardProps {
  item: MCPMarketItem;
}

export const MCPMarketCard: React.FC<MCPMarketCardProps> = ({ item }) => {
  const fetchMarketDetail = useMCPMarketStore((s) => s.fetchMarketDetail);
  const openModal = useSystemStore((s) => s.openModal);

  /** 点击卡片时加载详情并打开详情模态窗口。 */
  const handleCardClick = async () => {
    // 异步加载详情到 Store
    await fetchMarketDetail(item.id);
    // 打开详情模态窗口
    openModal('mcpMarketDetail');
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

      {/* 元数据：健康状态、工具数量、评分 */}
      <div className="card-meta">
        <div className="meta-item health-status">
          <span
            className={`status-dot ${item.health_status}`}
            title={MCP_HEALTH_STATUS_LABEL[item.health_status] || item.health_status}
          />
          {MCP_HEALTH_STATUS_LABEL[item.health_status] || item.health_status}
        </div>
        <div className="meta-item">
          <span className="meta-icon">🛠️</span>
          {item.tool_count} 个工具
        </div>
        <div className="meta-item trust-score">
          <span className="meta-icon">⭐</span>
          {(item.trust_score * 100).toFixed(0)} 分
        </div>
      </div>

      {/* 卡片底部：接入状态 */}
      <div className="card-footer">
        {item.is_installed ? (
          <span className="installed-badge">✓ 已接入</span>
        ) : (
          <span className="install-hint">点击查看详情</span>
        )}
        <span className="install-count">已接入 {item.install_count} 次</span>
      </div>
    </div>
  );
};
