/**
 * 已注册的 MCP Skill 列表组件。
 *
 * 做什么：展示已注册的 MCP Skill 列表，每行包含名称、描述、版本、启用状态，
 *         "编辑"和"删除"操作按钮。
 * 为什么这样做：将列表展示和删除确认逻辑封装在同一个组件中，便于状态管理。
 * 输入输出：skills 列表、onDelete 和 onRefresh 回调来自父组件。
 * 边界条件：空列表显示占位文案；删除中的 Skill 按钮禁用。
 * 异常行为：删除失败时通过 Store 抛出异常，按钮恢复可点击状态。
 */
import React, { useState } from 'react';
import type { SkillInfo } from '../../../shared/types';

interface SkillListProps {
  skills: SkillInfo[];
  onDelete: (skillId: string) => Promise<void>;
  onRefresh: () => Promise<void>;
}

export const SkillList: React.FC<SkillListProps> = ({
  skills,
  onDelete,
  onRefresh,
}) => {
  // 删除确认状态
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (skills.length === 0) {
    return (
      <div className="local-server-list__empty">
        暂无注册的 MCP Skill，请在上方填写配置并保存。
      </div>
    );
  }

  return (
    <div className="local-server-list">
      {skills.map((skill) => (
        <div key={skill.id} className="local-server-list__item">
          <div className="server-info">
            <span
              className={`server-status ${skill.enabled ? 'status-enabled' : 'status-disabled'}`}
            >
              <svg
                width="10"
                height="10"
                viewBox="0 0 24 24"
                fill={skill.enabled ? '#22c55e' : '#a0a0a0'}
                stroke="none"
              >
                <circle cx="12" cy="12" r="8" />
              </svg>
            </span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span className="server-name">{skill.name}</span>
              <span
                style={{
                  fontSize: 12,
                  color: '#8b95a7',
                  maxWidth: 300,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {skill.description || '暂无描述'}
              </span>
            </div>
            <span
              style={{
                fontSize: 12,
                color: '#64748b',
                background: 'rgba(148, 163, 184, 0.1)',
                padding: '2px 8px',
                borderRadius: 4,
              }}
            >
              v{skill.version}
            </span>
          </div>
          <div className="server-actions">
            {confirmDeleteId === skill.id ? (
              /* 删除二次确认按钮组 */
              <span className="delete-confirm-group">
                <button
                  className="btn-delete-confirm"
                  onClick={async () => {
                    setDeletingId(skill.id);
                    setConfirmDeleteId(null);
                    try {
                      await onDelete(skill.id);
                    } finally {
                      setDeletingId(null);
                    }
                  }}
                  disabled={deletingId === skill.id}
                >
                  {deletingId === skill.id ? '删除中...' : '确认删除'}
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
                onClick={() => setConfirmDeleteId(skill.id)}
                disabled={deletingId === skill.id}
              >
                删除
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};
