/**
 * Luna 用户画像服务层。
 *
 * 做什么：封装“Luna 眼中的你”页面所需的 HTTP API，包括列表、分类刷新、新增、编辑、删除、缓存状态和缓存重建。
 * 为什么这样做：React 组件不得直接拼接 URL、请求头或响应结构；所有跨层通信都通过 Python API 网关，并统一注入 TraceID 与幂等键。
 * 输入输出：输入为强类型请求载荷，输出为经过 ResponseModel 校验后的业务数据。
 * 边界条件：前端不传 user_id，不访问数据库、Redis 或模型服务；每个请求都有 AbortController 超时保护。
 * 异常行为：HTTP 错误、业务错误、结构异常、网络超时都会转成中文 Error，调用方负责展示 UI 降级状态。
 */
import { AI_SERVICE_BASE_URL } from '../appConfig';
import { useSystemStore } from '../stores/systemStore';
import { generateId } from '../../shared/utils/snowflake';
import {
  UserProfileApiResponse,
  UserProfileCacheRebuildResponse,
  UserProfileCacheStatusResponse,
  UserProfileCategory,
  UserProfileItem,
  UserProfileListResponse,
  UserProfileMutationPayload,
  USER_PROFILE_REQUEST_TIMEOUT_MS,
  USER_PROFILE_SUCCESS_CODE,
} from '../types/userProfile';

/** 用户画像 API 根路径。 */
const USER_PROFILE_API_BASE_URL = `${AI_SERVICE_BASE_URL}/api/v1/user-profile`;

/** 请求超时中止原因。 */
const USER_PROFILE_ABORT_REASON_TIMEOUT = 'USER_PROFILE_TIMEOUT';

/** 生成请求 TraceID，优先复用当前链路 TraceID。 */
function getTraceId(): string {
  return useSystemStore.getState().currentTraceID || `web-${generateId()}`;
}

/** 生成前端幂等键，供新增画像 POST 请求使用。 */
function getIdempotencyKey(): string {
  return `web-${generateId()}`;
}

/** 判断未知值是否符合后端标准 ResponseModel。 */
function isUserProfileApiResponse<T>(value: unknown): value is UserProfileApiResponse<T> {
  if (!value || typeof value !== 'object') {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.code === 'number' &&
    typeof candidate.msg === 'string' &&
    Object.prototype.hasOwnProperty.call(candidate, 'data') &&
    typeof candidate.trace_id === 'string'
  );
}

/** 解析 HTTP 响应并提取业务 data。 */
async function parseUserProfileResponse<T>(response: Response): Promise<T> {
  let body: unknown;

  try {
    body = await response.json();
  } catch {
    if (!response.ok) {
      throw new Error(`用户画像请求失败：HTTP ${response.status}`);
    }
    throw new Error('用户画像响应结构异常');
  }

  if (!response.ok) {
    if (isUserProfileApiResponse<T>(body) && body.msg) {
      throw new Error(body.msg);
    }

    const fallbackMessage = typeof (body as { msg?: unknown }).msg === 'string'
      ? String((body as { msg: string }).msg)
      : `用户画像请求失败：HTTP ${response.status}`;
    throw new Error(fallbackMessage);
  }

  if (!isUserProfileApiResponse<T>(body)) {
    throw new Error('用户画像响应结构异常');
  }

  if (body.code !== USER_PROFILE_SUCCESS_CODE) {
    throw new Error(body.msg || '用户画像请求返回业务错误');
  }

  if (body.data === null || body.data === undefined) {
    throw new Error('用户画像响应结构异常');
  }

  return body.data;
}

/** 构造安全的接口 URL，避免组件内拼接 QueryString。 */
function buildUrl(path: string, params?: Record<string, string | number | boolean>): string {
  const url = new URL(`${USER_PROFILE_API_BASE_URL}${path}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** 用户画像服务类，负责管理每次请求的超时生命周期。 */
class UserProfileService {
  /**
   * 发起标准 JSON 请求。
   * 做什么：创建 AbortController、设置超时、注入 TraceID，并在 finally 中回收定时器。
   * 为什么这样做：用户画像页面不允许因为本地 Python 服务异常而永久挂起。
   * 输入输出：输入为路径、方法、请求体和附加头；输出为校验后的业务 data。
   * 边界条件：DELETE 可以没有 body；GET 请求不会发送 Content-Type。
   * 异常行为：超时统一抛出“用户画像服务暂时不可用，请稍后刷新”。
   */
  private async request<T>(
    path: string,
    options: {
      method: 'GET' | 'POST' | 'PUT' | 'DELETE';
      body?: unknown;
      headers?: Record<string, string>;
      params?: Record<string, string | number | boolean>;
    },
  ): Promise<T> {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      controller.abort(USER_PROFILE_ABORT_REASON_TIMEOUT);
    }, USER_PROFILE_REQUEST_TIMEOUT_MS);

    try {
      const headers: Record<string, string> = {
        'X-Trace-ID': getTraceId(),
        ...options.headers,
      };

      const hasBody = options.body !== undefined;
      if (hasBody) {
        headers['Content-Type'] = 'application/json';
      }

      const response = await fetch(buildUrl(path, options.params), {
        method: options.method,
        headers,
        body: hasBody ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });

      return await parseUserProfileResponse<T>(response);
    } catch (error) {
      if (controller.signal.aborted) {
        throw new Error('用户画像服务暂时不可用，请稍后刷新');
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  /** 获取全部或指定类别画像列表。 */
  async listItems(category?: UserProfileCategory): Promise<UserProfileListResponse> {
    return await this.request<UserProfileListResponse>('/items', {
      method: 'GET',
      params: category ? { category } : undefined,
    });
  }

  /** 获取指定类别画像列表，用于局部分组刷新。 */
  async listCategoryItems(category: UserProfileCategory): Promise<UserProfileListResponse> {
    return await this.request<UserProfileListResponse>(`/categories/${encodeURIComponent(category)}/items`, {
      method: 'GET',
    });
  }

  /** 手动新增用户画像，并为请求附加幂等键。 */
  async createItem(payload: UserProfileMutationPayload): Promise<UserProfileItem> {
    const idempotencyKey = payload.idempotency_key || getIdempotencyKey();
    return await this.request<UserProfileItem>('/items', {
      method: 'POST',
      headers: {
        'Idempotency-Key': idempotencyKey,
      },
      body: {
        ...payload,
        idempotency_key: idempotencyKey,
      },
    });
  }

  /** 编辑已存在的手动用户画像。 */
  async updateItem(itemId: string, payload: UserProfileMutationPayload): Promise<UserProfileItem> {
    if (!itemId.trim()) {
      throw new Error('用户画像 ID 不能为空');
    }

    return await this.request<UserProfileItem>(`/items/${encodeURIComponent(itemId)}`, {
      method: 'PUT',
      body: payload,
    });
  }

  /** 软删除用户画像，后端确认后前端再刷新最终状态。 */
  async deleteItem(itemId: string): Promise<unknown> {
    if (!itemId.trim()) {
      throw new Error('用户画像 ID 不能为空');
    }

    return await this.request<unknown>(`/items/${encodeURIComponent(itemId)}`, {
      method: 'DELETE',
    });
  }

  /** 查询用户画像压缩缓存详细状态。 */
  async getCacheStatus(): Promise<UserProfileCacheStatusResponse> {
    return await this.request<UserProfileCacheStatusResponse>('/cache/status', {
      method: 'GET',
    });
  }

  /** 手动触发用户画像缓存重建任务。 */
  async rebuildCache(): Promise<UserProfileCacheRebuildResponse> {
    return await this.request<UserProfileCacheRebuildResponse>('/cache/rebuild', {
      method: 'POST',
    });
  }
}

export const userProfileService = new UserProfileService();
