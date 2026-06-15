/**
 * 已注册的本地服务器列表组件。
 *
 * 做什么：展示已注册的本地服务器列表，每行包含服务器名称、启动命令、工具数量、
 *        启用状态，"编辑"和"删除"操作按钮。
 *         编辑按钮打开编辑弹窗，删除按钮弹出二次确认框。
 * 为什么这样做：将列表展示、编辑弹窗和删除确认逻辑封装在同一个组件中，
 *              便于状态管理。
 * 输入输出：servers 列表、onDelete 和 onRefresh 回调来自父组件 LocalServerPanel。
 * 边界条件：空列表显示占位文案；删除中的服务器按钮禁用；编辑弹窗通过 overlay
 *           点击或 ESC 键关闭。
 * 异常行为：删除失败时通过 Store 抛出异常，按钮恢复可点击状态。
 */
import React, { useState } from 'react';
import type { LocalServerInfo } from '../../../shared/types';
import { EditServerModal } from './EditServerModal';

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
  // 编辑弹窗状态
  const [editingServer, setEditingServer] = useState<LocalServerInfo | null>(null);

  // 删除确认状态
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

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
              <svg width="10" height="10" viewBox="0 0 24 24" fill={server.enabled ? '#a082ff' : '#a0a0a0'} stroke="none">
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
              onClick={() => setEditingServer(server)}
            >
              编辑
            </button>
            {confirmDeleteId === server.id ? (
              /* 删除二次确认按钮组 */
              <span className="delete-confirm-group">
                <button
                  className="btn-delete-confirm"
                  onClick={async () => {
                    setDeletingId(server.id);
                    setConfirmDeleteId(null);
                    try {
                      await onDelete(server.id);
                    } finally {
                      setDeletingId(null);
                    }
                  }}
                  disabled={deletingId === server.id}
                >
                  {deletingId === server.id ? '删除中...' : '确认删除'}
                </button>
                <button
                  className="btn-delete-cancel"
                  onClick={() => setConfirmDeleteId(null)}
                >
                  取消
                </button>
              </span>
            ) : (
              <button
                className="btn-delete"
                onClick={() => setConfirmDeleteId(server.id)}
                disabled={deletingId === server.id}
              >
                删除
              </button>
            )}
          </div>
        </div>
      ))}

      {/* 编辑弹窗 */}
      {editingServer && (
        <EditServerModal
          server={editingServer}
          onClose={() => setEditingServer(null)}
          onSaved={onRefresh}
        />
      )}
    </div>
  );
};
