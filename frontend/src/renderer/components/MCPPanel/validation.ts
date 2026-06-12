import { LocalServerConfig } from '../../../shared/types';

/**
 * 校验本地 MCP 服务器配置行。
 *
 * 做什么：对单行配置进行前端校验。
 * 为什么这样做：在提交前捕捉明显的输入错误，减少后端无效请求。
 * 输入输出：输入行数据，输出校验结果和错误信息。
 * 边界条件：空名称和空命令视为必填不通过。
 * 异常行为：无。
 */
export function validateServerRow(row: Partial<LocalServerConfig>): {
  valid: boolean;
  errors: Record<string, string>;
} {
  const errors: Record<string, string> = {};

  // 名称校验
  if (!row.name || row.name.trim().length === 0) {
    errors.name = '服务器名称不能为空';
  } else if (row.name.trim().length > 128) {
    errors.name = '服务器名称不能超过 128 个字符';
  } else if (!/^[a-zA-Z0-9_-]+$/.test(row.name.trim())) {
    errors.name = '服务器名称只能包含字母、数字、下划线和连字符';
  }

  // 命令校验
  if (!row.command || row.command.trim().length === 0) {
    errors.command = '启动命令不能为空';
  }

  // 环境变量键名校验
  if (row.env) {
    for (const key of Object.keys(row.env)) {
      if (!key || key.trim().length === 0) {
        errors.env = '环境变量键名不能为空';
        break;
      }
    }
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
  };
}
