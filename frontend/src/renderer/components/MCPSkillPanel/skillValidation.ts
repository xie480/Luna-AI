/**
 * MCP Skill 配置校验工具。
 *
 * 做什么：对 Skill 配置进行前端校验。
 * 为什么这样做：在提交前捕捉明显的输入错误，减少后端无效请求。
 * 输入输出：输入 Skill 配置数据，输出校验结果和错误信息。
 * 边界条件：空名称视为必填不通过。
 * 异常行为：无。
 */
import type { SkillConfig } from '../services/mcpSkillService';

export function validateSkillRow(row: Partial<SkillConfig>): {
  valid: boolean;
  errors: Record<string, string>;
} {
  const errors: Record<string, string> = {};

  // 名称校验
  if (!row.name || row.name.trim().length === 0) {
    errors.name = 'Skill 名称不能为空';
  } else if (row.name.trim().length > 128) {
    errors.name = 'Skill 名称不能超过 128 个字符';
  } else if (!/^[a-zA-Z0-9_\-\u4e00-\u9fa5]+$/.test(row.name.trim())) {
    errors.name = 'Skill 名称只能包含字母、数字、下划线、连字符和中文';
  }

  // 版本号校验
  if (row.version && !/^\d+\.\d+\.\d+$/.test(row.version.trim())) {
    errors.version = '版本号格式应为 x.y.z（如 1.0.0）';
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
  };
}
