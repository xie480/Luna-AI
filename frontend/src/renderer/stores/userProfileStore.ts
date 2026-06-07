/**
 * Luna 用户画像 Zustand Store。
 *
 * 做什么：管理“Luna 眼中的你”页面的列表、分组、筛选、缓存状态和操作状态。
 * 为什么这样做：组件只负责展示和交互，不直接调用后端 API；画像真源始终在 Python/PostgreSQL，前端 Store 不做持久化。
 * 输入输出：输入为组件触发的 Action，输出为可订阅的 UI 状态。
 * 边界条件：刷新失败时保留旧数据；新增、编辑、删除成功后必须重新拉取服务端数据。
 * 异常行为：所有失败写入中文 error，并继续抛给组件用于阻止表单误清空。
 */
import { create } from 'zustand';
import { USER_PROFILE_CACHE_STATUS } from '../../shared/enum';
import { userProfileService } from '../services/userProfileService';
import {
  UserProfileCacheStatusResponse,
  UserProfileCategory,
  UserProfileCategoryFilter,
  UserProfileItem,
  UserProfileMutationPayload,
  USER_PROFILE_CACHE_MAX_POLL_COUNT,
  USER_PROFILE_CACHE_POLL_INTERVAL_MS,
} from '../types/userProfile';

/** 用户画像页面状态切片。 */
interface UserProfileState {
  items: UserProfileItem[];
  groupedItems: Record<string, UserProfileItem[]>;
  selectedCategory: UserProfileCategoryFilter;
  cacheStatus: UserProfileCacheStatusResponse | null;
  isLoading: boolean;
  isRefreshing: boolean;
  isSaving: boolean;
  isDeleting: boolean;
  deletingItemId: string | null;
  isRebuildingCache: boolean;
  error: string | null;
  lastLoadedAt: number | null;

  setSelectedCategory: (category: UserProfileCategoryFilter) => void;
  fetchItems: () => Promise<void>;
  fetchByCategory: (category: UserProfileCategory) => Promise<void>;
  createProfile: (payload: UserProfileMutationPayload) => Promise<void>;
  updateProfile: (itemId: string, payload: UserProfileMutationPayload) => Promise<void>;
  deleteProfile: (itemId: string) => Promise<void>;
  refreshCacheStatus: () => Promise<void>;
  rebuildCache: () => Promise<void>;
  clearError: () => void;
}

/** 缓存重建轮询代次，用于让后发起的重建流程终止旧流程。 */
let cacheRebuildPollGeneration = 0;

/** 等待指定毫秒数，供缓存重建轮询使用。 */
function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/** 将未知异常转换为不会暴露堆栈的中文错误文案。 */
function normalizeUserProfileError(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
}

/** 根据列表重新构造分组，作为后端 grouped 缺失分类时的兜底展示。 */
function groupItemsByCategory(items: UserProfileItem[]): Record<string, UserProfileItem[]> {
  return items.reduce<Record<string, UserProfileItem[]>>((acc, item) => {
    const key = item.category;
    if (!acc[key]) {
      acc[key] = [];
    }
    acc[key].push(item);
    return acc;
  }, {});
}

/** 创建用户画像 Store。 */
export const useUserProfileStore = create<UserProfileState>((set, get) => ({
  items: [],
  groupedItems: {},
  selectedCategory: 'all',
  cacheStatus: null,
  isLoading: false,
  isRefreshing: false,
  isSaving: false,
  isDeleting: false,
  deletingItemId: null,
  isRebuildingCache: false,
  error: null,
  lastLoadedAt: null,

  /** 设置当前类别筛选，仅改变前端展示筛选，不直接写入后端。 */
  setSelectedCategory: (category) => set({ selectedCategory: category }),

  /** 拉取画像列表和缓存状态，首屏显示骨架，刷新时保留旧数据。 */
  fetchItems: async () => {
    const hasExistingData = get().items.length > 0;
    set({
      isLoading: !hasExistingData,
      isRefreshing: hasExistingData,
      error: null,
    });

    try {
      const selectedCategory = get().selectedCategory;
      const listResponse = await userProfileService.listItems(selectedCategory === 'all' ? undefined : selectedCategory);
      const cacheStatus = await userProfileService.getCacheStatus().catch(() => null);

      set({
        items: listResponse.items,
        groupedItems: Object.keys(listResponse.grouped).length > 0 ? listResponse.grouped : groupItemsByCategory(listResponse.items),
        cacheStatus,
        lastLoadedAt: Date.now(),
        isLoading: false,
        isRefreshing: false,
        error: null,
      });
    } catch (error) {
      set({
        isLoading: false,
        isRefreshing: false,
        error: normalizeUserProfileError(error, '获取用户画像失败'),
      });
      throw error;
    }
  },

  /** 按类别局部刷新画像，成功后同步当前分组和缓存状态。 */
  fetchByCategory: async (category) => {
    set({ isRefreshing: true, error: null, selectedCategory: category });

    try {
      const listResponse = await userProfileService.listCategoryItems(category);
      const cacheStatus = await userProfileService.getCacheStatus().catch(() => null);

      set({
        items: listResponse.items,
        groupedItems: Object.keys(listResponse.grouped).length > 0 ? listResponse.grouped : groupItemsByCategory(listResponse.items),
        cacheStatus,
        lastLoadedAt: Date.now(),
        isRefreshing: false,
        error: null,
      });
    } catch (error) {
      set({
        isRefreshing: false,
        error: normalizeUserProfileError(error, '按类别刷新用户画像失败'),
      });
      throw error;
    }
  },

  /** 新增手动画像，后端确认后刷新列表与缓存状态。 */
  createProfile: async (payload) => {
    if (get().isSaving) {
      throw new Error('用户画像正在保存，请勿重复提交');
    }

    set({ isSaving: true, error: null });
    try {
      await userProfileService.createItem(payload);
      set({ isSaving: false });
      await get().fetchItems();
    } catch (error) {
      set({
        isSaving: false,
        error: normalizeUserProfileError(error, '新增用户画像失败'),
      });
      throw error;
    }
  },

  /** 编辑手动画像，后端确认后刷新列表与缓存状态。 */
  updateProfile: async (itemId, payload) => {
    if (get().isSaving) {
      throw new Error('用户画像正在保存，请勿重复提交');
    }

    set({ isSaving: true, error: null });
    try {
      await userProfileService.updateItem(itemId, payload);
      set({ isSaving: false });
      await get().fetchItems();
    } catch (error) {
      set({
        isSaving: false,
        error: normalizeUserProfileError(error, '编辑用户画像失败'),
      });
      throw error;
    }
  },

  /** 删除画像，后端软删除成功后刷新服务端最终状态。 */
  deleteProfile: async (itemId) => {
    if (get().isDeleting) {
      throw new Error('用户画像正在删除，请勿重复操作');
    }

    set({ isDeleting: true, deletingItemId: itemId, error: null });
    try {
      await userProfileService.deleteItem(itemId);
      set({ isDeleting: false, deletingItemId: null });
      await get().fetchItems();
    } catch (error) {
      set({
        isDeleting: false,
        deletingItemId: null,
        error: normalizeUserProfileError(error, '删除用户画像失败'),
      });
      throw error;
    }
  },

  /** 刷新缓存详细状态，不影响画像列表展示。 */
  refreshCacheStatus: async () => {
    try {
      const cacheStatus = await userProfileService.getCacheStatus();
      set({ cacheStatus });
    } catch (error) {
      set({ error: normalizeUserProfileError(error, '获取用户画像缓存状态失败') });
      throw error;
    }
  },

  /** 触发缓存重建，并在有限次数内轮询直到状态结束。 */
  rebuildCache: async () => {
    if (get().isRebuildingCache) {
      return;
    }

    cacheRebuildPollGeneration += 1;
    const currentGeneration = cacheRebuildPollGeneration;

    set({ isRebuildingCache: true, error: null });
    try {
      await userProfileService.rebuildCache();

      for (let index = 0; index < USER_PROFILE_CACHE_MAX_POLL_COUNT; index += 1) {
        await delay(USER_PROFILE_CACHE_POLL_INTERVAL_MS);
        if (cacheRebuildPollGeneration !== currentGeneration) {
          return;
        }

        const cacheStatus = await userProfileService.getCacheStatus();
        set({ cacheStatus });
        if (cacheStatus.status !== USER_PROFILE_CACHE_STATUS.REBUILDING) {
          set({ isRebuildingCache: false });
          return;
        }
      }

      set({
        isRebuildingCache: false,
        error: '用户画像缓存仍在整理中，请稍后刷新状态',
      });
    } catch (error) {
      set({
        isRebuildingCache: false,
        error: normalizeUserProfileError(error, '重建用户画像缓存失败'),
      });
      throw error;
    }
  },

  /** 清理页面错误条，不修改任何画像数据。 */
  clearError: () => set({ error: null }),
}));
