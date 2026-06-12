import React, { useEffect, useState } from 'react';
import { MCP_LOCAL_REGISTER_MODE } from '../../../shared/enum';
import { useLocalServerStore } from '../../stores/mcpLocalServerStore';
import { ManualRegisterForm } from './ManualRegisterForm';
import { JsonImportPanel } from './JsonImportPanel';
import { LocalServerList } from './LocalServerList';

export const LocalServerPanel: React.FC = () => {
  // 注册模式：manual 或 json_import
  const [registerMode, setRegisterMode] = useState<
    typeof MCP_LOCAL_REGISTER_MODE.MANUAL | typeof MCP_LOCAL_REGISTER_MODE.JSON_IMPORT
  >(MCP_LOCAL_REGISTER_MODE.MANUAL);

  const {
    servers,
    isLoading,
    loadError,
    loadServers,
    deleteServer,
  } = useLocalServerStore();

  // 初始化加载已注册列表
  useEffect(() => {
    loadServers();
  }, [loadServers]);

  return (
    <div className="local-server-panel">
      {/* 注册模式切换 */}
      <div className="local-server-panel__mode-switch">
        <button
          className={`mode-btn ${registerMode === MCP_LOCAL_REGISTER_MODE.MANUAL ? 'mode-btn--active' : ''}`}
          onClick={() => setRegisterMode(MCP_LOCAL_REGISTER_MODE.MANUAL)}
        >
          表格手动填写
        </button>
        <button
          className={`mode-btn ${registerMode === MCP_LOCAL_REGISTER_MODE.JSON_IMPORT ? 'mode-btn--active' : ''}`}
          onClick={() => setRegisterMode(MCP_LOCAL_REGISTER_MODE.JSON_IMPORT)}
        >
          JSON 批量导入
        </button>
      </div>

      {/* 注册表单区域 */}
      <div className="local-server-panel__register-section">
        {registerMode === MCP_LOCAL_REGISTER_MODE.MANUAL ? (
          <ManualRegisterForm />
        ) : (
          <JsonImportPanel />
        )}
      </div>

      {/* 已注册服务器列表 */}
      <div className="local-server-panel__list-section">
        <h3 className="section-title">已注册的本地服务器</h3>
        {isLoading ? (
          <div className="loading-indicator">加载中...</div>
        ) : loadError ? (
          <div className="error-message">{loadError}</div>
        ) : (
          <LocalServerList
            servers={servers}
            onDelete={deleteServer}
            onRefresh={loadServers}
          />
        )}
      </div>
    </div>
  );
};
