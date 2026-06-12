/**
 * MCP Skill JSON 批量导入解析器。
 *
 * 做什么：解析 MCP Skill 批量导入 JSON 文本，返回解析结果和校验统计。
 * 为什么这样做：将解析逻辑从组件中分离，便于单元测试。
 * 输入输出：输入 JSON 字符串，输出解析结果和统计信息。
 * 边界条件：
 *   - JSON 解析失败时抛出 SyntaxError。
 *   - 空 skills 数组视为校验失败。
 *   - 每条配置独立校验，不影响其他条目的解析。
 * 异常行为：无。
 */
import type { SkillConfig } from '../../services/mcpSkillService';
import { validateSkillRow } from './skillValidation';

/**
 * 批量导入的 JSON 文件 Schema。
 */
export interface SkillJSON {
  /** Schema 版本号。 */
  $schema?: string;
  /** Skill 配置列表。 */
  skills: Array<{
    /** Skill 名称（必填，全局唯一）。 */
    name: string;
    /** Skill 描述（可选）。 */
    description?: string;
    /** 版本号（可选，默认 1.0.0）。 */
    version?: string;
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
  /** 校验成功数。 */
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
 */
export function parseSkillJSON(jsonText: string): {
  rows: SkillConfig[];
  summary: ImportResultSummary;
} {
  // Step 1: 解析 JSON
  const parsed: SkillJSON = JSON.parse(jsonText);

  // Step 2: 校验顶层结构
  if (!parsed || typeof parsed !== 'object') {
    throw new Error('JSON 根节点必须是一个对象');
  }
  if (!Array.isArray(parsed.skills)) {
    throw new Error('JSON 必须包含 skills 数组字段');
  }
  if (parsed.skills.length === 0) {
    throw new Error('skills 数组不能为空（至少需要一条配置）');
  }

  // Step 3: 逐条校验
  const rows: SkillConfig[] = [];
  const invalidItems: ImportResultSummary['invalidItems'] = [];
  let validCount = 0;

  for (let i = 0; i < parsed.skills.length; i++) {
    const skill = parsed.skills[i];

    const configToValidate: Partial<SkillConfig> = {
      name: skill.name || '',
      description: skill.description ?? '',
      version: skill.version ?? '1.0.0',
      enabled: skill.enabled ?? true,
    };

    const validation = validateSkillRow(configToValidate);

    if (validation.valid) {
      validCount++;
      rows.push({
        name: skill.name.trim(),
        description: skill.description?.trim() ?? '',
        version: skill.version ?? '1.0.0',
        enabled: skill.enabled ?? true,
      });
    } else {
      invalidItems.push({
        index: i,
        name: skill.name || `条目 ${i + 1}`,
        errors: validation.errors,
      });
    }
  }

  return {
    rows,
    summary: {
      total: parsed.skills.length,
      parsed: parsed.skills.length,
      valid: validCount,
      invalid: parsed.skills.length - validCount,
      invalidItems,
    },
  };
}
