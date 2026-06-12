import React, { useState, useCallback } from 'react';
import type { LocalServerConfig } from '../../../shared/types';
import { validateServerRow } from './validation';
import { ArgsInput } from './ArgsInput';
import { EnvInput } from './EnvInput';
import { useLocalServerStore } from '../../stores/mcpLocalServerStore';

interface ServerRow {
  tempId: string;
  config: LocalServerConfig;
  validationErrors: Record<string, string>;
}

let rowCounter = 0;
function generateTempId(): string {
  return `row-${++rowCounter}-${Date.now()}`;
}

function createEmptyRow(): ServerRow {
  return {
    tempId: generateTempId(),
    config: { name: '', command: '', args: [], env: {}, enabled: true },
    validationErrors: {},
  };
}

export const ManualRegisterForm: React.FC = () => {
  const [rows, setRows] = useState<ServerRow[]>([createEmptyRow()]);
  const { registerServer, submitStatus, submitError, resetSubmitStatus } =
    useLocalServerStore();

  /**
   * 更新指定行的字段值。
   */
  const updateRow = useCallback(
    (tempId: string, field: keyof LocalServerConfig, value: unknown) => {
      setRows((prev) =>
        prev.map((row) =>
          row.tempId === tempId
            ? { ...row, config: { ...row.config, [field]: value } }
            : row
        )
      );
    },
    []
  );

  /**
   * 添加空行。
   */
  const addRow = useCallback(() => {
    setRows((prev) => [...prev, createEmptyRow()]);
  }, []);

  /**
   * 删除指定行。
   */
  const removeRow = useCallback((tempId: string) => {
    setRows((prev) => prev.filter((row) => row.tempId !== tempId));
  }, []);

  /**
   * 校验并提交所有行。
   */
  const handleSubmit = useCallback(async () => {
    resetSubmitStatus();

    // 校验所有行
    let hasError = false;
    const validatedRows = rows.map((row) => {
      const validation = validateServerRow(row.config);
      if (!validation.valid) {
        hasError = true;
      }
      return { ...row, validationErrors: validation.errors };
    });
    setRows(validatedRows);

    if (hasError) {
      return;
    }

    // 逐行提交
    for (const row of rows) {
      if (row.config.name && row.config.command) {
        try {
          await registerServer(row.config);
        } catch {
          // 错误已经在 Store 中处理
          break; // 遇到错误停止后续提交
        }
      }
    }
  }, [rows, registerServer, resetSubmitStatus]);

  return (
    <div className="manual-register-form">
      <div className="manual-register-form__header">
        <span className="field-label">服务器名称</span>
        <span className="field-label">启动命令</span>
        <span className="field-label">命令参数</span>
        <span className="field-label">环境变量</span>
        <span className="field-label">操作</span>
      </div>

      {rows.map((row) => (
        <div key={row.tempId} className="manual-register-form__row">
          <input
            type="text"
            placeholder="如 my-data-service"
            value={row.config.name}
            onChange={(e) => updateRow(row.tempId, 'name', e.target.value)}
            className={row.validationErrors.name ? 'input-error' : ''}
          />
          <input
            type="text"
            placeholder="如 npx, node, python"
            value={row.config.command}
            onChange={(e) => updateRow(row.tempId, 'command', e.target.value)}
            className={row.validationErrors.command ? 'input-error' : ''}
          />
          <ArgsInput
            value={row.config.args}
            onChange={(args) => updateRow(row.tempId, 'args', args)}
          />
          <EnvInput
            value={row.config.env}
            onChange={(env) => updateRow(row.tempId, 'env', env)}
          />
          <button
            className="btn-remove-row"
            onClick={() => removeRow(row.tempId)}
            title="删除此行"
            disabled={rows.length <= 1}
          >
            ×
          </button>
          {Object.keys(row.validationErrors).length > 0 && (
            <div className="row-errors">
              {Object.values(row.validationErrors).map((msg, i) => (
                <span key={i} className="error-text">{msg}</span>
              ))}
            </div>
          )}
        </div>
      ))}

      <div className="manual-register-form__actions">
        <button className="btn-add-row" onClick={addRow}>
          + 添加一行
        </button>
        <button
          className="btn-submit"
          onClick={handleSubmit}
          disabled={submitStatus === 'submitting'}
        >
          {submitStatus === 'submitting' ? '提交中...' : '保存并注册'}
        </button>
        <button
          className="btn-reset"
          onClick={() => setRows([createEmptyRow()])}
        >
          重置
        </button>
      </div>

      {submitStatus === 'error' && (
        <div className="submit-error">{submitError}</div>
      )}
      {submitStatus === 'success' && (
        <div className="submit-success">注册成功！</div>
      )}
    </div>
  );
};
