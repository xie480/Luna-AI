/**
 * MCP 一键接入弹窗。
 *
 * 做什么：收集用户接入远程 MCP 所需的配置信息（Endpoint URL、自定义名称、
 *         鉴权凭证等），调用接入 API。
 * 为什么这样做：用户不需要手动调用注册 API，通过友好界面完成配置。
 * 边界条件：
 *   - 如果 Server 无需鉴权，隐藏鉴权表单。
 *   - 如果 Server 需要鉴权，根据 auth_type 显示对应的输入框。
 *   - 接入完成后显示成功反馈并自动关闭弹窗。
 */
import React, { useState, useEffect } from 'react';
import { useMCPMarketStore } from '../../stores/mcpMarketStore';
import {
  MCP_AUTH_TYPE,
  MCP_AUTH_TYPE_LABEL,
} from '../../../shared/enum';
import type { InstallConfig } from '../../types/mcpMarket';
import './MCPMarket.css';

interface DialogProps {
  marketplaceId: string;
  displayName: string;
  defaultEndpoint?: string;
  authType: string;
  authHint?: string;
  onClose: () => void;
}

export const InstallRemoteMCPDialog: React.FC<DialogProps> = ({
  marketplaceId,
  displayName,
  defaultEndpoint,
  authType,
  authHint,
  onClose,
}) => {
  const { installRemoteMCP, installingMarketplaceId, installResult, clearInstallResult } =
    useMCPMarketStore();

  const [endpointUrl, setEndpointUrl] = useState(defaultEndpoint || '');
  const [customName, setCustomName] = useState(displayName);
  const [authToken, setAuthToken] = useState('');

  const isInstalling = installingMarketplaceId === marketplaceId;
  const needsAuth = authType !== MCP_AUTH_TYPE.NONE;

  /** 接入成功后自动关闭弹窗。 */
  useEffect(() => {
    if (installResult?.success) {
      const timer = setTimeout(() => {
        clearInstallResult();
        onClose();
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [installResult, clearInstallResult, onClose]);

  /** 处理接入操作。 */
  const handleInstall = async () => {
    const config: InstallConfig = {
      endpoint_url: endpointUrl,
      display_name: customName,
      auth_config: needsAuth
        ? {
            type: authType as InstallConfig['auth_config']['type'],
            token: authToken,
          }
        : undefined,
    };
    await installRemoteMCP(marketplaceId, config);
  };

  return (
    <div className="mcp-install-dialog-overlay" onClick={onClose}>
      <div
        className="mcp-install-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog-header">
          <h2>接入远程 MCP</h2>
          <span className="dialog-subtitle">{displayName}</span>
        </div>

        <div className="dialog-body">
          {/* Endpoint URL 输入 */}
          <div className="form-group">
            <label>Endpoint URL</label>
            <input
              type="text"
              value={endpointUrl}
              onChange={(e) => setEndpointUrl(e.target.value)}
              placeholder="https://mcp.example.com/sse 或 http://..."
              disabled={isInstalling}
            />
          </div>

          {/* 自定义名称输入 */}
          <div className="form-group">
            <label>自定义名称</label>
            <input
              type="text"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              placeholder="给这个 MCP 起个好记的名字"
              disabled={isInstalling}
            />
          </div>

          {/* 鉴权配置 */}
          {needsAuth && (
            <div className="form-group">
              <label>
                鉴权凭证（{MCP_AUTH_TYPE_LABEL[authType] || authType}）
              </label>
              {authHint && <p className="auth-hint">{authHint}</p>}
              {authType === MCP_AUTH_TYPE.BEARER && (
                <input
                  type="password"
                  value={authToken}
                  onChange={(e) => setAuthToken(e.target.value)}
                  placeholder="Bearer Token"
                  disabled={isInstalling}
                />
              )}
              {authType === MCP_AUTH_TYPE.API_KEY && (
                <input
                  type="password"
                  value={authToken}
                  onChange={(e) => setAuthToken(e.target.value)}
                  placeholder="API Key"
                  disabled={isInstalling}
                />
              )}
            </div>
          )}

          {/* 操作结果反馈 */}
          {installResult && (
            <div
              className={`install-result ${installResult.success ? 'success' : 'error'}`}
            >
              {installResult.success ? '✅ ' : '❌ '}
              {installResult.message}
            </div>
          )}
        </div>

        <div className="dialog-footer">
          <button
            className="btn-cancel"
            onClick={onClose}
            disabled={isInstalling}
          >
            取消
          </button>
          <button
            className="btn-confirm"
            onClick={handleInstall}
            disabled={isInstalling || !endpointUrl.trim()}
          >
            {isInstalling ? '正在接入……' : '确认接入'}
          </button>
        </div>
      </div>
    </div>
  );
};
