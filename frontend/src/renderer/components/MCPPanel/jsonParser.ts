import { LocalServerConfig } from '../../../shared/types';
import { validateServerRow } from './validation';

/**
 * 批量导入的 JSON 文件 Schema。
 */
export interface LocalServerJSON {
  /** Schema 版本号，用于向后兼容。 */
  $schema?: string;
  /** 服务器配置列表。 */
  servers: Array<{
    /** 服务器名称（必填，全局唯一）。 */
    name: string;
    /** 启动命令（必填）。 */
    command: string;
    /** 命令参数（可选）。 */
    args?: string[];
    /** 环境变量（可选）。 */
    env?: Record<string, string>;
    /** 服务器描述（可选）。 */
    description?: string;
    /** 是否启用（可选，默认 true）。 */
    enabled?: boolean;
  }>;
}

/**
 * 导入结果统计。
 */
export interface ImportResultSummary {
  /** 总条目数。 */
  total: number;
  /** 成功解析数。 */
  parsed: number;
  /** 校验成功数（即将提交）。 */
  valid: number;
  /** 校验失败数。 */
  invalid: number;
  /** 校验失败的条目详情。 */
  invalidItems: Array<{
    index: number;
    name: string;
    errors: Record<string, string>;
  }>;
}

/**
 * 解析和校验批量导入的 JSON 文本。
 *
 * 做什么：解析 MCP 本地服务器批量导入 JSON 文本，
 *         返回解析结果和校验统计。
 * 为什么这样做：将解析逻辑从组件中分离，便于单元测试。
 * 输入输出：输入 JSON 字符串，输出 ImportResultSummary。
 * 边界条件：
 *   - JSON 解析失败时抛出 SyntaxError。
 *   - 空 servers 数组视为校验失败。
 *   - 每条配置独立校验，不影响其他条目的解析。
 * 异常行为：无。
 */
export function parseLocalServerJSON(jsonText: string): {
  rows: LocalServerConfig[];
  summary: ImportResultSummary;
} {
  // Step 1: 解析 JSON
  const parsed: LocalServerJSON = JSON.parse(jsonText);

  // Step 2: 校验顶层结构
  if (!parsed || typeof parsed !== 'object') {
    throw new Error('JSON 根节点必须是一个对象');
  }
  if (!Array.isArray(parsed.servers)) {
    throw new Error('JSON 必须包含 servers 数组字段');
  }
  if (parsed.servers.length === 0) {
    throw new Error('servers 数组不能为空（至少需要一条配置）');
  }

  // Step 3: 逐条校验
  const rows: LocalServerConfig[] = [];
  const invalidItems: ImportResultSummary['invalidItems'] = [];
  let validCount = 0;

  for (let i = 0; i < parsed.servers.length; i++) {
    const server = parsed.servers[i];
    
    // 如果没有 command 或者 name 先填充空字符串以避免 validateServerRow 报错 undefined
    const configToValidate: Partial<LocalServerConfig> = {
      name: server.name || '',
      command: server.command || '',
      args: server.args ?? [],
      env: server.env ?? {},
      description: server.description ?? '',
      enabled: server.enabled ?? true,
    }

    const validation = validateServerRow(configToValidate);

    if (validation.valid) {
      validCount++;
      rows.push({
        name: server.name.trim(),
        command: server.command.trim(),
        args: server.args ?? [],
        env: server.env ?? {},
        description: server.description ?? '',
        enabled: server.enabled ?? true,
      });
    } else {
      invalidItems.push({
        index: i,
        name: server.name || `条目 ${i + 1}`,
        errors: validation.errors,
      });
    }
  }

  return {
    rows,
    summary: {
      total: parsed.servers.length,
      parsed: parsed.servers.length,
      valid: validCount,
      invalid: parsed.servers.length - validCount,
      invalidItems,
    },
  };
}
