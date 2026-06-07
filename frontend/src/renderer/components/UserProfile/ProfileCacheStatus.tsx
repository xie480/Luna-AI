/**
 * 用户画像缓存状态条组件。
 *
 * 做什么：展示 Redis 压缩缓存是否已同步到聊天提示词，并提供刷新或重建入口。
 * 为什么这样做：缓存状态是后端长期记忆注入链路的可见投影，组件只触发 Store 回调，不直接访问列表数据。
 * 输入输出：输入为缓存状态、重建状态和回调；输出为状态条 UI 与用户点击事件。
 * 边界条件：状态为空时展示“正在读取”；dirty/missing/failed 状态展示可操作按钮。
 * 异常行为：回调失败由 Store 写入页面级错误条，本组件不吞掉错误。
 */
import React from 'react';
import { USER_PROFILE_CACHE_STATUS } from '../../../shared/enum';
import { UserProfileCacheStatusResponse, formatUserProfileTime } from '../../types/userProfile';

interface ProfileCacheStatusProps {
  status: UserProfileCacheStatusResponse | null;
  isRebuilding: boolean;
  onRebuild: () => void;
  onRefresh: () => void;
}

/** 将缓存状态转换为中文文案与样式标识。 */
function getStatusView(status: UserProfileCacheStatusResponse | null): { label: string; className: string; actionLabel: string | null } {
  if (!status) {
    return { label: '正在读取缓存状态', className: 'unknown', actionLabel: null };
  }

  switch (status.status) {
    case USER_PROFILE_CACHE_STATUS.VALID:
      return { label: '已同步到聊天提示词', className: 'valid', actionLabel: null };
    case USER_PROFILE_CACHE_STATUS.DIRTY:
      return { label: '有更新待压缩', className: 'dirty', actionLabel: '重建' };
    case USER_PROFILE_CACHE_STATUS.MISSING:
      return { label: '暂无压缩缓存', className: 'missing', actionLabel: '生成' };
    case USER_PROFILE_CACHE_STATUS.REBUILDING:
      return { label: '正在整理画像', className: 'rebuilding', actionLabel: null };
    case USER_PROFILE_CACHE_STATUS.FAILED:
      return { label: '整理失败', className: 'failed', actionLabel: '重试' };
    default:
      return { label: '缓存状态异常', className: 'unknown', actionLabel: null };
  }
}

export const ProfileCacheStatus: React.FC<ProfileCacheStatusProps> = ({ status, isRebuilding, onRebuild, onRefresh }) => {
  const view = getStatusView(status);
  const shouldShowRebuild = Boolean(view.actionLabel) && !isRebuilding;

  return (
    <section className={`profile-cache-status ${view.className}`} aria-label="用户画像缓存状态">
      <div className="profile-cache-main">
        <span className={`profile-cache-dot ${view.className}`} aria-hidden="true" />
        <div className="profile-cache-text">
          <strong>{isRebuilding ? '正在整理画像' : view.label}</strong>
          <span>
            {status
              ? `更新时间：${formatUserProfileTime(status.updated_at)} · 来源 ${status.source_item_count} 条 · 摘要 ${status.summary_length} 字`
              : '正在从 Python 服务读取缓存元信息'}
          </span>
          {status?.status === USER_PROFILE_CACHE_STATUS.FAILED && status.last_error && (
            <em className="profile-cache-error">失败原因：{status.last_error}</em>
          )}
        </div>
      </div>

      <div className="profile-cache-actions">
        {shouldShowRebuild && (
          <button type="button" className="user-profile-secondary-button" onClick={onRebuild}>
            {view.actionLabel}
          </button>
        )}
        <button type="button" className="user-profile-ghost-button" onClick={onRefresh} disabled={isRebuilding}>
          刷新状态
        </button>
      </div>
    </section>
  );
};
