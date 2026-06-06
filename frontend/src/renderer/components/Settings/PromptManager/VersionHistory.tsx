/**
 * 版本历史组件
 * 做什么：展示选中模板的版本时间线，高亮当前 Published 版本，支持版本选择与发布操作。
 */
import React, { useCallback, useState } from 'react';
import { usePromptStore } from '../../../stores/promptStore';
import { PromptVersion } from '../../../types/prompt';

interface VersionHistoryProps {
  /** 当前选中的模板 ID */
  templateId: string | null;
  /** 选中版本后的回调 */
  onSelectVersion: (version: PromptVersion) => void;
  /** 当前选中的版本 ID */
  selectedVersionId: string | null;
}

/** 版本状态中文映射 */
const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  archived: '已归档',
};

export const VersionHistory: React.FC<VersionHistoryProps> = ({
  templateId,
  onSelectVersion,
  selectedVersionId,
}) => {
  const { versions, isLoadingVersions, publishVersion, rollbackVersion, templates } = usePromptStore();
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [rollingBackId, setRollingBackId] = useState<string | null>(null);

  const templateData = templateId ? templates.find(t => t.id === templateId) : null;

  const handlePublish = useCallback(async (versionId: string) => {
    if (!templateId) return;
    setPublishingId(versionId);
    try {
      await publishVersion(templateId, versionId);
    } catch (err) {
      // 错误由 store 层捕获并展示
    } finally {
      setPublishingId(null);
    }
  }, [templateId, publishVersion]);

  const handleRollback = useCallback(async (versionId: string) => {
    if (!templateId) return;
    if (!window.confirm('回滚操作将删除当前已发布的最新版本，并恢复该旧版本。确定要继续吗？')) {
      return;
    }
    setRollingBackId(versionId);
    try {
      await rollbackVersion(templateId, versionId);
    } catch (err) {
      // 错误由 store 层捕获并展示
    } finally {
      setRollingBackId(null);
    }
  }, [templateId, rollbackVersion]);

  if (!templateId) {
    return (
      <div className="version-history">
        <h3>版本历史</h3>
        <div className="empty-panel">
          <div className="empty-text">请先选择一个模板</div>
        </div>
      </div>
    );
  }

  if (isLoadingVersions) {
    return (
      <div className="version-history">
        <h3>版本历史</h3>
        <div className="prompt-list-loading">加载版本历史中...</div>
      </div>
    );
  }

  return (
    <div className="version-history">
      <h3>版本历史</h3>
      {versions.length === 0 ? (
        <div className="empty-panel">
          <div className="empty-text">暂无版本</div>
        </div>
      ) : (
        <div className="version-timeline">
          {versions.map((v) => {
            const isActive = templateData?.active_version_id === v.id;
            return (
              <div
                key={v.id}
                className={`version-item ${selectedVersionId === v.id ? 'selected' : ''} ${isActive ? 'active' : ''}`}
                onClick={() => onSelectVersion(v)}
              >
                <div className="version-header">
                  <span className="version-num">v{v.version_num}</span>
                  <span className={`version-status-badge status-${v.status}`}>
                    {STATUS_LABELS[v.status] || v.status}
                    {isActive && ' (当前)'}
                  </span>
                </div>
                <div className="version-time">
                  {new Date(v.created_at).toLocaleString('zh-CN')}
                </div>
                <div className="version-actions">
                  {v.status === 'draft' && (
                    <button
                      className="config-btn config-btn-primary config-btn-sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        handlePublish(v.id);
                      }}
                      disabled={publishingId === v.id}
                    >
                      {publishingId === v.id ? '发布中...' : '发布'}
                    </button>
                  )}
                  {v.status === 'deprecated' && (
                    <button
                      className="config-btn config-btn-secondary config-btn-sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRollback(v.id);
                      }}
                      disabled={rollingBackId === v.id}
                    >
                      {rollingBackId === v.id ? '回滚中...' : '回滚'}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
