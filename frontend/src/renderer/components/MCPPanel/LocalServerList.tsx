import React, { useState } from 'react';
import type { LocalServerInfo } from '../../../shared/types';

interface LocalServerListProps {
  servers: LocalServerInfo[];
  onDelete: (serverId: string) => Promise<void>;
  onRefresh: () => Promise<void>;
}

export const LocalServerList: React.FC<LocalServerListProps> = ({
  servers,
  onDelete,
  onRefresh,
}) => {
  const [deletingId, setDeletingId] = useState<string | null>(null);

  if (servers.length === 0) {
    return (
      <div className="local-server-list__empty">
        暂无注册的本地服务器，请在上方填写配置并保存。
      </div>
    );
  }

  return (
    <div className="local-server-list">
      {servers.map((server) => (
        <div key={server.id} className="local-server-list__item">
          <div className="server-info">
            <span className={`server-status ${server.enabled ? 'status-enabled' : 'status-disabled'}`}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill={server.enabled ? '#22c55e' : '#a0a0a0'} stroke="none">
                <circle cx="12" cy="12" r="8"/>
              </svg>
            </span>
            <span className="server-name">{server.name}</span>
            <span className="server-command">{server.command}</span>
            <span className="server-tool-count">{server.tool_count} 个工具</span>
          </div>
          <div className="server-actions">
            <button
              className="btn-edit"
              onClick={() => {/* TODO: 打开编辑弹窗 */}}
            >
              编辑
            </button>
            <button
              className="btn-delete"
              onClick={async () => {
                setDeletingId(server.id);
                try {
                  await onDelete(server.id);
                } finally {
                  setDeletingId(null);
                }
              }}
              disabled={deletingId === server.id}
            >
              {deletingId === server.id ? '删除中...' : '删除'}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};
