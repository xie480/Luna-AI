/**
 * 用户画像卡片组件。
 *
 * 做什么：展示单条画像的正文、来源、置信度、更新时间，并提供编辑和删除入口。
 * 为什么这样做：卡片只通过 props 回调触发 Store Action，不直接调用 service，保持展示层低耦合。
 * 输入输出：输入为画像条目和操作回调；输出为卡片 UI、内联编辑器和用户确认删除事件。
 * 边界条件：删除中禁用当前卡片所有操作；编辑取消不会修改 Store 状态。
 * 异常行为：删除前必须二次确认；操作失败由 Store 写入页面错误条。
 */
import React, { useState } from 'react';
import { USER_PROFILE_SOURCE_TYPE } from '../../../shared/enum';
import { UserProfileItem, UserProfileMutationPayload, formatUserProfileTime } from '../../types/userProfile';
import { ProfileEditor } from './ProfileEditor';

interface ProfileCardProps {
  item: UserProfileItem;
  isSaving: boolean;
  isDeleting: boolean;
  onUpdate: (itemId: string, payload: UserProfileMutationPayload) => Promise<void>;
  onDelete: (itemId: string) => Promise<void>;
}

/** 获取来源标签文案。 */
function getSourceLabel(item: UserProfileItem): string {
  if (item.source_type === USER_PROFILE_SOURCE_TYPE.MANUAL) {
    return '你手动告诉 Luna';
  }
  return 'Luna 从对话中整理';
}

/** 获取置信度展示文案。 */
function getConfidenceText(item: UserProfileItem): string {
  if (item.source_type === USER_PROFILE_SOURCE_TYPE.MANUAL) {
    return '已确认';
  }
  return `置信度 ${Math.round(item.confidence * 100)}%`;
}

export const ProfileCard: React.FC<ProfileCardProps> = ({ item, isSaving, isDeleting, onUpdate, onDelete }) => {
  const [isEditing, setIsEditing] = useState(false);

  /** 删除前进行用户确认，避免误删影响聊天提示词画像注入。 */
  const handleDelete = async (): Promise<void> => {
    const confirmed = window.confirm('删除后 Luna 将不再在聊天中参考这条画像。');
    if (!confirmed) {
      return;
    }
    await onDelete(item.id);
  };

  /** 编辑成功后退出内联编辑态。 */
  const handleUpdate = async (payload: UserProfileMutationPayload): Promise<void> => {
    await onUpdate(item.id, payload);
    setIsEditing(false);
  };

  return (
    <article className={`profile-card ${isDeleting ? 'deleting' : ''}`}>
      {isEditing ? (
        <ProfileEditor
          mode="edit"
          initialValue={item}
          isSaving={isSaving}
          onSubmit={handleUpdate}
          onCancel={() => setIsEditing(false)}
        />
      ) : (
        <>
          <p className="profile-card-content">{item.content}</p>
          <div className="profile-card-meta">
            <span className="profile-pill source">{getSourceLabel(item)}</span>
            <span className="profile-pill confidence">{getConfidenceText(item)}</span>
            <span className="profile-card-time">最近确认：{formatUserProfileTime(item.last_confirmed_at || item.updated_at)}</span>
          </div>
          <div className="profile-card-actions">
            <button
              type="button"
              className="user-profile-ghost-button"
              disabled={isDeleting || isSaving}
              onClick={() => setIsEditing(true)}
            >
              编辑
            </button>
            <button
              type="button"
              className="user-profile-danger-button"
              disabled={isDeleting || isSaving}
              onClick={handleDelete}
            >
              {isDeleting ? '删除中...' : '删除'}
            </button>
          </div>
        </>
      )}
    </article>
  );
};
