/**
 * Luna 用户画像前端类型契约。
 *
 * 做什么：集中描述“Luna 眼中的你”页面需要展示、筛选、编辑与缓存状态对接的数据结构。
 * 为什么这样做：用户画像属于隐私敏感数据，组件不得临时拼接跨层协议，必须通过强类型契约约束请求和响应。
 * 输入输出：输入来自用户表单与 Python API 网关响应，输出传递给 userProfileService、userProfileStore 和展示组件。
 * 边界条件：所有 ID 均按 Snowflake 字符串处理，避免 64 位整数在浏览器中精度丢失；前端不持久化画像正文。
 * 异常行为：字段非法时由表单和服务层分别做显式校验，非法响应会转成中文错误提示。
 */
import {
  USER_PROFILE_CACHE_SCHEMA_VERSION,
  USER_PROFILE_CACHE_STATUS,
  USER_PROFILE_CATEGORY,
  USER_PROFILE_SCHEMA_VERSION,
  USER_PROFILE_SOURCE_TYPE,
  USER_PROFILE_STATUS,
} from '../../shared/enum';

/** 用户画像标准类别联合类型。 */
export type UserProfileCategory = typeof USER_PROFILE_CATEGORY[keyof typeof USER_PROFILE_CATEGORY];

/** 用户画像来源类型联合类型。 */
export type UserProfileSourceType = typeof USER_PROFILE_SOURCE_TYPE[keyof typeof USER_PROFILE_SOURCE_TYPE];

/** 用户画像条目状态联合类型。 */
export type UserProfileStatus = typeof USER_PROFILE_STATUS[keyof typeof USER_PROFILE_STATUS];

/** 用户画像压缩缓存状态联合类型。 */
export type UserProfileCacheStatus = typeof USER_PROFILE_CACHE_STATUS[keyof typeof USER_PROFILE_CACHE_STATUS];

/** 页面筛选类别，“all”仅用于前端展示，不传给后端。 */
export type UserProfileCategoryFilter = UserProfileCategory | 'all';

/** 后端标准 JSON 响应中成功状态的数值。 */
export const USER_PROFILE_SUCCESS_CODE = 0;

/** 用户画像内容最小长度，与后端 Pydantic 校验保持一致。 */
export const USER_PROFILE_CONTENT_MIN_LENGTH = 4;

/** 用户画像内容最大长度，与后端 Pydantic 校验保持一致。 */
export const USER_PROFILE_CONTENT_MAX_LENGTH = 200;

/** 自定义类别名称最大长度，与后端 Pydantic 校验保持一致。 */
export const USER_PROFILE_CUSTOM_CATEGORY_MAX_LENGTH = 64;

/** 用户画像普通 HTTP 请求超时时间，防止本地服务异常时 UI 无限等待。 */
export const USER_PROFILE_REQUEST_TIMEOUT_MS = 10000;

/** 用户画像缓存重建状态轮询间隔。 */
export const USER_PROFILE_CACHE_POLL_INTERVAL_MS = 2000;

/** 用户画像缓存重建最大轮询次数，避免无界后台轮询。 */
export const USER_PROFILE_CACHE_MAX_POLL_COUNT = 20;

/** 类别展示配置，用于下拉框、筛选标签和分组排序。 */
export const USER_PROFILE_CATEGORY_OPTIONS: Array<{ value: UserProfileCategory; label: string; helper: string }> = [
  { value: USER_PROFILE_CATEGORY.APPEARANCE, label: '外貌特征', helper: '稳定的外貌或形象偏好' },
  { value: USER_PROFILE_CATEGORY.PERSONALITY, label: '性格特点', helper: '长期稳定的性格描述' },
  { value: USER_PROFILE_CATEGORY.LIKES, label: '喜欢的东西', helper: '稳定偏好与喜欢事项' },
  { value: USER_PROFILE_CATEGORY.DISLIKES, label: '厌恶的东西', helper: '明确不喜欢或排斥事项' },
  { value: USER_PROFILE_CATEGORY.FEARS, label: '害怕的事情', helper: '需要 Luna 谨慎对待的恐惧点' },
  { value: USER_PROFILE_CATEGORY.EXPECTATIONS, label: '期待与目标', helper: '长期期待、目标或理想状态' },
  { value: USER_PROFILE_CATEGORY.HABITS, label: '习惯癖好', helper: '稳定生活习惯或个人小癖好' },
  { value: USER_PROFILE_CATEGORY.CUSTOM, label: '自定义', helper: '不属于标准类别的稳定画像' },
];

/** 前端筛选标签配置，“全部”仅影响本地展示。 */
export const USER_PROFILE_FILTER_OPTIONS: Array<{ value: UserProfileCategoryFilter; label: string }> = [
  { value: 'all', label: '全部' },
  ...USER_PROFILE_CATEGORY_OPTIONS.map((option) => ({ value: option.value, label: option.label })),
];

/** 单条用户画像 DTO。 */
export interface UserProfileItem {
  schema_version: typeof USER_PROFILE_SCHEMA_VERSION;
  id: string;
  category: UserProfileCategory;
  category_label: string;
  custom_category_name: string | null;
  content: string;
  source_type: UserProfileSourceType;
  confidence: number;
  status: UserProfileStatus;
  source_excerpt?: string | null;
  created_at: string | null;
  updated_at: string | null;
  last_confirmed_at: string | null;
}

/** 用户画像列表响应。 */
export interface UserProfileListResponse {
  schema_version: typeof USER_PROFILE_SCHEMA_VERSION;
  items: UserProfileItem[];
  grouped: Record<string, UserProfileItem[]>;
  total: number;
  cache_status: UserProfileCacheStatus;
}

/** 新增或编辑用户画像请求载荷。 */
export interface UserProfileMutationPayload {
  schema_version: typeof USER_PROFILE_SCHEMA_VERSION;
  category: UserProfileCategory;
  custom_category_name?: string | null;
  content: string;
  idempotency_key?: string;
}

/** 用户画像缓存详细状态响应。 */
export interface UserProfileCacheStatusResponse {
  schema_version: typeof USER_PROFILE_CACHE_SCHEMA_VERSION;
  status: UserProfileCacheStatus;
  updated_at: string | null;
  source_item_count: number;
  summary_length: number;
  last_error: string;
}

/** 用户画像缓存重建响应。 */
export interface UserProfileCacheRebuildResponse {
  schema_version: typeof USER_PROFILE_CACHE_SCHEMA_VERSION;
  task_id: string;
  status: UserProfileCacheStatus;
}

/** 用户画像标准 API 响应。 */
export interface UserProfileApiResponse<T> {
  code: number;
  msg: string;
  data: T | null;
  trace_id: string;
}

/** 根据类别值获取中文展示名。 */
export function getUserProfileCategoryLabel(category: UserProfileCategory, customName?: string | null): string {
  if (category === USER_PROFILE_CATEGORY.CUSTOM && customName?.trim()) {
    return customName.trim();
  }
  return USER_PROFILE_CATEGORY_OPTIONS.find((option) => option.value === category)?.label || '未知类别';
}

/** 将 ISO 时间转换为本地可读文本，空值显示为未记录。 */
export function formatUserProfileTime(value: string | null | undefined): string {
  if (!value) {
    return '未记录';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '时间格式异常';
  }

  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
