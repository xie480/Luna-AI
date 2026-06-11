/**
 * MCP 市场详情页面（模态窗口版）。
 *
 * 做什么：展示单个 MCP Server 的完整信息，包括基础信息、工具能力清单、
 *         信任评分和接入入口。
 * 为什么这样做：用户在决定接入前需要深入了解工具能力和安全性。
 * 边界条件：未接入时显示"一键接入"按钮；已接入时提示已接入。
 */
import React, { useState } from 'react';
import { useMCPMarketStore } from '../../stores/mcpMarketStore';
import { useSystemStore } from '../../stores/systemStore';
import { InstallRemoteMCPDialog } from './InstallRemoteMCPDialog';
import './MCPMarket.css';

export const MCPMarketDetailPage: React.FC = () => {
  const { currentDetail, isDetailLoading, detailError } = useMCPMarketStore();
  const openModal = useSystemStore((s) => s.openModal);

  const [showInstallDialog, setShowInstallDialog] = useState(false);

  /** 加载态。 */
  if (isDetailLoading) {
    return (
      <div className="mcp-market-detail">
        <div className="detail-loading">
          <div className="spinner" />
          <span>加载中……</span>
        </div>
      </div>
    );
  }

  /** 错误态。 */
  if (detailError || !currentDetail) {
    return (
      <div className="mcp-market-detail">
        <div className="detail-error">
          <p>{detailError || '无法加载详情'}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="mcp-market-detail">
      {/* Banner 区 */}
      <div className="detail-banner">
        <div className="banner-logo">
          {currentDetail.logo_url ? (
            <img src={currentDetail.logo_url} alt={currentDetail.display_name} />
          ) : (
            <div className="banner-logo-placeholder">🔧</div>
          )}
        </div>
        <div className="banner-info">
          <h1 className="banner-name">{currentDetail.display_name}</h1>
          <p className="banner-author">作者: {currentDetail.author}</p>
          <div className="banner-meta">
            <span className={`health-badge ${currentDetail.health_status}`}>
              {currentDetail.health_status === 'online' ? '✅' : '⚠️'}{' '}
              {currentDetail.health_status === 'online' ? '在线' : '离线'}
            </span>
            <span className="stars-badge">
              ⭐ {currentDetail.github_stars.toLocaleString()}
            </span>
          </div>
        </div>
        <div className="banner-action">
          {currentDetail.is_installed ? (
            <button
              className="btn-manage"
              onClick={() => openModal('mcpInstalled')}
            >
              管理已接入
            </button>
          ) : (
            <button
              className="btn-install"
              onClick={() => setShowInstallDialog(true)}
            >
              一键接入
            </button>
          )}
        </div>
      </div>

      {/* 简介 */}
      <section className="detail-section">
        <h2>简介</h2>
        <p className="detail-description">{currentDetail.description}</p>
        {currentDetail.repository_url && (
          <a
            href={currentDetail.repository_url}
            target="_blank"
            rel="noopener noreferrer"
            className="repo-link"
          >
            📦 查看源代码
          </a>
        )}
      </section>

      {/* 工具能力清单 */}
      <section className="detail-section">
        <h2>能力清单（{currentDetail.tools.length} 个工具）</h2>
        <div className="tool-list">
          {currentDetail.tools.map((tool) => (
            <div key={tool.name} className="tool-item">
              <details>
                <summary className="tool-summary">
                  <span className="tool-name">{tool.name}</span>
                  <div className="tool-tags">
                    {tool.capability_tags.map((tag) => (
                      <span key={tag} className="tool-tag">
                        {tag}
                      </span>
                    ))}
                  </div>
                </summary>
                <div className="tool-detail">
                  <p className="tool-description">{tool.description}</p>
                  <div className="tool-schema">
                    <h4>参数 Schema</h4>
                    <pre>{JSON.stringify(tool.parameters_schema, null, 2)}</pre>
                  </div>
                </div>
              </details>
            </div>
          ))}
        </div>
      </section>

      {/* 信任与安全 */}
      <section className="detail-section">
        <h2>信任与安全</h2>
        <div className="trust-grid">
          <div className="trust-item">
            <span className="trust-label">信誉评分</span>
            <span className="trust-value">
              {(currentDetail.trust_score * 100).toFixed(0)} / 100
            </span>
          </div>
          <div className="trust-item">
            <span className="trust-label">许可证</span>
            <span className="trust-value">{currentDetail.license || '未知'}</span>
          </div>
          <div className="trust-item">
            <span className="trust-label">安全标记</span>
            <span className="trust-value">
              {currentDetail.security_flags.length > 0
                ? currentDetail.security_flags.join(', ')
                : '无安全警告'}
            </span>
          </div>
          <div className="trust-item">
            <span className="trust-label">最近提交</span>
            <span className="trust-value">
              {currentDetail.last_commit_at
                ? new Date(currentDetail.last_commit_at).toLocaleDateString()
                : '未知'}
            </span>
          </div>
        </div>
      </section>

      {/* 接入弹窗 */}
      {showInstallDialog && (
        <InstallRemoteMCPDialog
          marketplaceId={currentDetail.id}
          displayName={currentDetail.display_name}
          defaultEndpoint={
            currentDetail.install_instruction?.auth_type
              ? undefined
              : currentDetail.health_detail.protocol === 'sse'
                ? 'wss://...'
                : 'https://...'
          }
          authType={currentDetail.install_instruction?.auth_type || 'none'}
          authHint={currentDetail.install_instruction?.auth_hint}
          onClose={() => setShowInstallDialog(false)}
        />
      )}
    </div>
  );
};
