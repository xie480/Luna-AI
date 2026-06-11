/**
 * MCP 市场类型定义。
 *
 * 做什么：定义 MCP 市场相关的前端类型，包括市场条目、详情、已接入实例和接入配置。
 * 为什么这样做：与后端 API 响应结构对齐，确保前端类型安全。
 * 输入输出：所有接口来自后端 REST API 的 JSON 响应映射。
 * 边界条件：所有字段都应考虑为空或 undefined 的情况。
 */

/**
 * MCP 市场条目（列表展示用）。
 *
 * 做什么：描述 MCP 市场列表中单个 Server 条目的前端投影。
 * 为什么这样做：列表展示需要精简字段，与详情页的完整模型分离。
 * 输入输出：来自 GET /api/v1/mcp/market/list 的响应。
 * 边界条件：is_installed 用于区分"未接入"和"已接入"的按钮状态。
 */
export interface MCPMarketItem {
  /** 市场条目 ID（雪花算法）。 */
  id: string;
  /** 唯一名称。 */
  name: string;
  /** 展示名称。 */
  display_name: string;
  /** 简短描述。 */
  description: string;
  /** 作者/维护者。 */
  author: string;
  /** 分类。 */
  category: string;
  /** 标签。 */
  tags: string[];
  /** 工具数量。 */
  tool_count: number;
  /** 健康状态：online / offline / unknown。 */
  health_status: string;
  /** 信誉评分（0.00 ~ 1.00）。 */
  trust_score: number;
  /** GitHub Stars。 */
  github_stars: number;
  /** 接入计数。 */
  install_count: number;
  /** Logo URL。 */
  logo_url: string;
  /** 当前用户是否已接入。 */
  is_installed: boolean;
}

/**
 * MCP 市场条目详情（详情页展示用）。
 *
 * 做什么：描述单个 MCP Server 的完整信息，包含工具能力清单。
 * 为什么这样做：详情页需要展示工具级的 Schema 信息，帮助用户判断是否接入。
 * 输入输出：来自 GET /api/v1/mcp/market/detail/:id 的响应。
 */
export interface MCPMarketDetail {
  /** 基础信息（继承自 MCPMarketItem）。 */
  id: string;
  name: string;
  display_name: string;
  description: string;
  author: string;
  repository_url: string;
  homepage_url: string;
  license: string;
  category: string;
  tags: string[];
  logo_url: string;

  /** 工具能力清单。 */
  tools: MCPMarketToolDef[];

  /** 健康信息。 */
  health_status: string;
  health_detail: {
    latency_ms: number;
    protocol: string;
    auth_required: boolean;
  };

  /** 信任信息。 */
  trust_score: number;
  security_flags: string[];
  github_stars: number;
  last_commit_at: string;

  /** 接入状态。 */
  is_installed: boolean;
  installed_instance_id?: string;

  /** 默认 Endpoint URL（从市场元数据中自动填充）。 */
  endpoint_url: string;

  /** 接入指导。 */
  install_instruction?: {
    auth_type: string;
    auth_hint: string;
  };
}

/**
 * MCP 市场工具定义。
 *
 * 做什么：描述单个工具的能力清单，包含参数 Schema 和能力标签。
 * 为什么这样做：详情页需要展示工具的完整参数定义，方便用户了解工具能力。
 */
export interface MCPMarketToolDef {
  name: string;
  description: string;
  parameters_schema: Record<string, unknown>;
  capability_tags: string[];
}

/**
 * MCP 已接入实例。
 *
 * 做什么：描述用户已经接入的远程 MCP 实例。
 * 为什么这样做：管理面板需要展示实例的实时状态和配置。
 * 输入输出：来自 GET /api/v1/mcp/market/installed 的响应。
 */
export interface MCPInstalledInstance {
  /** 实例 ID。 */
  id: string;
  /** 关联的市场条目 ID。 */
  marketplace_id: string;
  /** 用户自定义名称。 */
  display_name: string;
  /** 市场条目名称。 */
  market_name: string;
  /** Endpoint URL。 */
  endpoint_url: string;
  /** 鉴权类型。 */
  auth_type: string;
  /** 是否启用。 */
  is_active: boolean;
  /** 健康状态。 */
  health_status: string;
  /** 上次健康检查时间。 */
  last_health_check: string;
  /** 工具数量。 */
  tool_count: number;
  /** 工具名称列表。 */
  tool_names: string[];
  /** 总调用次数。 */
  total_calls: number;
  /** 失败调用次数。 */
  failed_calls: number;
  /** 平均延迟（毫秒）。 */
  avg_latency_ms: number;
  /** 创建时间。 */
  created_at: string;
}

/**
 * 一键接入配置。
 *
 * 做什么：用户在接入远程 MCP 时需要提供的配置信息。
 * 为什么这样做：接入弹窗需要收集这些配置后调用安装 API。
 */
export interface InstallConfig {
  endpoint_url: string;
  display_name: string;
  auth_config?: {
    type: 'none' | 'bearer' | 'api_key' | 'basic';
    token?: string;
    api_key?: string;
    username?: string;
    password?: string;
  };
  timeout_ms?: number;
  max_retries?: number;
}

/**
 * MCP 市场列表响应。
 *
 * 做什么：定义市场列表 API 的响应结构。
 * 输入输出：来自 GET /api/v1/mcp/market/list 的响应。
 */
export interface MarketplaceListResponse {
  items: MCPMarketItem[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * MCP 接入结果响应。
 *
 * 做什么：定义一键接入 API 的响应结构。
 * 输入输出：来自 POST /api/v1/mcp/market/install/:id 的响应。
 */
export interface InstallResponse {
  instance_id: string;
  marketplace_id: string;
  display_name: string;
  health_status: string;
  tool_count: number;
  tool_names: string[];
  registered: boolean;
}
