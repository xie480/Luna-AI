/**
 * 版本历史组件
 * 做什么：展示选中模板的版本时间线，高亮当前 Published 版本，支持版本选择、发布、回滚与删除未使用旧版本。
 * 为什么这样做：Prompt 历史版本会不断增长，前端需要给用户提供受控清理入口，但不能绕过后端对 active 版本的保护。
 * 输入输出：输入当前模板 ID、当前选中版本 ID 与选择回调；输出版本列表 UI 和用户触发的版本操作。
 * 边界条件：未选中模板、版本加载中、当前使用版本、published 版本均不会提供删除入口。
 * 异常行为：操作失败由 zustand store 写入错误状态，本组件只负责恢复按钮 loading 状态。
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

export function VersionHistory({
  templateId,
  onSelectVersion,
  selectedVersionId,
}: VersionHistoryProps): React.ReactElement {
  const { versions, isLoadingVersions, publishVersion, rollbackVersion, deleteVersion, templates } = usePromptStore();
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [rollingBackId, setRollingBackId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

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

  /**
   * 删除未使用旧版本。
   * 做什么：用户点击删除后进行二次确认，再调用 Store Action 删除指定版本。
   * 为什么这样做：删除历史 Prompt 是不可恢复操作，必须避免误触；真实可删性仍以后端校验为准。
   * 输入输出：输入 version 对象；成功后 Store 会刷新版本历史。
   * 边界条件：当前 active 版本和 published 版本不允许发起删除。
   * 异常行为：请求失败时由 Store 记录错误，本组件在 finally 中恢复按钮状态。
   */
  const handleDelete = useCallback(async (version: PromptVersion) => {
    if (!templateId) return;
    const isActive = templateData?.active_version_id === version.id;
    if (isActive || version.status === 'published') return;
    if (!window.confirm(`确定要删除 Prompt 版本 v${version.version_num} 吗？此操作不可恢复。`)) {
      return;
    }
    setDeletingId(version.id);
    try {
      await deleteVersion(templateId, version.id);
    } catch (err) {
      // 错误由 store 层捕获并展示
    } finally {
      setDeletingId(null);
    }
  }, [templateId, templateData?.active_version_id, deleteVersion]);

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
            const canDelete = !isActive && v.status !== 'published';
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
                  {canDelete && (
                    <button
                      className="config-btn config-btn-danger config-btn-sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(v);
                      }}
                      disabled={deletingId === v.id}
                      title="删除未在使用中的旧版本"
                    >
                      {deletingId === v.id ? '删除中...' : '删除'}
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
}

export default VersionHistory;
