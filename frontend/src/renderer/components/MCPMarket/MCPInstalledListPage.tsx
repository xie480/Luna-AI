/**
 * 已接入远程 MCP 管理页面（模态窗口版）。
 *
 * 做什么：列出用户已经接入的所有远程 MCP 实例，支持启用/禁用、
 *         触发健康检查和卸载操作。
 * 为什么这样做：用户需要集中管理已接入的远程 MCP。
 * 边界条件：
 *   - 列表为空时提示用户前往市场接入。
 *   - 健康状态变更时自动刷新。
 *   - 卸载操作需要二次确认。
 */
import React, { useEffect, useState } from 'react';
import { useMCPMarketStore } from '../../stores/mcpMarketStore';
import { useSystemStore } from '../../stores/systemStore';
import { MCP_HEALTH_STATUS_LABEL } from '../../../shared/enum';
import './MCPMarket.css';

export const MCPInstalledListPage: React.FC = () => {
  const openModal = useSystemStore((s) => s.openModal);
  const {
    installedInstances,
    isInstancesLoading,
    fetchInstalledInstances,
    toggleInstanceActive,
    triggerHealthCheck,
    uninstallRemoteMCP,
  } = useMCPMarketStore();

  /** 当前正在确认卸载的实例 ID。 */
  const [confirmUninstall, setConfirmUninstall] = useState<string | null>(null);

  /** 进入页面时加载已接入列表。 */
  useEffect(() => {
    fetchInstalledInstances();
  }, [fetchInstalledInstances]);

  /** 切换启用/禁用。 */
  const handleToggleActive = async (instanceId: string, current: boolean) => {
    await toggleInstanceActive(instanceId, !current);
  };

  /** 触发健康检查。 */
  const handleHealthCheck = async (instanceId: string) => {
    await triggerHealthCheck(instanceId);
    await fetchInstalledInstances();
  };

  /** 确认卸载。 */
  const handleUninstall = async (instanceId: string) => {
    await uninstallRemoteMCP(instanceId);
    setConfirmUninstall(null);
    await fetchInstalledInstances();
  };

  /** 加载态。 */
  if (isInstancesLoading) {
    return (
      <div className="mcp-installed-page">
        <div className="installed-loading">
          <div className="spinner" />
          <span>加载中……</span>
        </div>
      </div>
    );
  }

  /** 空态：无已接入实例。 */
  if (installedInstances.length === 0) {
    return (
      <div className="mcp-installed-page">
        <div className="installed-empty">
          <div className="empty-icon">📦</div>
          <h2>还没有接入任何远程 MCP</h2>
          <p>前往 MCP 市场浏览并接入远程工具</p>
          <button
            className="btn-go-market"
            onClick={() => openModal('mcpMarket')}
          >
            前往市场
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mcp-installed-page">
      <header className="installed-header">
        <h1>已接入的远程 MCP</h1>
        <span className="installed-count">
          共 {installedInstances.length} 个实例
        </span>
        <button
          className="btn-browse-market"
          onClick={() => openModal('mcpMarket')}
        >
          浏览市场
        </button>
      </header>

      <div className="installed-list">
        {installedInstances.map((instance) => (
          <div key={instance.id} className="installed-card">
            <div className="card-main">
              {/* 状态指示器 */}
              <div className="card-status">
                <span
                  className={`status-indicator ${instance.health_status}`}
                  title={
                    MCP_HEALTH_STATUS_LABEL[instance.health_status] ||
                    instance.health_status
                  }
                />
              </div>

              {/* 实例信息 */}
              <div className="card-info">
                <h3 className="instance-name">{instance.display_name}</h3>
                <span className="instance-market-name">
                  {instance.market_name}
                </span>

                {/* 统计信息 */}
                <div className="instance-stats">
                  <span>🛠️ {instance.tool_count} 个工具</span>
                  <span>📞 {instance.total_calls} 次调用</span>
                  <span>
                    ⏱️{' '}
                    {instance.avg_latency_ms > 0
                      ? `${instance.avg_latency_ms}ms`
                      : '暂无数据'}
                  </span>
                </div>

                {/* 工具名称列表 */}
                <div className="instance-tools">
                  {instance.tool_names.slice(0, 5).map((name) => (
                    <span key={name} className="tool-name-badge">
                      {name}
                    </span>
                  ))}
                  {instance.tool_names.length > 5 && (
                    <span className="tool-name-more">
                      +{instance.tool_names.length - 5}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* 操作按钮区 */}
            <div className="card-actions">
              <button
                className={`btn-toggle ${instance.is_active ? 'active' : 'inactive'}`}
                onClick={() =>
                  handleToggleActive(instance.id, instance.is_active)
                }
                title={instance.is_active ? '禁用' : '启用'}
              >
                {instance.is_active ? '启用' : '禁用'}
              </button>

              <button
                className="btn-health-check"
                onClick={() => handleHealthCheck(instance.id)}
                title="健康检查"
              >
                刷新状态
              </button>

              {confirmUninstall === instance.id ? (
                <div className="confirm-uninstall">
                  <span>确认卸载？</span>
                  <button
                    className="btn-confirm-yes"
                    onClick={() => handleUninstall(instance.id)}
                  >
                    确认
                  </button>
                  <button
                    className="btn-confirm-no"
                    onClick={() => setConfirmUninstall(null)}
                  >
                    取消
                  </button>
                </div>
              ) : (
                <button
                  className="btn-uninstall"
                  onClick={() => setConfirmUninstall(instance.id)}
                >
                  卸载
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
