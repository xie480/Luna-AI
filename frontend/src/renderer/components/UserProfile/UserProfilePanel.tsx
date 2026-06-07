/**
 * 用户画像页面容器组件。
 *
 * 做什么：渲染“Luna 眼中的你”完整页面，包括顶部说明、缓存状态、手动录入、筛选、分组卡片、加载、空状态和错误条。
 * 为什么这样做：页面容器统一协调 Store 状态和子组件布局，子组件保持纯展示或局部交互职责。
 * 输入输出：输入来自 userProfileStore；输出为 Modal 内可滚动的现代化用户画像页面。
 * 边界条件：首屏失败显示重试；刷新失败保留旧数据；空列表显示引导添加第一条画像。
 * 异常行为：所有异步失败均由 Store 写入中文错误，页面不展示堆栈、不打印画像内容。
 */
import React, { useEffect, useMemo, useRef } from 'react';
import { createErrorToast } from '../../stores/errorToastStore';
import { useSystemStore } from '../../stores/systemStore';
import { useUserProfileStore } from '../../stores/userProfileStore';
import {
  UserProfileCategory,
  UserProfileItem,
  UserProfileMutationPayload,
  USER_PROFILE_CATEGORY_OPTIONS,
  USER_PROFILE_FILTER_OPTIONS,
  formatUserProfileTime,
} from '../../types/userProfile';
import { ProfileCacheStatus } from './ProfileCacheStatus';
import { ProfileCategorySection } from './ProfileCategorySection';
import { ProfileEditor } from './ProfileEditor';
import './UserProfilePanel.css';

/** 根据当前筛选条件获取要渲染的分组列表，并保持标准类别排序。 */
function buildVisibleGroups(
  groupedItems: Record<string, UserProfileItem[]>,
  selectedCategory: string,
): Array<{ category: UserProfileCategory; items: UserProfileItem[] }> {
  return USER_PROFILE_CATEGORY_OPTIONS
    .map((option) => ({
      category: option.value,
      items: groupedItems[option.value] || [],
    }))
    .filter((group) => selectedCategory === 'all' || group.category === selectedCategory)
    .filter((group) => group.items.length > 0);
}

/** 首屏骨架屏，避免加载阶段误显示空状态。 */
const ProfileSkeleton: React.FC = () => (
  <div className="user-profile-skeleton" aria-label="用户画像加载中">
    {[0, 1, 2].map((index) => (
      <div className="profile-skeleton-card" key={index}>
        <div className="profile-skeleton-line wide" />
        <div className="profile-skeleton-line" />
        <div className="profile-skeleton-line short" />
      </div>
    ))}
  </div>
);

export const UserProfilePanel: React.FC = () => {
  const items = useUserProfileStore((state) => state.items);
  const groupedItems = useUserProfileStore((state) => state.groupedItems);
  const selectedCategory = useUserProfileStore((state) => state.selectedCategory);
  const cacheStatus = useUserProfileStore((state) => state.cacheStatus);
  const isLoading = useUserProfileStore((state) => state.isLoading);
  const isRefreshing = useUserProfileStore((state) => state.isRefreshing);
  const isSaving = useUserProfileStore((state) => state.isSaving);
  const deletingItemId = useUserProfileStore((state) => state.deletingItemId);
  const isRebuildingCache = useUserProfileStore((state) => state.isRebuildingCache);
  const error = useUserProfileStore((state) => state.error);
  const lastLoadedAt = useUserProfileStore((state) => state.lastLoadedAt);

  const setSelectedCategory = useUserProfileStore((state) => state.setSelectedCategory);
  const fetchItems = useUserProfileStore((state) => state.fetchItems);
  const createProfile = useUserProfileStore((state) => state.createProfile);
  const updateProfile = useUserProfileStore((state) => state.updateProfile);
  const deleteProfile = useUserProfileStore((state) => state.deleteProfile);
  const refreshCacheStatus = useUserProfileStore((state) => state.refreshCacheStatus);
  const rebuildCache = useUserProfileStore((state) => state.rebuildCache);
  const clearError = useUserProfileStore((state) => state.clearError);
  const showGlobalMessage = useSystemStore((state) => state.showGlobalMessage);

  const editorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchItems().catch((requestError) => {
      createErrorToast('ERROR', 'user_profile_panel', '获取用户画像失败', requestError instanceof Error ? requestError.message : undefined);
    });
  }, [fetchItems]);

  const visibleGroups = useMemo(
    () => buildVisibleGroups(groupedItems, selectedCategory),
    [groupedItems, selectedCategory],
  );

  /** 手动刷新画像列表，刷新中保留旧数据。 */
  const handleRefresh = async (): Promise<void> => {
    try {
      await fetchItems();
      showGlobalMessage('用户画像已刷新', 1800);
    } catch (requestError) {
      createErrorToast('ERROR', 'user_profile_panel', '刷新用户画像失败', requestError instanceof Error ? requestError.message : undefined);
    }
  };

  /** 新增画像成功后显示全局提示，失败时保持表单内容。 */
  const handleCreate = async (payload: UserProfileMutationPayload): Promise<void> => {
    try {
      await createProfile(payload);
      showGlobalMessage('已添加到 Luna 的画像中', 2000);
    } catch (requestError) {
      createErrorToast('ERROR', 'user_profile_panel', '新增用户画像失败', requestError instanceof Error ? requestError.message : undefined);
      throw requestError;
    }
  };

  /** 编辑画像成功后显示全局提示。 */
  const handleUpdate = async (itemId: string, payload: UserProfileMutationPayload): Promise<void> => {
    try {
      await updateProfile(itemId, payload);
      showGlobalMessage('用户画像已更新', 2000);
    } catch (requestError) {
      createErrorToast('ERROR', 'user_profile_panel', '编辑用户画像失败', requestError instanceof Error ? requestError.message : undefined);
      throw requestError;
    }
  };

  /** 删除画像成功后显示全局提示。 */
  const handleDelete = async (itemId: string): Promise<void> => {
    try {
      await deleteProfile(itemId);
      showGlobalMessage('用户画像已删除', 2000);
    } catch (requestError) {
      createErrorToast('ERROR', 'user_profile_panel', '删除用户画像失败', requestError instanceof Error ? requestError.message : undefined);
      throw requestError;
    }
  };

  /** 重建缓存并展示状态提示。 */
  const handleRebuildCache = async (): Promise<void> => {
    try {
      await rebuildCache();
      showGlobalMessage('用户画像缓存整理已提交', 2000);
    } catch (requestError) {
      createErrorToast('ERROR', 'user_profile_panel', '重建用户画像缓存失败', requestError instanceof Error ? requestError.message : undefined);
    }
  };

  /** 刷新缓存状态，不触碰画像列表。 */
  const handleRefreshCacheStatus = async (): Promise<void> => {
    try {
      await refreshCacheStatus();
    } catch (requestError) {
      createErrorToast('ERROR', 'user_profile_panel', '刷新缓存状态失败', requestError instanceof Error ? requestError.message : undefined);
    }
  };

  /** 空状态按钮滚动到新增表单。 */
  const handleScrollToEditor = (): void => {
    editorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="user-profile-panel">
      <header className="user-profile-hero">
        <div>
          <p className="user-profile-eyebrow">Personal Profile</p>
          <h1>Luna眼中的你</h1>
          <p>
            这里是 Luna 当前保存的、用于理解你的稳定画像。你可以手动补充、修改或删除。Luna 不会把玩笑、反讽或角色扮演内容当成稳定画像。
          </p>
        </div>
        <div className="user-profile-hero-actions">
          <button type="button" className="user-profile-secondary-button" onClick={handleRefresh} disabled={isRefreshing || isLoading}>
            {isRefreshing ? '刷新中...' : '刷新'}
          </button>
          <span className="user-profile-last-loaded">最近加载：{formatUserProfileTime(lastLoadedAt ? new Date(lastLoadedAt).toISOString() : null)}</span>
        </div>
      </header>

      <ProfileCacheStatus
        status={cacheStatus}
        isRebuilding={isRebuildingCache}
        onRebuild={handleRebuildCache}
        onRefresh={handleRefreshCacheStatus}
      />

      {error && (
        <div className="user-profile-error-banner" role="alert">
          <span>{error}</span>
          <button type="button" onClick={clearError}>关闭</button>
        </div>
      )}

      <section className="user-profile-editor-card" ref={editorRef}>
        <div className="profile-section-heading">
          <div>
            <h2>新增画像</h2>
            <p>请填写稳定、明确、与你本人相关的信息，例如：我平时只喝无糖咖啡。</p>
          </div>
        </div>
        <ProfileEditor mode="create" isSaving={isSaving} onSubmit={handleCreate} />
      </section>

      <section className="user-profile-filter-bar" aria-label="用户画像类别筛选">
        {USER_PROFILE_FILTER_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`profile-filter-chip ${selectedCategory === option.value ? 'active' : ''}`}
            onClick={() => setSelectedCategory(option.value)}
          >
            {option.label}
          </button>
        ))}
      </section>

      <main className="user-profile-content-area">
        {isLoading && <ProfileSkeleton />}

        {!isLoading && items.length === 0 && (
          <section className="user-profile-empty-state">
            <div className="user-profile-empty-orb" aria-hidden="true">☾</div>
            <h2>Luna还没有形成稳定画像</h2>
            <p>你可以手动告诉 Luna 一些稳定偏好，或者在长期对话整理后由 Luna 谨慎提取。</p>
            <button type="button" className="user-profile-primary-button" onClick={handleScrollToEditor}>
              添加第一条画像
            </button>
          </section>
        )}

        {!isLoading && items.length > 0 && visibleGroups.length === 0 && (
          <section className="user-profile-empty-state compact">
            <h2>当前类别暂无画像</h2>
            <p>可以切换到“全部”，或在上方新增这一类别的稳定画像。</p>
          </section>
        )}

        {!isLoading && visibleGroups.length > 0 && (
          <div className="user-profile-group-list">
            {visibleGroups.map((group) => (
              <ProfileCategorySection
                key={group.category}
                category={group.category}
                items={group.items}
                deletingItemId={deletingItemId}
                isSaving={isSaving}
                onUpdate={handleUpdate}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
};
