/**
 * 用户画像类别分区组件。
 *
 * 做什么：按类别展示用户画像卡片、数量、最近更新时间，并支持折叠。
 * 为什么这样做：用户画像适合按关系域阅读，不使用普通表格，提升“Luna 眼中的你”的可读性。
 * 输入输出：输入为类别信息、条目列表和操作回调；输出为分区标题与卡片列表。
 * 边界条件：空分区不渲染，避免页面被无意义占位淹没。
 * 异常行为：卡片操作失败由上层 Store 的错误条统一展示。
 */
import React, { useMemo, useState } from 'react';
import {
  UserProfileCategory,
  UserProfileItem,
  UserProfileMutationPayload,
  formatUserProfileTime,
  getUserProfileCategoryLabel,
} from '../../types/userProfile';
import { ProfileCard } from './ProfileCard';

interface ProfileCategorySectionProps {
  category: UserProfileCategory;
  items: UserProfileItem[];
  deletingItemId: string | null;
  isSaving: boolean;
  onUpdate: (itemId: string, payload: UserProfileMutationPayload) => Promise<void>;
  onDelete: (itemId: string) => Promise<void>;
}

/** 计算该类别最近更新时间。 */
function getLatestUpdatedAt(items: UserProfileItem[]): string | null {
  const timestamps = items
    .map((item) => item.updated_at || item.created_at)
    .filter((value): value is string => Boolean(value))
    .map((value) => new Date(value).getTime())
    .filter((value) => !Number.isNaN(value));

  if (timestamps.length === 0) {
    return null;
  }

  return new Date(Math.max(...timestamps)).toISOString();
}

export const ProfileCategorySection: React.FC<ProfileCategorySectionProps> = ({
  category,
  items,
  deletingItemId,
  isSaving,
  onUpdate,
  onDelete,
}) => {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const latestUpdatedAt = useMemo(() => getLatestUpdatedAt(items), [items]);

  if (items.length === 0) {
    return null;
  }

  const title = getUserProfileCategoryLabel(category, items[0]?.custom_category_name);

  return (
    <section className="profile-category-section">
      <button type="button" className="profile-category-header" onClick={() => setIsCollapsed((value) => !value)}>
        <span className="profile-category-title">{title}</span>
        <span className="profile-category-count">{items.length} 条</span>
        <span className="profile-category-updated">最近更新：{formatUserProfileTime(latestUpdatedAt)}</span>
        <span className="profile-category-toggle">{isCollapsed ? '展开' : '收起'}</span>
      </button>

      {!isCollapsed && (
        <div className="profile-category-cards">
          {items.map((item) => (
            <ProfileCard
              key={item.id}
              item={item}
              isSaving={isSaving}
              isDeleting={deletingItemId === item.id}
              onUpdate={onUpdate}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </section>
  );
};
